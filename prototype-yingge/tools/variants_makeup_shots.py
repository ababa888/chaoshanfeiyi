"""生成「变体去重 + 补打」验收图（23–27）。

运行：py -3 prototype-yingge/tools/variants_makeup_shots.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame

import core
import render as r
import selftest as st

SHOTS = os.path.join(ROOT, "shots")
W1080, H1080 = 1920, 1080


def frame1080(ren: r.Renderer, game: core.Game) -> pygame.Surface:
    view = pygame.Surface((r.VIEW_W, r.VIEW_H))
    ren.draw(view, game, game.now, 0.0)
    return pygame.transform.scale(view, (W1080, H1080))


def label(img: pygame.Surface, text: str, pos, size=18,
          color=(255, 226, 160)) -> None:
    font = pygame.font.Font(None, size)
    img.blit(font.render(text, False, color), pos)


def layer_only(ren: r.Renderer, key: str, cam: float) -> pygame.Surface:
    """只画天空底图 + 指定视差层，用于同位置变体 A/B 对照。"""
    ren.cam_x = cam
    ren.cam_dip = 0.0
    view = pygame.Surface((r.VIEW_W, r.VIEW_H))
    view.blit(ren.bg_static, (0, 0))
    base = 64.0 if key == "far" else (ren._gy(r.SCREEN_BASE_X)
                                      - ren.bank.layers[key].get_height() + 14.0)
    ren._draw_layer(view, key, base)
    return view


def seed_for(ren: r.Renderer, key: str, cam: float, want: int) -> int:
    """找一个 seed，使屏幕中心所在平铺恰好是变体 want。"""
    factor = r.PARALLAX[key]["x"]
    iw = ren.bank.layer_variants[key][0].get_width()
    tile = int((cam * ren.world_px() * factor + r.VIEW_W // 2) // iw)
    for seed in range(1, 5000):
        ren.layer_variant_seed = seed
        if ren._layer_variant(key, tile)[1] == want:
            return seed
    return 0


def makeup_state(success: bool) -> core.Game:
    g = st.phase_fail_game(2)
    if success:
        for k in g.makeup_pattern:
            g.beat_press(k, g.now, 0.0)
    return g


def main() -> int:
    pygame.init()
    pygame.display.set_mode((r.VIEW_W, r.VIEW_H))
    ren = r.Renderer()
    os.makedirs(SHOTS, exist_ok=True)

    # ① 远景两套变体：同一相机位置 A/B
    cam = 12.0
    seed_a = seed_for(ren, "far", cam, 0)
    va = layer_only(ren, "far", cam).copy()
    seed_b = seed_for(ren, "far", cam, 1)
    vb = layer_only(ren, "far", cam).copy()
    ab = pygame.Surface((1920, 600))
    ab.fill((10, 8, 12))
    ab.blit(va, (0, 30))
    ab.blit(vb, (960, 30))
    label(ab, f"A · variant 0 (seed {seed_a})", (8, 8))
    label(ab, f"B · variant 1 (seed {seed_b})", (968, 8))
    label(ab, "same cam_x / identical horizon / seam <= 16", (8, 574), 15,
          (190, 170, 150))
    pygame.image.save(ab, os.path.join(SHOTS, "23_far_variant_ab.png"))

    # ② 中景三套模板：同一相机位置轮换
    mid = pygame.Surface((1920, 1400))
    mid.fill((10, 8, 12))
    for i in range(3):
        seed = seed_for(ren, "mid", cam, i)
        lay = layer_only(ren, "mid", cam)
        crop = lay.subsurface((0, 180, r.VIEW_W, 300)).copy()
        big = pygame.transform.scale(crop, (1920, 600))
        mid.blit(big, (0, i * 460))
        label(mid, f"mid template {i} (seed {seed})", (8, i * 460 + 8))
    pygame.image.save(mid, os.path.join(SHOTS, "24_mid_variants_abc.png"))

    # ③ 补打 1 拍倒计时环（全帧 1080p）
    ring = makeup_state(False)
    ren.layer_variant_seed = 20261104
    shot_ring = frame1080(ren, ring)
    pygame.image.save(shot_ring, os.path.join(SHOTS,
                                              "25_makeup_ring_1080p.png"))
    crop = shot_ring.subsurface((480, 120, 560, 300)).copy()
    pygame.image.save(pygame.transform.scale(
        crop, (crop.get_width() * 2, crop.get_height() * 2)),
        os.path.join(SHOTS, "25b_makeup_ring_2x.png"))

    # ④ 补打成功反馈
    ok = makeup_state(True)
    shot_ok = frame1080(ren, ok)
    pygame.image.save(shot_ok, os.path.join(SHOTS,
                                            "26_makeup_success_1080p.png"))
    crop = shot_ok.subsurface((480, 120, 560, 300)).copy()
    pygame.image.save(pygame.transform.scale(
        crop, (crop.get_width() * 2, crop.get_height() * 2)),
        os.path.join(SHOTS, "26b_makeup_success_2x.png"))

    # ⑤ 长距离推进：连续两段世界（同一 seed，相机真前进一个远景周期）
    step = 960.0 / (ren.world_px() * r.PARALLAX["far"]["x"])
    g1 = st.boss_game()
    g1.squad.x = 20.0
    g2 = st.boss_game()
    g2.squad.x = 20.0 + step
    ren.layer_variant_seed = 20261104
    ren.cam_x = g1.squad.x
    f1 = frame1080(ren, g1)
    ren.cam_x = g2.squad.x
    f2 = frame1080(ren, g2)
    strip = pygame.Surface((1920, 620))
    strip.fill((10, 8, 12))
    strip.blit(pygame.transform.scale(f1, (960, 540)), (0, 30))
    strip.blit(pygame.transform.scale(f2, (960, 540)), (960, 30))
    label(strip, "before · far tile t0", (8, 8))
    label(strip, "after ~1 far tile (83 units) · variant switched", (968, 8))
    pygame.image.save(strip, os.path.join(SHOTS,
                                          "27_variant_long_strip.png"))

    for name in ("23_far_variant_ab.png", "24_mid_variants_abc.png",
                 "25_makeup_ring_1080p.png", "25b_makeup_ring_2x.png",
                 "26_makeup_success_1080p.png", "26b_makeup_success_2x.png",
                 "27_variant_long_strip.png"):
        print("[shot]", os.path.join(SHOTS, name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
