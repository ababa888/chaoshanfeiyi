"""第十六轮验收图：输入两段式反馈 + 横向滚动谱面带。

运行：py -3 prototype-yingge/tools/beat_ribbon_shots.py
产出（shots/）：
- 52_input_press_3frames.png    同一按键连续三帧（按下 → 待确认 → 锁定）
- 53_ribbon_normal_1080p.png    谱面带常态整屏
- 54_ribbon_perfect.png         Perfect 金框落定
- 55_ribbon_miss.png            Miss 红斜杠
- 56_boss_ribbon_warning.png    Boss 公示预警叠在谱面带
- 57_ribbon_before_after.png    旧四拍条 vs 新谱面带（同区域）
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
W, H = 1920, 1080
BG = (16, 12, 16)
INK = (255, 226, 160)


def frame(ren: r.Renderer, game: core.Game) -> pygame.Surface:
    screen = pygame.display.set_mode((W, H))
    ren.draw(screen, game, game.now, 0.0)
    return screen.copy()


def label(img: pygame.Surface, text: str, pos, size=20,
          color=INK) -> None:
    font = pygame.font.SysFont("Consolas", size)
    img.blit(font.render(text, False, color), pos)


def crop(img: pygame.Surface, rect) -> pygame.Surface:
    return img.subsurface(pygame.Rect(*rect)).copy()


def banner(img: pygame.Surface, text: str, color=INK) -> pygame.Surface:
    """在图上加一条 34px 标头条，避免标注压住谱面带。"""
    out = pygame.Surface((img.get_width(), img.get_height() + 34),
                         pygame.SRCALPHA)
    out.fill(BG)
    label(out, text, (10, 6), 20, color)
    out.blit(img, (0, 34))
    return out


def stack(rows, texts, out_name: str, pad: int = 16) -> None:
    w = max(s.get_width() for s in rows)
    h = sum(s.get_height() + pad + 24 for s in rows) + pad
    img = pygame.Surface((w + pad * 2, h), pygame.SRCALPHA)
    img.fill(BG)
    y = pad
    for s, t in zip(rows, texts):
        label(img, t, (pad, y))
        y += 24
        img.blit(s, (pad, y))
        y += s.get_height() + pad
    pygame.image.save(img, os.path.join(SHOTS, out_name))
    print("[shot]", os.path.join(SHOTS, out_name))


def press_time(g: core.Game, beat: float) -> float:
    """把目标拍位换算成当前时钟下的时间戳。"""
    rate = g.clock.bpm / 60.0
    return g.now + (beat - g.clock.beat_pos) / rate


def main() -> int:
    pygame.init()
    pygame.display.set_mode((W, H))
    os.makedirs(SHOTS, exist_ok=True)
    ren = r.Renderer()

    # ① 同一按键连续三帧：按下前 → 按下当帧（下沉 1px + 待确认半格）→ 拍点锁定
    g = st.make_game()
    st.advance(g, 2.0)                          # 等 BPM 收敛，避免 beat_time 近似误差
    nbeat = 10
    bt = g.clock.beat_time(nbeat)
    st.advance(g, bt - 0.05)
    seq = [frame(ren, g)]                       # 按下前
    t = bt - 0.025
    g.push_input("J", t)
    g.update(t, t - g.now)
    seq.append(frame(ren, g))                   # 按下当帧
    for _ in range(2):
        g.update(g.now + 1.0 / 60.0, 1.0 / 60.0)
    seq.append(frame(ren, g))                   # 拍点锁定
    rows = []
    for f in seq:
        left = crop(f, (40, 805, 400, 190))     # 乐器架
        right = crop(f, (700, 805, 460, 190))   # 判定线附近
        row = pygame.Surface((860, 190))
        row.fill(BG)
        row.blit(left, (0, 0))
        row.blit(right, (400, 0))
        rows.append(row)
    stack(rows,
          ["FRAME 0  before press: no sink, empty slot",
           "FRAME +1 press: icon -1px + lit, slot PENDING (half fill + pulse)",
           "FRAME +2 beat lock: grade settles at judge line"],
          "52_input_press_3frames.png")

    # ② 谱面带常态（整屏）：本组两拍已确认，后两拍留空，下一组弱化预排
    g2 = st.make_game()
    st.advance(g2, 1.35)
    grp = g2._group(g2.cycle_index)
    grp.slots[1].key, grp.slots[1].grade, grp.slots[1].beat = "K", "good", 1
    grp.slots[2].key, grp.slots[2].grade, grp.slots[2].beat = "J", "perfect", 2
    normal = frame(ren, g2)
    pygame.image.save(normal, os.path.join(SHOTS, "53_ribbon_normal_1080p.png"))
    print("[shot]", os.path.join(SHOTS, "53_ribbon_normal_1080p.png"))

    ribbon_rect = (500, 790, 1420, 240)

    # ③ Perfect 落定（拍点后 40ms，金框 inflate 仍生效）
    g3 = st.make_game()
    st.advance(g3, 1.20)
    t3 = press_time(g3, 3.0) + 0.004
    g3.push_input("J", t3)
    g3.update(t3 + 0.040, 0.040)
    rf = frame(ren, g3)
    perfect = banner(crop(rf, ribbon_rect),
                     "PERFECT: gold frame + inflate (120ms)")
    pygame.image.save(perfect, os.path.join(SHOTS, "54_ribbon_perfect.png"))
    print("[shot]", os.path.join(SHOTS, "54_ribbon_perfect.png"))

    # ④ Miss 红斜杠（拍点后 100ms，仍在 420ms 停留窗口）
    g4 = st.make_game()
    st.advance(g4, 1.20)
    grp = g4._group(g4.cycle_index)
    slot = grp.slots[2]
    slot.key, slot.grade, slot.beat = "J", "miss", 2
    g4.now = max(g4.now, g4.clock.beat_time(2) + 0.10)
    rf = frame(ren, g4)
    miss = banner(crop(rf, ribbon_rect),
                  "MISS: red slash, 420ms hold", (255, 150, 140))
    pygame.image.save(miss, os.path.join(SHOTS, "55_ribbon_miss.png"))
    print("[shot]", os.path.join(SHOTS, "55_ribbon_miss.png"))

    # ⑤ Boss 公示预警：高亮段叠在谱面带内
    gb = st.boss_game()
    boss = banner(crop(frame(ren, gb), ribbon_rect),
                  "BOSS tell: band on ribbon (no 3rd panel)",
                  (255, 170, 130))
    pygame.image.save(boss, os.path.join(SHOTS, "56_boss_ribbon_warning.png"))
    print("[shot]", os.path.join(SHOTS, "56_boss_ribbon_warning.png"))

    # ⑥ 旧四拍条 vs 新谱面带，同区域
    old_path = os.path.join(SHOTS, "18_hud_1080p.png")
    old = pygame.image.load(old_path)
    rect6 = (460, 800, 1200, 200)
    old_c = crop(old, rect6)
    new_c = crop(normal, rect6)
    stack([old_c, new_c],
          ["BEFORE: static 4-beat cells + strong/weak marks",
           "AFTER: scrolling ribbon, fixed judge line at x=437"],
          "57_ribbon_before_after.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
