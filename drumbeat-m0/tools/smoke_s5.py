"""S5 关卡与战斗无窗口验收：杀敌 → 解锁铁壁 → Boss 破阵 → 放行收阵。

「完美玩家」剧本（假时钟精确踩拍，注入误差 ≤8.4ms 必 perfect）：
  - 最近活敌落入 JJJJ 执行小节扫描带（锚点 +11~+21，1.5× 行军下执行小节
    扫过 [a+11.5, a+20.5]，留边）→ 输入 JJJJ；
  - 否则输入 LLLL（防守占位，保持相位循环不中断）；
  - Boss 预警 / 逼近（x > boss.x-14）：非铁壁 → KLKL 变阵（铁壁已解锁），
    已是铁壁 → LLLL 保持齐整，等待激活拍 break_ok。
排期链式覆盖见 drumbeat/data/patapon_stage.json 注释。

断言：9 敌全灭、铁壁解锁、Boss 两次 break_ok 击破且零 break_fail、
队伍无伤（铁壁破阵不受击）、收阵 cleared、判定零脱拍。

用法（在 drumbeat-m0 目录下）：
    python tools/smoke_s5.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["DRUMBEAT_MODE"] = "PATAPON"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame                               # noqa: E402
from drumbeat.app import Game               # noqa: E402
from drumbeat.audio import NullAudioEngine  # noqa: E402

FIXED = 1.0 / 120.0
_KEYCODES = {"J": pygame.K_j, "K": pygame.K_k, "L": pygame.K_l, "S": pygame.K_s}
MAX_BARS = 120


def choose(pg) -> str:
    """完美玩家本小节指令（input 小节首帧决策，锚点 a 为该小节起点位置）。

    JJJJ 决策带 [a+12, a+18.5]：execute 起点 A = a+12（input+echo 各行军 6），
    命中拍点 {A, A+1.5, A+3, A+4.5} 须覆盖敌人 ⇒ 敌人须 ∈ [A, A+6.5]。
    带宽 6.5 ≥ 每小节行军 6 ⇒ 相邻小节决策带重叠，敌人必入带（链式排期）。
    """
    a = pg.anchor.x
    boss = pg.boss
    if boss is not None and not boss.dead and (boss.state == "startup" or a > boss.x - 14.0):
        if "tiebi" in pg.unlocked and pg.formation != "tiebi":
            return "KLKL"
        return "LLLL"
    live = [e for e in pg.enemies if not e.dead]
    if live:
        e = min(live, key=lambda e: e.x)
        if a + 12.0 <= e.x <= a + 18.5:
            return "JJJJ"
    return "LLLL"


def main() -> int:
    g = Game()
    g.audio.stop()
    g.audio = NullAudioEngine()
    g.audio.start()
    clock = {"t": 0.0}
    g.audio.audio_time = lambda: clock["t"]     # type: ignore[method-assign]
    pg = g.patapon
    pg.audio = g.audio                          # 编排器与拍源必须跟随被替换的引擎
    pg.music.audio = g.audio
    pg.music.reset()
    pg.music.last_t = 0.0

    script: dict[int, str] = {}
    pressed: set[tuple[int, int]] = set()
    frames = int(MAX_BARS * 4 * (60.0 / pg.music.bpm) / FIXED) + 8

    for i in range(frames):
        clock["t"] += FIXED
        t = clock["t"]
        beat = pg.music.beat_pos
        bar = int(beat // pg.music.bar_beats)
        if pg.phase == "input" and pg.status == "playing":
            if bar not in script:
                script[bar] = choose(pg)
            seq = script[bar]
            bib = int(beat % pg.music.bar_beats)
            if bib < len(seq) and (bar, bib) not in pressed:
                if t >= pg.music.time_at_beat(bar * pg.music.bar_beats + bib, t):
                    pressed.add((bar, bib))
                    pg.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                                       key=_KEYCODES[seq[bib]]))
        pg.update(FIXED)
        if i % 10 == 0:
            g.squad_view.draw(g.screen, pg, FIXED, 120.0)
        if pg.status != "playing":
            for _ in range(30):                 # 收尾几帧让结算屏渲染一轮
                clock["t"] += FIXED
                pg.update(FIXED)
                g.squad_view.draw(g.screen, pg, FIXED, 120.0)
            break

    st = pg.stats
    total = st["perfect"] + st["good"] + st["off"]
    boss = pg.boss
    print("=== S5 关卡与战斗验收 ===")
    print(f"状态 {pg.status}   行军 x = {pg.anchor.x:.2f} / {pg.goal_units:.0f}   小节 {pg.bar}")
    print(f"击杀 {pg.kills}/{len(pg.enemies)}   解锁 {sorted(pg.unlocked)}   "
          f"队伍HP {pg.squad_hp:.0f}")
    if boss is not None:
        print(f"Boss hp {boss.hp:.0f}/{boss.max_hp:.0f} dead={boss.dead}   "
              f"破阵 ok/fail = {st['break_ok']}/{st['break_fail']}")
    print(f"指令 ok/fail {st['cmd_ok']}/{st['cmd_fail']}   攻击拍 {st['attacks']}   "
          f"判定 {total}（perfect {st['perfect']} off {st['off']}）")
    ok = (pg.status == "cleared"
          and pg.kills == len(pg.enemies)
          and "tiebi" in pg.unlocked
          and boss is not None and boss.dead
          and st["break_ok"] >= 2 and st["break_fail"] == 0
          and pg.squad_hp == 100.0
          and st["off"] == 0)
    print("SMOKE-S5:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
