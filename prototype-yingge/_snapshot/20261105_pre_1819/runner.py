"""跑酷（急行）模式：提示队列 / 变阵 / 遇敌缺口 / 计时结算。

本模块不 import pygame，不依赖渲染；`runner_model.py` 负责纯公式，
这里负责“一局”的状态机，供 `main.py` 与无头脚本共用。

关键约定（与 config/runner.json 对齐）：
- 整组指令在接触前 4 拍出现；单格在落拍前 2 拍亮起；
- 预警提前 4 拍给出“该换什么阵”，敌阵两列有缺口；
- 3 拍内起手换阵、2 拍完成（取前两键作为阵法签名）即可穿缝，损失 2.3 拍；
- 不换阵撞上去，按 r_hit/t_recover 线性恢复，单撞等效损失 4.2 拍，最多叠 3 层；
- 全程无 HP、无失败，主指标是通关时间；R 重开立即回到可操作。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import core
import runner_model as rm

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config", "runner.json")

DEFAULT_ROUTE = (
    ("开阔横阵", 60.0, 1.00, "light", "shuanglong", "left", "holy"),
    ("正面盾墙", 60.0, 1.00, "shield", "menghu", "right", "holy"),
    ("直线窄道", 60.0, 1.04, "pike", "fengshi", "left", "history"),
    ("林间散兵", 60.0, 0.96, "light", "shuanglong", "right", "secular"),
)

DEFAULT_ENEMIES = {
    "light": {"name": "散兵", "r_hit": 0.56, "t_recover": 12},
    "shield": {"name": "盾墙", "r_hit": 0.56, "t_recover": 12},
    "pike": {"name": "拒马", "r_hit": 0.56, "t_recover": 12},
}


# ------------------------------------------------------------------ 配置
@dataclass(frozen=True)
class RouteSeg:
    name: str
    steps: float
    slope: float
    enemy: str
    recommend: str
    gap_side: str = "left"
    kind: str = "holy"

    @property
    def end_steps(self) -> float:
        return self.steps


@dataclass(frozen=True)
class CultureConfig:
    """三层文化状态的可调数值；全部来自 config/runner.json 的 culture 块。"""
    enabled: bool = True
    rain_beats: int = 8
    rain_slope: float = 1.08
    rain_loss_cut: float = 0.30
    rain_collect_beats: int = 6
    rain_collect_hits: int = 3
    rain_slow: float = 0.86
    rain_penalty_beats: float = 0.6
    guard_loss_cut: float = 0.30
    guard_beats: int = 4
    purify_per_drum: int = 3
    popularity_max: float = 100.0
    popularity_per_step: float = 1.2
    stop_beats: int = 4
    stop_pop: float = 30.0
    fever_normal: int = 14
    fever_pop: int = 10
    martial_per: int = 3
    martial_switch_beats: int = 1


@dataclass
class RunnerConfig:
    bpm: float = rm.BPM
    v_base: float = rm.V_BASE
    v_floor: float = rm.V_FLOOR
    p_cap: float = 0.90
    max_hit_stacks: int = rm.MAX_HIT_STACKS
    compound_rate: float = rm.COMPOUND_RATE
    compound_max: int = rm.COMPOUND_MAX
    group_lead: int = rm.GROUP_LEAD
    cell_lead: int = rm.GROUP_CELL_LEAD
    warning_lead: int = 4
    switch_window: int = 3
    switch_beats: int = 2
    switch_factor: float = rm.SWITCH_FACTOR
    gap_loss_beats: float = 2.3
    hit_loss_beats: float = 4.2
    display_level: str = "novice"
    display_levels: tuple[str, ...] = ("novice", "skilled", "master")
    forms: dict = field(default_factory=lambda: dict(rm.FORM_B))
    patterns: dict = field(default_factory=dict)
    enemies: dict = field(default_factory=lambda: dict(DEFAULT_ENEMIES))
    route: tuple[RouteSeg, ...] = field(default_factory=tuple)
    rating: dict = field(default_factory=lambda: {"S": 90.0, "A": 105.0, "B": 120.0})
    rating_culture: dict = field(default_factory=lambda: {"S": 115.0, "A": 130.0,
                                                          "B": 145.0})
    culture: CultureConfig = field(default_factory=CultureConfig)
    raw: dict = field(default_factory=dict)

    @property
    def beat_s(self) -> float:
        return 60.0 / float(self.bpm)

    @property
    def route_steps(self) -> float:
        return sum(s.steps for s in self.route)

    def pattern(self, formation: str) -> tuple[str, ...]:
        return tuple(self.patterns.get(formation, self.patterns.get("changshe", "KKKK")))

    def signature(self, formation: str) -> tuple[str, ...]:
        """阵法签名：前两键。跑酷里 2 拍完成变阵，其余两拍是确认/踏点。"""
        return self.pattern(formation)[:2]

    def form_name(self, formation: str) -> str:
        return self.forms.get(formation, ("长蛇挺进", 1.0))[0]

    def form_f(self, formation: str) -> float:
        return float(self.forms.get(formation, ("长蛇挺进", 1.0))[1])

    def route_segments(self) -> tuple[rm.Segment, ...]:
        return tuple(rm.Segment(s.name, s.steps, s.slope, s.enemy, s.recommend)
                     for s in self.route)

    def rating_for(self, t_s: float, culture: bool = False) -> str:
        scale = self.rating_culture if culture else self.rating
        if t_s <= float(scale.get("S", 90.0)):
            return "S"
        if t_s <= float(scale.get("A", 105.0)):
            return "A"
        if t_s <= float(scale.get("B", 120.0)):
            return "B"
        return "C"


def _raw_route() -> list[dict]:
    return [{"name": n, "steps": st, "slope": sl, "enemy": e,
             "recommend": rec, "gap_side": side, "kind": kind}
            for n, st, sl, e, rec, side, kind in DEFAULT_ROUTE]


def load_config(path: str = CONFIG_PATH) -> RunnerConfig:
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    forms = dict(rm.FORM_B)
    for key, spec in (data.get("forms") or {}).items():
        if isinstance(spec, dict) and "f" in spec:
            forms[key] = (str(spec.get("name", key)), float(spec["f"]))
    patterns = {k: "".join(v) for k, v in (data.get("patterns") or {}).items()
                if isinstance(v, (str, list, tuple))}
    if not patterns:
        patterns = {"changshe": "KKKK", "shuanglong": "JJKK",
                    "menghu": "KLKL", "fengshi": "JKJK", "guijia": "LKLK"}
    route_raw = data.get("route") or _raw_route()
    route = tuple(RouteSeg(str(s.get("name", "路段")),
                           float(s.get("steps", 60.0)),
                           float(s.get("slope", 1.0)),
                           str(s.get("enemy", "light")),
                           str(s.get("recommend", "shuanglong")),
                           str(s.get("gap_side", "left")),
                           str(s.get("kind", "holy"))) for s in route_raw)
    enemies = dict(DEFAULT_ENEMIES)
    for key, spec in (data.get("enemies") or {}).items():
        if isinstance(spec, dict) and "r_hit" in spec:
            enemies[key] = {"name": str(spec.get("name", key)),
                            "r_hit": float(spec["r_hit"]),
                            "t_recover": float(spec.get("t_recover", 12))}
    culture_raw = data.get("culture") or {}
    culture = CultureConfig(
        enabled=bool(culture_raw.get("enabled", True)),
        rain_beats=int(culture_raw.get("rain_beats", 8)),
        rain_slope=float(culture_raw.get("rain_slope", 1.08)),
        rain_loss_cut=float(culture_raw.get("rain_loss_cut", 0.30)),
        rain_collect_beats=int(culture_raw.get("rain_collect_beats", 6)),
        rain_collect_hits=int(culture_raw.get("rain_collect_hits", 3)),
        rain_slow=float(culture_raw.get("rain_slow", 0.86)),
        rain_penalty_beats=float(culture_raw.get("rain_penalty_beats", 0.6)),
        guard_loss_cut=float(culture_raw.get("guard_loss_cut", 0.30)),
        guard_beats=int(culture_raw.get("guard_beats", 4)),
        purify_per_drum=int(culture_raw.get("purify_per_drum", 3)),
        popularity_max=float(culture_raw.get("popularity_max", 100.0)),
        popularity_per_step=float(culture_raw.get("popularity_per_step", 1.2)),
        stop_beats=int(culture_raw.get("stop_beats", 4)),
        stop_pop=float(culture_raw.get("stop_pop", 30.0)),
        fever_normal=int(culture_raw.get("fever_normal", 14)),
        fever_pop=int(culture_raw.get("fever_pop", 10)),
        martial_per=int(culture_raw.get("martial_per", 3)),
        martial_switch_beats=int(culture_raw.get("martial_switch_beats", 1)),
    )
    cfg = RunnerConfig(
        bpm=float(data.get("bpm", rm.BPM)),
        v_base=float(data.get("v_base", rm.V_BASE)),
        v_floor=float(data.get("v_floor", rm.V_FLOOR)),
        p_cap=float(data.get("p_cap", 0.90)),
        max_hit_stacks=int(data.get("max_hit_stacks", rm.MAX_HIT_STACKS)),
        compound_rate=float(data.get("compound_rate", rm.COMPOUND_RATE)),
        compound_max=int(data.get("compound_max", rm.COMPOUND_MAX)),
        group_lead=int(data.get("group_lead", rm.GROUP_LEAD)),
        cell_lead=int(data.get("cell_lead", rm.GROUP_CELL_LEAD)),
        warning_lead=int(data.get("warning_lead", 4)),
        switch_window=int(data.get("switch_window", 3)),
        switch_beats=int(data.get("switch_beats", 2)),
        switch_factor=float(data.get("switch_factor", rm.SWITCH_FACTOR)),
        gap_loss_beats=float(data.get("gap_loss_beats", 2.3)),
        hit_loss_beats=float(data.get("hit_loss_beats", 4.2)),
        display_level=str(data.get("display_level", "novice")),
        display_levels=tuple(data.get("display_levels")
                             or ("novice", "skilled", "master")),
        forms=forms, patterns=patterns, enemies=enemies, route=route,
        rating={k: float(v) for k, v in (data.get("rating") or
                                         {"S": 90.0, "A": 105.0, "B": 120.0}).items()
                if isinstance(v, (int, float))},
        rating_culture={k: float(v) for k, v in (data.get("rating_culture") or
                                                 {"S": 115.0, "A": 130.0,
                                                  "B": 145.0}).items()
                        if isinstance(v, (int, float))},
        culture=culture,
        raw=data,
    )
    return cfg


# ------------------------------------------------------------------ 提示队列
@dataclass
class PromptGroup:
    start_beat: int
    keys: tuple[str, ...]
    formation: str
    contact_beat: int
    warning: bool = False
    label: str = ""

    def visible_at(self) -> int:
        return self.contact_beat - 4


class PromptQueue:
    """跑酷谱面：整组在接触前 4 拍出现，单格在落拍前 2 拍亮起。"""

    def __init__(self, cfg: RunnerConfig):
        self.cfg = cfg
        self.groups: list[PromptGroup] = []

    def clear(self) -> None:
        self.groups.clear()

    def schedule(self, start_beat: int, keys, formation: str,
                 contact_beat: int, warning: bool = False,
                 label: str = "") -> PromptGroup:
        keys = tuple(keys)
        group = PromptGroup(int(start_beat), keys, str(formation),
                            int(contact_beat), bool(warning), str(label))
        # 同起点以预警组优先，避免普通谱面覆盖换阵指令
        for i, old in enumerate(self.groups):
            if old.start_beat == group.start_beat:
                if group.warning or not old.warning:
                    self.groups[i] = group
                break
        else:
            self.groups.append(group)
        self.groups.sort(key=lambda g: (g.start_beat, not g.warning))
        return group

    def active_group(self, beat: int) -> PromptGroup | None:
        best = None
        for g in self.groups:
            if g.start_beat <= beat < g.start_beat + len(g.keys):
                if best is None or (g.warning and not best.warning) \
                        or g.contact_beat > best.contact_beat:
                    best = g
        return best

    def visible_groups(self, beat: int) -> list[PromptGroup]:
        return [g for g in self.groups if beat >= g.visible_at()]

    def key_at(self, beat: int) -> str | None:
        g = self.active_group(beat)
        if g is None:
            return None
        return g.keys[beat - g.start_beat]

    def cell_visible(self, beat: int, group: PromptGroup, index: int) -> bool:
        cell_beat = group.start_beat + index
        return beat >= cell_beat - self.cfg.cell_lead

    def warning_group(self) -> PromptGroup | None:
        for g in self.groups:
            if g.warning:
                return g
        return None


# ------------------------------------------------------------------ 一局
class RunnerSession:
    """一局急行：逐拍推进，所有速度/惩罚公式复用 runner_model。"""

    def __init__(self, cfg: RunnerConfig | None = None, leader: str = "wusong",
                 seed: int = 17, *, auto_plan: tuple[str, ...] | None = None,
                 sigma: float = 0.0, culture: bool | None = None) -> None:
        self.cfg = cfg or load_config()
        self.leader = leader
        self.seed = int(seed)
        self.auto_plan = tuple(auto_plan) if auto_plan else None
        self.sigma = float(sigma)
        self.culture_on = bool(self.cfg.culture.enabled and culture)
        self.culture_auto = bool(self.culture_on and self.auto_plan)
        self.rng = __import__("random").Random(self.seed)
        self.start_wall = time.perf_counter()
        self.reset()

    # -- 生命周期
    def reset(self) -> None:
        self.beat = 0
        self.elapsed_s = 0.0
        self.distance = 0.0
        self.seg = 0
        if self.auto_plan:
            self.formation = self.auto_plan[0]
            self.prev_form = self.formation
        else:
            self.formation = self.cfg.route[0].recommend
            self.prev_form = self.formation
        self.switch_left = 0
        self.switch_old = self.formation
        self.switch_started_beat = -1
        self.switch_done_beat = -1
        self.switch_seq: list[str] = []
        self.warning: dict | None = None
        self.queue = PromptQueue(self.cfg)
        self.tracker = rm.CollisionTracker(
            max_stacks=self.cfg.max_hit_stacks, p_cap=self.cfg.p_cap,
            enemies=self.cfg.enemies)
        self.counts = {"perfect": 0, "good": 0, "miss": 0}
        self.streak = 0
        self.perfect_streak = 0
        self.stacks = 0
        self.stacks_peak = 0
        self.min_speed = float("inf")
        self.max_speed = 0.0
        self.current_speed = self.cfg.v_floor
        self.c_value = 1.0
        self.ui_flash = {"whack": -1.0, "hit": -1.0, "gap": -1.0,
                         "warn": -1.0}
        self.splits: list[float] = []
        self.seg_speeds: list[float] = []
        self.hits = 0
        self.gaps = 0
        self.switches = 0
        self.gap_debits = 0.0
        self.last_grade: str | None = None
        self.last_key: str | None = None
        self.last_expected: str | None = None
        self.finished = False
        self.final_time_s = 0.0
        self.events: list[tuple] = []
        # ---- 三层文化状态（culture_on=False 时全部保持默认，不影响旧跑分）
        self.last_command: str | None = None
        self.last_command_beat = -99
        self._recent: list[tuple[int, str]] = []
        self.purifies = 0
        self.drum_charge = 0
        self.popularity = 0.0
        self.martial = 0
        self.martial_ready = False
        self.martial_used_switch = False
        self.guard_left = 0
        self.rain_left = 0
        self.rain_collect_left = 0
        self.rain_hits = 0
        self.rain_count = 0
        self.martial_count = 0
        self.guard_count = 0
        self.patrol_count = 0
        self.stop_count = 0
        self._silent_streak = 0
        self._auto_stop = 0
        self._auto_stopped = False
        self.rain_slow_beats = 0
        self.rain_boost_beats = 0
        self.hit_cut_credit_s = 0.0
        self.martial_credit_s = 0.0
        self.rain_penalty_s = 0.0
        if self.auto_plan and self.formation != self.cfg.route[0].recommend \
                and self._seg_challenging(0):
            # 与 runner_model 一致：错阵进段即撞阵；culture 下世俗/历史段不撞
            self.hits += 1
            self.tracker.hit(self.cfg.route[0].enemy)
        self._schedule_blocks()
        self.start_wall = time.perf_counter()

    def restart(self) -> "RunnerSession":
        self.reset()
        return self

    def ready(self) -> bool:
        """R 重开后应立即可操作：首拍已排队、无完成态。"""
        return (not self.finished and self.beat == 0 and self.distance == 0.0
                and self.queue.key_at(0) is not None)

    # -- 环境判定（三层文化状态）
    def state_for_seg(self, seg: int) -> str:
        """段 0 世俗 → 段 1 神圣 → 段 2 历史；后续段按 kind 继续解锁。"""
        if not self.culture_on or seg < 0 or seg >= len(self.cfg.route):
            return "holy"
        kind = self.cfg.route[seg].kind
        if kind == "secular":
            return "secular"
        if kind == "history":
            return "history" if seg >= 2 else ("holy" if seg >= 1 else "secular")
        return "holy" if seg >= 1 else "secular"

    @property
    def culture_state(self) -> str:
        return self.state_for_seg(self.seg)

    @property
    def state_label(self) -> str:
        return {"secular": "巡游", "holy": "净街", "history": "求雨·尚武"}.get(
            self.culture_state, "急行")

    def _seg_challenging(self, seg: int) -> bool:
        """该段是否有敌人接触：culture 下只有神圣段有；旧模式全段都有。"""
        if not self.culture_on:
            return True
        return self.state_for_seg(seg) == "holy"

    def _culture_prompt(self, b: int) -> tuple[tuple[str, ...], str, str]:
        """环境谱面：同键在不同态长出不同四拍令。"""
        state = self.culture_state
        form = self.formation
        if state == "secular":
            return ("KKKK", form, "巡游 KKKK · 驻足 4 拍")
        if state == "history":
            return ("JJJJ", form, "尚武 JJJJ · 弱拍 J 求雨")
        if (b // 4) % 2 == 0:
            return ("JJJJ", form, "破邪 JJJJ")
        return ("LLLL", form, "护阵 LLLL")

    # -- 谱面
    def _schedule_blocks(self) -> None:
        """把当前与未来 2 个 4 拍块排上；普通块跟随当前/推荐阵法。"""
        start = (self.beat // 4) * 4
        for k in range(2):
            b = start + k * 4
            if any(abs(g.start_beat - b) < 1 and not g.warning
                   for g in self.queue.groups):
                continue
            if self.culture_on and not self.warning:
                keys, form, label = self._culture_prompt(b)
                self.queue.schedule(b, keys, form, b + 4, label=label)
                continue
            form = self.formation
            if self.warning:
                form = self.warning["target"]
            keys = self.cfg.pattern(form)
            self.queue.schedule(b, keys, form, b + 4)

    # -- 预警与接触
    def _maybe_warn(self, speed: float, evs: list[tuple]) -> None:
        if self.warning is not None or self.seg >= len(self.cfg.route) - 1:
            return
        seg = self.cfg.route[self.seg + 1]
        if not self._seg_challenging(self.seg + 1):
            return
        end = sum(s.steps for s in self.cfg.route[:self.seg + 1])
        remain = end - self.distance
        if remain <= 0:
            return
        beats_left = remain / max(speed, self.cfg.v_floor)
        if beats_left > self.cfg.warning_lead:
            return
        target = seg.recommend
        contact = max(self.beat + 1, self.beat + int(round(beats_left)))
        self.warning = {
            "target": target, "enemy": seg.enemy, "gap_side": seg.gap_side,
            "start_beat": self.beat, "contact_beat": contact,
            "name": self.cfg.form_name(target),
            "enemy_name": self.cfg.enemies.get(seg.enemy, {}).get("name", seg.enemy),
        }
        self.switch_seq = []
        self.switch_started_beat = -1
        self.switch_done_beat = -1
        self.queue.schedule(self.beat, self.cfg.pattern(target), target,
                            contact, warning=True)
        self.ui_flash["warn"] = self.beat + 4
        evs.append(("warn", dict(self.warning)))

    def _hit_cut(self) -> float:
        """同类 buff 互斥：护阵与雨都只减撞阵损失，取较大值、不叠加。"""
        if not self.culture_on:
            return 0.0
        cut = 0.0
        if self.guard_left > 0:
            cut = max(cut, self.cfg.culture.guard_loss_cut)
        if self.rain_left > 0:
            cut = max(cut, self.cfg.culture.rain_loss_cut)
        return cut

    def _purify(self, evs: list[tuple]) -> None:
        if not self.culture_on:
            return
        self.purifies += 1
        need = max(1, self.cfg.culture.purify_per_drum)
        if self.purifies % need == 0:
            self.drum_charge += 1
        evs.append(("purify", {"total": self.purifies,
                               "drums": self.drum_charge}))

    def _collide(self, seg_idx: int) -> None:
        """实际撞阵：按护阵/雨 buff 减伤；不改变判定窗口与 4.2 拍基准。"""
        kind = self.cfg.route[seg_idx].enemy
        cut = self._hit_cut()
        self.tracker.hit(kind, factor=1.0 - cut)
        if cut > 0:
            self.hit_cut_credit_s += cut * self.cfg.hit_loss_beats * self.cfg.beat_s

    def _apply_command(self, cmd: str, evs: list[tuple]) -> None:
        state = self.culture_state
        self.last_command = cmd
        self.last_command_beat = self.beat
        if cmd == "attack" and state == "holy" and self._seg_challenging(self.seg):
            # 破邪冲撞：保留 4.2 拍损失，但撞散一处记一次净化
            self._collide(self.seg)
            self._purify(evs)
            self.ui_flash["purify"] = self.beat + 3
        elif cmd == "guard":
            self.guard_left = self.cfg.culture.guard_beats
            self.guard_count += 1
            evs.append(("guard", self.guard_left))
        elif cmd == "march":
            self.patrol_count += 1
            evs.append(("patrol", self.patrol_count))
        elif cmd == "martial":
            self.martial_count += 1
            self.martial += 1
            if self.martial >= max(1, self.cfg.culture.martial_per):
                self.martial = 0
                self.martial_ready = True
            self.ui_flash["martial"] = self.beat + 3
            evs.append(("martial", {"total": self.martial_count,
                                    "ready": self.martial_ready}))

    def _track_command(self, key: str | None, grade: str | None,
                       evs: list[tuple]) -> None:
        """同键在不同环境识别成不同四拍令；判定档仍是 ±45/±100/±160ms。"""
        if not self.culture_on:
            return
        if key is None or grade not in ("perfect", "good"):
            self._recent = []
            return
        self._recent.append((self.beat, key))
        self._recent = self._recent[-4:]
        if len(self._recent) < 4 or self.beat - self.last_command_beat < 4:
            return
        seq = "".join(k for _, k in self._recent)
        state = self.culture_state
        cmd = None
        if state == "holy":
            cmd = {"JJJJ": "attack", "LLLL": "guard"}.get(seq)
        elif state == "secular" and seq == "KKKK":
            cmd = "march"
        elif state == "history" and seq == "JJJJ":
            cmd = "martial"
        if cmd:
            self._apply_command(cmd, evs)
            self._recent = []

    def _rain_tick(self, key: str | None, grade: str | None,
                   evs: list[tuple]) -> None:
        """历史段求雨：弱拍连按 J 六拍内打三点 → 8 拍雨 buff。"""
        if not self.culture_on or self.culture_state != "history":
            return
        c = self.cfg.culture
        if key == "J" and grade in ("perfect", "good") and self.beat % 2 == 1 \
                and self.rain_left <= 0:
            if self.rain_collect_left <= 0:
                self.rain_collect_left = c.rain_collect_beats
                self.rain_hits = 0
                evs.append(("rain_start", self.beat))
            self.rain_hits += 1
            if self.rain_hits >= max(1, c.rain_collect_hits):
                self.rain_left = c.rain_beats
                self.rain_collect_left = 0
                self.rain_count += 1
                self.elapsed_s += c.rain_penalty_beats * self.cfg.beat_s
                self.rain_penalty_s += c.rain_penalty_beats * self.cfg.beat_s
                evs.append(("rain", {"count": self.rain_count,
                                     "beats": self.rain_left}))

    def _culture_tick(self, evs: list[tuple], v: float = 1.0) -> None:
        """每拍末：人气按里程累积、驻足、护阵/雨/求雨窗口倒计时。"""
        if not self.culture_on:
            return
        c = self.cfg.culture
        state = self.culture_state
        if state == "secular":
            self.popularity = min(c.popularity_max,
                                  self.popularity + c.popularity_per_step * max(0.0, v))
            self._silent_streak = self._silent_streak + 1 if self.last_key is None else 0
            if self._silent_streak == c.stop_beats and self.stop_count == 0:
                self.stop_count += 1
                self.popularity = min(c.popularity_max,
                                      self.popularity + c.stop_pop)
                evs.append(("stop_show", round(self.popularity, 1)))
        else:
            self._silent_streak = 0
        if self.guard_left > 0:
            self.guard_left -= 1
        if self.rain_collect_left > 0:
            self.rain_collect_left -= 1
            if self.rain_collect_left == 0 and self.rain_hits < max(
                    1, c.rain_collect_hits):
                self.rain_hits = 0
                evs.append(("rain_fail", self.beat))
        if self.rain_left > 0:
            self.rain_left -= 1

    def _contact(self, new_seg: int) -> tuple | None:
        """进入新段时结算：穿缝 / 直接通过 / 撞阵。"""
        seg = self.cfg.route[new_seg]
        if not self._seg_challenging(new_seg):
            return ("pass", {"seg": new_seg})
        target = seg.recommend
        if self.formation == target:
            switched_in_window = (
                self.warning is not None
                and self.switch_done_beat >= self.warning["start_beat"]
                and self.switch_started_beat >= 0
                and (self.switch_started_beat - self.warning["start_beat"])
                <= self.cfg.switch_window
                and (self.switch_done_beat - self.switch_started_beat)
                <= self.cfg.switch_beats
            )
            if switched_in_window:
                loss = self.cfg.gap_loss_beats
                if self.martial_used_switch:
                    loss = max(0.3, loss - 1.0)
                    self.martial_used_switch = False
                self.gaps += 1
                self.gap_debits += loss
                self.elapsed_s += loss * self.cfg.beat_s
                self.ui_flash["gap"] = self.beat + 3
                return ("gap", {"seg": new_seg, "side": seg.gap_side,
                                "loss_beats": loss})
            return ("pass", {"seg": new_seg})
        self.hits += 1
        self._collide(new_seg)
        if self.culture_on and self.culture_state == "holy" \
                and self.last_command == "attack" \
                and self.beat - self.last_command_beat <= 4:
            self._purify([])
        self.ui_flash["hit"] = self.beat + 6
        return ("hit", {"seg": new_seg, "enemy": seg.enemy,
                        "stacks": self.tracker.stacks})

    # -- 逐拍
    def step(self, key: str | None = None, dt_ms: float = 0.0) -> list[tuple]:
        if self.finished:
            return []
        evs: list[tuple] = []
        self._schedule_blocks()
        expected = self.queue.key_at(self.beat)
        if self.auto_plan is not None:
            if self.culture_auto and self.culture_state == "secular" \
                    and not self._auto_stopped and self.beat >= 4 \
                    and self.beat % 4 == 0:
                # 无头脚本：世俗段一次驻足表演，换大额人气
                self._auto_stop = self.cfg.culture.stop_beats
                self._auto_stopped = True
            if self.culture_auto and self._auto_stop > 0:
                self._auto_stop -= 1
                key = None
                dt_ms = 0.0
            else:
                key = expected
                dt_ms = self.rng.gauss(0.0, self.sigma)
        grade = None
        if key is not None and key == expected:
            grade = rm.judge_offset(dt_ms)
        self.last_key = key
        self.last_expected = expected
        self.last_grade = grade

        # 1) 判定 → C / G
        if grade in ("perfect", "good"):
            self.counts[grade] += 1
            self.streak += 1
            if grade == "perfect":
                self.perfect_streak += 1
                self.stacks = min(self.cfg.compound_max,
                                  self.perfect_streak // 8)
                self.stacks_peak = max(self.stacks_peak, self.stacks)
            else:
                self.perfect_streak = 0
                self.stacks = 0
        else:
            self.counts["miss"] += 1
            self.streak = 0
            self.perfect_streak = 0
            self.stacks = 0
        total = max(1, sum(self.counts.values()))
        p_p = self.counts["perfect"] / total
        p_g = self.counts["good"] / total
        p_m = self.counts["miss"] / total
        c = rm.coalesce_c(p_p, p_g, p_m, self.streak)
        self.c_value = c
        evs.append(("grade", grade, key, expected, dt_ms))
        self._track_command(key, grade, evs)
        self._rain_tick(key, grade, evs)

        # 2) 换阵：预警期内前两键签名生效（3 拍内起手、2 拍完成）
        if self.auto_plan is None and self.warning is not None \
                and grade in ("perfect", "good") and key is not None:
            seq = list(self.cfg.signature(self.warning["target"]))
            self.switch_seq.append(key)
            if len(self.switch_seq) == len(seq) and self.switch_seq == seq:
                self.switch_old = self.formation
                self.formation = self.warning["target"]
                self.switch_left = self.cfg.switch_beats
                self.martial_used_switch = False
                if self.martial_ready:
                    # 武艺满 3：一次免费变阵，2 拍压到 1 拍
                    self.martial_ready = False
                    self.martial_used_switch = True
                    self.martial_credit_s += self.cfg.beat_s
                    self.switch_left = self.cfg.culture.martial_switch_beats
                self.switch_started_beat = self.beat - len(seq) + 1
                self.switch_done_beat = self.beat
                self.switches += 1
                self.ui_flash["whack"] = self.beat + 3
                evs.append(("double_whack", self.formation))
        elif grade not in ("perfect", "good"):
            self.switch_seq = []

        # 3) 速度：F（含变阵损耗与合拍打折）、S、P、复利
        f = self.cfg.form_f(self.formation)
        if self.switch_left > 0:
            f = self.cfg.switch_factor * min(
                self.cfg.form_f(self.switch_old),
                self.cfg.form_f(self.formation))
            self.switch_left -= 1
        offbeat = min(1.0, max(0.6, p_p + p_g))
        f = 1.0 + (f - 1.0) * offbeat
        boost = (1.0 + self.cfg.compound_rate) ** self.stacks
        slope = self.cfg.route[self.seg].slope
        if self.culture_on and self.rain_left > 0 and slope > 1.0:
            # 雨 buff 只作用于坡面速度
            slope *= self.cfg.culture.rain_slope
            self.rain_boost_beats += 1
        v = rm.solve_speed(self.cfg.v_base, f, c, slope,
                           self.tracker.penalty(), boost, floor=self.cfg.v_floor)
        if self.culture_on and self.rain_collect_left > 0:
            # 求雨这 6 拍按慢板 0.86× 走（净损约 1.6 拍）
            v = max(self.cfg.v_floor, v * self.cfg.culture.rain_slow)
            self.rain_slow_beats += 1
        self.min_speed = min(self.min_speed, v)
        self.max_speed = max(self.max_speed, v)
        self.current_speed = v

        # 4) 位移积分
        self.distance += v
        self.beat += 1
        self.elapsed_s += self.cfg.beat_s
        self.tracker.tick()
        self._culture_tick(evs, v)
        self._maybe_warn(v, evs)

        # 5) 段边界
        new_seg = rm.segment_index(self.distance, self.cfg.route_segments())
        if new_seg != self.seg:
            if self.auto_plan is not None:
                nxt = self.auto_plan[min(new_seg, len(self.auto_plan) - 1)]
                if nxt != self.cfg.route[new_seg].recommend \
                        and self._seg_challenging(new_seg):
                    self.hits += 1
                    self._collide(new_seg)
                    self.ui_flash["hit"] = self.beat + 6
                    evs.append(("hit", {"seg": new_seg,
                                        "enemy": self.cfg.route[new_seg].enemy,
                                        "stacks": self.tracker.stacks}))
                if nxt != self.formation:
                    self.switch_old = self.formation
                    self.formation = nxt
                    self.switch_left = self.cfg.switch_beats
                    loss = self.cfg.gap_loss_beats
                    if self.martial_ready:
                        self.martial_ready = False
                        self.martial_used_switch = True
                        self.martial_credit_s += self.cfg.beat_s
                        self.switch_left = self.cfg.culture.martial_switch_beats
                        loss = max(0.3, loss - 1.0)
                    self.switches += 1
                    self.gaps += 1
                    self.ui_flash["gap"] = self.beat + 3
                    self.gap_debits += loss
                    self.elapsed_s += loss * self.cfg.beat_s
            else:
                ev = self._contact(new_seg)
                if ev:
                    evs.append(ev)
            self.splits.append(self.elapsed_s)
            self.seg = new_seg
            self.warning = None
            self.switch_seq = []
            self.switch_started_beat = -1
            self.switch_done_beat = -1
            self._schedule_blocks()

        # 6) 终点：按实际位移修正最后一拍的过冲
        if self.distance >= self.cfg.route_steps:
            over = self.distance - self.cfg.route_steps
            self.elapsed_s -= over / max(v, 1e-9) * self.cfg.beat_s
            self.distance = self.cfg.route_steps
            self.finished = True
            self.final_time_s = self.elapsed_s
            evs.append(("finish", self.result()))
        self.events.extend(evs)
        return evs

    # -- 读取
    @property
    def time_s(self) -> float:
        return self.final_time_s if self.finished else self.elapsed_s

    @property
    def beat_s(self) -> float:
        return self.cfg.beat_s

    @property
    def perfect_rate(self) -> float:
        total = max(1, sum(self.counts.values()))
        return self.counts["perfect"] / total

    @property
    def avg_speed(self) -> float:
        beats = self.time_s / max(1e-9, self.cfg.beat_s)
        return self.distance / max(1e-9, beats)

    @property
    def speed_mps(self) -> float:
        """HUD 用：1 步 ≈ 1.0 米，速度 = 步/拍 × 拍/秒。"""
        beats = self.time_s / max(1e-9, self.cfg.beat_s)
        return self.distance / max(1e-9, self.time_s)

    @property
    def speed_gear(self) -> str:
        v = self.avg_speed
        if self.tracker.penalty() > 0.15:
            return "受阻"
        if v >= 1.15:
            return "疾行"
        if v >= 1.0:
            return "常行"
        if v >= 0.7:
            return "缓行"
        return "拖行"

    def display_group(self) -> PromptGroup | None:
        g = self.queue.active_group(self.beat)
        if g is not None:
            return g
        vis = [x for x in self.queue.groups if x.start_beat >= self.beat]
        return min(vis, key=lambda x: x.start_beat) if vis else None

    @property
    def fever_threshold(self) -> int:
        """人气只降 Fever 门槛（14→10），不加速度。"""
        if not self.culture_on:
            return self.cfg.culture.fever_normal
        if self.popularity >= self.cfg.culture.popularity_max:
            return self.cfg.culture.fever_pop
        return self.cfg.culture.fever_normal

    @property
    def time_no_buff(self) -> float:
        """结算用：去掉雨/护阵/武艺收益，并回求雨慢板与额外罚拍后的可比时间。"""
        if not self.culture_on:
            return self.time_s
        c = self.cfg.culture
        credit = 0.0
        credit += self.rain_boost_beats * self.cfg.beat_s * (
            1.0 - 1.0 / max(1e-9, c.rain_slope))
        credit += self.hit_cut_credit_s + self.martial_credit_s
        cost = self.rain_slow_beats * self.cfg.beat_s * (
            1.0 / max(1e-9, c.rain_slow) - 1.0) + self.rain_penalty_s
        return self.time_s - credit + cost

    def result(self) -> dict:
        return {
            "time_s": round(self.time_s, 3),
            "rating": self.cfg.rating_for(self.time_s, culture=self.culture_on),
            "perfect_rate": round(self.perfect_rate, 4),
            "hits": self.hits,
            "gaps": self.gaps,
            "switches": self.switches,
            "splits": [round(x, 3) for x in self.splits],
            "avg_speed": round(self.avg_speed, 3),
            "min_speed": round(self.min_speed, 3),
            "max_stacks": self.tracker.max_stacks_seen,
            "gap_debits": round(self.gap_debits, 3),
            "beats": self.beat,
            "distance": round(self.distance, 2),
            "display": self.cfg.display_level,
            "culture": bool(self.culture_on),
            "state": self.culture_state if self.culture_on else "holy",
            "state_label": self.state_label if self.culture_on else "急行",
            "purifies": self.purifies,
            "drum_charge": self.drum_charge,
            "popularity": round(self.popularity, 1),
            "fever_threshold": self.fever_threshold,
            "rain_count": self.rain_count,
            "martial_count": self.martial_count,
            "guard_count": self.guard_count,
            "patrol_count": self.patrol_count,
            "stop_count": self.stop_count,
            "time_no_buff": round(self.time_no_buff, 3),
            "time_with_buff": round(self.time_s, 3),
            "rain_slow_beats": self.rain_slow_beats,
            "rain_boost_beats": self.rain_boost_beats,
        }

    def cycle_display(self) -> str:
        levels = list(self.cfg.display_levels)
        try:
            i = levels.index(self.cfg.display_level)
        except ValueError:
            i = 0
        self.cfg.display_level = levels[(i + 1) % len(levels)]
        return self.cfg.display_level


# ------------------------------------------------------------- 无头 / 对照
def _auto_session(cfg: RunnerConfig, tier: str, seed: int,
                  compound_rate: float | None = None,
                  culture: bool = False) -> RunnerSession:
    if compound_rate is not None:
        cfg.compound_rate = float(compound_rate)
    sess = RunnerSession(cfg, seed=seed, auto_plan=rm.PLANS[tier],
                         sigma=rm.TIER_SIGMA[tier], culture=culture)
    guard = 0
    while not sess.finished and guard < 4000:
        sess.step()
        guard += 1
    return sess


def headless_run(tier: str = "skilled", seed: int = 17,
                 cfg: RunnerConfig | None = None,
                 compound_rate: float | None = None,
                 culture: bool = False) -> dict:
    cfg = cfg or load_config()
    sess = _auto_session(cfg, tier, seed, compound_rate, culture)
    out = sess.result()
    out["leader"] = "wusong"
    out["seed"] = seed
    out["tier"] = tier
    return out


def culture_report(tier: str = "skilled", seed: int = 17,
                   cfg: RunnerConfig | None = None) -> dict:
    """无头跑一把文化三态，并与“不含新系统”的旧跑酷基线对比。"""
    cfg = cfg or load_config()
    with_culture = headless_run(tier, seed, cfg, culture=True)
    baseline = headless_run(tier, seed, cfg, culture=False)
    delta = with_culture["time_s"] - baseline["time_s"]
    return {
        "tier": tier, "seed": seed,
        "culture": with_culture, "baseline": baseline,
        "delta_s": round(delta, 3),
        "delta_pct": round(delta / max(1e-9, baseline["time_s"]) * 100.0, 2),
        "state_times": with_culture["splits"],
    }


def model_run(tier: str = "skilled", seed: int = 17,
              cfg: RunnerConfig | None = None,
              compound_rate: float | None = None) -> dict:
    """runner_model 同参数解析/逐拍结果，用作误差对照。"""
    cfg = cfg or load_config()
    rate = cfg.compound_rate if compound_rate is None else compound_rate
    res = rm.simulate("B", tier, seed=seed,
                      enemies=cfg.enemies, p_cap=cfg.p_cap,
                      gap_loss_beats=cfg.gap_loss_beats,
                      compound_rate=rate, compound_max=cfg.compound_max,
                      route=cfg.route_segments())
    return {"time_s": res.time_s, "hits": res.hits, "beats": res.beats,
            "avg_speed": res.distance / max(1e-9, res.time_s / cfg.beat_s),
            "perfect_rate": res.p_perfect, "splits": res.seg_times[:-1]}


def compare(tier: str = "skilled", seed: int = 17,
            cfg: RunnerConfig | None = None) -> dict:
    run = headless_run(tier, seed, cfg)
    model = model_run(tier, seed, cfg)
    err = abs(run["time_s"] - model["time_s"]) / max(1e-9, model["time_s"])
    return {"run": run, "model": model, "err": err, "within_2pct": err <= 0.02}


def sensitivity(seed: int = 17, cfg: RunnerConfig | None = None) -> dict:
    """复利敏感性：3.5% 之外再跑 2.0% / 5.0%，不改默认值。"""
    cfg = cfg or load_config()
    rows = {}
    for rate in (0.020, cfg.compound_rate, 0.050):
        nov = headless_run("novice", seed, cfg, compound_rate=rate)
        sk = headless_run("skilled", seed, cfg, compound_rate=rate)
        ms = headless_run("master", seed, cfg, compound_rate=rate)
        rows[rate] = {
            "novice_s": nov["time_s"],
            "master_minus_skilled_pct": (sk["time_s"] - ms["time_s"])
            / max(1e-9, ms["time_s"]),
        }
    # 恢复默认，避免配置对象被敏感性污染
    cfg.compound_rate = float(cfg.raw.get("compound_rate",
                                          rm.COMPOUND_RATE))
    return rows


# ---------------------------------------------------------------- 自测辅助
def measure_gap_loss(cfg: RunnerConfig | None = None) -> float:
    """实测一次“预警内变阵穿缝”多花的拍数。"""
    cfg = cfg or load_config()
    sess = RunnerSession(cfg, seed=7)
    target = cfg.route[1].recommend
    sess.formation = target
    sess.warning = {"target": target, "start_beat": 0, "contact_beat": 4}
    sess.switch_started_beat = 1
    sess.switch_done_beat = 2
    before = sess.elapsed_s
    sess._contact(1)
    return (sess.elapsed_s - before) / cfg.beat_s


def measure_hit_loss(cfg: RunnerConfig | None = None) -> float:
    """实测一次撞阵的等效损失拍：线性恢复期内 (1/v − 1) 的积分。"""
    cfg = cfg or load_config()
    tracker = rm.CollisionTracker(max_stacks=cfg.max_hit_stacks,
                                  p_cap=cfg.p_cap, enemies=cfg.enemies)
    tracker.hit("light")
    extra = 0.0
    for _ in range(20):
        v = rm.solve_speed(cfg.v_base, 1.0, 1.0, 1.0,
                           tracker.penalty(), 1.0, floor=cfg.v_floor)
        extra += (1.0 / v - 1.0)
        tracker.tick()
    return extra


def measure_rain_loss(cfg: RunnerConfig | None = None) -> float:
    """求雨净损拍数：6 拍慢板 0.86× 的等效延时 + 额外罚拍。"""
    cfg = cfg or load_config()
    c = cfg.culture
    slow_extra = c.rain_collect_beats * (1.0 / max(1e-9, c.rain_slow) - 1.0)
    return slow_extra + c.rain_penalty_beats
