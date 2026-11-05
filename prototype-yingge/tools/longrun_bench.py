"""无头跑完整长关卡：完美模拟手逐帧更新 + 渲染，记录帧耗时与战果。

运行：py -3 prototype-yingge/tools/longrun_bench.py
输出：控制台一行 LONGRUN: 摘要 + playtest/longrun.json（不生成截图）

说明：11 波杂兵的总伤害高于初始 110 HP；关卡用「整波清空回血/扶起」
（level_long.json 的 wave_clear_heal / wave_clear_revive）作为长图中途补给。
本脚本不做任何基准端作弊，完整跑「杂兵 → Boss 战 → 结算」。
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

import core
import render as r

MAX_SIM_SEC = 420.0
DT = 1.0 / 60.0
WARMUP_FRAMES = 30
DEFEND_BELOW = 0.60        # 血量低于 60% 时穿插防守
DEFEND_EVERY = 5           # 每 5 个循环守一次
PLAYTEST_DIR = os.path.join(ROOT, "playtest")
OUT_PATH = os.path.join(PLAYTEST_DIR, "longrun.json")
OUT_PATH_1080 = os.path.join(PLAYTEST_DIR, "longrun_1080.json")

# 开场先立「双龙出海」：机动 1.45，缩短长图行军时间；之后一律 JJJJ 攻击。
OPENING_FORMATION = "JJKK"


def choose_keys(g: core.Game, beat: int) -> list[str]:
    """返回本拍要按的键。前 4 拍收令，动作拍踏点驱动自动行军。"""
    slot = beat % core.CYCLE_BEATS
    cycle = beat // core.CYCLE_BEATS
    if slot < core.INPUT_BEATS:
        if cycle == 0:
            return [OPENING_FORMATION[slot]]
        low = g.squad.hp < DEFEND_BELOW * g.squad.max_hp
        if not g.boss_active and low and cycle % DEFEND_EVERY == 0:
            return ["LLLL"[slot]]
        return ["JJJJ"[slot]]
    if g.boss_active and g.intent_key and g.intent:
        keys = g.intent["keys"]
        if slot - core.INPUT_BEATS < len(keys):
            return [keys[slot - core.INPUT_BEATS]]
    return ["J"]  # 动作拍踏点：自动行军 / 硬直期追打


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[idx]


def main() -> int:
    pygame.init()
    # 默认 960×540（与历次基准可比）；--1080 按真实输出 1920×1080 跑 HUD 原生层
    if "--1080" in sys.argv:
        screen = pygame.display.set_mode((r.VIEW_W * 2, r.VIEW_H * 2))
    else:
        screen = pygame.display.set_mode((r.VIEW_W, r.VIEW_H))
    g = core.Game(seed=20261104, difficulty="standard")
    g.makeup_enabled = True
    ren = r.Renderer()

    frame_ms: list[float] = []
    next_beat = 0
    t = 0.0
    frames = 0
    ground_max = 0
    wall_start = time.perf_counter()

    while t < MAX_SIM_SEC and g.status == "playing":
        t += DT
        # 先收令再 update（与 main.py 同序，自动行军才能吃到本拍按键）
        predicted = g.clock.beat_at(t, g.fever_active)
        guard = 0
        while predicted >= next_beat and guard < 4:
            guard += 1
            for key in choose_keys(g, next_beat):
                g.beat_press(key, t, 0.0)
            next_beat += 1
        if g.makeup_pending:
            for key in g.makeup_pattern:
                g.beat_press(key, t, 0.0)

        g.update(t, DT)
        g.drain_events()

        start = time.perf_counter()
        ren.draw(screen, g, t, DT)
        cost = (time.perf_counter() - start) * 1000.0
        frames += 1
        if frames > WARMUP_FRAMES:
            frame_ms.append(cost)
        ground_max = max(ground_max, int(getattr(ren, "ground_cells", 0)))

    wall_sec = time.perf_counter() - wall_start
    stats = g.stats
    break_success = int(stats.get("intents_read", 0))
    break_fail = int(stats.get("intents_fail", 0))
    summary = {
        "status": g.status,
        "seed": g.seed,
        "squad_x": round(float(g.squad.x), 2),
        "segment_index": int(getattr(g, "segment_index", 0)),
        "wave_cursor": int(getattr(g, "wave_cursor", 0)),
        "squad_hp": round(float(g.squad.hp), 1),
        "difficulty": g.difficulty,
        "wave_clear_heal": float(core.LEVEL.get("wave_clear_heal", 0.0)),
        "wave_clear_revive": float(core.LEVEL.get("wave_clear_revive", 0.0)),
        "sim_sec": round(float(g.now), 3),
        "wall_sec": round(wall_sec, 2),
        "frames_total": frames,
        "frames_timed": len(frame_ms),
        "avg_ms": round(statistics.mean(frame_ms), 2) if frame_ms else 0.0,
        "median_ms": round(statistics.median(frame_ms), 2) if frame_ms else 0.0,
        "p95_ms": round(p95(frame_ms), 2),
        "peak_ms": round(max(frame_ms), 2) if frame_ms else 0.0,
        "break_attempts": break_success + break_fail,
        "break_success": break_success,
        "break_fail": break_fail,
        "boss_perfect_breaks": int(stats.get("boss_perfect_breaks", 0)),
        "makeup_ok": int(stats.get("makeup_ok", 0)),
        "makeup_fail": int(stats.get("makeup_fail", 0)),
        "defends": int(stats.get("defends", 0)),
        "ground_cells_max": ground_max,
    }

    os.makedirs(PLAYTEST_DIR, exist_ok=True)
    out_path = OUT_PATH_1080 if "--1080" in sys.argv else OUT_PATH
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(
        "LONGRUN: "
        f"status={summary['status']} "
        f"sim={summary['sim_sec']:.1f}s wall={summary['wall_sec']:.1f}s "
        f"frames={summary['frames_total']} "
        f"avg={summary['avg_ms']:.2f}ms "
        f"med={summary['median_ms']:.2f}ms "
        f"p95={summary['p95_ms']:.2f}ms "
        f"peak={summary['peak_ms']:.2f}ms "
        f"breaks={summary['break_success']}/{summary['break_fail']} "
        f"makeup={summary['makeup_ok']}/{summary['makeup_fail']} "
        f"ground_max={summary['ground_cells_max']} "
        f"json={out_path}"
    )
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
