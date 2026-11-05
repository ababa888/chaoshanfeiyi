"""第18-19轮默认流程的同机位新图 + 性能复测（只增不删）。

输出到 shots/70..75_restore_*.png，不覆盖旧 58..64。
用法：py -3 prototype-yingge/tools/restore_1819_shots.py
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

import core
import render as r
import scene_ui as sui
import scenes

SHOTS = os.path.join(ROOT, "shots")


def save(screen, name: str) -> str:
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name + ".png")
    pygame.image.save(screen, path)
    print(f"SHOT: {path}")
    return path


def bench(label: str, draw, n: int = 200) -> list[float]:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        draw()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    p95 = samples[max(0, int(len(samples) * 0.95) - 1)]
    print(f"BENCH {label}: avg={statistics.mean(samples):.2f}ms "
          f"p95={p95:.2f}ms peak={samples[-1]:.2f}ms")
    return samples


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((r.VIEW_W * 2, r.VIEW_H * 2))
    ren = r.Renderer()
    ui = sui.SceneUI(ren, screen)
    tmp = tempfile.mkdtemp(prefix="yingge_1819_")
    path = os.path.join(tmp, "settings.json")

    # ① 标题（18-19 单入口）
    title = scenes.Flow(path, core.BPM)
    ui.draw_title(screen, title, 0.0)
    save(screen, "70_restore_title")
    bench("title", lambda: ui.draw_title(screen, title, 0.0))

    # ② 选将网格（与旧 59 同机位）
    roster = scenes.Flow(path, core.BPM)
    roster.scene = "roster"
    roster.roster.cursor = 0
    roster.roster.leader = "wusong"
    roster.roster.set_hover(4)
    ui.draw_roster(screen, roster, 0.0)
    save(screen, "71_restore_roster_grid")
    bench("roster", lambda: ui.draw_roster(screen, roster, 0.0))

    # ③ 武松详情（与旧 60 同机位）
    roster.roster.set_hover(-1)
    roster.roster.tick(1 / 60)
    ui.draw_roster(screen, roster, 0.0)
    save(screen, "72_restore_roster_wusong")

    # ④ 指南第 2 步（与旧 61 同机位）
    gflow = scenes.Flow(path, core.BPM)
    gflow.scene = "guide"
    g = scenes.Guide(core.BPM, start_time=0.8)
    g.step = 1
    g.done[0] = True
    g.slots = [core.Slot("J", "perfect", 0.0, 0),
               core.Slot("J", "good", 68.0, 1)]
    g.msg = ("四拍成令 · 过", 99.0)
    gflow.guide = g
    ui.draw_guide(screen, gflow, 0.0)
    save(screen, "73_restore_guide_step2")
    bench("guide_step2", lambda: ui.draw_guide(screen, gflow, 0.0))

    # ⑤ 战场首帧（与旧 64 同机位）+ 性能
    game = scenes.new_battle("wusong", core.BPM, "standard",
                             start_time=1.1, seed=20261104)
    frozen = screen.copy()
    ren.draw(screen, game, 0.35, 1.0 / 60.0)
    save(screen, "74_restore_battle_first")
    bench("battle", lambda: ren.draw(screen, game, 0.35, 1.0 / 60.0))

    # ⑥ 暂停（用同一帧作为冻结底图）
    pflow = scenes.Flow(path, core.BPM, mode="boss")
    pflow.skip_to_battle()
    pflow.key("ESC", 0.0)
    frozen = screen.copy()
    screen.blit(frozen, (0, 0))
    ui.draw_pause(screen, pflow, 0.0)
    save(screen, "75_restore_pause")

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
