"""运行遥测：每局结束向 playtest/telemetry.csv 追加一行。

只读 core.Game 的公开统计，不 import pygame，可在无显示器环境跑。
"""
from __future__ import annotations

import csv
import os
import time as _time

ROOT = os.path.dirname(os.path.abspath(__file__))
PLAYTEST_DIR = os.path.join(ROOT, "playtest")
TELEMETRY_PATH = os.path.join(PLAYTEST_DIR, "telemetry.csv")
GUIDE_PATH = os.path.join(PLAYTEST_DIR, "guide.csv")

GUIDE_FIELDS = ("time", "leader", "skipped", "steps_done", "calib_ms",
                "retries")

FIELDS = (
    "time", "hand", "seed", "difficulty", "status", "win",
    "duration_sec", "perfect", "good", "miss", "perfect_rate",
    "avg_offset_ms", "avg_abs_offset_ms", "combo_breaks",
    "fever_count", "break_success", "break_fail", "break_rate",
    "boss_hp_left", "squad_hp_left", "phase_reached",
    "phase1_survived", "phase2_survived", "makeup_ok", "makeup_fail",
    "counter_hits", "countered_hits",
)


def _ratio(num: float, den: float) -> float:
    return (num / den) if den else 0.0


class RunRecorder:
    def __init__(self, enabled: bool = True, hand: str = "human",
                 path: str | None = None, seed: int = 0,
                 difficulty: str = "standard") -> None:
        self.enabled = enabled
        self.hand = hand
        self.path = path or TELEMETRY_PATH
        self.seed = seed
        self.difficulty = difficulty
        self.finished = False

    def snapshot(self, game, reason: str = "exit") -> dict:
        offs = getattr(game, "judge_offsets",
                       {"perfect": [0.0, 0], "good": [0.0, 0],
                        "miss": [0.0, 0]})
        counts = {g: offs.get(g, [0.0, 0])[1] for g in ("perfect", "good", "miss")}
        total = sum(counts.values())
        avg = (_ratio(sum(offs[g][0] for g in counts), total)
               if total else 0.0)
        abs_sum = sum(abs(offs[g][0] / offs[g][1]) * offs[g][1]
                      for g in counts if offs[g][1])
        avg_abs = _ratio(abs_sum, total)
        duration = max(0.0, float(game.now) - float(game.clock.start_time))
        breaks = int(game.stats.get("intents_read", 0))
        fails = int(game.stats.get("intents_hit", 0))
        status = game.status
        return {
            "time": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "hand": self.hand,
            "seed": self.seed,
            "difficulty": self.difficulty,
            "status": status,
            "win": int(status == "cleared"),
            "duration_sec": round(duration, 2),
            "perfect": counts["perfect"],
            "good": counts["good"],
            "miss": counts["miss"],
            "perfect_rate": round(_ratio(counts["perfect"], total) * 100.0, 1),
            "avg_offset_ms": round(avg, 2),
            "avg_abs_offset_ms": round(avg_abs, 2),
            "combo_breaks": int(game.stats.get("missed_commands", 0)),
            "fever_count": int(game.stats.get("fever_count", 0)),
            "break_success": breaks,
            "break_fail": fails,
            "break_rate": round(_ratio(breaks, breaks + fails) * 100.0, 1),
            "boss_hp_left": int(max(0.0, game.boss.hp)) if game.boss else 0,
            "squad_hp_left": int(max(0.0, game.squad.hp)),
            "phase_reached": int(getattr(game, "boss_phase_reached", 1)),
            "phase1_survived": int(getattr(game, "boss_phase_reached", 1) >= 2),
            "phase2_survived": int(getattr(game, "boss_phase_reached", 1) >= 3),
            "makeup_ok": int(game.stats.get("makeup_ok", 0)),
            "makeup_fail": int(game.stats.get("makeup_fail", 0)),
            "counter_hits": int(game.stats.get("counter_hits", 0)),
            "countered_hits": int(game.stats.get("countered_hits", 0)),
            "reason": reason,
        }

    def finish(self, game, reason: str = "exit") -> dict | None:
        if not self.enabled or self.finished:
            return None
        self.finished = True
        row = self.snapshot(game, reason)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            new = not os.path.exists(self.path)
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
                if new:
                    writer.writeheader()
                writer.writerow(row)
            print(f"[telemetry] {self.path} <- {self.hand} "
                  f"status={row['status']} perfect={row['perfect_rate']}%")
        except Exception as exc:
            print(f"[telemetry] skipped: {exc}")
        return row


class GuideRecorder:
    """新手指南一行遥测：跳过/完成步数/校准值/重试次数。"""

    def __init__(self, enabled: bool = True, path: str | None = None) -> None:
        self.enabled = enabled
        self.path = path or GUIDE_PATH

    def write(self, leader: str, report: dict) -> dict | None:
        if not self.enabled:
            return None
        row = {
            "time": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "leader": leader,
            "skipped": int(bool(report.get("skipped", False))),
            "steps_done": int(report.get("steps_done", 0)),
            "calib_ms": int(report.get("calib_ms", 0)),
            "retries": int(report.get("retries", 0)),
        }
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            new = not os.path.exists(self.path)
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=GUIDE_FIELDS,
                                        extrasaction="ignore")
                if new:
                    writer.writeheader()
                writer.writerow(row)
            print(f"[guide] {self.path} <- skipped={row['skipped']} "
                  f"steps={row['steps_done']} calib={row['calib_ms']}ms")
        except Exception as exc:
            print(f"[guide] skipped: {exc}")
        return row
