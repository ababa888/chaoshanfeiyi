"""无窗口冒烟测试：用合成音频时钟快速驱动核心循环。

验证目标：
1. 运动 / 判定 / 战斗 / 节拍 / 渲染 全链路不抛异常
2. 会看路的机器人能跑完赛段（关卡可通）
3. 踩着判定点出招时判定结果为「完美合拍」（按键帧锚点链路正确）

用法（在 drumbeat-m0 目录下）：
    python tools/smoke_test.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("DRUMBEAT_MODE", "CLASSIC")   # 本脚本验证单角色跑打链路

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drumbeat.app import Game                 # noqa: E402
from drumbeat.audio import NullAudioEngine    # noqa: E402
from drumbeat.inputs import Press             # noqa: E402

FIXED = 1.0 / 120.0
PERFECT_PRESS_MS = 12.0     # 机器人「完美玩家」的按键精度


def _ground_at(level, x: float) -> bool:
    for r in level.ground_rects:
        if r.left - 0.4 <= x <= r.right + 0.4:
            return True
    return False


def _hazard_ahead(level, x: float) -> bool:
    for hz in level.hazard_rects:
        if 0.0 <= hz.left - x <= 1.2:
            return True
    return False


def _low_wall_ahead(level, x: float) -> bool:
    for w in level.low_wall_rects:
        if 0.0 <= w.left - x <= 1.4:
            return True
    return False


def main() -> int:
    g = Game()
    g.show_help = False
    g.show_debug = False
    g.audio.stop()
    g.audio = NullAudioEngine()
    g.audio.start()

    clock = {"t": 0.0}
    g.audio.audio_time = lambda: clock["t"]   # type: ignore[method-assign]
    g.music.audio = g.audio                   # 音乐时钟必须跟随被替换的引擎
    g.music.reset()
    g.music.last_t = 0.0

    seconds = 60.0
    frames = int(seconds / FIXED)
    attacks = jumps = dashes = 0
    trace: list[str] = []
    prev_hp = g.player.hp
    prev_state = g.state

    for i in range(frames):
        clock["t"] += FIXED
        t = clock["t"]
        g.inputs.set_frame_time(t)

        p = g.player
        f = g.inputs.frame
        f.presses = []
        f.releases = []

        # 近身有存活敌人时逼近至攻击距离，否则持续右行
        alive_near = any((not e.dead) and abs(p.x - e.x) < 1.5 for e in g.level.enemies)
        f.held = {"right": not alive_near}

        # --- 移动决策：坑洞/尖刺起跳；悬空横梁下滑通过 ---
        pit_ahead = not _ground_at(g.level, p.x + 1.0)
        if p.on_ground and not p.sliding:
            if pit_ahead or _hazard_ahead(g.level, p.x):
                f.presses.append(Press("jump", t))
                f.held["jump"] = True
                jumps += 1
        if (not pit_ahead) and _low_wall_ahead(g.level, p.x):
            f.held["down"] = True

        # --- 攻击：优先对击弹反，否则踩判定点出招 ---
        want_attack = False
        for e in g.level.enemies:
            if e.dead or e.state != "startup":
                continue
            if abs(p.x - e.x) <= 3.2 and 0.0 <= (e.startup_s - e.t) <= 0.10:
                want_attack = True
                break
        if not want_attack:
            _, dt_ms = g.music.judge_delta_ms(g.music.beat_pos)
            if abs(dt_ms) <= PERFECT_PRESS_MS:
                want_attack = True
        if want_attack:
            f.presses.append(Press("attack", t))
            attacks += 1

        # --- 满堂彩：就绪即放 ---
        if g.energy.can_finish(g.judgement.streak):
            f.presses.append(Press("finisher", t))

        g._handle_input(f, t)
        if g.state == "playing":
            g._step(FIXED, t)
        if i % 10 == 0:
            g._render(t)

        if g.player.hp != prev_hp:
            trace.append(f"t={t:5.2f} x={g.player.x:5.2f} y={g.player.y:5.2f} "
                         f"hp {prev_hp:5.1f}->{g.player.hp:5.1f} ground={g.player.on_ground}")
            prev_hp = g.player.hp
        if g.state != prev_state:
            trace.append(f"t={t:5.2f} x={g.player.x:5.2f} y={g.player.y:5.2f} state {prev_state}->{g.state}")
            prev_state = g.state
            if g.state in ("dead", "cleared"):
                break

    if trace:
        print("--- 损伤/状态轨迹（前 24 条）---")
        for ln in trace[:24]:
            print("  " + ln)

    # --- 面板与手感参数自检（这些路径只在按键时才走，需单独覆盖）---
    panel_err: list[str] = []
    saved_state = g.state
    try:
        g.show_debug = True
        g.show_feel = True
        g.show_help = True
        for name in ("slow", "mid", "fast", "extreme"):
            g.music.force_layer(name)
            g.music.update(g.player.speed)
            g._render(clock["t"])
        for fp in g.feel_params:
            fp.setter(1)
            fp.setter(-1)
            fp.value_str()
        g._render(clock["t"])
        for st_name in ("dead", "cleared"):
            g.state = st_name
            g._render(clock["t"])
    except Exception as exc:  # noqa: BLE001
        panel_err.append(repr(exc))
    g.state = saved_state
    print("面板/手感自检:", "PASS" if not panel_err else f"FAIL {panel_err}")

    st = g.judgement.stats()
    print("=== 冒烟测试结果 ===")
    print(f"玩家 x = {g.player.x:.2f} (目标 {g.level.goal_x:.0f})   状态 = {g.state}   HP = {g.player.hp:.0f}")
    print(f"移速 = {g.player.speed:.2f}   板式 = {g.music.layer_name} {g.music.bpm:.0f}BPM")
    print(f"攻击按键 {attacks}   跳跃 {jumps}   抢步 {dashes}")
    print(f"判定样本 {st['total']}   perfect {st['perfect_rate']*100:.0f}%  "
          f"good {st['good_rate']*100:.0f}%  off {st['off_rate']*100:.0f}%")
    print(f"Δt 均值 {st['mean_dt_ms']:+.1f}ms   标准差 {st['std_dt_ms']:.1f}ms   最高连段 {st['best_streak']}")
    print(f"槌花 {g.combat.hit_count}   鼓劲 {g.energy.value:.1f}   满堂彩 {g.finisher_count}")
    print(f"敌人 {g.level.killed_enemies}/{g.level.total_enemies}")

    # 判定样本中的 off 主要来自「非拍点的对击尝试」，属预期；故完美率阈值取 0.75
    ok = (g.state == "cleared"
          and st["total"] > 0
          and st["perfect_rate"] >= 0.75
          and abs(st["mean_dt_ms"]) <= 30.0
          and g.level.killed_enemies == g.level.total_enemies
          and not panel_err)
    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())