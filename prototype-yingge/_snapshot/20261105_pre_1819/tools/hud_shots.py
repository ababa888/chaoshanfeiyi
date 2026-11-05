"""第十五轮 HUD 字体验收图：1080p 原生输出层 + 字形特写。

运行：py -3 prototype-yingge/tools/hud_shots.py
产出（shots/）：
- 47_hud_font_before_after_3x.png  改前/改后同区域 3× 对比
- 48_hud_confusable_3x.png         形近字并排 3×
- 49_hud_16px_full_1080p.png       最小 16px 整屏 HUD（1080p）
- 50_hud_dense_glyph_6x.png        密字（围/阵/减）单字 6× 特写
- 51_hud_world_composite_1080p.png HUD 层与世界层叠合实景
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame

import core
import pixel_font as pf
import render as r
import selftest as st

SHOTS = os.path.join(ROOT, "shots")
W, H = 1920, 1080
INK = (255, 240, 206)
BG = (16, 12, 16)


def frame(ren: r.Renderer, game: core.Game) -> pygame.Surface:
    """真实输出分辨率：HUD 按 1920×1080 原生排版，世界层 960→2×。"""
    screen = pygame.display.set_mode((W, H))
    ren.draw(screen, game, game.now, 0.0)
    return screen.copy()


def label(img: pygame.Surface, text: str, pos, size=22,
          color=(255, 226, 160)) -> None:
    font = pygame.font.SysFont("Consolas", size)
    surf = font.render(text, False, color)
    img.blit(surf, pos)


def state(low: bool = False, fever: bool = False, combo: int = 16) -> core.Game:
    g = st.boss_game()
    keys = st.correct_keys(g.intent_key or "")
    for i in range(2):
        st.press_at(g, 4 + i, keys[i])
    g.combo = combo
    g.result_pop = ("PERFECT!", 0.72)
    if low:
        for u in g.squad.units:
            u.hp = 5.0
        g.boss.hp = g.boss.max_hp * 0.12
    if fever:
        g.fever_active = True
        g.fever_until = g.now + 4.0
    return g


def glyph_img(ch: str, px: int, zoom: int) -> pygame.Surface:
    """px 为输出像素字号（最小 16），按整数倍 nearest 放大。"""
    logical = 8 if px <= 16 else 10 if px <= 20 else 12
    img = pf._compose(ch, logical, INK, False, True, None)
    return pygame.transform.scale(img, (img.get_width() * zoom,
                                        img.get_height() * zoom))


def shot_before_after(after: pygame.Surface) -> None:
    before = pygame.image.load(os.path.join(SHOTS, "18_hud_1080p_before.png"))
    # 同一屏幕区域：读招面板左侧（含标题与化解键位）
    rect = pygame.Rect(500, 140, 600, 200)
    bc = before.subsurface(rect).copy()
    ac = after.subsurface(rect).copy()
    z = 3
    cw, chh = rect.w * z, rect.h * z
    montage = pygame.Surface((max(cw + 40, 1880), chh * 2 + 120))
    montage.fill(BG)
    montage.blit(pygame.transform.scale(bc, (cw, chh)), (20, 44))
    montage.blit(pygame.transform.scale(ac, (cw, chh)), (20, chh + 92))
    label(montage, "BEFORE x3 / old 5x7 font, 960->1080 resample", (20, 10))
    label(montage, "AFTER x3 / native 1920 HUD, Fusion Pixel 20px", (20, chh + 58))
    pygame.image.save(montage, os.path.join(
        SHOTS, "47_hud_font_before_after_3x.png"))


def shot_confusable() -> None:
    pairs = [("围", "团", "wei", "tuan"), ("阵", "陈", "zhen", "chen"),
             ("减", "咸", "jian", "xian"), ("响", "晌", "xiang", "shang"),
             ("撤", "撒", "che", "sa"), ("锣", "罗", "luo", "luo2")]
    z = 3
    cell_w, cell_h = 250, 260
    img = pygame.Surface((cell_w * len(pairs), cell_h + 60))
    img.fill(BG)
    for i, (a, b, pa, pb) in enumerate(pairs):
        x = i * cell_w
        label(img, f"{i + 1}. {pa}/{pb}", (x + 8, 8), 20)
        ga, gb = glyph_img(a, 16, z), glyph_img(b, 16, z)
        img.blit(ga, (x + 30, 50))
        img.blit(gb, (x + 110, 50))
    pygame.image.save(img, os.path.join(SHOTS, "48_hud_confusable_3x.png"))


def shot_dense() -> None:
    z = 6
    img = pygame.Surface((120 * 3 + 60, 260))
    img.fill(BG)
    for i, (ch, py) in enumerate(zip("围阵减", ("wei", "zhen", "jian"))):
        g = glyph_img(ch, 16, z)
        img.blit(g, (30 + i * 120, 36))
        label(img, py, (30 + i * 120 + 6, 190), 24)
        label(img, "16px x6", (30 + i * 120, 220), 16,
              (200, 190, 170))
    pygame.image.save(img, os.path.join(SHOTS, "50_hud_dense_glyph_6x.png"))


def main() -> int:
    pygame.init()
    pygame.display.set_mode((W, H))
    os.makedirs(SHOTS, exist_ok=True)
    ren = r.Renderer()

    g = state()
    after = frame(ren, g)
    shot_before_after(after)

    pygame.image.save(after, os.path.join(SHOTS,
                                          "49_hud_16px_full_1080p.png"))

    shot_confusable()
    shot_dense()

    # 世界层叠合实景：行军段（杂兵 + 坡面 + 灯笼），HUD 原样压在上层
    ren2 = r.Renderer()
    g2 = core.Game(start_time=0.0)
    for n in range(9):
        g2.beat_press("K", n * (60.0 / g2.clock.base_bpm), 0.0)
    st.advance(g2, g2.now + 0.9)
    comp = frame(ren2, g2)
    pygame.image.save(comp, os.path.join(
        SHOTS, "51_hud_world_composite_1080p.png"))

    for name in ("47_hud_font_before_after_3x.png",
                 "48_hud_confusable_3x.png",
                 "49_hud_16px_full_1080p.png",
                 "50_hud_dense_glyph_6x.png",
                 "51_hud_world_composite_1080p.png"):
        print("[shot]", os.path.join(SHOTS, name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
