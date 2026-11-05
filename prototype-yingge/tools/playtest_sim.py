"""三个模拟手各跑相同 seed 组的 Boss 战，输出难度曲线表。

运行：py -3 prototype-yingge/tools/playtest_sim.py
输出：
  playtest/sim_runs.csv        每次模拟一行的遥测
  playtest/difficulty_table.csv / difficulty_table.md
  shots/07_playtest_table.png  表格截图

模拟手：
  perfect  0ms 误差、0 漏拍、指令永远正确
  skilled  ±28ms 高斯误差（截断 ±70）、2% 漏拍
  skilled_makeup  同上，二/三阶段失败后有 90% 概率补打成功
  novice_before  改前旧手：±90~140ms、10% 漏拍，且关闭引导/石台加成
  novice_guided  改后引导手：前 3 招仍 ±90~140ms（教学期），第 4 招起
                 收敛到 ±55~105ms、4% 漏拍（模拟看过 6 拍公示后上手）
  novice_makeup  同上，补打成功率 55%
除 `*_makeup` 档外全部关闭补打，作为「开启前」对照。
只 import core / telemetry，不需要真实显示窗口。
"""
from __future__ import annotations

import csv
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

import core
import telemetry

PLAYTEST_DIR = os.path.join(ROOT, "playtest")
SHOTS_DIR = os.path.join(ROOT, "shots")
SIM_RUNS = os.path.join(PLAYTEST_DIR, "sim_runs.csv")
SEEDS = (20261104, 20261105, 20261106, 20261107, 20261108)
MAX_SEC = 100.0
STEP = 1.0 / 120.0

HANDS = {
    "perfect": {"label": "完美", "sigma": 0.0, "cap": 0.0, "miss": 0.0},
    "skilled": {"label": "熟练", "sigma": 28.0, "cap": 70.0, "miss": 0.02},
    "skilled_makeup": {"label": "熟练+补打", "sigma": 28.0, "cap": 70.0,
                       "miss": 0.02, "makeup_prob": 0.90},
    "novice_before": {"label": "新手·改前", "sigma": 0.0, "cap": 0.0,
                      "miss": 0.10},
    "novice_guided": {"label": "新手·改后", "sigma": 0.0, "cap": 0.0,
                      "miss": 0.10, "learned_miss": 0.05,
                      "elite_miss": 0.035},
    "novice_makeup": {"label": "新手·改后+补打", "sigma": 0.0, "cap": 0.0,
                      "miss": 0.10, "learned_miss": 0.05,
                      "elite_miss": 0.035, "makeup_prob": 0.55},
}
HAND_ORDER = ("perfect", "skilled", "skilled_makeup",
              "novice_before", "novice_guided", "novice_makeup")
# 成对档共用同一 RNG 序列，保证「开/关补打」是同一局面的 A/B 对照
HAND_SEED_SLOT = {"perfect": 0, "skilled": 1, "skilled_makeup": 1,
                  "novice_before": 2, "novice_guided": 3, "novice_makeup": 3}


def hand_error_ms(kind: str, rng: random.Random,
                  learned: bool = False, elite: bool = False) -> float:
    if kind == "novice_before":
        mag = rng.uniform(90.0, 140.0)
        return mag if rng.random() < 0.5 else -mag
    if kind == "novice_guided" or kind == "novice_makeup":
        if elite:
            lo, hi = 30.0, 80.0
        else:
            lo, hi = (35.0, 90.0) if learned else (90.0, 140.0)
        mag = rng.uniform(lo, hi)
        return mag if rng.random() < 0.5 else -mag
    spec = HANDS[kind]
    if spec["sigma"] <= 0:
        return 0.0
    return max(-spec["cap"],
               min(spec["cap"], rng.gauss(0.0, spec["sigma"])))


def choose_key(g: core.Game, beat: int, kind: str = "perfect") -> str | None:
    slot = beat % core.CYCLE_BEATS
    if slot < core.INPUT_BEATS:
        # 新手也会看距离：被击退后先按 K 向前顶，而不是原地空挥
        if (kind in ("novice_before", "novice_guided", "novice_makeup")
                and g.boss_active
                and g.boss is not None and g.boss.x - g.squad.x > 2.7):
            return "K"
        return "JJJJ"[slot]
    if g.intent_key and g.intent:
        return g.intent["keys"][slot - core.INPUT_BEATS]
    return None


def run_one(kind: str, seed: int, rng: random.Random) -> dict:
    g = core.Game(seed=seed, start_time=0.0, difficulty="standard",
                  spawn_boss=True)
    if kind == "novice_before":
        g.guidance = False
        g.platform_enabled = False
    # 只有 *+补打 档开启补打，其余档作为「开启前」对照
    g.makeup_enabled = bool(HANDS[kind].get("makeup_prob"))
    g.start_boss_fight(squad_x=6.0, boss_x=8.4)
    recorder = telemetry.RunRecorder(path=SIM_RUNS, hand=kind,
                                     seed=seed, difficulty="standard")
    next_beat = 0
    err_ms = hand_error_ms(kind, rng)
    err_beats = err_ms / core.BEAT_MS
    tried_cycle = -999
    t = 0.0
    while t < MAX_SEC and g.status == "playing":
        t += STEP
        g.update(t, STEP)
        # 补打：每招只尝试一次；命中概率由帧内随机决定（仍受 1 拍硬窗口约束）
        if g.makeup_pending and g.attempt is not None \
                and g.attempt.cycle != tried_cycle:
            tried_cycle = g.attempt.cycle
            prob = float(HANDS[kind].get("makeup_prob", 0.0))
            if rng.random() < prob:
                for k in g.makeup_pattern:
                    g.beat_press(k, t, 0.0)
        predicted = g.clock.beat_at(t, g.fever_active)
        learned = (kind in ("novice_guided", "novice_makeup") and
                   g.boss_attacks >= int(core.TUTORIAL["grace_attacks"]))
        elite = kind in ("novice_guided", "novice_makeup") and g.boss_attacks >= 8
        miss = HANDS[kind]["miss"]
        if elite:
            miss = HANDS[kind]["elite_miss"]
        elif learned:
            miss = HANDS[kind]["learned_miss"]
        guard = 0
        while predicted >= next_beat + err_beats and guard < 4:
            guard += 1
            n = next_beat
            if rng.random() >= miss:
                key = choose_key(g, n, kind)
                if key:
                    g.beat_press(key, t, err_ms)
            next_beat += 1
            err_ms = hand_error_ms(kind, rng, learned, elite)
            err_beats = err_ms / core.BEAT_MS
    row = recorder.finish(g, "sim")
    return row or recorder.snapshot(g, "sim")


def summarize(kind: str, rows: list[dict]) -> dict:
    n = len(rows)
    wins = sum(r["win"] for r in rows)
    times = [r["duration_sec"] for r in rows if r["win"]] or \
            [r["duration_sec"] for r in rows]
    return {
        "hand": kind,
        "label": HANDS[kind]["label"],
        "runs": n,
        "win_rate": round(wins / n * 100.0, 1) if n else 0.0,
        "avg_time": round(sum(times) / len(times), 1) if times else 0.0,
        "perfect_rate": round(sum(r["perfect_rate"] for r in rows) / n, 1)
        if n else 0.0,
        "break_rate": round(sum(r["break_rate"] for r in rows) / n, 1)
        if n else 0.0,
        "phase1_survive": round(sum(r["phase1_survived"] for r in rows) / n
                                * 100.0, 1) if n else 0.0,
        "phase2_survive": round(sum(r["phase2_survived"] for r in rows) / n
                                * 100.0, 1) if n else 0.0,
        "makeup_ok": sum(r["makeup_ok"] for r in rows),
        "makeup_fail": sum(r["makeup_fail"] for r in rows),
        "combo_breaks_per_min": round(
            sum(r["combo_breaks"] for r in rows)
            / max(1.0, sum(r["duration_sec"] for r in rows)) * 60.0, 1),
    }


def write_tables(sums: list[dict]) -> None:
    os.makedirs(PLAYTEST_DIR, exist_ok=True)
    path = os.path.join(PLAYTEST_DIR, "difficulty_table.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sums[0].keys()))
        w.writeheader()
        w.writerows(sums)
    md = os.path.join(PLAYTEST_DIR, "difficulty_table.md")
    lines = [
        "# 模拟手难度曲线",
        "",
        f"同一 seed 组：{', '.join(str(s) for s in SEEDS)}；"
        f"每档 {len(SEEDS)} 局；Boss 600 HP；时限 {int(MAX_SEC)}s。",
        "",
        "| 模拟手 | 胜率 | 平均用时(s) | Perfect 率 | 破阵成功率 | 一阶段存活 | 二阶段存活 | 补打成功/失败 | 断连/分钟 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in sums:
        lines.append(
            f"| {s['label']} | {s['win_rate']}% | {s['avg_time']} | "
            f"{s['perfect_rate']}% | {s['break_rate']}% | "
            f"{s['phase1_survive']}% | {s['phase2_survive']}% | "
            f"{s['makeup_ok']}/{s['makeup_fail']} | "
            f"{s['combo_breaks_per_min']} |")
    novice = next(s for s in sums if s["hand"] == "novice_guided")
    lines += ["", f"**新手第一阶段存活率：{novice['phase1_survive']}%**"]
    with open(md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def draw_table(sums: list[dict]) -> None:
    os.makedirs(SHOTS_DIR, exist_ok=True)
    pygame.init()
    W, H = 1200, 640
    surf = pygame.Surface((W, H))
    for y in range(H):
        k = y / H
        surf.fill((int(22 + 16 * k), int(14 + 10 * k), int(26 + 8 * k)),
                  (0, y, W, 1))
    font_path = None
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            font_path = p
            break

    def text(s, size, color, pos, center=False, bold=False):
        f = pygame.font.Font(font_path, size) if font_path else \
            pygame.font.SysFont("Microsoft YaHei", size, bold=bold)
        img = f.render(s, True, color)
        rect = img.get_rect()
        rect.center = pos if center else rect.center
        if not center:
            rect.topleft = pos
        surf.blit(img, rect)

    text("踏鼓 · 模拟手难度曲线", 30, (238, 186, 88),
         (W // 2, 34), center=True)
    text("同一 seed 组 / 每档 5 局 / Boss 600 HP / 标准难度", 14,
         (196, 176, 152), (W // 2, 74), center=True)
    cols = ("模拟手", "胜率", "用时", "Perfect", "破阵",
            "一阶段", "二阶段", "补打", "断连/分")
    xs = (50, 230, 330, 430, 560, 670, 790, 910, 1040)
    for x, col in zip(xs, cols):
        text(col, 16, (255, 240, 206), (x, 118))
    pygame.draw.line(surf, (128, 78, 52), (50, 148), (W - 50, 148), 2)
    colors = [(255, 220, 150), (180, 230, 190), (130, 240, 160),
              (150, 150, 145), (255, 150, 120), (255, 196, 130)]
    for i, s in enumerate(sums):
        y = 166 + i * 56
        color = colors[i % len(colors)]
        vals = (s["label"], f"{s['win_rate']}%", f"{s['avg_time']}s",
                f"{s['perfect_rate']}%", f"{s['break_rate']}%",
                f"{s['phase1_survive']}%", f"{s['phase2_survive']}%",
                f"{s['makeup_ok']}/{s['makeup_fail']}",
                f"{s['combo_breaks_per_min']}")
        for x, v in zip(xs, vals):
            text(v, 17, color, (x, y), bold=(x == xs[0]))
        pygame.draw.line(surf, (70, 44, 40), (50, y + 40),
                         (W - 50, y + 40), 1)
    before = next(s for s in sums if s["hand"] == "novice_before")
    after = next(s for s in sums if s["hand"] == "novice_guided")
    mk = next(s for s in sums if s["hand"] == "novice_makeup")
    text(f"新手胜率 {before['win_rate']}% → {after['win_rate']}% → "
         f"{mk['win_rate']}%（+补打）· 二阶段存活 "
         f"{after['phase2_survive']}% → {mk['phase2_survive']}%",
         15, (255, 190, 120), (W // 2, H - 66), center=True)
    text("补打 = 二/三阶段每招一次、1 拍内补令、半伤、Good 计、不累积 Fever",
         13, (196, 176, 152), (W // 2, H - 36), center=True)
    out = os.path.join(SHOTS_DIR, "07_playtest_table.png")
    pygame.image.save(surf, out)
    print(f"[shot] {out}")


def main() -> int:
    os.makedirs(PLAYTEST_DIR, exist_ok=True)
    if os.path.exists(SIM_RUNS):
        os.remove(SIM_RUNS)
    all_rows: dict[str, list[dict]] = {k: [] for k in HAND_ORDER}
    for kind in HAND_ORDER:
        rng = random.Random(0xA11CE + HAND_SEED_SLOT[kind])
        for seed in SEEDS:
            row = run_one(kind, seed, rng)
            all_rows[kind].append(row)
            print(f"[sim] {kind:<8} seed={seed} status={row['status']:<9} "
                  f"t={row['duration_sec']:.1f}s perfect={row['perfect_rate']}% "
                  f"break={row['break_rate']}% phase={row['phase_reached']}")
    sums = [summarize(k, all_rows[k]) for k in HAND_ORDER]
    write_tables(sums)
    draw_table(sums)
    print("PLAYTEST SIM: DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
