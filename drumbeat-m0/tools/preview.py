"""渲染预览：无窗口跑一段并把画面存成 PNG，便于快速验收美术与镜头效果。

用法（在 drumbeat-m0 目录下）：
    python tools/preview.py [输出目录] [模拟秒数]

默认输出到 preview_out/，按时间点存多张 PNG。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame                                    # noqa: E402

from drumbeat.app import Game                    # noqa: E402
from drumbeat.audio import NullAudioEngine       # noqa: E402
from drumbeat.inputs import Press                # noqa: E402

FIXED = 1.0 / 120.0


def ground_at(level, x: float) -> bool:
    for r in level.ground_rects:
        if r.left - 0.4 <= x <= r.right + 0.4:
            return True
    return False


def hazard_ahead(level, x: float) -> bool:
    for hz in level.hazard_rects:
        if 0.0 <= hz.left - x <= 1.2:
            return True
    return False


def low_wall_ahead(level, x: float) -> bool:
    for w in level.low_wall_rects:
        if 0.0 <= w.left - x <= 1.4:
            return True
    return False


def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "preview_out"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0
    os.makedirs(out_dir, exist_ok=True)

    g = Game()
    g.show_help = False
    g.show_debug = False
    g.audio.stop()
    g.audio = NullAudioEngine()
    g.audio.start()

    clock = {"t": 0.0}
    g.audio.audio_time = lambda: clock["t"]   # type: ignore[method-assign]
    g.music.audio = g.audio
    g.music.reset()
    g.music.last_t = 0.0

    shots = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0]
    frames = int(seconds / FIXED)
    saved = 0
    for i in range(frames):
        clock["t"] += FIXED
        t = clock["t"]
        g.inputs.set_frame_time(t)
        p = g.player
        f = g.inputs.frame
        f.presses = []
        f.releases = []
        f.held = {"right": True}

        pit = not ground_at(g.level, p.x + 1.0)
        if p.on_ground and not p.sliding and (pit or hazard_ahead(g.level, p.x)):
            f.presses.append(Press("jump", t))
            f.held["jump"] = True
        if (not pit) and low_wall_ahead(g.level, p.x):
            f.held["down"] = True

        g._handle_input(f, t)
        if g.state == "playing":
            g._step(FIXED, t)
        g._render(t)

        if saved < len(shots) and t >= shots[saved]:
            for suffix in ("", "_debug", "_feel"):
                if suffix == "_debug":
                    g.show_debug = True
                elif suffix == "_feel":
                    g.show_debug = False
                    g.show_feel = True
                else:
                    g.show_debug = False
                    g.show_feel = False
                g._render(t)
                path = os.path.join(out_dir, f"t{t:05.1f}{suffix}.png")
                pygame.image.save(g.screen, path)
            saved += 1
        if g.state in ("dead", "cleared"):
            g.show_debug = False
            g.show_feel = False
            g._render(t)
            pygame.image.save(g.screen, os.path.join(out_dir, f"state_{g.state}.png"))
            break

    print(f"已输出 {saved} 组预览到 {out_dir}（玩家 x={g.player.x:.1f}，状态={g.state}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
