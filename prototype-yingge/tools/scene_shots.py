"""战前场景截图：标题 / 选将网格 / 武松详情 / 指南 2·5 步 / 校准 / 首帧战斗。

运行：py -3 prototype-yingge/tools/scene_shots.py
输出：prototype-yingge/shots/58..64_*.png（1920×1080）
"""
from __future__ import annotations

import os
import sys
import tempfile

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
NAMES = ("58_scene_title", "59_scene_roster_grid",
         "60_scene_roster_wusong", "61_guide_step2",
         "62_guide_step5", "63_guide_calib", "64_battle_first_frame")


def save(screen, name: str) -> None:
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name + ".png")
    pygame.image.save(screen, path)
    print(f"SHOT: {path}")


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((r.VIEW_W * 2, r.VIEW_H * 2))
    ren = r.Renderer()
    ui = sui.SceneUI(ren)
    tmp = tempfile.mkdtemp(prefix="yingge_shots_")
    path = os.path.join(tmp, "settings.json")

    # ① 标题
    title = scenes.Flow(path, core.BPM)
    ui.draw_title(screen, title, 0.0)
    save(screen, NAMES[0])

    # ② 选将网格：光标在武松（金框 + 领队），悬停锁定格看条件
    roster = scenes.Flow(path, core.BPM)
    roster.scene = "roster"
    roster.roster.cursor = 0
    roster.roster.leader = "wusong"
    roster.roster.set_hover(4)
    ui.draw_roster(screen, roster, 0.0)
    save(screen, NAMES[1])

    # ③ 选中武松的详情预览
    roster.roster.set_hover(-1)
    roster.roster.tick(1 / 60)
    ui.draw_roster(screen, roster, 0.0)
    save(screen, NAMES[2])

    # ④ 指南第 2 步（四拍成令）
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
    save(screen, NAMES[3])

    # ⑤ 指南第 5 步（读谱破阵）
    g.step = 4
    g.done[1] = g.done[2] = g.done[3] = True
    g.form_index = 2
    g.slots = [core.Slot("K", "perfect", 0.0, 0),
               core.Slot("K", "perfect", 0.0, 1),
               core.Slot("K", "good", 72.0, 2)]
    g.msg = ("晚 0ms，看判定线落手", 99.0)
    ui.draw_guide(screen, gflow, 0.0)
    save(screen, NAMES[4])

    # ⑥ 校准结果页
    g.step = 5
    g.done[5] = True
    g.calib_ms = 30
    g.taps = [30.0] * 8
    g.msg = ("平均偏移 +30ms，已写入配置", 0.0)
    ui.draw_guide(screen, gflow, 0.0)
    save(screen, NAMES[5])

    # ⑦ 从 Roster 进战斗的第一帧
    game = scenes.new_battle("wusong", core.BPM, "standard",
                             start_time=1.1, seed=20261104)
    frozen = screen.copy()
    ren.draw(screen, game, 0.35, 1.0 / 60.0)
    save(screen, NAMES[6])

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
