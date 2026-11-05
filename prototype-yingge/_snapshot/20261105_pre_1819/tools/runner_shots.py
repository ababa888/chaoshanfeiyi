"""急行模式验收截图：常态 / 预警缺口 / 穿缝 / 撞阵减速 / 结算
+ 三层文化状态：破邪 / 巡游民众 / 求雨雨幕 / 尚武 / 结算双时间。

用法：py -3 prototype-yingge/tools/runner_shots.py
输出到 prototype-yingge/shots/runner_*.png（1920×1080），并打印绘制耗时。
"""
from __future__ import annotations

import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

import core  # noqa: E402
import render as r  # noqa: E402
import runner  # noqa: E402
import scene_ui as sui  # noqa: E402
import scenes  # noqa: E402

OUT = os.path.join(ROOT, "shots")


def save(ui, screen, flow, sess, name: str) -> str:
    ui.draw_runner(screen, flow, sess, 0.0)
    path = os.path.join(OUT, name)
    pygame.image.save(screen, path)
    return path


def culture_session(cfg, seg: int) -> runner.RunnerSession:
    s = runner.RunnerSession(cfg, seed=23, culture=True)
    s.seg = seg
    s.distance = sum(x.steps for x in cfg.route[:seg])
    s.warning = None
    s.queue.groups.clear()
    s._schedule_blocks()
    key = "K" if seg == 0 else "J"
    for _ in range(6):
        s.step(key)
    return s


def bench(ui, screen, flow, cfg) -> None:
    """绘制耗时 avg/p95/peak，对齐上一版跑酷数字（旧版约 4–6ms/帧）。"""
    for seg, name in ((0, "secular"), (1, "holy"), (2, "history")):
        s = culture_session(cfg, seg)
        if seg == 2:
            s.rain_left = cfg.culture.rain_beats
            s.rain_count = 2
        samples = []
        for _ in range(200):
            t0 = time.perf_counter()
            ui.draw_runner(screen, flow, s, 0.0)
            samples.append((time.perf_counter() - t0) * 1000.0)
        samples.sort()
        p95 = samples[int(len(samples) * 0.95) - 1]
        print(f"BENCH {name}: avg={statistics.mean(samples):.2f}ms "
              f"p95={p95:.2f}ms peak={samples[-1]:.2f}ms")


def main() -> int:
    pygame.init()
    os.makedirs(OUT, exist_ok=True)
    pygame.display.set_mode((r.VIEW_W, r.VIEW_H))
    ren = r.Renderer()
    screen = pygame.Surface((1920, 1080))
    ui = sui.SceneUI(ren, screen)
    path = os.path.join(OUT, "_settings.json")
    flow = scenes.Flow(path, core.BPM)
    cfg = runner.load_config()
    sess = runner.RunnerSession(cfg, seed=21)

    # 1) 急行常态
    for _ in range(18):
        sess.step(None)
    print(save(ui, screen, flow, sess, "runner_normal.png"))

    # 2) 遇敌预警 + 两列缺口
    sess.distance = 56.5
    sess.warning = {
        "target": cfg.route[1].recommend, "enemy": "shield", "gap_side": "left",
        "start_beat": sess.beat, "contact_beat": sess.beat + 4,
        "name": cfg.form_name(cfg.route[1].recommend), "enemy_name": "盾墙",
    }
    sess.queue.schedule(sess.beat, cfg.pattern(cfg.route[1].recommend),
                        cfg.route[1].recommend, sess.beat + 4, warning=True)
    print(save(ui, screen, flow, sess, "runner_warning_gap.png"))

    # 3) 穿缝成功（变阵 + 双槌 + 计时损失）
    sess.formation = cfg.route[1].recommend
    sess.gaps, sess.switches = 1, 1
    sess.ui_flash["gap"] = sess.beat + 3
    sess.ui_flash["whack"] = sess.beat + 3
    sess.gap_debits = cfg.gap_loss_beats
    print(save(ui, screen, flow, sess, "runner_gap_pass.png"))

    # 4) 撞阵减速（线性恢复中）
    sess.formation = cfg.route[0].recommend
    sess.hits = 1
    sess.tracker.hit("shield")
    sess.ui_flash["gap"] = -1.0
    sess.ui_flash["whack"] = -1.0
    sess.ui_flash["hit"] = sess.beat + 6
    print(save(ui, screen, flow, sess, "runner_hit_slow.png"))

    # 5) 结算页（S 评级）
    final = runner.headless_run("master", 17, cfg)
    sess.finished = True
    sess.final_time_s = float(final["time_s"])
    sess.warning = None
    sess.ui_flash = {"whack": -1.0, "hit": -1.0, "gap": -1.0, "warn": -1.0}
    sess.current_speed = 1.25
    sess.tracker.active.clear()
    sess.counts = {"perfect": 92, "good": 6, "miss": 2}
    sess.hits, sess.switches, sess.gaps = 0, 3, 3
    sess.splits = list(final["splits"])
    print(save(ui, screen, flow, sess, "runner_result.png"))

    # 6) 遇敌破邪（神圣段，提示为 JJJJ 破邪）
    s = runner.RunnerSession(cfg, seed=23, culture=True)
    s.seg, s.distance = 1, 116.5
    s.queue.groups.clear()
    s.warning = {
        "target": cfg.route[1].recommend, "enemy": "shield", "gap_side": "left",
        "start_beat": 0, "contact_beat": 4,
        "name": cfg.form_name(cfg.route[1].recommend), "enemy_name": "盾墙",
    }
    s.queue.schedule(0, "JJJJ", cfg.route[1].recommend, 4, label="破邪 JJJJ")
    s.purifies, s.drum_charge = 3, 1
    s.last_command, s.last_command_beat = "attack", -1
    s.ui_flash["purify"] = s.beat + 2
    s.tracker.hit("shield", factor=1.0)
    print(save(ui, screen, flow, s, "runner_culture_purify.png"))

    # 7) 城镇巡游与民众（世俗段）
    s = culture_session(cfg, 0)
    s.popularity = cfg.culture.popularity_max
    s.patrol_count = 3
    s.last_command = "march"
    print(save(ui, screen, flow, s, "runner_culture_patrol.png"))

    # 8) 求雨雨幕（历史段）
    s = culture_session(cfg, 2)
    s.rain_left = cfg.culture.rain_beats - 2
    s.rain_count, s.rain_hits = 2, 2
    s.rain_collect_left = 3
    s.last_command = "martial"
    print(save(ui, screen, flow, s, "runner_culture_rain.png"))

    # 9) 尚武演练（历史段）
    s = culture_session(cfg, 2)
    s.rain_left = s.rain_collect_left = s.rain_count = 0
    s.rain_hits = 0
    s.martial, s.martial_count, s.martial_ready = 2, 3, True
    s.last_command = "martial"
    s.ui_flash = {"martial": s.beat + 2}
    print(save(ui, screen, flow, s, "runner_culture_martial.png"))

    # 10) 结算双时间（真实无头文化跑分）
    s = runner._auto_session(cfg, "skilled", 17, culture=True)
    print(save(ui, screen, flow, s, "runner_culture_result.png"))

    bench(ui, screen, flow, cfg)
    print("SHOTS OK", len([n for n in os.listdir(OUT) if n.startswith("runner_")]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
