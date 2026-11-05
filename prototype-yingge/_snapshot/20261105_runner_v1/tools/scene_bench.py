"""战前场景性能复测：标题 / 选将 / 指南 / 暂停（1920×1080 输出层）。

运行：py -3 prototype-yingge/tools/scene_bench.py [--1080]
输出：控制台 SCENE_BENCH 行 + playtest/scene_bench.json

口径与 longrun_bench 对齐：只计场景绘制本身的耗时（含 960→1920 合成与
screen blit），不计 flip 与事件循环。
"""
from __future__ import annotations

import json
import math
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

DT = 1.0 / 60.0
WARMUP = 20
FRAMES = 240
PLAYTEST_DIR = os.path.join(ROOT, "playtest")
OUT_PATH = os.path.join(PLAYTEST_DIR, "scene_bench.json")


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[idx]


def _fresh_flow(tmp: str, scene: str = "title") -> scenes.Flow:
    flow = scenes.Flow(os.path.join(tmp, "settings.json"), core.BPM)
    flow.scene = scene
    return flow


def _guide_flow(tmp: str, step: int, done: int = 0,
                calib: int = 0) -> scenes.Flow:
    flow = _fresh_flow(tmp, "guide")
    g = scenes.Guide(core.BPM, start_time=0.8)
    g.step = step
    for i in range(done):
        g.done[i] = True
    if step == 1:
        g.slots = [core.Slot("J", "perfect", 0.0, 0),
                   core.Slot("J", "good", 68.0, 1)]
    elif step == 4:
        g.slots = [core.Slot("K", "perfect", 0.0, 0),
                   core.Slot("K", "perfect", 0.0, 1),
                   core.Slot("K", "good", 72.0, 2)]
    elif step == 5:
        g.done[5] = True
        g.calib_ms = calib
        g.taps = [float(calib)] * 8
    flow.guide = g
    return flow


def bench(name: str, screen, ui, flow, now_ref: list[float],
          frames: int = FRAMES, hook=None) -> dict:
    cost: list[float] = []
    for i in range(frames + WARMUP):
        if hook:
            hook(i)
        now_ref[0] += DT
        t0 = time.perf_counter()
        draw = {"title": ui.draw_title, "roster": ui.draw_roster,
                "guide": ui.draw_guide}[flow.scene]
        draw(screen, flow, now_ref[0])
        ms = (time.perf_counter() - t0) * 1000.0
        if i >= WARMUP:
            cost.append(ms)
    return {"scene": name, "frames": len(cost),
            "avg_ms": round(statistics.mean(cost), 2),
            "median_ms": round(statistics.median(cost), 2),
            "p95_ms": round(p95(cost), 2),
            "peak_ms": round(max(cost), 2)}


def main() -> int:
    pygame.init()
    size = ((r.VIEW_W * 2, r.VIEW_H * 2) if "--1080" in sys.argv
            else (r.VIEW_W, r.VIEW_H))
    screen = pygame.display.set_mode(size)
    ren = r.Renderer()
    ui = sui.SceneUI(ren)
    tmp = tempfile.mkdtemp(prefix="yingge_bench_")
    now_ref = [0.0]

    rows = []

    title_flow = _fresh_flow(tmp, "title")
    rows.append(bench("title", screen, ui, title_flow, now_ref))

    roster_flow = _fresh_flow(tmp, "roster")
    roster_flow.roster.cursor = 0
    roster_flow.roster.leader = "wusong"

    def hover_hook(i: int) -> None:
        if i % 12 == 0:
            roster_flow.roster.set_hover(3 if (i // 12) % 2 else -1)
    rows.append(bench("roster", screen, ui, roster_flow, now_ref,
                      hook=hover_hook))

    g2 = _guide_flow(tmp, 1, done=1)
    rows.append(bench("guide_step2", screen, ui, g2, now_ref))

    g5 = _guide_flow(tmp, 4, done=4)
    rows.append(bench("guide_step5", screen, ui, g5, now_ref))

    cal = _guide_flow(tmp, 5, done=5, calib=30)
    rows.append(bench("guide_calib", screen, ui, cal, now_ref))

    pause_flow = _fresh_flow(tmp, "battle")
    pause_flow.paused = True
    pause_flow.pause = scenes.PauseMenu(True)
    frozen = screen.copy()
    cost: list[float] = []
    for i in range(FRAMES + WARMUP):
        pause_flow.pause.sel = (i // 30) % 3
        t0 = time.perf_counter()
        screen.blit(frozen, (0, 0))
        ui.draw_pause(screen, pause_flow, 0.0)
        ms = (time.perf_counter() - t0) * 1000.0
        if i >= WARMUP:
            cost.append(ms)
    rows.append({"scene": "pause", "frames": len(cost),
                 "avg_ms": round(statistics.mean(cost), 2),
                 "median_ms": round(statistics.median(cost), 2),
                 "p95_ms": round(p95(cost), 2),
                 "peak_ms": round(max(cost), 2)})

    os.makedirs(PLAYTEST_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"size": list(size), "rows": rows}, f,
                  ensure_ascii=False, indent=2)

    for row in rows:
        print(f"SCENE_BENCH: {row['scene']:12s} avg={row['avg_ms']:.2f}ms "
              f"med={row['median_ms']:.2f}ms p95={row['p95_ms']:.2f}ms "
              f"peak={row['peak_ms']:.2f}ms")
    print(f"SCENE_BENCH: json={OUT_PATH}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
