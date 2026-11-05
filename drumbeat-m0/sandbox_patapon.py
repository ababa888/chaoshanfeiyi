"""沙盒：Patapon 阵法模式 S1 最小验证（无头，不改动主项目任何文件）。

对应《可行性报告》§6.4 / §7.7 的三项技术生死题：
  A. 拍量化行军位移：x = f(beat_pos) 闭式函数 —— 卡顿不漂移、不瞬移，换板连续
  B. 逐拍判定：拍 1-4 等权 Δt 评级（平行路径，绕开 judgement.py 的 1/3 拍吸附）
  C. 变阵完整度：交错过渡 + integrity 数值窗口（≥0.9 激活技能，乱阵 <0.9）

隔离边界（报告 §5.1）：只 import config / tempo / audio / synth 的公开 API；
不 import drumbeat.app；judgement.py / tempo.py / motion.py 等保护区零改动。

用法（在 drumbeat-m0 目录下）：
    python sandbox_patapon.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drumbeat.audio import NullAudioEngine    # noqa: E402
from drumbeat.config import DATA              # noqa: E402
from drumbeat.synth import Bank               # noqa: E402
from drumbeat.tempo import MusicDirector      # noqa: E402

STRIDE = 1.0            # 每拍行军步幅（世界单位）
FIXED = 1.0 / 120.0


def smoothstep(u: float) -> float:
    return u * u * (3.0 - 2.0 * u)


# ================================================================== A. 拍量化行军
class MarchAnchor:
    """虚拟质心：位置是 beat_pos 的纯函数，永不积分，因此永不漂移（报告 §6.2 方案 B）。

    S2 扩展：stride 倍率（长蛇提速）与乱阵冻结/恢复——两者都通过「重定基 x0」
    保持 x 连续：参数切换瞬间位置不跳变。"""

    def __init__(self, x0: float = 0.0):
        self.x0 = x0
        self.x = x0
        self.mult = 1.0
        self.frozen_beat: float | None = None   # 乱阵时冻结的拍位

    def _curve(self, b: float) -> float:
        whole = math.floor(b)
        return self.x0 + STRIDE * self.mult * (whole + smoothstep(b - whole))

    def x_at(self, b: float) -> float:
        if self.frozen_beat is not None:
            b = min(b, self.frozen_beat)
        return self._curve(b)

    def _rebase(self, x_cur: float, at_beat: float) -> None:
        whole = math.floor(at_beat)
        self.x0 = x_cur - STRIDE * self.mult * (whole + smoothstep(at_beat - whole))

    def set_mult(self, m: float, at_beat: float) -> None:
        x_cur = self.x_at(at_beat)
        self.mult = m
        self._rebase(x_cur, at_beat)

    def freeze(self, at_beat: float) -> None:
        self.frozen_beat = at_beat

    def resume(self, at_beat: float) -> None:
        x_cur = self.x_at(self.frozen_beat)
        self.frozen_beat = None
        self._rebase(x_cur, at_beat)

    def step(self, beat_pos: float) -> None:
        self.x = self.x_at(beat_pos)


def test_march(music: MusicDirector, clock: dict) -> list[str]:
    """A1 卡顿不瞬移（含 dt>0.25 防追帧守卫路径）；A2 存储位置恒等于闭式重算（零漂移）；
    A3 换板瞬间位移连续、拍 cadence 跟随新 BPM；A4 对照积分方案在卡顿中漂移。"""
    import random
    err: list[str] = []
    rng = random.Random(20261030).random

    anchor = MarchAnchor()
    integ_x = 0.0                     # 对照组：墙钟积分位移（错误示范）
    prev_x = 0.0
    prev_floor = 0
    prev_cross_t = 0.0
    stutter_at = {8.0: False, 18.0: False}
    switch_dx: float | None = None
    cadences: list[float] = []
    crossed_after_switch = 0
    layer_switched = False

    while clock["t"] < 26.0:
        dt = FIXED * (0.6 + 0.8 * rng())
        for ts, done in stutter_at.items():
            if not done and clock["t"] >= ts:
                dt = 0.4              # 模拟卡顿：触发 tempo.py 的 dt>0.25 守卫
                stutter_at[ts] = True
        clock["t"] += dt
        t = clock["t"]
        speed = 9.0 if t > 12.0 else 0.0     # t>12s 模拟长蛇阵提速 → 触发自然换板
        music.update(speed)

        b_before = music.beat_pos
        anchor.step(b_before)
        integ_x += STRIDE * (music.bpm / 60.0) * dt    # 对照组不看守卫，墙钟硬积

        # A1：相邻帧位移上界（无瞬移）；卡顿帧必须零位移
        dx = anchor.x - prev_x
        bound = STRIDE * (music.bpm / 60.0) * dt * 1.5 + 1e-9
        if dt > 0.25:
            if abs(dx) > 1e-12:
                err.append(f"A1 卡顿帧位移应为 0，实际 {dx:+.4f} (t={t:.2f})")
        elif dx < -1e-9 or dx > bound:
            err.append(f"A1 帧间位移越界 {dx:+.4f}（上界 {bound:.4f}，t={t:.2f}）")

        # A2：存储位置恒等于闭式重算（纯函数 ⇒ 任意卡顿后零漂移）
        if abs(anchor.x - anchor.x_at(b_before)) > 1e-12:
            err.append(f"A2 位置漂移 {anchor.x - anchor.x_at(b_before):+.2e} (t={t:.2f})")

        # 换板瞬间的位移连续性
        if music.layer_index != 0 and not layer_switched:
            layer_switched = True
            switch_dx = dx

        # 整数拍穿越：换板后记录拍 cadence
        fl = math.floor(b_before)
        if fl > prev_floor:
            if layer_switched and prev_cross_t > 0.0:
                cadences.append(t - prev_cross_t)
                crossed_after_switch += 1
            prev_cross_t = t
            prev_floor = fl

        prev_x = anchor.x

    if not layer_switched:
        err.append("A3 26 秒内未触发换板（speed 阈值路径失效？）")
    elif switch_dx is not None and switch_dx > STRIDE * 0.2:
        err.append(f"A3 换板帧位移不连续：{switch_dx:+.4f}")
    if crossed_after_switch >= 3:
        expect = 60.0 / music.bpm
        bad = [c for c in cadences[-3:] if abs(c - expect) > FIXED * 1.6]
        if bad:
            err.append(f"A3 换板后拍 cadence 偏离 {expect*1000:.0f}ms：{bad}")
    else:
        err.append("A3 换板后整数拍穿越样本不足")

    integ_err = abs(integ_x - anchor.x)
    if integ_err < 0.5 * STRIDE:
        err.append(f"A4 对照积分组应显著漂移（两次卡顿 ≈ 2 步幅），实际仅 {integ_err:.3f}")
    print(f"  [A] 行军 26s：x={anchor.x:.2f}，换板={'OK' if layer_switched else 'NO'}，"
          f"对照组漂移 {integ_err:.2f} 步幅（闭式组恒为 0）")
    return err


# ================================================================== B. 逐拍判定
def grade_beat_press(music: MusicDirector, t_press: float) -> tuple[int, float, str]:
    """平行判定路径（报告 §2.2）：对最近【任意拍】取 Δt，不经 judgement.py，
    避免 1/3 拍吸附与 streak/counts 统计污染。窗口数值复用 DATA.judgement。"""
    b = music.beat_at(t_press)
    n = round(b)
    dt_ms = (b - n) * (60000.0 / music.bpm)
    adt = abs(dt_ms)
    if adt <= float(DATA.judgement["perfect_ms"]):
        grade = "perfect"
    elif adt <= float(DATA.judgement["good_ms"]):
        grade = "good"
    else:
        grade = "off"
    return n % music.bar_beats + 1, dt_ms, grade


def advance_to(music: MusicDirector, clock: dict, t_target: float, speed: float = 0.0) -> None:
    """按固定步长推进虚拟时钟（模拟真实帧循环）。

    禁止直接 teleport：tempo.py:58 有 dt>0.25 防追帧守卫，
    大步跳变会让 beat_pos 停走，等效于游戏里的卡顿冻结。"""
    while clock["t"] < t_target:
        clock["t"] = min(clock["t"] + FIXED, t_target)
        music.update(speed)


def test_per_beat_judge(music: MusicDirector, clock: dict) -> list[str]:
    """B1 拍 2/4 上的按键相对本拍计 Δt（不吸附 1/3 拍）；B2 ±10ms 抖动全 perfect；
    B3 +100ms 脱拍判 off，且证明 judgement.py 的最近判定点确实会吸附走。"""
    err: list[str] = []
    bar_beats = music.bar_beats
    # 先以当前速度走 0.5s：让 _pending_layer 在新速度下挂牌，
    # 否则 time_at_beat 看不到即将到来的换板（真实主循环每帧 update，无此窗口）
    advance_to(music, clock, clock["t"] + 0.5)
    base = math.ceil(music.beat_pos) + 1
    jitters = [-10.0, 7.0, -4.0, 9.0, 3.0, -8.0, 5.0, -6.0]   # ±10ms 确定性抖动

    for k in range(8):
        abeat = base + k
        t_exact = music.time_at_beat(abeat, clock["t"])
        advance_to(music, clock, t_exact + jitters[k] / 1000.0)
        beat_in_bar, dt_ms, grade = grade_beat_press(music, clock["t"])
        want = abeat % bar_beats + 1
        if beat_in_bar != want:
            err.append(f"B1 拍位错认：按在拍 {want}，识别为拍 {beat_in_bar}")
        if abs(dt_ms) > 10.5:
            err.append(f"B2 拍 {want} 上 Δt={dt_ms:+.1f}ms 超出注入抖动 ±10ms")
        if grade != "perfect":
            err.append(f"B2 拍 {want} ±10ms 应判 perfect，实际 {grade}（Δt={dt_ms:+.1f}）")

    # B3：非判定点拍（拍 2/4，索引 %4 ∈ {1,3}）上 +100ms 脱拍 → off；
    # 且 judgement.py 的最近判定点确实会吸附到拍 1/3
    abeat = base + 8
    while abeat % bar_beats not in (1, 3):
        abeat += 1
    t_exact = music.time_at_beat(abeat, clock["t"])
    advance_to(music, clock, t_exact + 0.100)
    beat_in_bar, dt_ms, grade = grade_beat_press(music, clock["t"])
    if grade != "off":
        err.append(f"B3 +100ms 应判 off，实际 {grade}")
    b = music.beat_at(clock["t"])
    snapped = music.nearest_judge_beat(b)    # judgement.py 路径（只读调用，无副作用）
    if snapped == round(b):
        err.append("B3 拍 2 按键未被 1/3 拍吸附 —— 与 ADR-001 判定点设定不符？")
    print(f"  [B] 逐拍判定 8 键全 perfect（拍 1-4 等权）；+100ms 脱拍判 off，"
          f"judgement.py 吸附至拍 {snapped % bar_beats + 1}（平行路径判拍 {beat_in_bar}，Δt={dt_ms:+.1f}ms）")
    return err


# ================================================================== C. 变阵完整度
def _gen_wedge(n: int) -> list:
    """楔形箭头（猛虎）：1,2,2,…,2,1 分层，半宽 0.75·min(k, K−k)。"""
    K = max(1, math.ceil(n / 2))
    out: list = []
    for k in range(K + 1):
        yh = 0.75 * min(k, K - k)
        x = 0.3 - 0.9 * k
        if yh <= 1e-9:
            out.append((x, 0.0))
        else:
            out += [(x, yh), (x, -yh)]
        if len(out) >= n:
            break
    return out[:n]


GENERATORS = {
    "line": lambda n: [(-1.0 * i, 0.0) for i in range(n)],
    "block2": lambda n: [(-0.9 * (i % 4) - 0.45 * (i // 4), -0.9 * (i // 4)) for i in range(n)],
    "wedge": _gen_wedge,
}


def _load_formations() -> tuple[dict, dict, list, dict]:
    """S3/S4：阵型与成长表来自 sandbox_formations.json（数据驱动，报告 §6.1）。

    返回 (FORMATIONS[id] -> slots_fn(n), FSTATS, FORDER, GROWTH)。
    slots_fn 由 generator 支持任意人数（S4 扩编）；加载时校验
    n=len(slots) 的生成结果与 JSON 规范槽位一致。"""
    import json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_formations.json")
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    formations: dict = {}
    stats: dict = {}
    order: list[str] = []
    for fs in spec["formations"]:
        gen = GENERATORS[fs["generator"]]
        canonical = [(float(x), float(y)) for x, y in fs["slots"]]
        produced = gen(len(canonical))
        for (px, py), (cx, cy) in zip(produced, canonical):
            if abs(px - cx) > 1e-9 or abs(py - cy) > 1e-9:
                raise ValueError(f"阵型 {fs['id']} 生成器与规范槽位不一致：{produced} vs {canonical}")
        formations[fs["id"]] = gen
        stats[fs["id"]] = dict(fs["stats"])
        order.append(fs["id"])
    return formations, stats, order, dict(spec["growth"])


FORMATIONS, FSTATS, FORDER, GROWTH = _load_formations()
# 阵型技能缺省值（integrity < SKILL_ON 或乱阵时全队生效）
DEFAULT_STATS = {"speed_mult": 1.0, "damage_mult": 1.0, "damage_taken_mult": 1.0,
                 "pierce": False, "knockback_immune": False, "aoe_radius": 0.0}
INTEGRITY_R = 0.7         # 完整度容差半径（世界单位）
SKILL_ON = 0.9            # 技能激活阈值


class FormationMorph:
    """交错过渡（报告 §7.3）：单位 i 的窗口 = [start + i·stagger, +window]，
    expected = 过渡曲线上的应处位置；integrity 相对 expected 计算，
    使变阵期的正常跟随不产生误罚（对照：相对终态槽位会误跌）。"""

    def __init__(self, old: list, new: list, start_beat: float, stagger: float = 0.2, window: float = 3.0):
        self.old, self.new = old, new
        self.start, self.stagger, self.window = start_beat, stagger, window

    def expected(self, i: int, b: float) -> tuple[float, float]:
        p = (b - (self.start + i * self.stagger)) / self.window
        if p <= 0.0:
            return self.old[i]
        if p >= 1.0:
            return self.new[i]
        u = smoothstep(p)
        ox, oy = self.old[i]
        nx, ny = self.new[i]
        return ox + (nx - ox) * u, oy + (ny - oy) * u


class UnitBody:
    """阻尼跟随者（报告 §6.1 第三层）：朝应处槽位收敛，无碰撞无重力。"""

    K = 22.0              # 跟随刚度（1/s）

    def __init__(self, x: float, y: float):
        self.x, self.y = x, y

    def follow(self, tx: float, ty: float, dt: float) -> None:
        a = 1.0 - math.exp(-self.K * dt)
        self.x += (tx - self.x) * a
        self.y += (ty - self.y) * a


def integrity(units: list[UnitBody], expected: list[tuple[float, float]]) -> float:
    mean_err = sum(math.hypot(u.x - ex, u.y - ey) for u, (ex, ey) in zip(units, expected)) / len(units)
    return max(0.0, min(1.0, 1.0 - mean_err / INTEGRITY_R))


def test_formation() -> list[str]:
    """C1 稳态 integrity≈1；C2 变阵全程（相对 expected）≥0.9 技能不断；
    C3 变阵结束 ≥0.99；C4 乱阵散射 <0.9 技能关闭；
    C5 对照：相对终态槽位的朴素算法在变阵中期 <0.9（证明 expected 路径定义必要）。"""
    err: list[str] = []
    n = 8
    old = FORMATIONS["changshe"](n)
    new = FORMATIONS["tiebi"](n)
    units = [UnitBody(x, y) for x, y in old]
    bpm_rate = 90.0 / 60.0                      # 90 BPM → 1.5 拍/秒
    morph = FormationMorph(old, new, start_beat=2.0)
    min_during, max_naive_dip = 1.0, 1.0
    b = 0.0
    while b < 9.0:
        dt_beat = FIXED * bpm_rate
        b += dt_beat
        exp = [morph.expected(i, b) for i in range(n)]
        for u, (ex, ey) in zip(units, exp):
            u.follow(ex, ey, FIXED)
        integ = integrity(units, exp)
        if b < 2.0:
            if integ < 0.99:
                err.append(f"C1 稳态完整度 {integ:.3f} < 0.99 (b={b:.2f})")
        elif 2.0 <= b < 2.0 + (n - 1) * morph.stagger + morph.window:
            min_during = min(min_during, integ)
            naive = integrity(units, new)        # 对照：相对终态槽位
            max_naive_dip = min(max_naive_dip, naive)
        else:
            if integ < 0.99:
                err.append(f"C3 变阵结束完整度 {integ:.3f} < 0.99 (b={b:.2f})")

    if min_during < SKILL_ON:
        err.append(f"C2 变阵全程完整度最低 {min_during:.3f} < {SKILL_ON}（技能会误断）")
    if max_naive_dip >= SKILL_ON:
        err.append(f"C5 朴素算法应跌破 {SKILL_ON}，实际最低 {max_naive_dip:.3f}（对照不成立）")

    # C4：乱阵 = 散射（seeded），完整度必须跌破技能阈值
    rng = [346346435, 967778, 12412, 7857383, 536456, 9568678, 2352456, 876543]
    for i, u in enumerate(units):
        u.x += ((rng[i] % 1000) / 1000.0 - 0.5) * 5.0
        u.y += ((rng[(i + 3) % n] % 1000) / 1000.0 - 0.5) * 4.0
    scattered = integrity(units, [morph.expected(i, b) for i in range(n)])
    if scattered >= SKILL_ON:
        err.append(f"C4 乱阵完整度 {scattered:.3f} 应 < {SKILL_ON}")

    print(f"  [C] 变阵 {n} 人 长蛇→铁壁：全程最低完整度 {min_during:.3f}（阈值 {SKILL_ON}），"
          f"朴素算法同期最低 {max_naive_dip:.3f}（会误断），乱阵散射后 {scattered:.3f}")
    return err


# ================================================================== S2. 四相循环
COMMANDS = {"JJJJ": "attack4", "KKKK": "stride", "LLLL": "defend", "KLKL": "morph"}
CHANT_GAIN = 0.63                # 应答唱和增益（避开背景鼓的既有档位，便于区分）
DT2 = 1.0 / 480.0                # S2 仿真步长（拍穿越测量误差 ≤2.1ms，满足 ±5ms 验收）


class RecordingAudio(NullAudioEngine):
    """记录每次 schedule 的（目标时刻, 样本 id），供应答唱和数值验收。"""

    def __init__(self) -> None:
        super().__init__()
        self.scheduled: list[tuple[float, int]] = []

    def schedule(self, t: float, data, gain: float = 1.0) -> None:
        self.scheduled.append((t, id(data)))


class SandboxMusic(MusicDirector):
    """子类化（非修改，报告 §2.5）：输入小节静音背景鼓。

    在 audio.schedule 出口处丢弃而非跳过 _ev_i 递增，
    保证事件索引照常推进，恢复后不会补播过期事件。"""

    def __init__(self, *args, phase_fn, **kwargs):
        super().__init__(*args, **kwargs)
        self._phase_fn = phase_fn

    def _schedule(self, now: float) -> None:
        if self._phase_fn() != "input":
            super()._schedule(now)
            return
        orig = self.audio.schedule
        self.audio.schedule = lambda *a, **k: None
        try:
            super()._schedule(now)
        finally:
            self.audio.schedule = orig


class BeatScheduler:
    """拍事件有序队列：「第 N 拍执行 X」→ 拍位到达时触发（报告 §5.2）。"""

    def __init__(self, music: MusicDirector) -> None:
        self.music = music
        self.q: list[tuple[float, tuple]] = []

    def schedule_at_beat(self, abeat: float, payload: tuple) -> None:
        self.q.append((abeat, payload))
        self.q.sort(key=lambda e: e[0])

    def poll(self) -> list[tuple]:
        out = []
        b = self.music.beat_pos
        while self.q and self.q[0][0] <= b + 1e-6:
            out.append(self.q.pop(0)[1])
        return out


class RhythmCommander:
    """输入小节采集 4 次按键 → 逐拍评级 → 匹配指令表（报告 §5.2）。"""

    def __init__(self, music: MusicDirector) -> None:
        self.music = music
        self.presses: list[tuple[str, str, int, float]] = []

    def on_press(self, key: str, t: float) -> None:
        bib, dt_ms, grade = grade_beat_press(self.music, t)
        self.presses.append((key, grade, bib, dt_ms))

    def evaluate(self) -> str | None:
        if len(self.presses) != 4:
            return None
        if any(g == "off" for _, g, _, _ in self.presses):
            return None
        return COMMANDS.get("".join(k for k, *_ in self.presses))

    def clear(self) -> None:
        self.presses.clear()


class Enemy:
    """S3 最小敌人：站位 + HP（沙盒纯平地，无 AI）。"""

    def __init__(self, x: float, hp: float = 30.0):
        self.x = x
        self.hp = hp
        self.dead = False


class Boss:
    """S3 最小 Boss：锚点逼近后预警，active_beat 帧结算破阵（报告 §6.2 破阵窗口）。

    破阵判定与 combat.py:104 对击窗口同构：
    激活帧检查 阵型 ∈ breakable_by 且 integrity ≥ SKILL_ON。"""

    def __init__(self, x: float, breakable_by: list, hp: float = 200.0, dmg: float = 40.0, kb: float = 1.5):
        self.x = x
        self.hp = hp
        self.dmg = dmg
        self.kb = kb
        self.breakable_by = list(breakable_by)
        self.state = "idle"               # idle / startup / done
        self.active_beat = -1.0


# ---- S3 动作库（报告 §7.1：姿态 = 拍相位闭式函数，零积分）
def leap_y(p: float, h: float = 1.2) -> float:
    """跃起劈山：闭式抛物线，p∈[0,1] 为一个动作拍，两端落地精确卡拍。"""
    p = max(0.0, min(1.0, p))
    return 4.0 * h * p * (1.0 - p)


def march_bob(b: float, amp: float = 0.12) -> float:
    """行军摆动：三角波，整数拍归零（步伐钉在拍点上，卡帧的「卡」）。"""
    frac = b % 1.0
    return amp * (1.0 - abs(2.0 * frac - 1.0))


class SquadGame:
    """四相循环：input(输入) → echo(应答唱和) → execute(执行) → input…
    输入失败 → luan(乱阵) 一小节 → 下一小节边界复阵（ADR-001 惯用法）。"""

    def __init__(self, unlock_all: bool = False) -> None:
        self.audio = RecordingAudio()
        self.audio.start()
        self.clock = {"t": 0.0}
        self.audio.audio_time = lambda: self.clock["t"]
        self.bank = Bank()
        self.phase = "input"
        self.music = SandboxMusic(self.audio, self.bank, phase_fn=lambda: self.phase)
        self.music.last_t = 0.0
        self.anchor = MarchAnchor()
        self.commander = RhythmCommander(self.music)
        self.scheduler = BeatScheduler(self.music)

        self.fids = FORDER
        self.fid = 0
        self.n_units = 8
        self.cur_slots = FORMATIONS[self.fids[0]](self.n_units)
        self.units = [UnitBody(x, y) for x, y in self.cur_slots]
        self.morph: FormationMorph | None = None

        self.bar = 0
        self.command: str | None = None
        self.defend_until = -1.0
        self.events: list[tuple[float, str, object]] = []
        self.chant = self.bank.samples.get("台")
        if self.chant is None:
            self.chant = next(iter(self.bank.samples.values()))
        self.measured_beat_t: dict[int, float] = {}
        self._prev_floor = 0
        self.x_series: list[tuple[float, int, float]] = []        # (t, bar, x)
        self.integrity_series: list[tuple[float, str, float]] = []

        # ---- S3：阵型数值 / 战斗 / Boss
        self.enemies: list = []
        self.boss: Boss | None = None
        self.squad_hp = 100.0
        self.cmd_mult = 1.0                  # 指令层提速（KKKK），与阵型 speed_mult 相乘
        self.integrity = 1.0                 # 上一拍完整度（供 stats 门控与破阵检查）

        # ---- S4：成长（击杀 → 解锁阵型 + 扩编）
        self.kills = 0
        self.unlocked: set = set(FORDER) if unlock_all else {"changshe"}
        self._grown: set = set()             # 已生效的扩编档位

    # ------------------------------------------------------------- 小节边界
    def _chant(self, bar: int) -> None:
        now = self.clock["t"]
        for k in range(4):
            t = self.music.time_at_beat(bar * 4 + k, now)
            self.audio.schedule(t, self.chant, CHANT_GAIN)
        self.events.append((now, "chant", bar))

    def _execute(self, bar: int) -> None:
        cmd = self.command
        now = self.clock["t"]
        if cmd == "attack4":
            for k in range(4):
                self.scheduler.schedule_at_beat(bar * 4 + k, ("attack", k))
        elif cmd == "stride":
            self.cmd_mult = 1.5
            self.scheduler.schedule_at_beat(bar * 4 + 4, ("stride_end", None))
        elif cmd == "defend":
            self.defend_until = bar * 4 + 4
            self.events.append((now, "defend_on", bar))
        elif cmd == "morph":
            self.switch_formation(self.fid + 1, bar * 4)

    def on_bar(self, bar: int) -> None:
        if self.phase == "input":
            self.command = self.commander.evaluate()
            self.commander.clear()
            if self.command is None:
                self.anchor.freeze(self.music.beat_pos)
                self.phase = "luan"
                self.events.append((self.clock["t"], "luan", bar))
            else:
                self.phase = "echo"
                self._chant(bar)
        elif self.phase == "echo":
            self.phase = "execute"
            self._execute(bar)
        elif self.phase == "execute":
            self.phase = "input"
        elif self.phase == "luan":
            self.anchor.resume(self.music.beat_pos)
            self.phase = "input"

    # ------------------------------------------------------------- 步进
    def tick(self, dt: float) -> None:
        self.clock["t"] += dt
        self.music.update(0.0)
        b = self.music.beat_pos
        bar = int(b // 4)
        if bar != self.bar:
            self.bar = bar
            self.on_bar(bar)
        fl = math.floor(b)
        if fl > self._prev_floor:
            self.measured_beat_t[fl] = self.clock["t"]
            self._prev_floor = fl
        for kind, val in self.scheduler.poll():
            self.events.append((self.clock["t"], kind, val))
            if kind == "stride_end":
                self.cmd_mult = 1.0
            elif kind == "attack":
                self._resolve_attack()
        # 行军速度 = 指令倍率 × 阵型速度（仅 integrity≥0.9 时阵型部分生效）
        want = self.cmd_mult * self.stats["speed_mult"]
        if abs(want - self.anchor.mult) > 1e-9:
            self.anchor.set_mult(want, b)
        self.anchor.step(b)
        expected = [self.morph.expected(i, b) if self.morph else self.cur_slots[i]
                    for i in range(self.n_units)]
        for u, (ex, ey) in zip(self.units, expected):
            u.follow(ex, ey, dt)
        integ = 0.0 if self.phase == "luan" else integrity(self.units, expected)
        self.integrity = integ
        self._update_boss(b)
        self.integrity_series.append((b, self.phase, integ))
        self.x_series.append((self.clock["t"], bar, self.anchor.x))

    def advance(self, t_target: float) -> None:
        while self.clock["t"] < t_target:
            self.tick(DT2)

    def inject_bar_presses(self, bar: int, keys: str, jitters: list[float]) -> None:
        for k, key in enumerate(keys):
            ab = bar * 4 + k
            t = self.music.time_at_beat(ab, self.clock["t"]) + jitters[k] / 1000.0
            self.advance(t)
            self.commander.on_press(key, self.clock["t"])

    # ------------------------------------------------------------- S3 战斗
    @property
    def stats(self) -> dict:
        """阵型数值门控（报告 §6.1）：integrity ≥ 0.9 才激活，否则全队缺省。"""
        if self.phase != "luan" and self.integrity >= SKILL_ON:
            return FSTATS[self.fids[self.fid]]
        return DEFAULT_STATS

    def switch_formation(self, fid_index: int, start_beat: float) -> None:
        """循环切换到下一个【已解锁】阵型（S4 解锁门控；fid_index 保留兼容）。"""
        order = [f for f in self.fids if f in self.unlocked]
        cur = self.fids[self.fid]
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
        self.fid = self.fids.index(nxt)
        new = FORMATIONS[nxt](self.n_units)
        self.morph = FormationMorph(self.cur_slots, new, start_beat=start_beat)
        self.cur_slots = new
        self.events.append((self.clock["t"], "morph", nxt))

    def _check_growth(self) -> None:
        for fid, need in GROWTH["unlock_kills"].items():
            if self.kills >= need and fid not in self.unlocked:
                self.unlocked.add(fid)
                self.events.append((self.clock["t"], "unlock", fid))
        for step in GROWTH["size_steps"]:
            key = step["kills"]
            if self.kills >= key and key not in self._grown and self.n_units < step["n"]:
                self._grown.add(key)
                self._grow_to(step["n"])

    def _grow_to(self, n: int) -> None:
        """扩编：新兵自锚点入列（阻尼跟随归位，integrity 短暂下探后回升）。"""
        for _ in range(n - self.n_units):
            self.units.append(UnitBody(self.anchor.x * 0.0, 0.0))   # 槽位空间原点附近
        self.n_units = n
        self.morph = None                       # 旧变阵的槽位表人数已失效
        self.cur_slots = FORMATIONS[self.fids[self.fid]](n)
        self.events.append((self.clock["t"], "grow", n))

    def _resolve_attack(self) -> None:
        """攻击结算：长蛇穿透全线 / 猛虎 AOE 半径 / 其余单体最近（报告 §6.1 技能表）。"""
        st = self.stats
        ahead = sorted((e for e in self.enemies
                        if not e.dead and self.anchor.x - 0.5 <= e.x <= self.anchor.x + 2.5),
                       key=lambda e: e.x)
        if not ahead:
            self.events.append((self.clock["t"], "miss", None))
            return
        dmg = 25.0 * st["damage_mult"]
        if st["aoe_radius"] > 0.0:
            c = ahead[0].x
            targets = [e for e in self.enemies if not e.dead and abs(e.x - c) <= st["aoe_radius"]]
        elif st["pierce"]:
            targets = ahead
        else:
            targets = [ahead[0]]
        for e in targets:
            e.hp -= dmg
            if e.hp <= 0.0 and not e.dead:
                e.dead = True
                self.kills += 1
        self.events.append((self.clock["t"], "hit", len(targets)))
        self._check_growth()

    def squad_hit(self, dmg: float, kb: float) -> None:
        """受击：铁壁减伤 0.4 且免疫击退；击退伴随散射 → integrity 自然下跌。"""
        self.squad_hp -= dmg * self.stats["damage_taken_mult"]
        if kb > 0.0 and not self.stats["knockback_immune"]:
            self.anchor.x0 -= kb                       # 击退位移（有意打破连续性）
            rng = [346346435, 967778, 12412, 7857383, 536456, 9568678, 2352456, 876543]
            for i, u in enumerate(self.units):
                u.x += ((rng[i % 8] % 1000) / 1000.0 - 0.5) * 2.0
                u.y += ((rng[(i + 3) % 8] % 1000) / 1000.0 - 0.5) * 1.5

    def _update_boss(self, b: float) -> None:
        boss = self.boss
        if boss is None or boss.state == "done":
            return
        if boss.state == "idle":
            if self.anchor.x >= boss.x - 6.0:
                boss.state = "startup"
                boss.active_beat = math.ceil(b / 4) * 4 + 6   # 预警 1 小节 + 2 拍缓冲
                self.events.append((self.clock["t"], "boss_warn", boss.active_beat))
        elif boss.state == "startup" and b >= boss.active_beat:
            if self.fids[self.fid] in boss.breakable_by and self.integrity >= SKILL_ON:
                boss.hp -= 60.0
                self.events.append((self.clock["t"], "break_ok", boss.hp))
            else:
                self.squad_hit(boss.dmg, boss.kb)
                self.events.append((self.clock["t"], "break_fail", self.squad_hp))
            boss.state = "done"


def test_s2_cycle() -> list[str]:
    """S2 验收：四相循环 + 应答唱和 + 指令执行 + 乱阵 + 背景鼓静音。

    剧本（每小节 4 拍，90BPM ≈ 2.67s/小节）：
      bar0 输入 JJJJ → bar1 应答 → bar2 执行攻击×4
      bar3 输入 KKKK → bar4 应答 → bar5 执行提速 1.5×
      bar6 输入 KLKL → bar7 应答 → bar8 执行变阵 长蛇→铁壁
      bar9 输入 JJ（缺拍）→ bar10 乱阵 → bar11 复阵输入 LLLL
      bar12 应答 → bar13 执行防守"""
    err: list[str] = []
    g = SquadGame(unlock_all=True)           # S2 不测解锁门控（S4 职责）
    JIT = [6.0, -8.0, 4.0, -5.0]
    plans = {0: "JJJJ", 3: "KKKK", 6: "KLKL", 9: "JJ", 11: "LLLL"}
    injected: set[int] = set()
    while g.bar < 13:                       # 停在 bar13 执行小节内，避免 bar14 空输入再乱阵
        if g.phase == "input" and g.bar in plans and g.bar not in injected:
            g.inject_bar_presses(g.bar, plans[g.bar], JIT)
            injected.add(g.bar)
        else:
            g.advance(g.clock["t"] + 0.05)
    g.advance(g.clock["t"] + 0.5)           # 让 bar13 的 defend_on 事件落地

    kinds = [k for _, k, _ in g.events]

    # S2-1 指令识别：4 条合法指令全部识别（恰好 1 次乱阵来自 bar9 缺拍）
    if kinds.count("luan") != 1:
        err.append(f"S2-1 乱阵应恰好 1 次（bar9 缺拍），实际 {kinds.count('luan')} 次：{kinds}")
    if kinds.count("attack") != 4:
        err.append(f"S2-1 JJJJ 应产生 4 次攻击事件，实际 {kinds.count('attack')}")
    for want in ("stride_end", "defend_on", "morph"):
        if want not in kinds:
            err.append(f"S2-1 缺少 {want} 事件（指令未识别或未执行）")
    if ("morph" in kinds) and g.events[kinds.index("morph")][2] != "tiebi":
        err.append("S2-1 KLKL 应变阵为 tiebi（铁壁）")

    # S2-2 应答唱和：4 个应答小节 × 4 声，schedule 时刻与拍点误差 ≤5ms
    chant_id = id(g.chant)
    chant_times = sorted(t for t, d in g.audio.scheduled if d == chant_id)
    if len(chant_times) != 16:
        err.append(f"S2-2 应答唱和应 16 声（4 小节 × 4 拍），实际 {len(chant_times)}")
    else:
        worst = 0.0
        for echo_bar in (1, 4, 7, 12):
            for k in range(4):
                beat = echo_bar * 4 + k
                meas = g.measured_beat_t.get(beat)
                sched = chant_times[(1, 4, 7, 12).index(echo_bar) * 4 + k]
                if meas is None or abs(sched - meas) > 0.005:
                    err.append(f"S2-2 拍 {beat} 唱和偏差 {(sched - (meas or 0)) * 1000:+.1f}ms > 5ms")
                worst = max(worst, abs(sched - (meas or 0)))
        print(f"  [S2] 应答唱和 16 声，最大调度偏差 {worst * 1000:.1f}ms（容差 5ms）")

    # S2-3 执行同步：JJJJ 的 4 次攻击落在执行小节拍点 ±30ms
    atk = [(t, v) for t, k, v in g.events if k == "attack"]
    for t, k in atk:
        beat = 2 * 4 + k
        meas = g.measured_beat_t.get(beat)
        if meas is None or abs(t - meas) > 0.030:
            err.append(f"S2-3 攻击 {k} 与拍 {beat} 偏差 {(t - (meas or 0)) * 1000:+.1f}ms > 30ms")
    print(f"  [S2] 攻击×4 执行偏差 ≤ {max(abs(t - g.measured_beat_t[8 + k]) for t, k in atk) * 1000:.1f}ms（容差 30ms）")

    # S2-4 乱阵：bar10 全程锚点冻结、integrity=0；bar11 复阵位置连续
    luan_x = [x for _, bar, x in g.x_series if bar == 10]
    if luan_x and max(luan_x) - min(luan_x) > 1e-9:
        err.append(f"S2-4 乱阵期间锚点应冻结，位移 {max(luan_x) - min(luan_x):.4f}")
    if any(i != 0.0 for _, ph, i in g.integrity_series if ph == "luan"):
        err.append("S2-4 乱阵期间 integrity 应恒为 0")
    resume = [(bar, x) for _, bar, x in g.x_series if bar in (10, 11)]
    if resume:
        x10 = [x for bar, x in resume if bar == 10][-1]
        x11 = [x for bar, x in resume if bar == 11][0]
        if abs(x11 - x10) > 1e-6:
            err.append(f"S2-4 复阵位置不连续：{x10:.4f} → {x11:.4f}")
    print(f"  [S2] 乱阵 1 小节：锚点冻结、integrity=0、复阵连续（Δx={abs(x11 - x10):.2e}）")

    # S2-5 背景鼓静音：输入小节中后段无非唱和事件；执行小节有背景鼓
    bar_t = {b: g.measured_beat_t[b * 4] for b in range(14) if b * 4 in g.measured_beat_t}
    for ib in (0, 3, 6, 9, 11):
        t0, t1 = bar_t.get(ib, 0) + 0.3, bar_t.get(ib + 1, 9e9)
        n_bg = sum(1 for t, d in g.audio.scheduled if d != chant_id and t0 <= t < t1)
        if n_bg != 0:
            err.append(f"S2-5 输入小节 bar{ib} 背景鼓未静音（{n_bg} 个事件）")
    t0, t1 = bar_t.get(2, 0), bar_t.get(3, 9e9)
    n_exec = sum(1 for t, d in g.audio.scheduled if d != chant_id and t0 <= t < t1)
    if n_exec == 0:
        err.append("S2-5 执行小节 bar2 背景鼓应正常播放")
    print(f"  [S2] 背景鼓静音：输入小节 0 事件，执行小节 bar2 有 {n_exec} 事件")

    # S2-6 提速指令：执行小节（mult 1.5）行军距离 ≈ 常规小节 1.5 倍
    dist = {}
    for b0 in (1, 5):
        xs = [x for _, bar, x in g.x_series if bar == b0]
        if xs:
            dist[b0] = xs[-1] - xs[0]
    if len(dist) == 2 and abs(dist[5] / dist[1] - 1.5) > 0.05:
        err.append(f"S2-6 提速小节节距比 {dist[5] / dist[1]:.2f} ≠ 1.5")
    print(f"  [S2] 提速：bar5/bar1 节距比 {dist.get(5, 0) / max(dist.get(1, 1e-9), 1e-9):.2f}（期望 1.5）")

    # S2-7 变阵：发生在小节边界 ±30ms；变阵全程 integrity ≥0.9
    if "morph" in kinds:
        t_m = g.events[kinds.index("morph")][0]
        meas = g.measured_beat_t.get(8 * 4)
        if meas is None or abs(t_m - meas) > 0.030:
            err.append(f"S2-7 变阵未落在小节边界（偏差 {(t_m - (meas or 0)) * 1000:+.1f}ms）")
        integ8 = [i for b, _, i in g.integrity_series if 8 * 4 <= b < 9 * 4]
        if integ8 and min(integ8) < SKILL_ON:
            err.append(f"S2-7 变阵全程 integrity 最低 {min(integ8):.3f} < {SKILL_ON}")
        print(f"  [S2] 变阵：长蛇→铁壁 @小节边界，bar8 最低 integrity {min(integ8):.3f}")

    n_ev = len(g.events)
    print(f"  [S2] 四相循环 14 小节跑通，事件 {n_ev} 个："
          + ", ".join(f"{k}×{kinds.count(k)}" for k in dict.fromkeys(kinds)))
    return err


def test_s3() -> list[str]:
    """S3 验收：JSON 阵型数值 + 技能门控 + 穿透/AOE + 免击退 + Boss 破阵 + 动作卡拍。"""
    err: list[str] = []

    # S3-1 JSON 数据驱动：三阵型齐全、8 槽位、数值键完整
    if FORDER != ["changshe", "tiebi", "menghu"]:
        err.append(f"S3-1 阵型顺序异常：{FORDER}")
    for fid in FORDER:
        if len(FORMATIONS[fid](8)) != 8:
            err.append(f"S3-1 {fid} 槽位数 ≠ 8")
        for key in ("speed_mult", "damage_mult", "damage_taken_mult",
                    "pierce", "knockback_immune", "aoe_radius"):
            if key not in FSTATS[fid]:
                err.append(f"S3-1 {fid} 缺数值键 {key}")

    def mk_game(fid_idx: int) -> SquadGame:
        g = SquadGame()
        g.fid = fid_idx
        g.cur_slots = FORMATIONS[g.fids[fid_idx]](g.n_units)
        g.units = [UnitBody(x, y) for x, y in g.cur_slots]
        g.integrity = 1.0
        return g

    # S3-2 技能门控：integrity≥0.9 激活阵型数值，跌破则回缺省
    g = mk_game(0)
    if g.stats["damage_taken_mult"] != 1.25:
        err.append(f"S3-2 长蛇承伤应 1.25，实际 {g.stats['damage_taken_mult']}")
    g.integrity = 0.5
    if g.stats is not DEFAULT_STATS:
        err.append("S3-2 integrity<0.9 时技能应回缺省")

    # S3-3 穿透 vs 单体
    g = mk_game(0)                                    # 长蛇：穿透
    g.enemies = [Enemy(1.0), Enemy(1.8), Enemy(2.4)]
    g._resolve_attack()
    if sum(1 for e in g.enemies if e.hp < 30) != 3:
        err.append("S3-3 长蛇穿透应命中全部 3 个敌人")
    g = mk_game(1)                                    # 铁壁：单体
    g.enemies = [Enemy(1.0), Enemy(1.8)]
    g._resolve_attack()
    if sum(1 for e in g.enemies if e.hp < 30) != 1:
        err.append("S3-3 铁壁应只命中最近 1 个敌人")

    # S3-4 猛虎 AOE：半径 3.0 覆盖次目标、排除远处；伤害倍率 1.5
    g = mk_game(2)
    g.enemies = [Enemy(1.0), Enemy(2.5), Enemy(5.0)]
    g._resolve_attack()
    hits = [e.hp < 30 for e in g.enemies]
    if hits != [True, True, False]:
        err.append(f"S3-4 猛虎 AOE 命中模式错误：{hits}")
    if abs(g.enemies[0].hp - (30 - 25 * 1.5)) > 1e-9:
        err.append(f"S3-4 猛虎伤害倍率应 1.5（hp={g.enemies[0].hp}）")

    # S3-5 铁壁免击退 + 减伤 0.4；长蛇不免击退 + 承伤 1.25
    g = mk_game(1)
    x0 = g.anchor.x0
    g.squad_hit(40.0, 1.5)
    if abs(g.anchor.x0 - x0) > 1e-9:
        err.append("S3-5 铁壁应免疫击退位移")
    if abs(g.squad_hp - 84.0) > 1e-9:
        err.append(f"S3-5 铁壁减伤 0.4 后 hp 应 84，实际 {g.squad_hp}")
    g = mk_game(0)
    x0 = g.anchor.x0
    g.squad_hit(40.0, 1.5)
    if abs(g.anchor.x0 - (x0 - 1.5)) > 1e-9:
        err.append("S3-5 长蛇应被击退 1.5")
    if abs(g.squad_hp - 50.0) > 1e-9:
        err.append(f"S3-5 长蛇承伤 1.25 后 hp 应 50，实际 {g.squad_hp}")

    # S3-6 Boss 破阵：预警后变铁壁 → 存活反伤；保持长蛇 → 掉血击退 + integrity 崩
    def run_boss(switch: bool) -> SquadGame:
        g = SquadGame(unlock_all=True)       # S3 不测解锁门控（S4 职责）
        g.boss = Boss(14.0, breakable_by=["tiebi"])
        plans = {0: "KLKL"} if switch else {}
        injected: set[int] = set()
        guard = 0
        while g.boss.state != "done" and guard < 40000:
            guard += 1
            if g.phase == "input" and g.bar not in injected:
                g.inject_bar_presses(g.bar, plans.get(g.bar, "JJJJ"), [5.0, -6.0, 4.0, -7.0])
                injected.add(g.bar)
            else:
                g.advance(g.clock["t"] + 0.05)
        return g

    g_ok = run_boss(True)
    kinds_ok = [k for _, k, _ in g_ok.events]
    if "boss_warn" not in kinds_ok:
        err.append("S3-6 Boss 未预警")
    if "break_ok" not in kinds_ok:
        err.append(f"S3-6 变铁壁应破阵成功，事件：{kinds_ok}")
    if abs(g_ok.squad_hp - 100.0) > 1e-9:
        err.append(f"S3-6 破阵成功应零伤亡，hp={g_ok.squad_hp}")
    g_ng = run_boss(False)
    kinds_ng = [k for _, k, _ in g_ng.events]
    if "break_fail" not in kinds_ng:
        err.append(f"S3-6 保持长蛇应破阵失败，事件：{kinds_ng}")
    if g_ng.squad_hp >= 100.0:
        err.append("S3-6 破阵失败应掉血")
    tail = [i for _, _, i in g_ng.integrity_series[-400:]]
    if tail and min(tail) >= SKILL_ON:
        err.append(f"S3-6 破阵失败后 integrity 应跌破 {SKILL_ON}（击退散射）")
    print(f"  [S3] Boss 破阵：变铁壁→break_ok(hp={g_ok.squad_hp:.0f})，"
          f"长蛇→break_fail(hp={g_ng.squad_hp:.0f}, 事后最低 integrity {min(tail):.2f})")

    # S3-7 动作卡拍：跃起抛物线两端落地、行军摆动整数拍归零（闭式保证 <1 帧）
    if leap_y(0.0) != 0.0 or abs(leap_y(1.0)) > 1e-12 or abs(leap_y(0.5) - 1.2) > 1e-9:
        err.append("S3-7 跃起抛物线端点/顶点错误")
    if any(abs(march_bob(float(k))) > 1e-12 for k in range(8)):
        err.append("S3-7 行军摆动应在整数拍归零")

    print(f"  [S3] 阵型数值：长蛇穿透×3 / 铁壁单体+免击退 / 猛虎 AOE×2(半径3.0) 全部应验")
    return err


def test_s4() -> list[str]:
    """S4 验收：生成器一致性、解锁门控、扩编归位、长流程成长整合。"""
    err: list[str] = []

    # S4-1 生成器：n ∈ {4,8,12,16} 槽位数正确；加载时已校验 n=8 与规范一致
    for fid in FORDER:
        for n in (4, 8, 12, 16):
            if len(FORMATIONS[fid](n)) != n:
                err.append(f"S4-1 {fid} 生成 {n} 槽位失败")

    # S4-2 解锁门控：0 击杀只能长蛇；5 杀解锁铁壁；12 杀解锁猛虎
    g = SquadGame()
    g.switch_formation(0, 0.0)
    if g.fids[g.fid] != "changshe":
        err.append(f"S4-2 未解锁时应保持长蛇，实际 {g.fids[g.fid]}")
    g.kills = 5
    g._check_growth()
    g.switch_formation(0, 0.0)
    if g.fids[g.fid] != "tiebi":
        err.append(f"S4-2 5 杀应解锁铁壁，实际 {g.fids[g.fid]}")
    g.kills = 12
    g._check_growth()
    g.switch_formation(0, 0.0)
    if g.fids[g.fid] != "menghu":
        err.append(f"S4-2 12 杀应解锁猛虎，实际 {g.fids[g.fid]}")

    # S4-3 扩编：8→12 新兵入列，2 拍内 integrity 回到 ≥0.9，行军不停
    g = SquadGame()
    g.advance(1.0)                            # 先走起来
    x_before = g.anchor.x
    g.kills = 6
    g._check_growth()
    if g.n_units != 12 or len(g.units) != 12 or len(g.cur_slots) != 12:
        err.append(f"S4-3 扩编应为 12 人，实际 n={g.n_units}")
    b0 = g.music.beat_pos
    n0 = len(g.integrity_series)
    while g.music.beat_pos < b0 + 2.0:
        g.tick(DT2)
    integ_low = min((i for _, _, i in g.integrity_series[n0:]), default=1.0)
    if g.integrity < SKILL_ON:
        err.append(f"S4-3 扩编 2 拍后 integrity={g.integrity:.3f} 应 ≥{SKILL_ON}（谷底 {integ_low:.3f}）")
    if g.anchor.x <= x_before:
        err.append("S4-3 扩编期间行军不应停止")
    print(f"  [S4] 扩编 8→12：integrity 谷底 {integ_low:.2f} → {g.integrity:.3f}（2 拍内归位），行军未停")

    # S4-4 成长表来自 JSON
    if GROWTH["unlock_kills"].get("tiebi") != 5 or GROWTH["size_steps"][1]["n"] != 16:
        err.append("S4-4 成长表读取异常")

    # S4-5 整合：敌流 + 指令循环 24 小节，验证 解锁→扩编→变阵 全链
    g = SquadGame()
    g.enemies = [Enemy(4.0 + 1.2 * i, hp=20.0) for i in range(40)]
    plans: dict = {}
    for bar in range(0, 24, 3):
        plans[bar] = "KLKL" if bar in (15, 18) else "JJJJ"
    injected: set[int] = set()
    guard = 0
    while g.bar < 24 and guard < 80000:
        guard += 1
        if g.phase == "input" and g.bar in plans and g.bar not in injected:
            g.inject_bar_presses(g.bar, plans[g.bar], [5.0, -6.0, 4.0, -7.0])
            injected.add(g.bar)
        else:
            g.advance(g.clock["t"] + 0.05)
    kinds = [k for _, k, _ in g.events]
    grows = [v for _, k, v in g.events if k == "grow"]
    unlocks = [v for _, k, v in g.events if k == "unlock"]
    morphs = [v for _, k, v in g.events if k == "morph"]
    if grows != [12, 16]:
        err.append(f"S4-5 扩编应为 [12, 16]，实际 {grows}")
    if set(unlocks) != {"tiebi", "menghu"}:
        err.append(f"S4-5 解锁应为铁壁+猛虎，实际 {unlocks}")
    if g.kills < 14:
        err.append(f"S4-5 击杀应 ≥14，实际 {g.kills}")
    if g.fids[g.fid] != "menghu":
        err.append(f"S4-5 两次 KLKL 后应为猛虎，实际 {g.fids[g.fid]}（morphs={morphs}）")
    if g.squad_hp <= 0:
        err.append("S4-5 队伍不应团灭")
    print(f"  [S4] 整合 24 小节：击杀 {g.kills}，解锁 {unlocks}，扩编 {grows}，"
          f"变阵链 {morphs}，终阵型 {g.fids[g.fid]}×{g.n_units} 人")
    return err


# ================================================================== main
def main() -> int:
    audio = NullAudioEngine()
    audio.start()
    clock = {"t": 0.0}
    audio.audio_time = lambda: clock["t"]       # 虚拟时钟（smoke_test 同款模式）
    music = MusicDirector(audio, Bank())
    music.last_t = 0.0

    print("=== Patapon 沙盒 S1：三项最小验证 ===")
    errors: list[str] = []
    errors += test_march(music, clock)
    errors += test_per_beat_judge(music, clock)
    errors += test_formation()

    print("=== Patapon 沙盒 S2：四相循环 + 应答唱和 + 拍调度 ===")
    errors += test_s2_cycle()

    print("=== Patapon 沙盒 S3：阵型数值 + Boss 破阵 ===")
    errors += test_s3()

    print("=== Patapon 沙盒 S4：成长 + 解锁 + 扩编 ===")
    errors += test_s4()

    for e in errors:
        print("  FAIL:", e)
    print("SANDBOX:", "PASS" if not errors else f"FAIL ({len(errors)} 项)")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
