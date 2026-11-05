"""第十九轮出图：叠印前后对比、选人整屏、指南第 1/2 步、悬停-禁用态、F2 热区。"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pygame
from PIL import Image, ImageDraw, ImageFont

import core
import render as r
import scenes
import scene_ui as sui

SHOTS = os.path.join(HERE, "shots")
LEGACY = os.path.join(SHOTS, "_probe_roster.png")


def font(size: int):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def label(im: Image.Image, text: str, xy=(12, 8), size=34):
    ImageDraw.Draw(im).text(xy, text, fill=(232, 210, 150), font=font(size))
    return im


def compose(pairs, out, title, zoom=2):
    """pairs: [(PIL 图, 说明)]，横排并叠加说明条。"""
    tiles = []
    for im, cap in pairs:
        w, h = im.size
        t = im.resize((w * zoom, h * zoom), Image.NEAREST)
        t = label(t, cap, (10, 8), 30)
        tiles.append(t)
    gap = 16
    W = sum(t.width for t in tiles) + gap * (len(tiles) - 1)
    H = max(t.height for t in tiles) + 64
    canvas = Image.new("RGB", (W, H), (8, 6, 10))
    x = 0
    for t in tiles:
        canvas.paste(t, (x, 64))
        x += t.width + gap
    ImageDraw.Draw(canvas).text((12, 14), title, fill=(255, 226, 160),
                                font=font(34))
    canvas.save(out)
    print("shot", out, canvas.size)


def main() -> int:
    pygame.init()
    pygame.display.set_mode((960, 540))
    ren = r.Renderer()
    screen = pygame.Surface((1920, 1080))
    ui = sui.SceneUI(ren, screen)
    tmp = tempfile.mkdtemp(prefix="yingge_shots_")
    path = os.path.join(tmp, "settings.json")
    NEW_ROSTER = os.path.join(tmp, "roster_full.png")
    NEW_GUIDE0 = os.path.join(tmp, "guide0.png")
    NEW_GUIDE1 = os.path.join(tmp, "guide1.png")
    NEW_GUIDE_DISABLED = os.path.join(tmp, "disabled.png")
    NEW_GUIDE_ENABLED = os.path.join(tmp, "enabled.png")
    HOT = os.path.join(tmp, "hotzones.png")

    def save(name):
        pygame.image.save(screen, name)
        return Image.open(name).convert("RGB")

    # 选人整屏（无调试浮层）
    f = scenes.Flow(path, core.BPM)
    f.key("ENTER", 0.0)
    ui.draw_roster(screen, f, 0.0)
    roster = save(NEW_ROSTER)

    # ① 叠印区域：旧头像烘焙字幕 vs 新脸部裁切
    if os.path.exists(LEGACY):
        before = _pad_top(Image.open(LEGACY).convert("RGB").crop((192, 224, 360, 392)))
        after = _pad_top(roster.crop((192, 224, 360, 392)))
        compose([(before, "修复前 · 头像字幕压住名字"),
                 (after, "修复后 · 眼部裁切 + 单层字")],
                os.path.join(SHOTS, "65_overlap_before_after.png"),
                "选人格子文字叠印：修复前 / 修复后", zoom=3)
    # ② 选人整屏
    roster.save(os.path.join(SHOTS, "66_roster_no_debug.png"))

    # ③ 指南第 1 步（大鼓 + 绸带）
    fm = scenes.Flow(path, core.BPM)
    fm.key("ENTER", 0.0)
    fm.key("ENTER", 0.0)
    ui.draw_guide(screen, fm, 0.0)
    save(NEW_GUIDE0).save(os.path.join(SHOTS, "67_guide_step1_new.png"))

    # ④ 指南第 2 步完成态（印章）
    fm.click(*_center(scenes.GUIDE_KEY_RECT["J"]), 0.0)   # 第 1 步过
    fm.click(*_center(scenes.GUIDE_NEXT_RECT), 0.0)       # → 第 2 步
    for _ in range(4):
        fm.click(*_center(scenes.GUIDE_KEY_RECT["J"]), 0.4)
    ui.draw_guide(screen, fm, 3.0)
    save(NEW_GUIDE1).save(os.path.join(SHOTS, "68_guide_step2_done.png"))

    # ⑤ 悬停 / 禁用态对比（同一按钮区域）
    f0 = scenes.Flow(path, core.BPM)
    f0.key("ENTER", 0.0)
    f0.key("ENTER", 0.0)
    f0.hover(*_center(scenes.GUIDE_NEXT_RECT))
    ui.draw_guide(screen, f0, 0.0)
    save(NEW_GUIDE_DISABLED)
    f1 = scenes.Flow(path, core.BPM)
    f1.key("ENTER", 0.0)
    f1.key("ENTER", 0.0)
    f1.click(*_center(scenes.GUIDE_KEY_RECT["J"]), 0.0)   # 完成第 1 步
    f1.hover(*_center(scenes.GUIDE_NEXT_RECT))
    ui.draw_guide(screen, f1, 0.5)
    save(NEW_GUIDE_ENABLED)
    dis = _pad_top(Image.open(NEW_GUIDE_DISABLED).convert("RGB")
                   .crop((660, 850, 1120, 944)))
    ena = _pad_top(Image.open(NEW_GUIDE_ENABLED).convert("RGB")
                   .crop((660, 850, 1120, 944)))
    compose([(dis, "未达条件 · 悬停仍是禁用态"),
             (ena, "达成条件 · 悬停高亮可点")],
            os.path.join(SHOTS, "69_hover_disabled.png"),
            "下一步按钮：禁用态 / 悬停可用", zoom=2)

    # ⑥ F2 热区覆盖（1px）
    fh = scenes.Flow(path, core.BPM)
    fh.key("ENTER", 0.0)
    fh.key("ENTER", 0.0)
    ui.show_hotzones = True
    ui.draw_guide(screen, fh, 0.0)
    ui.overlay(screen, fh)
    ui.show_hotzones = False
    save(HOT).save(os.path.join(SHOTS, "70_hotzones.png"))
    print("ROUND19_SHOTS: OK")
    return 0


def _center(rect):
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


def _pad_top(im: Image.Image, pad: int = 40):
    """裁图上留一条说明栏，避免标题压住按钮边框。"""
    out = Image.new("RGB", (im.width, im.height + pad), (8, 6, 10))
    out.paste(im, (0, pad))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
