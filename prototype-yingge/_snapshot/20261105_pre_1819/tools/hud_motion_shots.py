"""第十一轮 HUD 交互动效验收图（28–32）+ 交互预览 GIF。

运行：py -3 prototype-yingge/tools/hud_motion_shots.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame

import core
import render as r
import selftest as st
from gif_writer import write_gif

SHOTS = os.path.join(ROOT, "shots")
BG = (12, 8, 12)


def view(ren: r.Renderer, game: core.Game, dt: float = 0.0) -> pygame.Surface:
    s = pygame.Surface((r.VIEW_W, r.VIEW_H))
    ren.draw(s, game, game.now, dt)
    return s


def big(ren: r.Renderer, game: core.Game) -> pygame.Surface:
    return pygame.transform.scale(view(ren, game), (1920, 1080))


def label(img: pygame.Surface, text: str, pos, color=(255, 226, 160)) -> None:
    font = pygame.font.Font(None, 20)
    img.blit(font.render(text, False, color), pos)


def montage(left: pygame.Surface, right: pygame.Surface,
            ltext: str, rtext: str, name: str,
            zoom: tuple[int, int, int, int] | None = None,
            ztext: tuple[str, str] = ("", "")) -> None:
    out = pygame.Surface((1920, 1080))
    out.fill(BG)
    out.blit(pygame.transform.scale(left, (960, 540)), (0, 0))
    out.blit(pygame.transform.scale(right, (960, 540)), (960, 0))
    label(out, ltext, (12, 548))
    label(out, rtext, (972, 548))
    if zoom:
        x, y, w, h = zoom
        zl = left.subsurface((x, y, w, h)).copy()
        zr = right.subsurface((x, y, w, h)).copy()
        out.blit(pygame.transform.scale(zl, (w * 3, h * 3)), (40, 600))
        out.blit(pygame.transform.scale(zr, (w * 3, h * 3)), (1000, 600))
        label(out, ztext[0], (40, 610 + h * 3))
        label(out, ztext[1], (1000, 610 + h * 3))
    pygame.image.save(out, os.path.join(SHOTS, name))
    print("[shot]", os.path.join(SHOTS, name))


def scene_press() -> None:
    g = st.make_game()
    st.advance(g, 0.02)
    g.beat_press("J", g.now, 0.0)
    g.press_times["J"] = g.now - 0.060
    g.press_grades["J"] = "perfect"
    ren = r.Renderer()
    pressed = view(ren, g)
    g.press_times["J"] = g.now - 0.122
    rebound = view(ren, g)
    montage(pressed, rebound,
            "PRESS · 下沉 2px + 暗一阶 + 火星 + 金边",
            "REBOUND · 命中帧回弹 -1px",
            "28_hud_press_rebound.png",
            zoom=(20, 416, 128, 92),
            ztext=("按下 3×", "回弹 3×"))


def scene_slots() -> None:
    g = st.make_game()
    beat = 60.0 / g.clock.base_bpm
    st.press_at(g, 0, "J")
    st.press_at(g, 1, "J")
    st.press_at(g, 2, "K")
    st.advance(g, 2.62 * beat)
    ren = r.Renderer()
    ghost = view(ren, g)
    st.press_at(g, 3, "K")
    st.advance(g, 3.06 * beat)
    solid = view(ren, g)
    montage(ghost, solid,
            "第 3 拍 · JJK → 灰版预测「双龙」（落位砸入）",
            "第 4 拍 · JJKK 实色发亮",
            "29_hud_slot_predict.png",
            zoom=(210, 418, 660, 96),
            ztext=("落位 + 幽灵预测 3×", "满 4 拍实色 3×"))


def scene_lowhp() -> None:
    g = st.make_game()
    g.fever_gauge = g.diff["fever_gauge"]
    g.combo = 41
    for u in g.squad.units:
        u.hp = u.max_hp * 0.9
    ren = r.Renderer()
    ren._update_hud_motion(g, 0.0)
    for u in g.squad.units:
        u.hp = u.max_hp * 0.22
    for _ in range(4):
        ren._update_hud_motion(g, 0.02)
    ren._combo_t = 0.01
    img = big(ren, g)
    pygame.image.save(img, os.path.join(SHOTS, "30_hud_lowhp_gauge.png"))
    print("[shot]", os.path.join(SHOTS, "30_hud_lowhp_gauge.png"))


def scene_fever() -> None:
    g = st.boss_game()
    g.fever_active = True
    g.fever_until = g.now + 5.0
    ren = r.Renderer()
    ren._fever_level = 1.0
    ren._fever_prev = True
    fin = view(ren, g)
    g.fever_active = False
    ren._fever_level = 0.35
    ren._fever_prev = False
    fout = view(ren, g)
    montage(fin, fout,
            "FEVER IN · 金红描边 + 流光 + 压暗（0.4s）",
            "FEVER OUT · 0.25s 逐档退回",
            "31_hud_fever_inout.png")


def scene_break_result() -> None:
    g = st.boss_game()
    ren = r.Renderer()
    g.last_stagger_cycle = 0
    ren._update_hud_motion(g, 0.0)
    ren._seal_t = 0.20
    ren._flash_frames = 1
    brk = view(ren, g)
    g.status = "cleared"
    g.last_stagger_cycle = -1
    ren2 = r.Renderer()
    for _ in range(24):
        ren2._update_hud_motion(g, 1.0 / 60.0)
    ren2._flash_frames = 0
    ren2._seal_t = 99.0
    res = view(ren2, g)
    montage(brk, res,
            "破阵 · 「破」字印章落下 + 白闪 ≤3 帧",
            "胜利结算 · 暖金面板推入（0.3s）",
            "32_hud_break_result.png")


def make_gif() -> None:
    g = st.make_game()
    ren = r.Renderer()
    beat = 60.0 / g.clock.base_bpm
    fps = 15
    total = 8.0
    presses = {0: "J", 1: "J", 2: "K", 3: "K"}
    done_press: set[int] = set()
    low = fever = broke = result = False
    frames: list[pygame.Surface] = []
    delays: list[int] = []
    t = 0.0
    while t < total - 1e-6:
        st.advance(g, t, step=1.0 / fps)
        for b, k in presses.items():
            if b not in done_press and t >= (b + 0.35) * beat:
                st.press_at(g, b, k)
                done_press.add(b)
        if not low and t >= 2.3:
            low = True
            ren._update_hud_motion(g, 0.0)
            for u in g.squad.units:
                u.hp = u.max_hp * 0.22
        if not fever and t >= 3.1:
            fever = True
            g.fever_gauge = g.diff["fever_gauge"]
            g.fever_active = True
            g.fever_until = g.now + 10.0
        if not broke and t >= 4.4:
            broke = True
            g.last_stagger_cycle = 0
        if not result and t >= 5.6:
            result = True
            g.status = "cleared"
        if t >= 6.6 and g.fever_active:
            g.fever_active = False
            g.fever_until = g.now
        frame = view(ren, g, 1.0 / fps)
        frames.append(pygame.transform.scale(frame, (480, 270)))
        delays.append(int(1000 / fps))
        t += 1.0 / fps

    palette = [(rr, gg, bb) for rr in range(0, 256, 51)
               for gg in range(0, 256, 51) for bb in range(0, 256, 51)]
    palette += [(v, v, v) for v in range(0, 256, 32)]
    path = os.path.join(SHOTS, "hud_interaction.gif")
    w, h = write_gif(path, frames, palette, delays)
    print(f"[gif] {path} {w}x{h} {len(frames)}f {total:.1f}s")


def main() -> int:
    pygame.init()
    pygame.display.set_mode((r.VIEW_W, r.VIEW_H))
    scene_press()
    scene_slots()
    scene_lowhp()
    scene_fever()
    scene_break_result()
    make_gif()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
