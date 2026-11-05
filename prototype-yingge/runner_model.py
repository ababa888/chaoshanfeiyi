"""跑酷闭环纯逻辑模型：提示队列 → 输入判定 → 速度求解 → 位移积分 → 撞阵恢复。

设计依据：docs/gameplay_rework_v1.md §4。本模块不 import pygame、不读素材、不读配置，
纯数据进出，可被无头脚本与 selftest 直接驱动；判定窗口数值留在本文件，
由 selftest 与 core.py 对齐断言，避免逻辑层被渲染依赖污染。

公式：
    v = v_base × F × C × S × (1 − P) × G
    C = clamp(0.88 + 0.12 pP + 0.06 pG − 0.18 pM + 0.04 min(streak/8, 1), 0.80, 1.08)
    P = 1 − R_hit，按 t_recover 拍线性衰减回 0（本模型按真实积分计，见 docs）
    G = 1.035^stacks（仅组 B：每 8 拍全 Perfect +1 层，断一拍清零，上限 4 层）

三条硬约束在代码里可直接断言：
    1. 速度下限 V_FLOOR > 0（队伍永不停止）；
    2. 撞阵惩罚有恢复期，t_recover 拍后归零；
    3. 连续撞击叠加上限 MAX_HIT_STACKS，超出只刷新不到第 4 层。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import combinations
from math import factorial

# ---------------------------------------------------------- 与判定层对齐的常数
BPM = 132.0
BEAT_S = 60.0 / BPM            # 0.4545 秒/拍
V_BASE = 1.0                   # 步/拍
V_FLOOR = 0.22                 # 速度下限：永不停止
P_CAP = 0.70                   # 瞬时惩罚上限（防叠撞把速度压到 0）
MAX_HIT_STACKS = 3             # 连续撞击最多叠 3 层
PERFECT_MS = 45.0
GOOD_MS = 100.0
MISS_MS = 160.0
C_MIN, C_MAX = 0.80, 1.08

COMPOUND_RATE = 0.035          # 组 B：每层加速度 +3.5%
COMPOUND_MAX = 4               # 最多 4 层（+14.8%）

GROUP_CELL_LEAD = 2            # 单格提示提前 2 拍
GROUP_LEAD = 4                 # 整组提示提前 4 拍


# --------------------------------------------------------------------- 路线
@dataclass(frozen=True)
class Segment:
    name: str
    steps: float
    slope: float
    enemy: str
    recommend: str


# 参考段：4 段 × 60 步 = 240 步，平地 S=1.00（与文档口径一致）
ROUTE: tuple[Segment, ...] = (
    Segment("开阔横阵", 60.0, 1.00, "light", "shuanglong"),
    Segment("正面盾墙", 60.0, 1.00, "shield", "menghu"),
    Segment("直线窄道", 60.0, 1.00, "pike", "fengshi"),
    Segment("林间散兵", 60.0, 1.00, "light", "shuanglong"),
)
ROUTE_STEPS = sum(s.steps for s in ROUTE)


# --------------------------------------------------------------- 阵型系数 F
# 组 A：文档原参数 0.86–1.22；组 B：压到 0.92–1.12
FORM_A = {
    "changshe": ("长蛇挺进", 1.08),
    "shuanglong": ("双龙出海", 1.16),
    "menghu": ("猛虎下山", 1.22),
    "fengshi": ("锋矢", 1.12),
    "guijia": ("龟甲", 0.86),
    "sihu": ("四虎并驱", 1.10),
    "maisui": ("麦穗花", 0.98),
    "tianluo": ("田螺圈", 0.94),
    "sasimen": ("杀四门", 1.00),
}
FORM_B = {
    "changshe": ("长蛇挺进", 1.06),
    "shuanglong": ("双龙出海", 1.12),
    "menghu": ("猛虎下山", 1.12),
    "fengshi": ("锋矢", 1.09),
    "guijia": ("龟甲", 0.92),
    "sihu": ("四虎并驱", 1.07),
    "maisui": ("麦穗花", 0.98),
    "tianluo": ("田螺圈", 0.95),
    "sasimen": ("杀四门", 1.02),
}
FORMS = {"A": FORM_A, "B": FORM_B}
SWITCH_FACTOR = 0.9            # 变阵期 F = 0.9 × min(F_old, F_new)
SWITCH_BEATS = 2


# --------------------------------------------------------------- 撞阵代价
ENEMIES = {
    "light": {"name": "散兵", "r_hit": 0.75, "t_recover": 2},
    "shield": {"name": "盾墙", "r_hit": 0.55, "t_recover": 3},
    "pike": {"name": "拒马", "r_hit": 0.35, "t_recover": 4},
    "boss": {"name": "Boss 躯干", "r_hit": 0.30, "t_recover": 6},
}


# ------------------------------------------------- 三档：精度与选阵轨迹
TIER_SIGMA = {"novice": 70.0, "skilled": 38.0, "master": 18.0}
# 新手只走对 1 段（第 3 段窄道）；熟练错第 1 段（轻撞）；高手 4 段全对
PLANS = {
    "novice": ("changshe", "changshe", "fengshi", "changshe"),
    "skilled": ("changshe", "menghu", "fengshi", "shuanglong"),
    "master": ("shuanglong", "menghu", "fengshi", "shuanglong"),
}
MASTER_SIGMA = TIER_SIGMA["master"]


def judge_offset(dt_ms: float) -> str:
    """按核心判定窗口（±45 / ±100 / ±160ms）给档；超窗算 miss（漏拍）。"""
    v = abs(float(dt_ms))
    if v <= PERFECT_MS:
        return "perfect"
    if v <= GOOD_MS:
        return "good"
    if v <= MISS_MS:
        return "miss"
    return "miss"


def coalesce_c(p_perfect: float, p_good: float, p_miss: float, streak: int) -> float:
    """文档 §4.3 的合拍系数，边界 clamp 0.80–1.08。"""
    raw = (0.88 + 0.12 * p_perfect + 0.06 * p_good - 0.18 * p_miss
           + 0.04 * min(max(streak, 0) / 8.0, 1.0))
    return min(C_MAX, max(C_MIN, raw))


def solve_speed(v_base: float = V_BASE, f: float = 1.0, c: float = 1.0,
                slope: float = 1.0, penalty: float = 0.0, boost: float = 1.0,
                floor: float = V_FLOOR) -> float:
    """v = v_base × F × C × S × (1 − P) × G，恒 ≥ floor > 0。"""
    p = min(max(float(penalty), 0.0), P_CAP)
    v = float(v_base) * float(f) * float(c) * float(slope) * (1.0 - p) * float(boost)
    return max(float(floor), v)


# ------------------------------------------------------------------ 提示队列
@dataclass
class PromptGroup:
    start_beat: int
    keys: tuple[str, ...]


class PromptQueue:
    """提示队列：整组提前 4 拍出现，单格提前 2 拍亮起。

    纯数据：只回答“这一刻屏幕上应有什么”，不关心怎么画。
    """

    def __init__(self, group_lead: int = GROUP_LEAD, cell_lead: int = GROUP_CELL_LEAD):
        self.group_lead = int(group_lead)
        self.cell_lead = int(cell_lead)
        self.groups: list[PromptGroup] = []

    def schedule_group(self, start_beat: int, keys) -> "PromptQueue":
        start = int(start_beat)
        for g in self.groups:
            if g.start_beat == start:
                g.keys = tuple(keys)
                return self
        self.groups.append(PromptGroup(start, tuple(keys)))
        self.groups.sort(key=lambda g: g.start_beat)
        return self

    def group_shown(self, beat: int, start_beat: int) -> bool:
        return beat >= start_beat - self.group_lead and beat <= start_beat + 3

    def visible_groups(self, beat: int) -> list[int]:
        return [g.start_beat for g in self.groups if self.group_shown(beat, g.start_beat)]

    def visible_cells(self, beat: int) -> list[tuple[int, str]]:
        """当前拍应亮起的单格：从现在到 cell_lead 拍之后。"""
        out: list[tuple[int, str]] = []
        for g in self.groups:
            for i, key in enumerate(g.keys):
                b = g.start_beat + i
                if beat >= b - self.cell_lead and beat >= g.start_beat - self.group_lead:
                    out.append((b, key))
        return out

    def key_at(self, beat: int) -> str | None:
        for g in self.groups:
            if g.start_beat <= beat < g.start_beat + len(g.keys):
                return g.keys[beat - g.start_beat]
        return None


# ------------------------------------------------------------ 撞阵惩罚与恢复
class CollisionTracker:
    """撞阵惩罚：R_hit 决定碰撞期速度比，t_recover 拍线性衰减回 0。

    - 叠加有上限：最多 MAX_HIT_STACKS 层，多出的撞击只刷新剩余时间；
    - 总惩罚 P_CAP 封顶，配合 V_FLOOR 保证“减速但不阻断”。
    """

    def __init__(self, max_stacks: int = MAX_HIT_STACKS, p_cap: float = P_CAP,
                 enemies: dict | None = None):
        self.max_stacks = int(max_stacks)
        self.p_cap = float(p_cap)
        self.enemies = dict(enemies or ENEMIES)
        self.active: list[list[float]] = []   # [remaining, total, r_hit]
        self.count = 0
        self.kinds: list[str] = []
        self.max_stacks_seen = 0

    def hit(self, kind: str, factor: float = 1.0) -> None:
        """factor < 1 表示本次撞击减伤（护阵/雨 buff 的 −30%）；默认 1.0 不变。"""
        meta = self.enemies[kind]
        total = float(meta["t_recover"])
        r_hit = 1.0 - (1.0 - float(meta["r_hit"])) * max(0.0, float(factor))
        self.count += 1
        self.kinds.append(kind)
        if len(self.active) >= self.max_stacks:
            # 不新增第 4 层，只把剩余最长的一条延长到本次恢复期
            target = max(self.active, key=lambda e: e[0])
            target[0] = max(target[0], total)
            target[1] = max(target[1], total)
            target[2] = min(target[2], r_hit)
        else:
            self.active.append([total, total, r_hit])
        self.max_stacks_seen = max(self.max_stacks_seen, len(self.active))

    def penalty(self) -> float:
        p = 0.0
        for remaining, total, r_hit in self.active:
            if remaining > 0 and total > 0:
                p += (1.0 - r_hit) * (remaining / total)
        return min(self.p_cap, p)

    def tick(self, beats: float = 1.0) -> None:
        for entry in self.active:
            entry[0] = max(0.0, entry[0] - float(beats))
        self.active = [e for e in self.active if e[0] > 0.0]

    @property
    def stacks(self) -> int:
        return len(self.active)


# ------------------------------------------------------------------ 结果对象
@dataclass
class SimResult:
    group: str
    tier: str
    seed: int
    time_s: float
    beats: int
    distance: float
    seg_speeds: list[float] = field(default_factory=list)
    seg_times: list[float] = field(default_factory=list)
    hits: int = 0
    hit_kinds: list[str] = field(default_factory=list)
    plan: tuple[str, ...] = ()
    p_perfect: float = 0.0
    p_good: float = 0.0
    p_miss: float = 0.0
    min_speed: float = 0.0
    max_speed: float = 0.0
    max_stacks: int = 0
    max_compound: int = 0

    @property
    def formation_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for name in self.plan:
            out[name] = out.get(name, 0) + 1
        return out


def segment_index(distance: float, route: tuple[Segment, ...] = ROUTE) -> int:
    acc = 0.0
    for i, seg in enumerate(route):
        acc += seg.steps
        if distance < acc:
            return i
    return len(route) - 1


def simulate(group: str = "A", tier: str = "novice", seed: int = 17, *,
             plan=None, sigma: float | None = None, collisions_enabled: bool = True,
             compound: bool | None = None, discount: bool | None = None,
             route: tuple[Segment, ...] = ROUTE,
             enemies: dict | None = None, p_cap: float | None = None,
             gap_loss_beats: float = 0.0,
             compound_rate: float | None = None,
             compound_max: int | None = None) -> SimResult:
    """逐拍推进：输入按 N(0, σ) 抖动 → 判定 → C/G → v → 位移。

    纯函数式（同 seed 同参数必得同结果），不依赖渲染。
    """
    group = str(group).upper()
    if group not in FORMS:
        raise ValueError(f"unknown group: {group}")
    form_table = FORMS[group]
    plan = tuple(plan or PLANS[tier])
    sigma = float(TIER_SIGMA[tier] if sigma is None else sigma)
    if compound is None:
        compound = group == "B"
    if discount is None:
        discount = group == "B"

    rng = random.Random(seed)
    queue = PromptQueue()
    group_keys = ("J", "K", "L", "J")
    tracker = CollisionTracker(p_cap=p_cap or P_CAP, enemies=enemies)
    route_steps = sum(s.steps for s in route)
    rate = COMPOUND_RATE if compound_rate is None else float(compound_rate)
    cmax = COMPOUND_MAX if compound_max is None else int(compound_max)

    beat = 0
    elapsed_s = 0.0
    distance = 0.0
    seg = 0
    prev_form = plan[0]
    switch_left = 0
    # 入口段同样结算：错阵进段即撞阵（否则第 1 段永远不计撞）
    if collisions_enabled and plan[0] != route[0].recommend:
        tracker.hit(route[0].enemy)
    seg_dist_start = 0.0
    seg_beat_start = 0
    seg_speeds: list[float] = []
    seg_times: list[float] = []
    counts = {"perfect": 0, "good": 0, "miss": 0}
    streak = 0          # 连续合拍（perfect/good）
    perfect_streak = 0  # 连续 Perfect
    stacks = 0
    stacks_peak = 0
    min_speed = float("inf")
    max_speed = 0.0

    while distance < route_steps and beat < 2000:
        # 1) 提示排队：保证当前拍与未来 4 拍有组卡
        while len(queue.groups) * 4 <= beat + queue.group_lead + 4:
            g = len(queue.groups)
            queue.schedule_group(g * 4, group_keys)

        # 2) 输入：玩家敲的是提示键，误差 N(0, σ)
        err = rng.gauss(0.0, sigma)
        grade = judge_offset(err)
        counts[grade] += 1
        if grade == "miss":
            streak = 0
            perfect_streak = 0
            stacks = 0
        else:
            streak += 1
            if grade == "perfect":
                perfect_streak += 1
                if compound:
                    stacks = min(cmax, perfect_streak // 8)
                    stacks_peak = max(stacks_peak, stacks)
            else:
                perfect_streak = 0
                stacks = 0
        total = max(1, counts["perfect"] + counts["good"] + counts["miss"])
        p_p = counts["perfect"] / total
        p_g = counts["good"] / total
        p_m = counts["miss"] / total
        c = coalesce_c(p_p, p_g, p_m, streak)

        # 3) 速度：阵型 F（含变阵损耗与组 B 的合拍打折）、坡度、惩罚、复利
        form = plan[seg]
        f = form_table[form][1]
        if switch_left > 0:
            f = SWITCH_FACTOR * min(form_table[prev_form][1], f)
            switch_left -= 1
        if discount:
            offbeat = min(1.0, max(0.6, p_p + p_g))
            f = 1.0 + (f - 1.0) * offbeat
        boost = (1.0 + rate) ** stacks if compound else 1.0
        v = solve_speed(V_BASE, f, c, route[seg].slope, tracker.penalty(), boost)
        min_speed = min(min_speed, v)
        max_speed = max(max_speed, v)

        # 4) 位移积分
        distance += v
        beat += 1
        elapsed_s += BEAT_S
        if distance > route_steps:
            elapsed_s -= (distance - route_steps) / v * BEAT_S
            distance = route_steps
        tracker.tick()

        # 5) 段边界：结算上一段平均速度；换阵 2 拍；错阵撞阵
        new_seg = segment_index(distance, route)
        if new_seg != seg:
            seg_speeds.append((distance - seg_dist_start) / max(1, beat - seg_beat_start))
            seg_times.append((beat - seg_beat_start) * BEAT_S)
            seg = new_seg
            seg_dist_start = distance
            seg_beat_start = beat
            if collisions_enabled and plan[seg] != route[seg].recommend:
                tracker.hit(route[seg].enemy)
            if plan[seg] != prev_form:
                switch_left = SWITCH_BEATS
                # 成功穿缝的等效损失拍（跑酷场景用它把“变阵 + 绕后”折成时间）
                elapsed_s += float(gap_loss_beats) * BEAT_S
            prev_form = plan[seg]

    seg_speeds.append((distance - seg_dist_start) / max(1, beat - seg_beat_start))
    seg_times.append((beat - seg_beat_start) * BEAT_S)

    return SimResult(
        group=group, tier=tier, seed=seed, time_s=elapsed_s, beats=beat,
        distance=distance, seg_speeds=seg_speeds, seg_times=seg_times,
        hits=tracker.count, hit_kinds=list(tracker.kinds), plan=plan,
        p_perfect=p_p, p_good=p_g, p_miss=p_m,
        min_speed=min_speed, max_speed=max_speed,
        max_stacks=tracker.max_stacks_seen, max_compound=stacks_peak,
    )


# -------------------------------------------------------- 文档解析式复现口径
DOC_REF = {
    # 文档 §4.6 给出的三档假设：有效 F / C / 撞阵等效损失拍
    "novice": {"F": 1.00, "C": 0.902, "hit_beats": 2.6},
    "skilled": {"F": 1.16, "C": 0.988, "hit_beats": 0.5},
    "master": {"F": 1.16, "C": 1.040, "hit_beats": 0.0},
}
DOC_TIMES = {"novice": 122.1, "skilled": 95.4, "master": 90.4}


def reference_times(steps: float = ROUTE_STEPS, beat_s: float = BEAT_S) -> dict[str, float]:
    """T = L / (v_base × F × C) + Σ t_hit，按文档给定的三档参数解析求解。"""
    out: dict[str, float] = {}
    for tier, cfg in DOC_REF.items():
        beats = steps / (V_BASE * cfg["F"] * cfg["C"]) + cfg["hit_beats"]
        out[tier] = beats * beat_s
    return out


# ------------------------------------------------------------- 差距归属（Shapley）
FACTORS = ("form", "rhythm", "collision")


def attribution(group: str = "A", seed: int = 17) -> dict[str, float]:
    """新手 → 高手的差距归属：选阵(form) / 合拍(rhythm) / 撞阵(collision)。

    三个因子各自取“新手档 / 高手档”，用 Shapley 值把总差距精确分摊（和为 1）。
    - form：新手固定长蛇 vs 高手全对；
    - rhythm：σ=70 vs σ=18（含合拍系数 C 与组 B 的复利 G）；
    - collision：新手 3 撞 vs 高手 0 撞。
    """
    group = str(group).upper()

    def value(subset: set[str]) -> float:
        return simulate(
            group=group, tier="novice", seed=seed,
            plan=PLANS["master"] if "form" in subset else PLANS["novice"],
            sigma=MASTER_SIGMA if "rhythm" in subset else TIER_SIGMA["novice"],
            collisions_enabled=False if "collision" in subset else True,
        ).time_s

    n = len(FACTORS)
    phi = {f: 0.0 for f in FACTORS}
    for factor in FACTORS:
        others = [f for f in FACTORS if f != factor]
        for r in range(len(others) + 1):
            weight = factorial(r) * factorial(n - r - 1) / factorial(n)
            for subset in combinations(others, r):
                base = set(subset)
                # 取负号：返回“该因子替新手省下的秒数”，三项之和 = 新手 − 高手
                phi[factor] -= weight * (value(base | {factor}) - value(base))
    total = sum(phi.values())
    return {"total_s": total, **{f: phi[f] for f in FACTORS}}


def tier_times(group: str = "A", seed: int = 17) -> dict[str, SimResult]:
    return {tier: simulate(group=group, tier=tier, seed=seed)
            for tier in ("novice", "skilled", "master")}


def evaluate(group: str = "A", seed: int = 17) -> dict:
    """跑三档 + 归属，返回可直接打印的指标字典。"""
    runs = tier_times(group, seed)
    gap = runs["skilled"].time_s - runs["master"].time_s
    attr = attribution(group, seed)
    form = abs(attr["form"])
    rhythm = abs(attr["rhythm"])
    collision = abs(attr["collision"])
    denom = max(1e-9, form + rhythm + collision)
    return {
        "group": str(group).upper(),
        "seed": seed,
        "runs": runs,
        "attr_s": attr,
        "share": {"form": form / denom, "rhythm": rhythm / denom,
                  "collision": collision / denom},
        "gap_s": gap,
        "gap_pct": gap / max(1e-9, runs["master"].time_s),
        "criteria": {
            "rhythm_ge_form": rhythm >= form,
            "gap_ge_12pct": gap / max(1e-9, runs["master"].time_s) >= 0.12,
        },
    }
