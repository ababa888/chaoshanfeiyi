"""PATAPON 模式无窗口冒烟：四拍指令管线全链路。

脚本化「完美玩家」在输入小节踩拍敲 JJJJ（→ 应答 → 执行：攻击×4）与 KKKK（→ 突进），
再敲错序 JLJL 验证乱阵；连续全 PERFECT 两小节验证满堂彩触发。
判定锚点为音频时钟（注入虚拟时钟，帧推进 1/120s ⇒ 按键误差 ≤8.4ms，落在完美窗内）。

用法（在 drumbeat-m0 目录下）：
    python tools/smoke_patapon.py
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
SCRIPT = {0: "JJJJ", 3: "KKKK", 6: "JLJL"}   # 输入小节号 → 该小节要敲的 4 拍


def main() -> int:
    g = Game()
    g.audio.stop()
    g.audio = NullAudioEngine()
    g.audio.start()
    clock = {"t": 0.0}
    g.audio.audio_time = lambda: clock["t"]   # type: ignore[method-assign]
    pg = g.patapon
    pg.audio = g.audio                        # 编排器与拍源必须跟随被替换的引擎
    pg.music.audio = g.audio
    pg.music.reset()
    pg.music.last_t = 0.0

    pressed: set[tuple[int, int]] = set()
    saw = {"echo": False, "execute": False, "luan": False}
    fever_peak = False
    bars = 10
    frames = int(bars * 4 * (60.0 / pg.music.bpm) / FIXED) + 8

    for i in range(frames):
        clock["t"] += FIXED
        t = clock["t"]
        beat = pg.music.beat_pos
        bar = int(beat // pg.music.bar_beats)
        # 脚本化「完美玩家」：拍点时刻到达即敲对应鼓键
        if pg.phase == "input" and bar in SCRIPT:
            bib = int(beat % pg.music.bar_beats)
            seq = SCRIPT[bar]
            if bib < len(seq) and (bar, bib) not in pressed:
                if t >= pg.music.time_at_beat(bar * pg.music.bar_beats + bib, t):
                    pressed.add((bar, bib))
                    pg.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                                       key=_KEYCODES[seq[bib]]))
        pg.update(FIXED)
        if i % 10 == 0:
            g.squad_view.draw(g.screen, pg, FIXED, 120.0)
        if pg.phase in saw:
            saw[pg.phase] = True
        fever_peak = fever_peak or pg.fever

    st = pg.stats
    total = st["perfect"] + st["good"] + st["off"]
    print("=== PATAPON 冒烟测试结果 ===")
    print(f"相位覆盖 echo/execute/luan: {saw['echo']}/{saw['execute']}/{saw['luan']}   "
          f"满堂彩曾触发: {fever_peak}")
    print(f"指令成功 {st['cmd_ok']}   失误 {st['cmd_fail']}   攻击拍执行 {st['attacks']}")
    print(f"判定样本 {total}   perfect {st['perfect']}   good {st['good']}   off {st['off']}")
    print(f"行军 x = {pg.anchor.x:.2f} / 收阵 {pg.goal_units:.0f}   状态 {pg.status}")
    ok = (st["attacks"] == 4
          and st["cmd_ok"] >= 2 and st["cmd_fail"] >= 1
          and saw["echo"] and saw["execute"] and saw["luan"]
          and fever_peak
          and total == 12 and st["off"] == 0)
    print("SMOKE-PATAPON:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
