"""程序化生成原型素材（可重跑、无第三方依赖）。

用法：python prototype-yingge/tools/gen_assets.py
输出：prototype-yingge/assets_gen/ 下的透明 PNG + manifest.json

约定：
- 20 色统一调色板（见 PALETTE）。
- 角色按族使用同一整数倍缩放：玩家/敌人/Boss 4x，UI 2x，环境 2x/4x。
- 每个角色的所有状态帧共用同一脚底基线（manifest 里逐图记录）。
- 不使用随机数，重跑结果一致。
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets_gen")
sys.path.insert(0, ROOT)
import pseudo3d as p3d  # noqa: E402  投影档位是唯一真源，预烘必须与自测同表

PALETTE = {
    "ink": (18, 14, 20),
    "night": (30, 22, 44),
    "deep_red": (118, 26, 34),
    "red": (184, 44, 40),
    "vermilion": (232, 80, 46),
    "gold": (238, 186, 88),
    "amber": (255, 216, 122),
    "cream": (255, 240, 206),
    "skin": (238, 196, 148),
    "skin_dark": (194, 142, 102),
    "teal": (36, 112, 98),
    "jade": (92, 178, 138),
    "purple": (92, 64, 138),
    "violet": (154, 108, 188),
    "blue": (58, 94, 160),
    "steel": (122, 138, 156),
    "brown": (116, 76, 52),
    "leather": (166, 118, 72),
    "grass": (74, 110, 58),
    "white": (255, 255, 255),
    # 三层景深扩展色（总 28 色上限，低饱和远景/近景剪影）
    "sky_low": (46, 34, 62),
    "sea": (42, 52, 76),
    "mist": (96, 96, 122),
    "wall": (62, 46, 58),
    "tile": (38, 30, 44),
    "window": (214, 138, 78),
    "fg": (14, 10, 16),
    "fg_green": (34, 48, 36),
}

# 好汉定妆照/动作帧扩展到 40 色：新增 12 个三阶明暗专用色
# （基础 28 色保留不动，仅补硬边高光与暗部，语义见 docs/hero_style_guide.md）
PALETTE_ADDED = {
    "shadow": (10, 8, 14),           # 统一轮廓/投影暗部
    "gold_dark": (162, 112, 44),     # 金饰暗部
    "gold_light": (255, 232, 170),   # 金饰高光
    "skin_light": (252, 218, 180),   # 皮肤高光
    "skin_shadow": (146, 96, 72),    # 皮肤暗部
    "red_dark": (88, 18, 26),        # 赤面/红衣暗部
    "red_light": (236, 118, 84),     # 赤面/红衣高光
    "teal_dark": (18, 68, 58),       # 青甲暗部
    "teal_light": (132, 200, 164),   # 青甲高光
    "violet_dark": (56, 34, 90),     # 紫甲暗部
    "violet_light": (198, 160, 224), # 紫甲高光
    "steel_dark": (72, 82, 98),      # 铁器/斧刃暗部
}
PALETTE.update(PALETTE_ADDED)
C = {k: v for k, v in PALETTE.items()}

MANIFEST: dict = {
    "palette": {k: "#%02x%02x%02x" % v for k, v in PALETTE.items()},
    "palette_count": len(PALETTE),
    "palette_added": list(PALETTE_ADDED),
    "scale": {"characters": 4, "ui": 2, "environment": 2,
              "heroes": 3, "portraits": 1, "sheets": 1},
    "images": {},
    "sheets": {},
    "animations": {},
}


def surf(w: int, h: int) -> pygame.Surface:
    return pygame.Surface((w, h), pygame.SRCALPHA)


def rect(s, x, y, w, h, c):
    pygame.draw.rect(s, C[c], (int(x), int(y), int(w), int(h)))


def ellipse(s, x, y, w, h, c, width=0):
    pygame.draw.ellipse(s, C[c], (int(x), int(y), int(w), int(h)), width)


def poly(s, pts, c):
    pygame.draw.polygon(s, C[c], [(int(x), int(y)) for x, y in pts])


def line(s, x1, y1, x2, y2, c, width=1):
    pygame.draw.line(s, C[c], (int(x1), int(y1)), (int(x2), int(y2)), width)


def save(s: pygame.Surface, rel: str, scale: int, family: str,
         baseline: int | None = None):
    path = os.path.join(OUT, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = pygame.transform.scale(s, (s.get_width() * scale, s.get_height() * scale))
    pygame.image.save(out, path)
    MANIFEST["images"][rel] = {
        "path": rel,
        "size": list(out.get_size()),
        "base_size": list(s.get_size()),
        "scale": scale,
        "family": family,
        "baseline": None if baseline is None else baseline * scale,
    }


# ------------------------------------------------------------------ 玩家
PLAYER_STYLE = {
    "drummer": dict(vest="red", trim="gold", mask="vermilion", pants="ink",
                    skin="skin", weapon="drum", accent="amber"),
    "shield": dict(vest="teal", trim="jade", mask="ink", pants="brown",
                   skin="skin", weapon="shield", accent="gold"),
    "spear": dict(vest="purple", trim="violet", mask="cream", pants="night",
                  skin="skin", weapon="spear", accent="gold"),
}


def draw_player(kind: str, state: str, frame: int) -> pygame.Surface:
    """28×36 基础画布，脚底基线 y=34。"""
    w, h, base = 28, 36, 34
    s = surf(w, h)
    st = PLAYER_STYLE[kind]
    bob = -1 if (state == "idle" and frame == 1) else 0
    lean = 1 if state == "attack" else (-1 if state == "hurt" else 0)

    if state == "down":
        # 倒地：身体横躺，武器落地，脚底仍在基线
        rect(s, 4, 29, 18, 4, st["vest"])
        rect(s, 4, 27, 5, 5, st["trim"])
        ellipse(s, 2, 25, 8, 8, st["mask"])
        rect(s, 5, 28, 1, 1, "white")
        rect(s, 7, 28, 1, 1, "white")
        if st["weapon"] == "drum":
            ellipse(s, 19, 27, 7, 6, "gold")
            ellipse(s, 20, 28, 5, 4, "red")
            line(s, 21, 30, 25, 33, "leather", 1)
        elif st["weapon"] == "shield":
            ellipse(s, 15, 24, 9, 8, "jade")
            ellipse(s, 16, 25, 7, 6, "gold", 1)
        else:
            line(s, 8, 33, 26, 33, "leather", 2)
            poly(s, [(26, 33), (24, 31), (24, 35)], "amber")
        return s

    leg_swing = 0
    if state == "march":
        leg_swing = 3 if frame == 0 else -3
    # 腿
    lx, rx = 10, 16
    if leg_swing:
        rect(s, lx - 1 + leg_swing, 25, 4, 7, st["pants"])
        rect(s, rx + 1 - leg_swing, 25, 4, 7, st["pants"])
        rect(s, lx - 1 + leg_swing, 32, 5, 2, "ink")
        rect(s, rx + 1 - leg_swing, 32, 5, 2, "ink")
    else:
        rect(s, lx, 25, 4, 9, st["pants"])
        rect(s, rx, 25, 4, 9, st["pants"])
        rect(s, lx - 1, 32, 5, 2, "ink")
        rect(s, rx, 32, 5, 2, "ink")

    by = 14 + bob
    # 披风/背饰
    if kind == "drummer":
        poly(s, [(8, by + 2), (3, by + 12), (6, by + 13), (9, by + 10)], "deep_red")
    elif kind == "shield":
        poly(s, [(20, by + 2), (26, by + 12), (22, by + 14), (19, by + 10)], "blue")
    else:
        poly(s, [(7, by + 2), (2, by + 13), (5, by + 14), (9, by + 11)], "violet")

    # 身体
    rect(s, 8 + lean, by, 12, 12, st["vest"])
    rect(s, 8 + lean, by + 10, 12, 2, "gold")
    rect(s, 10 + lean, by + 2, 8, 2, st["trim"])
    # 手臂（后手 / 前手）
    if state == "attack":
        line(s, 9 + lean, by + 3, 4 + lean, by + 1, "skin", 2)
        line(s, 18 + lean, by + 3, 24 + lean, by + 1, "skin", 2)
        rect(s, 3 + lean, by, 2, 2, "skin_dark")
        rect(s, 23 + lean, by, 2, 2, "skin_dark")
    elif state == "hurt":
        line(s, 9, by + 4, 4, by + 9, "skin", 2)
        line(s, 18, by + 4, 23, by + 9, "skin", 2)
        rect(s, 3, by + 8, 2, 2, "skin_dark")
        rect(s, 23, by + 8, 2, 2, "skin_dark")
    else:
        line(s, 9 + lean, by + 3, 5 + lean, by + 9, "skin", 2)
        line(s, 18 + lean, by + 3, 22 + lean, by + 9, "skin", 2)
        rect(s, 4 + lean, by + 8, 2, 2, "skin_dark")
        rect(s, 21 + lean, by + 8, 2, 2, "skin_dark")

    # 头 / 脸谱
    ellipse(s, 9 + lean, 4 + bob, 11, 11, st["skin"])
    ellipse(s, 10 + lean, 5 + bob, 9, 9, st["mask"])
    rect(s, 12 + lean, 8 + bob, 2, 2, "white")
    rect(s, 16 + lean, 8 + bob, 2, 2, "white")
    rect(s, 13 + lean, 9 + bob, 1, 1, "ink")
    rect(s, 17 + lean, 9 + bob, 1, 1, "ink")
    rect(s, 13 + lean, 11 + bob, 3, 1, st["accent"])
    # 头饰/角
    poly(s, [(10 + lean, 5 + bob), (8 + lean, 1 + bob), (12 + lean, 3 + bob)], "gold")
    poly(s, [(18 + lean, 5 + bob), (20 + lean, 1 + bob), (16 + lean, 3 + bob)], "gold")
    if kind == "drummer":
        line(s, 14 + lean, 5 + bob, 12 + lean, 1 + bob, "vermilion", 2)
        line(s, 14 + lean, 5 + bob, 16 + lean, 0 + bob, "amber", 2)
    elif kind == "shield":
        rect(s, 9 + lean, 2 + bob, 11, 3, "jade")
    else:
        line(s, 14 + lean, 5 + bob, 15 + lean, 0 + bob, "amber", 2)

    # 武器
    if st["weapon"] == "drum":
        ellipse(s, 10, 22, 8, 6, "gold")
        ellipse(s, 11, 23, 6, 4, "red")
        if state == "attack":
            line(s, 4, by + 1, 11, 24, "leather", 1)
            line(s, 24, by + 1, 17, 24, "leather", 1)
            rect(s, 10, 23, 2, 2, "amber")
            rect(s, 16, 23, 2, 2, "amber")
        else:
            line(s, 5, by + 8, 11, 25, "leather", 1)
            line(s, 22, by + 8, 17, 25, "leather", 1)
    elif st["weapon"] == "shield":
        ellipse(s, 19 + lean, 12, 8, 15, "jade")
        ellipse(s, 20 + lean, 13, 6, 13, "gold", 1)
        ellipse(s, 22 + lean, 18, 3, 4, "amber")
        if state == "attack":
            rect(s, 23 + lean, 14, 4, 12, "steel")
            line(s, 20 + lean, 15, 27 + lean, 15, "cream", 1)
    else:
        if state == "attack":
            line(s, 18 + lean, by + 5, 28, by + 4, "leather", 2)
            poly(s, [(28, by + 4), (25, by + 2), (25, by + 6)], "amber")
        else:
            line(s, 5, by + 9, 25, 4, "leather", 2)
            poly(s, [(25, 4), (23, 1), (23, 7)], "amber")

    # 受击红痕
    if state == "hurt":
        line(s, 8, 6, 19, 12, "vermilion", 2)
    return s


def gen_players():
    for kind in PLAYER_STYLE:
        for state, count in (("idle", 2), ("march", 2), ("attack", 2),
                             ("hurt", 1), ("down", 1)):
            for i in range(count):
                s = draw_player(kind, state, i)
                save(s, f"players/{kind}/{state}_{i}.png", 4, "player", 34)


# ------------------------------------------------------------------ 敌人
def draw_grunt(state: str, frame: int) -> pygame.Surface:
    """26×32，脚底 y=30。小妖：绿皮、角盔、木棒。"""
    s = surf(26, 32)
    if state == "down":
        rect(s, 3, 26, 15, 3, "grass")
        ellipse(s, 1, 23, 8, 8, "teal")
        rect(s, 4, 26, 1, 1, "amber")
        rect(s, 6, 26, 1, 1, "amber")
        line(s, 17, 29, 24, 29, "leather", 2)
        return s
    swing = 2 if (state == "march" and frame == 0) else (-2 if state == "march" else 0)
    bob = -1 if (state == "idle" and frame == 1) else 0
    # 腿
    rect(s, 9, 24, 4, 6, "night")
    rect(s, 14, 24, 4, 6, "night")
    if swing:
        rect(s, 9 + swing, 24, 4, 6, "night")
        rect(s, 14 - swing, 24, 4, 6, "night")
    # 身体
    rect(s, 7, 14 + bob, 12, 11, "grass")
    rect(s, 7, 22 + bob, 12, 2, "leather")
    # 手臂
    if state == "attack":
        line(s, 8, 17, 3, 13, "grass", 2)
        line(s, 17, 17, 24, 12, "grass", 2)
    else:
        line(s, 8, 17, 4, 23, "grass", 2)
        line(s, 17, 17, 22, 23, "grass", 2)
    # 头
    ellipse(s, 8, 5 + bob, 10, 10, "teal")
    ellipse(s, 9, 6 + bob, 8, 8, "ink")
    rect(s, 11, 9 + bob, 2, 2, "amber")
    rect(s, 15, 9 + bob, 2, 2, "amber")
    poly(s, [(9, 7 + bob), (6, 2 + bob), (11, 4 + bob)], "cream")
    poly(s, [(17, 7 + bob), (20, 2 + bob), (15, 4 + bob)], "cream")
    # 木棒
    if state == "attack":
        line(s, 24, 12, 25, 27, "leather", 2)
        rect(s, 23, 25, 4, 5, "brown")
    else:
        line(s, 22, 23, 25, 14, "leather", 2)
        rect(s, 23, 12, 4, 5, "brown")
    if state == "hurt":
        line(s, 7, 7, 17, 13, "vermilion", 2)
    return s


def draw_brute(state: str, frame: int) -> pygame.Surface:
    """32×38，脚底 y=36。重甲：宽体、獠牙、大锤。"""
    s = surf(32, 38)
    if state == "down":
        rect(s, 3, 31, 21, 4, "deep_red")
        ellipse(s, 2, 27, 9, 9, "red")
        ellipse(s, 20, 33, 10, 4, "steel")
        return s
    swing = 3 if (state == "march" and frame == 0) else (-3 if state == "march" else 0)
    bob = -1 if (state == "idle" and frame == 1) else 0
    # 腿
    rect(s, 10, 28, 5, 8, "ink")
    rect(s, 18, 28, 5, 8, "ink")
    if swing:
        rect(s, 10 + swing, 28, 5, 8, "ink")
        rect(s, 18 - swing, 28, 5, 8, "ink")
    # 身体
    ellipse(s, 6, 13 + bob, 20, 18, "deep_red")
    rect(s, 8, 25 + bob, 16, 4, "gold")
    rect(s, 11, 16 + bob, 10, 4, "leather")
    # 肩甲
    ellipse(s, 3, 15 + bob, 8, 7, "steel")
    ellipse(s, 21, 15 + bob, 8, 7, "steel")
    # 手臂
    if state == "attack":
        line(s, 6, 19, 1, 13, "deep_red", 3)
        line(s, 26, 19, 31, 13, "deep_red", 3)
    else:
        line(s, 6, 19, 3, 27, "deep_red", 3)
        line(s, 26, 19, 29, 27, "deep_red", 3)
    # 头 / 獠牙
    ellipse(s, 10, 3 + bob, 12, 12, "red")
    ellipse(s, 11, 4 + bob, 10, 10, "ink")
    rect(s, 13, 7 + bob, 2, 2, "amber")
    rect(s, 17, 7 + bob, 2, 2, "amber")
    rect(s, 10, 11 + bob, 3, 2, "cream")
    rect(s, 19, 11 + bob, 3, 2, "cream")
    poly(s, [(10, 5 + bob), (7, 0 + bob), (13, 3 + bob)], "gold")
    poly(s, [(22, 5 + bob), (25, 0 + bob), (19, 3 + bob)], "gold")
    # 大锤
    if state == "attack":
        line(s, 31, 13, 30, 31, "brown", 3)
        rect(s, 26, 29, 8, 6, "steel")
    else:
        line(s, 29, 27, 31, 15, "brown", 3)
        rect(s, 28, 11, 6, 7, "steel")
    if state == "hurt":
        line(s, 8, 5, 22, 14, "vermilion", 2)
    return s


def gen_enemies():
    for state, count in (("idle", 2), ("march", 2), ("attack", 2),
                         ("hurt", 1), ("down", 1)):
        for i in range(count):
            save(draw_grunt(state, i), f"enemies/grunt/{state}_{i}.png",
                 4, "enemy", 30)
            save(draw_brute(state, i), f"enemies/brute/{state}_{i}.png",
                 4, "enemy", 36)


# ------------------------------------------------------------------ Boss
def draw_boss(state: str, frame: int) -> pygame.Surface:
    """48×60，脚底 y=58。鼓王：巨鼓腹、鬼面、双槌、披风。"""
    s = surf(48, 60)
    bob = -1 if (state == "idle" and frame == 1) else 0
    if state == "down":
        rect(s, 4, 48, 36, 8, "deep_red")
        ellipse(s, 2, 42, 16, 14, "red")
        ellipse(s, 36, 52, 11, 6, "gold")
        return s
    lean = -2 if state == "hurt" else (2 if state == "attack" else 0)
    # 披风
    poly(s, [(10, 24), (2, 55), (16, 50), (20, 28)], "purple")
    poly(s, [(36, 24), (46, 55), (32, 50), (28, 28)], "violet")
    # 腿
    rect(s, 14, 46, 7, 11, "ink")
    rect(s, 28, 46, 7, 11, "ink")
    rect(s, 12, 55, 9, 3, "brown")
    rect(s, 28, 55, 9, 3, "brown")
    # 身体 / 鼓腹
    ellipse(s, 7 + lean, 20 + bob, 34, 30, "deep_red")
    ellipse(s, 13 + lean, 25 + bob, 22, 20, "gold")
    ellipse(s, 16 + lean, 28 + bob, 16, 14, "red")
    ellipse(s, 19 + lean, 31 + bob, 10, 8, "amber")
    rect(s, 10 + lean, 41 + bob, 28, 4, "gold")
    # 手臂
    if state in ("telegraph", "roar"):
        line(s, 9 + lean, 26, 2, 10, "deep_red", 4)
        line(s, 39 + lean, 26, 46, 10, "deep_red", 4)
        rect(s, 0, 7, 6, 6, "red")
        rect(s, 43, 7, 6, 6, "red")
    elif state == "attack":
        line(s, 9 + lean, 26, 5, 50, "deep_red", 4)
        line(s, 39 + lean, 26, 43, 50, "deep_red", 4)
        rect(s, 2, 47, 8, 7, "steel")
        rect(s, 38, 47, 8, 7, "steel")
    else:
        line(s, 9 + lean, 26, 4, 40, "deep_red", 4)
        line(s, 39 + lean, 26, 44, 40, "deep_red", 4)
        rect(s, 1, 38, 6, 6, "red")
        rect(s, 42, 38, 6, 6, "red")
    # 鬼面
    ellipse(s, 15 + lean, 4 + bob, 18, 18, "red")
    ellipse(s, 17 + lean, 6 + bob, 14, 14, "deep_red")
    rect(s, 20 + lean, 10 + bob, 3, 3, "amber")
    rect(s, 28 + lean, 10 + bob, 3, 3, "amber")
    rect(s, 22 + lean, 16 + bob, 8, 2, "cream")
    rect(s, 24 + lean, 18 + bob, 2, 2, "cream")
    rect(s, 28 + lean, 18 + bob, 2, 2, "cream")
    # 巨角
    poly(s, [(17 + lean, 6 + bob), (10 + lean, 0 + bob), (19 + lean, 4 + bob)], "gold")
    poly(s, [(31 + lean, 6 + bob), (38 + lean, 0 + bob), (29 + lean, 4 + bob)], "gold")
    # 鼓槌
    if state == "attack":
        line(s, 5, 50, 10, 55, "leather", 3)
        line(s, 43, 50, 38, 55, "leather", 3)
    else:
        line(s, 2, 10, 8, 24, "leather", 3)
        line(s, 46, 10, 40, 24, "leather", 3)
        ellipse(s, 0, 6, 5, 5, "amber")
        ellipse(s, 43, 6, 5, 5, "amber")
    if state == "telegraph":
        for r in (22, 27):
            pygame.draw.circle(s, (*C["amber"], 45), (24, 31), r, 1)
            pygame.draw.circle(s, (*C["vermilion"], 30), (24, 31), r + 3, 1)
    if state == "roar":
        for r in (18, 24, 30):
            pygame.draw.circle(s, (*C["amber"], 55), (24, 13), r, 1)
    if state == "hurt":
        line(s, 10, 9, 34, 28, "amber", 2)
    return s


def gen_boss():
    for state, count in (("idle", 2), ("telegraph", 1), ("attack", 1),
                         ("roar", 1), ("hurt", 1), ("down", 1)):
        for i in range(count):
            save(draw_boss(state, i), f"boss/drumking/{state}_{i}.png",
                 4, "boss", 58)


# ------------------------------------------------------------------ UI / 道具
def gen_ui():
    # 鼓面
    s = surf(48, 48)
    pygame.draw.circle(s, C["ink"], (24, 24), 22)
    pygame.draw.circle(s, C["gold"], (24, 24), 20)
    pygame.draw.circle(s, C["red"], (24, 24), 17)
    pygame.draw.circle(s, C["deep_red"], (24, 24), 13)
    pygame.draw.circle(s, C["amber"], (24, 24), 8)
    for k in range(8):
        a = math.tau * k / 8
        pygame.draw.circle(s, C["cream"],
                           (24 + int(19 * math.cos(a)), 24 + int(19 * math.sin(a))), 2)
    save(s, "ui/drum.png", 2, "ui")

    # 铜镲
    s = surf(48, 48)
    pygame.draw.circle(s, C["ink"], (24, 24), 21)
    pygame.draw.circle(s, C["gold"], (24, 24), 19)
    pygame.draw.circle(s, C["amber"], (24, 24), 16)
    pygame.draw.circle(s, C["leather"], (24, 24), 7)
    pygame.draw.circle(s, C["cream"], (24, 24), 4)
    for k in range(12):
        a = math.tau * k / 12
        line(s, 24, 24, 24 + int(17 * math.cos(a)), 24 + int(17 * math.sin(a)),
             "cream", 1)
    save(s, "ui/cymbal.png", 2, "ui")

    # 兵种徽记
    s = surf(24, 24)
    pygame.draw.circle(s, C["ink"], (12, 12), 11)
    pygame.draw.circle(s, C["gold"], (12, 12), 9)
    pygame.draw.circle(s, C["red"], (12, 12), 7)
    for k in range(6):
        a = math.tau * k / 6
        pygame.draw.circle(s, C["cream"],
                           (12 + int(6 * math.cos(a)), 12 + int(6 * math.sin(a))), 1)
    save(s, "ui/role_drummer.png", 2, "ui")

    s = surf(24, 24)
    pygame.draw.circle(s, C["ink"], (12, 12), 11)
    ellipse(s, 3, 3, 18, 18, "jade")
    ellipse(s, 6, 6, 12, 12, "teal", 1)
    ellipse(s, 10, 10, 4, 4, "gold")
    save(s, "ui/role_shield.png", 2, "ui")

    s = surf(24, 24)
    pygame.draw.circle(s, C["ink"], (12, 12), 11)
    line(s, 5, 20, 19, 5, "leather", 2)
    poly(s, [(19, 5), (15, 4), (17, 9)], "amber")
    line(s, 4, 18, 8, 22, "violet", 2)
    save(s, "ui/role_spear.png", 2, "ui")

    # Boss 读谱图标
    icons = {
        "slam": "fist",
        "charge": "arrow",
        "roar": "wave",
        "sweep": "sweep",
        "grab": "claw",
    }
    for key, kind in icons.items():
        s = surf(24, 24)
        pygame.draw.circle(s, C["ink"], (12, 12), 11)
        pygame.draw.circle(s, C["deep_red"], (12, 12), 10)
        if kind == "fist":
            rect(s, 7, 8, 10, 8, "amber")
            rect(s, 7, 6, 3, 4, "amber")
            rect(s, 10, 6, 3, 4, "amber")
            rect(s, 13, 6, 3, 4, "amber")
            rect(s, 6, 11, 12, 2, "cream")
        elif kind == "arrow":
            line(s, 5, 18, 18, 6, "amber", 3)
            poly(s, [(18, 6), (13, 5), (15, 10)], "cream")
        elif kind == "wave":
            for r in (3, 6, 9):
                pygame.draw.arc(s, C["amber"], (12 - r, 12 - r, r * 2, r * 2),
                                -1.1, 1.1, 2)
            rect(s, 7, 8, 4, 8, "cream")
        elif kind == "claw":
            for k in range(3):
                line(s, 6 + k * 4, 5, 9 + k * 4, 17, "amber", 2)
                line(s, 6 + k * 4, 17, 4 + k * 4, 20, "cream", 1)
        else:
            pygame.draw.arc(s, C["amber"], (4, 4, 16, 16), -0.4, 2.2, 3)
            line(s, 5, 12, 19, 12, "cream", 1)
        save(s, f"ui/intent_{key}.png", 2, "ui")

    # 阵法图标（4 阵 + 长蛇）
    forms = {
        "changshe": "column",
        "fengshi": "arrow",
        "guijia": "shell",
        "shuanglong": "wavedouble",
        "menghu": "clawrow",
    }
    for key, kind in forms.items():
        s = surf(24, 24)
        pygame.draw.circle(s, C["ink"], (12, 12), 11)
        pygame.draw.circle(s, C["gold"], (12, 12), 9)
        pygame.draw.circle(s, C["night"], (12, 12), 8)
        if kind == "column":
            for k in range(3):
                pygame.draw.circle(s, C["jade"], (12, 6 + k * 6), 2)
        elif kind == "arrow":
            poly(s, [(4, 6), (20, 12), (4, 18), (8, 12)], "amber")
        elif kind == "shell":
            pygame.draw.arc(s, C["jade"], (4, 5, 16, 14), 3.3, 6.1, 2)
            pygame.draw.arc(s, C["teal"], (6, 8, 12, 9), 3.3, 6.1, 1)
            line(s, 8, 16, 16, 16, "gold", 1)
        elif kind == "wavedouble":
            for dy in (-2, 2):
                for x in range(5, 21, 4):
                    line(s, x, 12 + dy - 2, x + 2, 12 + dy + 2, "vermilion", 2)
        else:
            for y in (7, 12, 17):
                line(s, 4, y, 20, y, "vermilion", 2)
                line(s, 4, y, 2, y - 2, "cream", 1)
        save(s, f"ui/form_{key}.png", 2, "ui")

    # 阶段徽记：1/2/3 颗鼓钉，颜色递进
    phase_cols = ("jade", "amber", "vermilion")
    for i, col in enumerate(phase_cols, start=1):
        s = surf(24, 24)
        pygame.draw.circle(s, C["ink"], (12, 12), 11)
        pygame.draw.circle(s, C[col], (12, 12), 9)
        pygame.draw.circle(s, C["night"], (12, 12), 7)
        for k in range(i):
            x = 12 - (i - 1) * 3 + k * 6
            pygame.draw.circle(s, C["cream"], (x, 12), 2)
        save(s, f"ui/phase_{i}.png", 2, "ui")

    # 克制印底纹（克字由渲染层叠加）
    s = surf(24, 24)
    pygame.draw.circle(s, C["ink"], (12, 12), 11)
    pygame.draw.circle(s, C["red"], (12, 12), 10, 2)
    pygame.draw.circle(s, C["amber"], (12, 12), 7, 1)
    for k in range(4):
        a = math.tau * k / 4 + math.pi / 4
        line(s, 12 + int(6 * math.cos(a)), 12 + int(6 * math.sin(a)),
             12 + int(9 * math.cos(a)), 12 + int(9 * math.sin(a)), "gold", 1)
    save(s, "ui/counter_mark.png", 2, "ui")


def gen_guide():
    """第十九轮：新手引导右栏重绘（全部整数像素、无抗锯齿）。"""
    # 大鼓鼓面 236×146：4 拍刻度刻在鼓面（位置与 scenes.GUIDE_TICKS 对齐）
    s = surf(236, 146)
    ellipse(s, 0, 0, 236, 142, "ink")
    ellipse(s, 3, 2, 230, 136, "gold_dark")
    ellipse(s, 6, 5, 224, 130, "gold")
    ellipse(s, 10, 9, 216, 122, "red")
    ellipse(s, 15, 14, 206, 112, "deep_red")
    ellipse(s, 20, 19, 196, 102, "red_dark")
    # 鼓钉：沿边缘 10 颗（整数坐标）
    for px, py in ((24, 22), (70, 8), (166, 8), (212, 22), (224, 62),
                   (12, 62), (34, 122), (202, 122), (58, 132), (178, 132)):
        ellipse(s, px, py, 8, 8, "ink")
        ellipse(s, px + 2, py + 2, 4, 4, "gold")
    # 鼓面高光（纯色硬边，不做渐变）
    ellipse(s, 44, 30, 58, 20, "red_light")
    ellipse(s, 54, 34, 38, 10, "amber")
    # 4 拍刻度：局部 x=40/94/148/202，y=96（与 scenes.GUIDE_TICKS 对齐）
    for i in range(4):
        tx = 40 + i * 54
        rect(s, tx - 9, 87, 18, 18, "ink")
        rect(s, tx - 7, 89, 14, 14, "gold_dark")
        rect(s, tx - 4, 92, 8, 8, "cream")
    save(s, "ui/guide_drum.png", 2, "ui")

    # 锣键位牌 58×104（K）
    s = surf(58, 104)
    rect(s, 0, 0, 58, 104, "ink")
    rect(s, 2, 2, 54, 100, "gold_dark")
    rect(s, 4, 4, 50, 96, "night")
    ellipse(s, 7, 8, 44, 44, "gold")
    ellipse(s, 10, 11, 38, 38, "steel_dark")
    ellipse(s, 14, 15, 30, 30, "steel")
    ellipse(s, 22, 23, 14, 14, "gold_dark")
    ellipse(s, 25, 26, 8, 8, "cream")
    line(s, 12, 60, 46, 60, "gold", 1)
    rect(s, 6, 62, 46, 38, "shadow")
    save(s, "ui/guide_gong.png", 2, "ui")

    # 钹键位牌 58×104（L）
    s = surf(58, 104)
    rect(s, 0, 0, 58, 104, "ink")
    rect(s, 2, 2, 54, 100, "gold_dark")
    rect(s, 4, 4, 50, 96, "night")
    ellipse(s, 5, 6, 48, 48, "gold_dark")
    ellipse(s, 9, 10, 40, 40, "steel")
    ellipse(s, 14, 15, 30, 30, "steel_dark")
    ellipse(s, 21, 22, 16, 16, "gold")
    ellipse(s, 25, 26, 8, 8, "cream")
    line(s, 12, 60, 46, 60, "gold", 1)
    rect(s, 6, 62, 46, 38, "shadow")
    save(s, "ui/guide_cymbal.png", 2, "ui")

    # 绸带进度 532×22：节点与 RIBBON 位置对齐（30 + i*94）
    s = surf(532, 22)
    wave = (0, 0, 1, 1, 2, 2, 1, 0)
    for x in range(0, 532, 4):
        oy = wave[(x // 4) % len(wave)]
        rect(s, x, 7 + oy, 4, 8, "red_dark")
        rect(s, x, 9 + oy, 4, 4, "vermilion")
        rect(s, x, 7 + oy, 4, 1, "gold_dark")
        rect(s, x, 14 + oy, 4, 1, "gold")
    # 节点由渲染层画菱形（JADE/GOLD），底图只保留绸带本体，避免双层节点
    save(s, "ui/guide_ribbon.png", 2, "ui")

    # 印章 64×64（字由渲染层叠「过」）
    s = surf(64, 64)
    rect(s, 2, 2, 60, 60, "ink")
    rect(s, 4, 4, 56, 56, "red_dark")
    rect(s, 6, 6, 52, 52, "red")
    rect(s, 9, 9, 46, 46, "deep_red")
    rect(s, 12, 12, 40, 40, "red")
    rect(s, 10, 10, 44, 1, "gold")
    rect(s, 10, 53, 44, 1, "gold")
    rect(s, 10, 10, 1, 44, "gold")
    rect(s, 53, 10, 1, 44, "gold")
    # 做旧缺口（透明像素，保证盖在面板上不糊成整块）
    pygame.draw.rect(s, (0, 0, 0, 0), (4, 4, 6, 4))
    pygame.draw.rect(s, (0, 0, 0, 0), (54, 8, 6, 5))
    pygame.draw.rect(s, (0, 0, 0, 0), (6, 56, 5, 4))
    pygame.draw.rect(s, (0, 0, 0, 0), (52, 52, 8, 8))
    save(s, "ui/guide_stamp.png", 2, "ui")

    # Boss 公示示意窄条 532×38：左图标 + 4 个化解键槽（槽位 x=300+i*56）
    s = surf(532, 38)
    rect(s, 0, 0, 532, 38, "ink")
    rect(s, 2, 2, 528, 34, "gold_dark")
    rect(s, 3, 3, 526, 32, "night")
    poly(s, [(10, 6), (38, 6), (44, 19), (38, 32), (10, 32), (16, 19)],
         "red_dark")
    poly(s, [(16, 10), (32, 10), (36, 19), (32, 28), (16, 28), (20, 19)],
         "vermilion")
    poly(s, [(22, 14), (28, 14), (30, 19), (28, 24), (22, 24), (24, 19)],
         "amber")
    for i in range(4):
        bx = 300 + i * 56
        rect(s, bx, 7, 40, 24, "shadow")
        rect(s, bx, 7, 40, 1, "gold")
        rect(s, bx, 30, 40, 1, "gold")
        rect(s, bx, 7, 1, 24, "gold")
        rect(s, bx + 39, 7, 1, 24, "gold")
        rect(s, bx + 3, 10, 34, 18, "night")
    save(s, "ui/guide_boss.png", 2, "ui")


def gen_props():
    # 灯笼
    s = surf(32, 48)
    rect(s, 12, 0, 8, 4, "ink")
    rect(s, 8, 4, 16, 3, "gold")
    ellipse(s, 2, 7, 28, 30, "red")
    ellipse(s, 5, 10, 22, 24, "vermilion")
    for k in range(3):
        line(s, 8 + k * 8, 8, 6 + k * 10, 35, "gold", 1)
    rect(s, 8, 34, 16, 3, "gold")
    line(s, 16, 37, 16, 45, "amber", 2)
    for k in range(3):
        line(s, 16, 44, 10 + k * 6, 48, "gold", 1)
    save(s, "props/lantern.png", 2, "prop")

    # 树（56×88 基础画布，脚底基线贴图片底边；右上受光、左侧暗部）
    s = surf(56, 88)
    # 树干：左侧暗、右侧受光
    rect(s, 24, 46, 9, 42, "ink")
    rect(s, 26, 46, 7, 42, "brown")
    rect(s, 32, 46, 2, 42, "leather")
    rect(s, 21, 84, 16, 4, "shadow")
    rect(s, 24, 84, 11, 4, "brown")
    # 下层树冠
    rect(s, 4, 42, 48, 12, "teal_dark")
    rect(s, 6, 34, 44, 12, "grass")
    rect(s, 38, 34, 12, 12, "jade")          # 右上受光
    rect(s, 46, 42, 6, 12, "teal")
    rect(s, 6, 34, 6, 20, "teal_dark")        # 左侧暗部
    # 上层树冠
    rect(s, 12, 24, 32, 12, "teal_dark")
    rect(s, 14, 14, 28, 12, "grass")
    rect(s, 34, 14, 8, 12, "jade")
    rect(s, 14, 14, 5, 12, "teal_dark")
    rect(s, 20, 7, 16, 8, "grass")
    rect(s, 30, 7, 6, 8, "jade")
    # 硬边轮廓缺口，保持像素块状
    rect(s, 2, 48, 3, 4, "teal_dark")
    rect(s, 51, 36, 3, 6, "jade")
    rect(s, 10, 12, 3, 3, "teal_dark")
    rect(s, 39, 5, 3, 3, "jade")
    save(s, "props/tree_0.png", 2, "prop")

    # 旗（30×78；旗杆居左、三角旗向右，赤底金边）
    s = surf(30, 78)
    rect(s, 3, 4, 4, 74, "ink")
    rect(s, 4, 4, 3, 74, "brown")
    rect(s, 6, 4, 1, 74, "leather")
    rect(s, 2, 0, 6, 4, "gold")
    rect(s, 3, 0, 4, 2, "amber")
    poly(s, [(7, 8), (29, 14), (7, 34)], "red")
    poly(s, [(8, 10), (25, 15), (8, 31)], "vermilion")
    line(s, 7, 8, 29, 14, "gold", 2)
    line(s, 29, 14, 7, 34, "gold", 2)
    line(s, 7, 8, 7, 34, "gold", 2)
    save(s, "props/flag_0.png", 2, "prop")

    # 林地石阶门（青灰石）
    s = surf(120, 96)
    rect(s, 24, 86, 72, 10, "steel_dark")
    rect(s, 30, 78, 60, 8, "steel")
    rect(s, 36, 70, 48, 8, "steel_dark")
    rect(s, 32, 28, 12, 44, "steel_dark")
    rect(s, 34, 28, 10, 44, "steel")
    rect(s, 42, 30, 2, 40, "mist")
    rect(s, 76, 28, 12, 44, "steel_dark")
    rect(s, 78, 28, 10, 44, "steel")
    rect(s, 86, 30, 2, 40, "mist")
    rect(s, 20, 16, 80, 14, "steel_dark")
    rect(s, 22, 14, 76, 6, "steel")
    rect(s, 24, 10, 72, 4, "mist")
    rect(s, 44, 30, 32, 40, "night")
    rect(s, 48, 34, 24, 36, "ink")
    save(s, "props/gate_forest.png", 2, "prop")

    # 街市牌坊（赤柱金匾）
    s = surf(120, 96)
    rect(s, 30, 24, 12, 66, "red_dark")
    rect(s, 32, 24, 10, 66, "deep_red")
    rect(s, 40, 26, 2, 62, "red_light")
    rect(s, 78, 24, 12, 66, "red_dark")
    rect(s, 80, 24, 10, 66, "deep_red")
    rect(s, 88, 26, 2, 62, "red_light")
    rect(s, 18, 18, 84, 12, "deep_red")
    rect(s, 18, 16, 84, 3, "gold")
    rect(s, 14, 10, 92, 6, "ink")
    rect(s, 10, 8, 100, 3, "tile")
    rect(s, 42, 32, 36, 18, "gold_dark")
    rect(s, 43, 31, 34, 16, "gold")
    rect(s, 46, 34, 28, 10, "amber")
    rect(s, 54, 36, 4, 6, "deep_red")
    rect(s, 62, 36, 4, 6, "deep_red")
    rect(s, 70, 36, 4, 6, "deep_red")
    save(s, "props/gate_market.png", 2, "prop")

    # 广场白玉石阶门（浅灰）
    s = surf(120, 96)
    rect(s, 24, 86, 72, 10, "steel_dark")
    rect(s, 30, 79, 60, 7, "steel")
    rect(s, 36, 72, 48, 7, "mist")
    rect(s, 32, 26, 12, 46, "steel")
    rect(s, 34, 26, 10, 46, "mist")
    rect(s, 40, 28, 2, 42, "white")
    rect(s, 76, 26, 12, 46, "steel")
    rect(s, 78, 26, 10, 46, "mist")
    rect(s, 84, 28, 2, 42, "white")
    rect(s, 20, 14, 80, 14, "steel")
    rect(s, 22, 12, 76, 6, "mist")
    rect(s, 26, 8, 68, 4, "white")
    rect(s, 44, 28, 32, 44, "night")
    rect(s, 48, 32, 24, 40, "ink")
    save(s, "props/gate_plaza.png", 2, "prop")

    # 石里程桩（16×36，刻一横槽）
    s = surf(16, 36)
    rect(s, 5, 4, 8, 30, "steel_dark")
    rect(s, 6, 3, 6, 31, "steel")
    rect(s, 7, 4, 4, 29, "mist")
    rect(s, 3, 2, 10, 4, "steel")
    rect(s, 2, 30, 12, 6, "steel_dark")
    rect(s, 5, 14, 6, 3, "steel_dark")
    rect(s, 5, 17, 6, 1, "white")
    save(s, "props/mile_0.png", 2, "prop")


# ------------------------------------------------------------------ 环境
def gen_env():
    # 地面砖（128×64 基础图，2x 导出；横向无缝）
    s = surf(128, 64)
    rect(s, 0, 0, 128, 64, "brown")
    rect(s, 0, 0, 128, 6, "leather")
    for row in range(2):
        y = 8 + row * 28
        rect(s, 0, y, 128, 2, "ink")
        off = 0 if row == 0 else 32
        for x in range(-64, 160, 64):
            rect(s, x + off, y, 2, 28, "ink")
        for x in range(-48, 160, 64):
            rect(s, x + off, y + 4, 44, 18, "leather")
            rect(s, x + off, y + 4, 44, 2, "gold")
    save(s, "environment/ground.png", 2, "environment")

    # 远景：山脊 + 潮汕厝角头剪影（透明底）
    s = surf(640, 200)
    poly(s, [(0, 200), (0, 150), (60, 115), (130, 140), (210, 90),
             (300, 135), (390, 105), (470, 145), (560, 118), (640, 150),
             (640, 200)], "night")
    poly(s, [(0, 200), (0, 175), (90, 150), (180, 168), (260, 142),
             (360, 170), (450, 150), (540, 172), (640, 158), (640, 200)],
         "purple")
    # 屋顶剪影
    roofs = [(40, 172), (150, 165), (260, 175), (380, 160), (500, 176)]
    for x, y in roofs:
        rect(s, x, y, 70, 28, "deep_red")
        poly(s, [(x - 10, y), (x + 20, y - 14), (x + 50, y - 14),
                 (x + 80, y), (x + 70, y + 5), (x + 10, y + 5)], "ink")
        poly(s, [(x - 8, y), (x + 8, y + 12), (x + 2, y + 14)], "ink")
        poly(s, [(x + 72, y), (x + 56, y + 12), (x + 62, y + 14)], "ink")
        for k in range(4):
            rect(s, x + 8 + k * 16, y + 8, 8, 7, "amber")
    # 远处灯火
    for x, y in ((70, 185), (205, 180), (318, 190), (440, 182), (552, 190)):
        rect(s, x, y, 3, 3, "amber")
    save(s, "environment/far.png", 2, "environment")


# ------------------------------------------------------------------ 三层景深
def gen_parallax():
    """960 宽无缝平铺：远（海/山）、中（骑楼街景）、近（草丛石栏剪影）。

    远景 2 套、中景 3 套变体，共用同一平铺宽度与完全一致的左右边列，
    因此任意两套在平铺边界处换图也不会断层（接缝阈值沿用 16）。
    所有元素仍按 -W / 0 / +W 画三遍，跨边界形状左右连续。
    """
    TILE = 960

    # 远：海平线 + 两层低饱和山脊 + 雾带（透明底，天空由程序底图承担）
    def make_far(variant: int) -> pygame.Surface:
        far = surf(TILE, 260)
        # 海平线/雾带在每套里完全一致 → 变体边界处像素相同
        rect(far, 0, 196, TILE, 64, "sea")
        rect(far, 0, 190, TILE, 5, "mist")
        if variant == 0:
            ridge = [(0, 196), (70, 150), (150, 176), (235, 132), (330, 170),
                     (420, 144), (520, 178), (610, 150), (700, 172),
                     (800, 140), (890, 168), (960, 196)]
            near_ridge = [(0, 196), (120, 172), (210, 186), (320, 164),
                          (410, 182), (520, 166), (640, 184), (760, 168),
                          (880, 184), (960, 174), (960, 196)]
            cloud_y = (118, 126)
        else:
            # 变体 B：山脊更高更疏、第二层更低，额外一条横向云带
            ridge = [(0, 196), (90, 138), (170, 162), (280, 118), (380, 158),
                     (470, 126), (590, 160), (690, 132), (820, 154),
                     (900, 176), (960, 196)]
            near_ridge = [(0, 196), (150, 168), (260, 180), (380, 158),
                          (520, 174), (660, 160), (790, 176), (960, 168),
                          (960, 196)]
            cloud_y = (104, 112)
        poly(far, ridge, "sky_low")
        poly(far, near_ridge, "purple")
        for i in range(7):
            zx = 120 + i * 128
            rect(far, zx, 206 + (i % 2) * 5, 40, 2, "mist")
        # 云层：低对比横条 + 稀疏云头，边缘留空不触碰左右边列
        for i in range(5):
            cx = 90 + i * 178 + variant * 30
            cy = cloud_y[0] + (i % 2) * cloud_y[1]
            rect(far, cx, cy, 96 + (i % 3) * 24, 4, "mist")
            ellipse(far, cx + 18, cy - 5, 26, 9, "sky_low")
            ellipse(far, cx + 62, cy - 7, 34, 11, "sky_low")
        return far

    for i in range(2):
        name = "far_sky" + ("" if i == 0 else f"_{i}") + ".png"
        save(make_far(i), "environment/" + name, 1, "parallax")

    # 中：骑楼街景/屋脊剪影（透明底），底部由地面层遮住
    def make_mid(variant: int) -> pygame.Surface:
        mid = surf(TILE, 220)
        for i in range(6):
            bx = i * 160
            bh = 118 + ((i + variant * 2) % 3) * 12
            top = 220 - bh
            rect(mid, bx + 6, top, 148, bh, "tile")
            rect(mid, bx + 6, top, 148, 6, "wall")
            # 潮汕厝角头：两端起翘的屋脊
            poly(mid, [(bx, top), (bx + 22, top - 12), (bx + 132, top - 12),
                       (bx + 154, top), (bx + 148, top + 6),
                       (bx + 10, top + 6)], "wall")
            poly(mid, [(bx + 2, top), (bx + 22, top + 10),
                       (bx + 10, top + 12)], "ink")
            poly(mid, [(bx + 152, top), (bx + 132, top + 10),
                       (bx + 144, top + 12)], "ink")
            # 窗格模板：3 / 2 / 4 列，窗台高度不同
            cols = (3, 2, 4)[variant]
            for k in range(cols):
                wx = bx + 20 + k * (104 // cols)
                wy = top + 22 + (k % 2) * 2
                rect(mid, wx, wy, 24, 18, "window")
                rect(mid, wx + 2, wy + 2, 20, 4, "amber")
            # 门洞位置随模板变化
            door_x = bx + (56, 40, 72)[variant]
            rect(mid, door_x, 220 - 52, 32, 52, "night")
            rect(mid, door_x, 220 - 52, 32, 3, "window")
            # 檐下彩灯点（静态装饰；动态灯笼仍在 render 层，逻辑不变）
            lights = (2, 4, 3)[variant]
            for k in range(lights):
                lx = bx + 24 + k * (104 // max(1, lights))
                rect(mid, lx, top + 8, 4, 5, "amber")
                rect(mid, lx, top + 13, 2, 2, "deep_red")
        # 街口横匾：位置/底色随模板变化，远离左右边列
        sign_x = (300, 124, 468)[variant]
        sign_col = ("deep_red", "blue", "deep_red")[variant]
        rect(mid, sign_x, 118, 70, 20, sign_col)
        rect(mid, sign_x + 4, 122, 62, 4,
             "gold" if variant != 1 else "amber")
        return mid

    for i in range(3):
        name = "mid_street" + ("" if i == 0 else f"_{i}") + ".png"
        save(make_mid(i), "environment/" + name, 1, "parallax")

    # 近：草丛 + 石栏 + 掠过的人物剪影（画在角色之上，镂空处透景）
    near = surf(TILE, 150)
    def near_copy(ox: float) -> None:
        for i in range(24):
            gx = ox + i * 40
            rect(near, gx, 138, 3, 12, "fg_green")
            rect(near, gx + 5, 134, 2, 16, "grass")
            rect(near, gx + 9, 140, 3, 10, "fg_green")
        # 石栏两段（中间留空，保证不是全程挡住角色）
        for sx0, sw in ((80, 190), (640, 250)):
            rect(near, ox + sx0, 118, sw, 10, "fg")
            rect(near, ox + sx0, 118, sw, 2, "mist")
            for k in range(sw // 46 + 1):
                rect(near, ox + sx0 + k * 46, 118, 6, 32, "fg")
        # 掠过的人物剪影：半透明，压住角色但透出轮廓
        def passer(px: float, h: int) -> None:
            lay = surf(70, 110)
            rect(lay, 23, 18, 24, 86, "fg")
            ellipse(lay, 15, 6, 40, 12, "fg")
            ellipse(lay, 19, 0, 32, 10, "fg")
            rect(lay, 9, 44, 8, 62, "fg")
            lay.set_alpha(165)
            near.blit(lay, (ox + px - 35, 140 - h - 22))
        passer(520, 74)
        passer(788, 52)
    for ox in (-TILE, 0, TILE):
        near_copy(ox)
    save(near, "environment/near_fg.png", 1, "parallax")


# ------------------------------------------------------------------ 水浒好汉
# 定妆照 256×256（底部 24px 标注带），动作帧 48×64 基础画布 3× 导出 → 144×192。
# 全部硬边像素块 + 三阶明暗，统一左上光源；脚底基线动作帧 y=60（导出 180）。
HERO_W, HERO_H, HERO_BASE = 48, 64, 60
PORTRAIT_W = PORTRAIT_H = 256
BAND_H = 24
CJK_SIZE = 11

HERO_STYLE = {
    "wusong": dict(
        name="武松", nick="行者", face="赤面", kind="drummer",
        kind_label="鼓手", role="鼓手 · 赤手重击", skill="双抛槌", weapon="双槌",
        tagline="赤面金睛，领鼓开阵",
        latin="WUSONG / XINGZHE / RED FACE / DRUMMER",
        face_col="vermilion", face_light="red_light", face_dark="deep_red",
        vest="red", vest_light="red_light", vest_dark="red_dark",
        trim="gold", trim_light="gold_light", trim_dark="gold_dark",
        armor="gold", armor_light="gold_light", armor_dark="gold_dark",
        pants="ink", pants_light="night", pants_dark="shadow",
        boot="leather", boot_light="amber", boot_dark="brown",
        limb="skin", limb_light="skin_light", limb_dark="skin_shadow",
    ),
    "linchong": dict(
        name="林冲", nick="豹子头", face="白面豹纹", kind="spear",
        kind_label="矛兵", role="矛兵 · 枪棒突刺", skill="回马枪", weapon="长枪",
        tagline="枪出如龙，回马封喉",
        latin="LINCHONG / BAOZITOU / WHITE FACE / SPEAR",
        face_col="cream", face_light="white", face_dark="skin",
        vest="purple", vest_light="violet_light", vest_dark="violet_dark",
        trim="gold", trim_light="gold_light", trim_dark="gold_dark",
        armor="steel", armor_light="white", armor_dark="steel_dark",
        pants="night", pants_light="purple", pants_dark="shadow",
        boot="leather", boot_light="amber", boot_dark="brown",
        limb="skin", limb_light="skin_light", limb_dark="skin_shadow",
    ),
    "likui": dict(
        name="李逵", nick="黑旋风", face="黑面环眼", kind="shield",
        kind_label="盾兵", role="盾兵 · 双斧横扫", skill="旋风劈", weapon="双斧",
        tagline="双斧开路，黑塔承伤",
        latin="LIKUI / HEIXUANFENG / BLACK RING EYE",
        face_col="ink", face_light="steel", face_dark="shadow",
        vest="teal", vest_light="teal_light", vest_dark="teal_dark",
        trim="steel", trim_light="white", trim_dark="steel_dark",
        armor="steel", armor_light="white", armor_dark="steel_dark",
        pants="brown", pants_light="leather", pants_dark="shadow",
        boot="leather", boot_light="amber", boot_dark="brown",
        limb="skin_dark", limb_light="skin", limb_dark="skin_shadow",
    ),
}

# 每人 6 态 22 帧；攻击/技能峰值帧号 = 2（第 3 帧）。
HERO_FRAMES_SPEC = {
    "idle": {"count": 4, "durations_ms": [520, 520, 520, 520],
             "peak": -1, "loop": "loop", "cancelable": True},
    "march": {"count": 6, "durations_ms": [140, 140, 150, 150, 140, 140],
              "peak": -1, "loop": "loop", "cancelable": True},
    "attack": {"count": 4, "durations_ms": [90, 110, 130, 150],
               "peak": 2, "loop": "once", "cancelable": False},
    "hurt": {"count": 2, "durations_ms": [120, 220],
             "peak": -1, "loop": "once", "cancelable": False},
    "down": {"count": 2, "durations_ms": [200, 800],
             "peak": -1, "loop": "hold", "cancelable": False},
    "skill": {"count": 4, "durations_ms": [100, 130, 140, 180],
              "peak": 2, "loop": "once", "cancelable": False},
}

# 自绘 5×7 位图字（字母/数字/常用符号），不依赖系统字体
_G5 = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "A": (14, 17, 17, 31, 17, 17, 17), "B": (30, 17, 17, 30, 17, 17, 30),
    "C": (14, 17, 16, 16, 16, 17, 14), "D": (30, 17, 17, 17, 17, 17, 30),
    "E": (31, 16, 16, 30, 16, 16, 31), "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15), "H": (17, 17, 17, 31, 17, 17, 17),
    "I": (14, 4, 4, 4, 4, 4, 14), "J": (7, 4, 4, 4, 4, 20, 8),
    "K": (17, 18, 20, 24, 20, 18, 17), "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17), "N": (17, 25, 21, 19, 17, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14), "P": (30, 17, 17, 30, 16, 16, 16),
    "Q": (14, 17, 17, 17, 21, 18, 13), "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30), "T": (31, 4, 4, 4, 4, 4, 4),
    "U": (17, 17, 17, 17, 17, 17, 14), "V": (17, 17, 17, 17, 17, 10, 4),
    "W": (17, 17, 17, 21, 21, 27, 17), "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 10, 4, 4, 4, 4), "Z": (31, 1, 2, 4, 8, 16, 31),
    "0": (14, 17, 19, 21, 25, 17, 14), "1": (4, 12, 4, 4, 4, 4, 14),
    "2": (14, 17, 1, 2, 4, 8, 31), "3": (30, 1, 1, 14, 1, 1, 30),
    "4": (2, 6, 10, 18, 31, 2, 2), "5": (31, 16, 16, 30, 1, 1, 30),
    "6": (14, 16, 16, 30, 17, 17, 14), "7": (31, 1, 2, 4, 8, 8, 8),
    "8": (14, 17, 17, 14, 17, 17, 14), "9": (14, 17, 17, 15, 1, 1, 14),
    ".": (0, 0, 0, 0, 0, 12, 12), "-": (0, 0, 0, 31, 0, 0, 0),
    "/": (1, 1, 2, 4, 8, 16, 16), ":": (0, 12, 12, 0, 12, 12, 0),
}


def text5_width(text: str) -> int:
    return max(1, len(text) * 6 - 1)


def draw_text5(s, text: str, x: int, y: int, color: str,
               spacing: int = 1) -> int:
    """逐像素写入 5×7 位图字，返回绘制宽度。"""
    for ch in text.upper():
        glyph = _G5.get(ch, _G5[" "])
        for row, bits in enumerate(glyph):
            for col in range(5):
                if bits & (1 << (4 - col)):
                    rect(s, x + col, y + row, 1, 1, color)
        x += 5 + spacing
    return x


def draw_text5_center(s, text: str, cx: int, y: int, color: str) -> None:
    draw_text5(s, text, int(cx - text5_width(text) / 2), y, color)


def draw_label_cjk(s, text: str, cx: int, y: int, color: str,
                   size: int = CJK_SIZE) -> None:
    """中文标注带：非抗锯齿渲染成 1bit 位图，再按调色板硬边落点。"""
    img = _font(size).render(text, False, C[color])
    s.blit(img, (int(cx - img.get_width() / 2), int(y)))


def _ppoly(s, pts, mid: str, light: str | None = None,
           dark: str | None = None) -> None:
    """带 2px 暗轮廓的多边形；沿左上边加高光、右下边压暗。"""
    pygame.draw.polygon(s, C[mid], pts)
    pygame.draw.polygon(s, C["shadow"], pts, 2)
    if light or dark:
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if x1 == x2 and y1 == y2:
                continue
            if (x2 - x1) - (y2 - y1) > 0:
                if light:
                    line(s, x1, y1, x2, y2, light, 2)
            elif dark:
                line(s, x1, y1, x2, y2, dark, 2)


def _plimb(s, pts, mid: str, light: str, dark: str, w: int = 8) -> None:
    pygame.draw.lines(s, C["shadow"], False, [(x, y) for x, y in pts], w + 3)
    pygame.draw.lines(s, C[mid], False, [(x, y) for x, y in pts], w)
    pygame.draw.lines(s, C[light], False, [(x - 2, y - 2) for x, y in pts], 2)
    pygame.draw.lines(s, C[dark], False, [(x + 2, y + 2) for x, y in pts], 2)


def _pell(s, x, y, w, h, mid: str, light: str, dark: str) -> None:
    ellipse(s, x - 1, y - 1, w + 2, h + 2, "shadow")
    ellipse(s, x, y, w, h, mid)
    ellipse(s, x + 2, y + 2, max(2, w // 3), max(2, h // 2), light)
    ellipse(s, x + w // 2, y + h // 2, max(2, w // 3), max(2, h // 2), dark)


def _box(s, x, y, w, h, mid: str, light: str, dark: str,
         outline: bool = True) -> None:
    if outline:
        rect(s, x - 1, y - 1, w + 2, h + 2, "shadow")
    rect(s, x, y, w, h, mid)
    rect(s, x, y, w, 2, light)
    rect(s, x, y, 2, h, light)
    rect(s, x + w - 2, y, 2, h, dark)
    rect(s, x, y + h - 2, w, 2, dark)



def _font(size: int):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return pygame.font.Font(p, size)
            except Exception:
                break
    return pygame.font.SysFont("Microsoft YaHei", size)


def _hero_face_small(s, hero: str, cx: int, cy: int,
                     mood: str = "idle", bob: int = 0):
    """48×64 动作帧的头部（约 16×17px）+ 盔缨/髯口/谱式。"""
    st = HERO_STYLE[hero]
    cy += bob
    _pell(s, cx - 8, cy - 8, 16, 17,
          st["face_col"], st["face_light"], st["face_dark"])
    # 左耳（3/4 正面，右耳被遮）
    ellipse(s, cx - 10, cy - 2, 4, 6, st["face_col"])
    ellipse(s, cx - 10, cy - 1, 2, 3, st["face_dark"])
    eye_y = cy - 2 + 1

    if hero == "wusong":
        # 黑眼窝 + 金睛 + 朱砂额纹 + 金箍
        rect(s, cx - 6, eye_y - 1, 5, 4, "ink")
        rect(s, cx + 1, eye_y - 1, 5, 4, "ink")
        rect(s, cx - 4, eye_y, 2, 3, "amber")
        rect(s, cx + 3, eye_y, 2, 3, "amber")
        line(s, cx - 7, cy - 5, cx + 1, cy - 3, "ink", 2)
        line(s, cx + 1, cy - 3, cx + 8, cy - 5, "ink", 2)
        # 金箍（额带）+ 火纹
        rect(s, cx - 8, cy - 9, 16, 3, "gold")
        rect(s, cx - 8, cy - 9, 16, 1, "gold_light")
        rect(s, cx - 8, cy - 7, 16, 1, "gold_dark")
        poly(s, [(cx, cy - 14), (cx - 3, cy - 10), (cx, cy - 7),
                 (cx + 3, cy - 10)], "amber")
        line(s, cx - 2, cy + 8, cx + 3, cy + 8, "red_dark", 1)
        # 黑髯三绺
        poly(s, [(cx - 6, cy + 8), (cx - 2, cy + 15), (cx, cy + 10),
                 (cx + 3, cy + 15), (cx + 6, cy + 8)], "ink")
        # 赤缨（贴左上，短促后掠）
        line(s, cx - 2, cy - 14, cx - 12, cy - 18, "red", 2)
        line(s, cx, cy - 14, cx - 8, cy - 20, "vermilion", 1)
        rect(s, cx - 13, cy - 19, 2, 2, "gold_light")
    elif hero == "linchong":
        # 白面豹纹：白底眼 + 黑豹斑 + 金盔红缨
        for bx, by, bw, bh in ((cx - 7, cy + 1, 3, 3),
                               (cx + 4, cy + 3, 2, 3),
                               (cx - 3, cy - 8, 2, 2),
                               (cx + 6, cy - 4, 2, 2)):
            rect(s, bx, by, bw, bh, "ink")
        rect(s, cx - 6, eye_y - 1, 5, 4, "white")
        rect(s, cx + 1, eye_y - 1, 5, 4, "white")
        rect(s, cx - 4, eye_y, 2, 3, "ink")
        rect(s, cx + 3, eye_y, 2, 3, "ink")
        line(s, cx - 7, cy - 5, cx + 1, cy - 3, "ink", 2)
        line(s, cx + 1, cy - 3, cx + 8, cy - 5, "ink", 2)
        # 金盔 + 红缨
        poly(s, [(cx - 9, cy - 8), (cx, cy - 14), (cx + 9, cy - 8)], "gold")
        poly(s, [(cx - 9, cy - 8), (cx, cy - 14), (cx + 9, cy - 8)],
             "gold")
        line(s, cx - 9, cy - 8, cx + 9, cy - 8, "gold_dark", 2)
        line(s, cx - 7, cy - 9, cx, cy - 13, "gold_light", 1)
        line(s, cx, cy - 14, cx - 9, cy - 19, "red", 2)
        rect(s, cx + 1, cy - 13, 2, 3, "red")
        # 颔下短髯
        rect(s, cx - 3, cy + 9, 6, 2, "ink")
        line(s, cx - 5, cy + 7, cx + 5, cy + 7, "ink", 1)
    else:
        # 黑面环眼：琥珀环眼 + 红巾 + 黑髯
        ellipse(s, cx - 7, eye_y - 2, 6, 6, "amber")
        ellipse(s, cx + 1, eye_y - 2, 6, 6, "amber")
        rect(s, cx - 5, eye_y, 2, 2, "white")
        rect(s, cx + 3, eye_y, 2, 2, "white")
        line(s, cx - 8, cy - 5, cx + 1, cy - 3, "ink", 2)
        line(s, cx + 1, cy - 3, cx + 9, cy - 5, "ink", 2)
        # 红巾 + 后飘巾尾
        rect(s, cx - 9, cy - 9, 18, 4, "red")
        rect(s, cx - 9, cy - 9, 18, 1, "red_light")
        line(s, cx - 9, cy - 7, cx - 17, cy - 10, "red", 2)
        rect(s, cx - 18, cy - 11, 3, 3, "gold")
        # 大髯（覆盖下颌）
        poly(s, [(cx - 8, cy + 4), (cx - 6, cy + 15), (cx - 1, cy + 18),
                 (cx + 6, cy + 15), (cx + 8, cy + 4)], "ink")
        for k in range(4):
            rect(s, cx - 6 + k * 3, cy + 7 + (k % 2) * 2, 1, 5, "steel")
        rect(s, cx - 4, cy + 7, 8, 2, "deep_red")
        rect(s, cx - 3, cy + 7, 2, 1, "cream")
        rect(s, cx + 1, cy + 7, 2, 1, "cream")

    # 鼻梁/嘴
    line(s, cx + 3, cy + 2, cx + 2, cy + 6, "skin_dark", 1)
    if mood == "hurt":
        rect(s, cx - 2, cy + 7, 4, 2, "red")
    elif hero == "wusong":
        line(s, cx - 2, cy + 8, cx + 3, cy + 8, "deep_red", 1)



def _mace(s, hx, hy, tx, ty, r: int = 5):
    """短槌：木杆 + 金环槌头 + 四向尖刺。"""
    line(s, hx, hy, tx, ty, "shadow", 7)
    line(s, hx, hy, tx, ty, "leather", 5)
    line(s, hx - 1, hy - 1, tx - 1, ty - 1, "amber", 1)
    ellipse(s, tx - r - 1, ty - r - 1, r * 2 + 2, r * 2 + 2, "shadow")
    ellipse(s, tx - r, ty - r, r * 2, r * 2, "gold")
    ellipse(s, tx - r + 1, ty - r + 1, max(2, r), max(2, r), "gold_light")
    ellipse(s, tx + r // 2, ty + r // 2,
            max(2, r // 2), max(2, r // 2), "gold_dark")
    rect(s, tx - r + 1, ty - 1, r * 2 - 2, 2, "red")
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        line(s, tx + dx * r, ty + dy * r,
             tx + dx * (r + 3), ty + dy * (r + 3), "gold_dark", 1)


def _spear(s, x1, y1, x2, y2, tip: int = 6):
    """长枪：枪杆 + 钢枪头 + 红缨。"""
    line(s, x1, y1, x2, y2, "shadow", 5)
    line(s, x1, y1, x2, y2, "leather", 3)
    line(s, x1 - 1, y1 - 1, x2 - 1, y2 - 1, "amber", 1)
    dx, dy = x2 - x1, y2 - y1
    d = max(1.0, (dx * dx + dy * dy) ** 0.5)
    nx, ny = dx / d, dy / d
    px, py = -ny, nx
    poly(s, [(x2, y2),
             (int(x2 - nx * tip + px * 3), int(y2 - ny * tip + py * 3)),
             (int(x2 - nx * tip - px * 3), int(y2 - ny * tip - py * 3))],
         "steel")
    line(s, int(x2 - nx * tip), int(y2 - ny * tip),
         int(x2 - nx * (tip - 2)), int(y2 - ny * (tip - 2)), "white", 1)
    for k in range(3):
        line(s, int(x2 - nx * 3), int(y2 - ny * 3),
             int(x2 - nx * (4 + k * 2) + px * (2 + k)), 
             int(y2 - ny * (4 + k * 2) + py * (2 + k)), "red", 1)


def _axe(s, hx, hy, tx, ty, flip: int = 1):
    """手斧：木柄 + 钢斧刃（flip=-1 刃朝左）。"""
    line(s, hx, hy, tx, ty, "shadow", 5)
    line(s, hx, hy, tx, ty, "leather", 3)
    poly(s, [(tx, ty),
             (tx - flip * 9, ty - 4),
             (tx - flip * 8, ty + 7),
             (tx - flip * 3, ty + 10)], "steel")
    line(s, tx, ty, tx - flip * 8, ty - 3, "white", 1)
    line(s, tx, ty, tx - flip * 3, ty + 9, "steel_dark", 1)
    line(s, tx - flip * 5, ty - 2, tx - flip * 5, ty + 7, "steel_dark", 1)


def _shield_small(s, cx, cy, r: int = 7):
    ellipse(s, cx - r - 1, cy - r - 1, r * 2 + 2, r * 2 + 2, "shadow")
    ellipse(s, cx - r, cy - r, r * 2, r * 2, "steel")
    ellipse(s, cx - r + 2, cy - r + 2, r * 2 - 4, r * 2 - 4, "jade")
    ellipse(s, cx - r + 3, cy - r + 3, 3, 3, "teal_light")
    ellipse(s, cx - 2, cy - 2, 4, 4, "gold")
    line(s, cx - r + 2, cy, cx + r - 2, cy, "steel_dark", 1)
    line(s, cx, cy - r + 2, cx, cy + r - 2, "steel_dark", 1)


def _spark(s, x, y, col: str = "cream"):
    for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4),
                   (-3, -3), (3, 3), (-3, 3), (3, -3)):
        line(s, x, y, x + dx, y + dy, col, 1)


def _hero_weapon(s, hero: str, state: str, frame: int,
                 x0: int, hip: int, lh, rh) -> None:
    """按状态/帧摆武器；技能帧同时画出轨迹起止，脚底基线不参与。"""
    if hero == "wusong":
        if state == "skill":
            tips = {
                0: ((lh[0] - 3, lh[1] + 5), (rh[0] + 3, rh[1] + 6)),
                1: ((x0 - 15, 7), (x0 + 16, 9)),
                2: ((x0 - 16, 3), (x0 + 16, 4)),
                3: ((x0 + 18, hip + 2), (x0 + 15, hip + 6)),
            }[frame]
            _mace(s, *lh, *tips[0], r=5)
            _mace(s, *rh, *tips[1], r=5)
            # 双槌抛接轨迹：左起右落，始终可见
            pygame.draw.arc(s, C["amber"],
                            (x0 - 20, 2, 44, hip + 8), 0.2, 2.8, 1)
            rect(s, x0 - 16, hip + 3, 3, 3, "amber")
            rect(s, x0 + 17, hip + 2, 3, 3, "amber")
            if frame == 2:
                _spark(s, x0, 4)
        elif state == "attack":
            tips = {
                0: ((lh[0] - 3, lh[1] - 6), (rh[0] - 2, rh[1] - 8)),
                1: ((lh[0] - 5, lh[1] - 8), (rh[0] - 4, rh[1] - 10)),
                2: ((lh[0] + 5, hip - 2), (rh[0] + 9, hip - 3)),
                3: ((lh[0] + 4, hip + 1), (rh[0] + 6, hip + 1)),
            }[frame]
            _mace(s, *lh, *tips[0], r=5)
            _mace(s, *rh, *tips[1], r=5)
            if frame == 2:
                _spark(s, rh[0] + 10, rh[1] - 5)
        else:
            _mace(s, *lh, lh[0] - 5, lh[1] - 10, r=5)
            _mace(s, *rh, rh[0] + 5, rh[1] - 11, r=5)
    elif hero == "linchong":
        if state == "skill":
            ends = {
                0: (x0 + 16, 4), 1: (x0 - 15, 2),
                2: (x0 - 17, hip + 7), 3: (x0 + 13, 5),
            }[frame]
            starts = {
                0: (x0 - 10, hip - 2), 1: (x0 + 8, hip - 6),
                2: (x0 + 14, hip - 8), 3: (x0 - 8, hip - 2),
            }[frame]
            _spear(s, *starts, *ends, tip=8)
            pygame.draw.arc(s, C["amber"],
                            (x0 - 20, 2, 44, hip + 8), 0.9, 3.4, 1)
            rect(s, x0 + 15, 3, 3, 3, "amber")
            rect(s, x0 - 18, hip + 5, 3, 3, "amber")
            if frame == 2:
                _spark(s, x0 - 18, hip + 7)
        elif state == "attack":
            ends = {
                0: (x0 + 17, hip - 5), 1: (x0 + 13, hip - 9),
                2: (x0 + 24, hip - 3), 3: (x0 + 15, hip - 1),
            }[frame]
            _spear(s, x0 - 11, hip - 2, *ends)
            if frame == 2:
                _spark(s, x0 + 24, hip - 3)
        else:
            _spear(s, x0 - 13, hip - 2, x0 + 15, 5)
    else:
        if state == "skill":
            tips = {
                0: ((x0 - 17, hip - 9), (x0 + 17, hip - 9)),
                1: ((x0 - 8, 4), (x0 + 9, 4)),
                2: ((x0 - 16, hip - 1), (x0 + 16, hip - 1)),
                3: ((x0 - 11, hip + 6), (x0 + 13, hip + 6)),
            }[frame]
            _axe(s, *lh, *tips[0], flip=-1)
            _axe(s, *rh, *tips[1], flip=1)
            pygame.draw.arc(s, C["amber"],
                            (x0 - 18, 2, 40, hip + 8), 0.4, 1.6, 1)
            pygame.draw.arc(s, C["amber"],
                            (x0 - 18, 2, 40, hip + 8), 3.6, 1.6, 1)
            rect(s, x0 - 18, hip - 9, 3, 3, "amber")
            rect(s, x0 + 16, hip - 9, 3, 3, "amber")
            if frame == 2:
                _spark(s, x0, hip + 2)
        elif state == "attack":
            tips = {
                0: ((lh[0] - 4, lh[1] - 7), (rh[0] + 4, rh[1] - 7)),
                1: ((lh[0] - 6, lh[1] - 10), (rh[0] + 6, rh[1] - 10)),
                2: ((lh[0] + 7, lh[1] - 3), (rh[0] + 10, rh[1] - 3)),
                3: ((lh[0] + 5, lh[1] + 1), (rh[0] + 7, rh[1] + 1)),
            }[frame]
            _axe(s, *lh, *tips[0], flip=-1)
            _axe(s, *rh, *tips[1], flip=1)
            if frame == 2:
                _spark(s, rh[0] + 11, rh[1] - 3)
        else:
            _axe(s, *lh, lh[0] - 4, lh[1] + 5, flip=-1)
            _axe(s, *rh, rh[0] + 4, rh[1] + 5, flip=1)



def _hero_hands(hero: str, state: str, frame: int, x0: int, hip: int):
    """返回 (左手, 右手) 掌心坐标；左右以观者视角。"""
    if state == "idle":
        return (x0 - 9, hip - 4), (x0 + 9, hip - 4)
    if state == "march":
        sw = (3, 1, -2, -3, -1, 2)[frame]
        return ((x0 - 9 - sw * 0.5, hip - 4 - sw * 0.4),
                (x0 + 9 + sw * 0.5, hip - 4 + sw * 0.4))
    if state == "hurt":
        return ((x0 - 11, hip - 7), (x0 + 11, hip - 4)) if frame == 0 \
            else ((x0 - 7, hip - 2), (x0 + 9, hip - 3))
    if state == "attack":
        return {
            0: ((x0 - 10, hip - 9), (x0 - 7, hip - 11)),
            1: ((x0 - 12, hip - 14), (x0 - 9, hip - 16)),
            2: ((x0 + 11, hip - 4), (x0 + 13, hip - 7)),
            3: ((x0 + 7, hip - 1), (x0 + 9, hip - 2)),
        }[frame]
    if hero == "wusong":
        return {
            0: ((x0 - 8, hip - 2), (x0 + 8, hip - 2)),
            1: ((x0 - 10, hip - 8), (x0 + 9, hip - 12)),
            2: ((x0 - 2, hip - 20), (x0 + 4, hip - 22)),
            3: ((x0 + 10, hip - 4), (x0 + 12, hip - 1)),
        }[frame]
    if hero == "linchong":
        return {
            0: ((x0 - 4, hip - 3), (x0 + 11, hip - 5)),
            1: ((x0 - 7, hip - 2), (x0 - 10, hip - 14)),
            2: ((x0 - 6, hip - 2), (x0 - 12, hip - 4)),
            3: ((x0 + 2, hip - 3), (x0 + 12, hip - 6)),
        }[frame]
    return {
        0: ((x0 - 13, hip - 10), (x0 + 13, hip - 10)),
        1: ((x0 - 5, hip - 20), (x0 + 5, hip - 22)),
        2: ((x0 - 4, hip - 4), (x0 + 4, hip - 4)),
        3: ((x0 - 12, hip - 2), (x0 + 12, hip - 2)),
    }[frame]


def _draw_hero_down(s, hero: str, frame: int) -> None:
    st = HERO_STYLE[hero]
    if frame == 0:
        # 倒下：身体前扑，脚仍贴基线，尘土刚起
        _ppoly(s, [(10, 50), (20, 40), (34, 47), (30, 57)],
               st["vest"], st["vest_light"], st["vest_dark"])
        _hero_face_small(s, hero, 14, 39, "hurt")
        _ppoly(s, [(24, 54), (32, 55), (42, 60), (34, 60)],
               st["pants"], st["pants_light"], st["pants_dark"])
        rect(s, 38, 56, 8, 4, st["boot"])
        for k in range(3):
            rect(s, 33 + k * 3, 56 - (k % 2) * 2, 2, 2, "mist")
        line(s, 6, 58, 22, 60, "leather", 2)
    else:
        # 落地横躺 + 尘团
        ellipse(s, 26, 54, 22, 8, "shadow")
        _ppoly(s, [(12, 52), (30, 50), (44, 55), (42, 60), (14, 59)],
               st["vest"], st["vest_light"], st["vest_dark"])
        ellipse(s, 4, 46, 14, 13, "shadow")
        ellipse(s, 5, 47, 12, 11, st["face_col"])
        rect(s, 13, 50, 2, 2, "white")
        rect(s, 8, 55, 7, 2, "ink")
        poly(s, [(30, 55), (40, 54), (44, 59), (30, 59)], st["pants"])
        rect(s, 40, 55, 5, 4, st["boot"])
        for k in range(6):
            rect(s, 34 + (k % 3) * 4, 48 - (k // 3) * 3, 3, 3,
                 "mist" if k % 2 else "steel")
        line(s, 2, 60, 20, 60, "leather", 2)


def draw_hero(hero: str, state: str, frame: int) -> pygame.Surface:
    """48×64 动作帧，脚底基线 y=60，左上光源，统一 2px 暗轮廓。"""
    s = surf(HERO_W, HERO_H)
    st = HERO_STYLE[hero]
    if state == "down":
        _draw_hero_down(s, hero, frame)
        return s

    mood = "hurt" if state == "hurt" else "idle"
    bob = crouch = lean = swing = 0
    lift_l = lift_r = 0
    if state == "idle":
        bob = (0, -1, 1, 0)[frame]
    elif state == "march":
        swing = (3, 1, -2, -3, -1, 2)[frame]
        bob = (0, -1, -2, 0, -1, -2)[frame]
        lean = 1
        lift_l = 3 if frame in (2, 5) else 0
        lift_r = 3 if frame in (1, 4) else 0
    elif state == "attack":
        lean = (-2, -3, 4, 2)[frame]
        crouch = (0, 0, 2, 1)[frame]
    elif state == "hurt":
        lean = -5 if frame == 0 else 1
        bob = -1 if frame == 0 else 0
        swing = -1
    elif state == "skill":
        lean = (-1, -2, 3, 1)[frame]
        crouch = (0, 0, 1, 0)[frame]

    x0 = 24 + lean
    hip = 36 + crouch + bob
    shoulder = 22 + crouch + bob
    head_cy = 15 + crouch + bob

    # 腿：前后步幅 ±3，过渡帧抬脚 3px；脚底落点始终 60
    lfx = x0 - 4 + swing
    rfx = x0 + 4 - swing
    _plimb(s, [(x0 - 5, hip), (lfx, 56 - lift_l)],
           st["pants"], st["pants_light"], st["pants_dark"], 6)
    _plimb(s, [(x0 + 3, hip), (rfx, 56 - lift_r)],
           st["pants"], st["pants_light"], st["pants_dark"], 6)
    rect(s, lfx - 4, 60 - lift_l - 5, 9, 5, "shadow")
    rect(s, lfx - 3, 60 - lift_l - 5, 8, 4, st["boot"])
    rect(s, lfx - 3, 60 - lift_l - 5, 8, 1, st["boot_light"])
    rect(s, rfx - 3, 60 - lift_r - 5, 10, 5, "shadow")
    rect(s, rfx - 2, 60 - lift_r - 5, 9, 4, st["boot"])
    rect(s, rfx - 2, 60 - lift_r - 5, 9, 1, st["boot_light"])

    # 披挂/后饰
    if hero == "linchong":
        _ppoly(s, [(x0 - 7, shoulder + 2), (x0 - 13, hip + 4),
                   (x0 - 2, hip + 7), (x0 + 3, shoulder + 2)],
               "violet_dark", "purple", "shadow")
    elif hero == "likui":
        _ppoly(s, [(x0 - 7, shoulder + 1), (x0 - 12, hip + 2),
                   (x0 - 4, hip + 4)], "red_dark", "red", "shadow")
        # 盾背在身后，从左肩外侧露半面，不遮双斧
        _shield_small(s, x0 - 11, shoulder + 5, 6)

    # 躯干 + 胸甲/腰带
    _ppoly(s, [(x0 - 7, hip), (x0 - 6, shoulder), (x0 + 6, shoulder),
               (x0 + 7, hip)], st["vest"], st["vest_light"], st["vest_dark"])
    if hero != "wusong":
        _ppoly(s, [(x0 - 5, shoulder + 4), (x0 + 5, shoulder + 4),
                   (x0 + 4, hip - 4), (x0 - 4, hip - 4)],
               st["armor"], st["armor_light"], st["armor_dark"])
    line(s, x0 - 6, shoulder + 3, x0 + 6, shoulder + 3, st["trim"], 1)
    _box(s, x0 - 7, hip - 4, 14, 4, st["trim"], st["trim_light"],
         st["trim_dark"])

    # 肩甲
    _pell(s, x0 - 11, shoulder - 3, 9, 8,
          st["armor"], st["armor_light"], st["armor_dark"])
    _pell(s, x0 + 3, shoulder - 3, 9, 8,
          st["armor"], st["armor_light"], st["armor_dark"])

    lh, rh = _hero_hands(hero, state, frame, x0, hip)
    # 后手 → 头 → 前手，保证 3/4 层次
    _plimb(s, [(x0 - 6, shoulder + 3),
               (int((x0 - 6 + lh[0]) / 2), int((shoulder + 3 + lh[1]) / 2)),
               (int(lh[0]), int(lh[1]))],
           st["limb"], st["limb_light"], st["limb_dark"], 5)
    rect(s, x0 - 3, shoulder - 2, 6, 5, st["limb"])
    _hero_face_small(s, hero, x0, head_cy, mood)
    _plimb(s, [(x0 + 6, shoulder + 3),
               (int((x0 + 6 + rh[0]) / 2), int((shoulder + 3 + rh[1]) / 2)),
               (int(rh[0]), int(rh[1]))],
           st["limb"], st["limb_light"], st["limb_dark"], 5)
    for hx, hy in (lh, rh):
        _pell(s, int(hx) - 2, int(hy) - 2, 5, 5,
              st["limb"], st["limb_light"], st["limb_dark"])
        rect(s, int(hx) - 2, int(hy) + 1, 5, 2,
             st["armor_dark"] if hero != "wusong" else "leather")

    _hero_weapon(s, hero, state, frame, x0, hip, lh, rh)
    if state == "hurt" and frame == 0:
        line(s, x0 + 2, head_cy - 4, x0 + 12, head_cy + 8, "vermilion", 2)
    if state == "march" and frame in (0, 3):
        for dx in (-10, 8):
            rect(s, x0 + dx, 58, 3, 1, "mist")
    return s


# 俯视 3/4 帧：斜俯视机位下能读到头顶、肩线与武器的纵向投影。
TOP_SPEC = {"idle": 3, "march": 3, "attack": 3, "skill": 3,
            "hurt": 2, "down": 2}


def draw_hero_top(hero: str, state: str, frame: int) -> pygame.Surface:
    """48×64 斜俯视 3/4 帧，脚底基线 y=60；硬边、无抗锯齿。"""
    s = surf(HERO_W, HERO_H)
    st = HERO_STYLE[hero]
    if state == "down":
        # 倒地：横向躯干 + 头朝右，武器脱手落在脚边
        rect(s, 12, 54, 24, 7, "shadow")
        _ppoly(s, [(13, 52), (32, 50), (35, 58), (16, 60)],
               st["vest"], st["vest_light"], st["vest_dark"])
        _pell(s, 33, 48, 12, 12, st["face_col"], st["face_light"],
              st["face_dark"])
        rect(s, 33, 47, 12, 3, st["trim"])
        line(s, 12, 58, 24, 56, st["boot"], 3)
        if hero == "wusong":
            _mace(s, 8, 58, 4, 58, r=4)
        elif hero == "linchong":
            _spear(s, 4, 59, 30, 62, tip=6)
        else:
            _axe(s, 7, 57, 3, 57, flip=-1)
        return s

    bob = 0
    swing = 0
    lean = 0
    arm_l = (-10, 40)
    arm_r = (10, 40)
    weapon = 0
    if state == "idle":
        bob = (0, 1, 0)[frame % 3]
    elif state == "march":
        swing = (3, 1, -2)[frame % 3]
        bob = (0, -1, -2)[frame % 3]
        arm_l = (-10, 38 - swing)
        arm_r = (10, 38 + swing)
    elif state in ("attack", "skill"):
        lean = (0, -2, 2)[frame % 3]
        weapon = (0, 1, 2)[frame % 3]
        arm_l = (-12, 34)
        arm_r = (12, 32)
        if state == "skill":
            weapon += 1
    elif state == "hurt":
        lean = 3 if frame == 0 else 1
        bob = -1 if frame == 0 else 0

    cx = 24 + lean
    hip = 44 + bob
    shoulder = 24 + bob
    head_y = 14 + bob

    # 腿：俯视下压缩到 12px，步幅靠左右错位表达
    lx = cx - 5 + swing
    rx = cx + 5 - swing
    _plimb(s, [(cx - 4, hip), (lx, 57)], st["pants"], st["pants_light"],
           st["pants_dark"], 6)
    _plimb(s, [(cx + 4, hip), (rx, 57)], st["pants"], st["pants_light"],
           st["pants_dark"], 6)
    rect(s, lx - 4, 56, 9, 5, "shadow")
    rect(s, lx - 3, 56, 8, 4, st["boot"])
    rect(s, lx - 3, 56, 8, 1, st["boot_light"])
    rect(s, rx - 4, 56, 10, 5, "shadow")
    rect(s, rx - 3, 56, 9, 4, st["boot"])
    rect(s, rx - 3, 56, 9, 1, st["boot_light"])

    # 背后的披挂/盾：先画，让肩背遮住一部分
    if hero == "linchong":
        _ppoly(s, [(cx - 9, shoulder + 2), (cx - 14, hip),
                   (cx - 4, hip + 6), (cx + 2, shoulder + 3)],
               "violet_dark", "purple", "shadow")
    elif hero == "likui":
        _shield_small(s, cx - 12, shoulder + 10, 7)

    # 躯干：肩宽 26、腰宽 16，宽肩是俯视可读性的关键
    _ppoly(s, [(cx - 13, shoulder), (cx - 8, hip), (cx + 8, hip),
               (cx + 13, shoulder)], st["vest"], st["vest_light"],
           st["vest_dark"])
    if hero != "wusong":
        _ppoly(s, [(cx - 9, shoulder + 5), (cx + 9, shoulder + 5),
                   (cx + 6, hip - 4), (cx - 6, hip - 4)],
               st["armor"], st["armor_light"], st["armor_dark"])
        line(s, cx - 6, hip - 5, cx + 6, hip - 5, st["trim"], 2)
    _box(s, cx - 8, hip - 2, 16, 5, st["trim"], st["trim_light"],
         st["trim_dark"])

    # 肩甲：大椭圆压住上臂，形成俯视的“肩线”
    _pell(s, cx - 16, shoulder - 2, 12, 10, st["armor"],
          st["armor_light"], st["armor_dark"])
    _pell(s, cx + 4, shoulder - 2, 12, 10, st["armor"],
          st["armor_light"], st["armor_dark"])

    # 后手
    _plimb(s, [(cx - 10, shoulder + 5), (cx + arm_l[0], arm_l[1])],
           st["limb"], st["limb_light"], st["limb_dark"], 5)
    # 头：椭圆偏宽（俯视），上暗下亮；脸只露左下 1/3
    _pell(s, cx - 9, head_y - 7, 19, 16, st["face_col"],
          st["face_light"], st["face_dark"])
    # 头顶发髻/盔缨
    _pell(s, cx - 7, head_y - 9, 15, 9, "ink", "steel", "shadow")
    if hero == "wusong":
        rect(s, cx - 8, head_y - 5, 16, 3, "gold")
        rect(s, cx - 8, head_y - 5, 16, 1, "gold_light")
        line(s, cx - 1, head_y - 12, cx - 10, head_y - 15, "red", 2)
        rect(s, cx - 11, head_y - 16, 2, 2, "gold_light")
    elif hero == "linchong":
        _ppoly(s, [(cx - 9, head_y - 5), (cx, head_y - 12),
                   (cx + 9, head_y - 5)], "gold", "gold_light", "gold_dark")
        line(s, cx, head_y - 12, cx - 8, head_y - 16, "red", 2)
    else:
        rect(s, cx - 9, head_y - 6, 18, 4, "red")
        rect(s, cx - 9, head_y - 6, 18, 1, "red_light")
        line(s, cx - 9, head_y - 4, cx - 18, head_y - 8, "red", 2)
        rect(s, cx - 19, head_y - 9, 3, 3, "gold")
    # 下半张脸/眼：斜俯视只保留左上眼与鼻梁
    eye_y = head_y + 1
    if hero == "wusong":
        rect(s, cx - 6, eye_y, 4, 3, "ink")
        rect(s, cx - 5, eye_y + 1, 2, 2, "amber")
        line(s, cx - 7, eye_y - 3, cx + 1, eye_y - 1, "ink", 2)
        line(s, cx + 1, eye_y - 1, cx + 7, eye_y - 3, "ink", 2)
        line(s, cx - 3, head_y + 6, cx + 3, head_y + 6, "deep_red", 1)
    elif hero == "linchong":
        rect(s, cx - 6, eye_y, 4, 3, "white")
        rect(s, cx - 5, eye_y + 1, 2, 2, "ink")
        rect(s, cx - 6, head_y + 5, 2, 2, "ink")
        rect(s, cx + 4, head_y + 3, 2, 2, "ink")
        line(s, cx - 7, eye_y - 3, cx + 1, eye_y - 1, "ink", 2)
    else:
        ellipse(s, cx - 7, eye_y - 1, 6, 5, "amber")
        rect(s, cx - 5, eye_y + 1, 2, 2, "white")
        line(s, cx - 8, eye_y - 3, cx + 1, eye_y - 1, "ink", 2)
        poly(s, [(cx - 8, head_y + 4), (cx - 4, head_y + 11),
                 (cx + 4, head_y + 11), (cx + 8, head_y + 4)], "ink")
    # 前手 + 武器
    _plimb(s, [(cx + 10, shoulder + 5), (cx + arm_r[0], arm_r[1])],
           st["limb"], st["limb_light"], st["limb_dark"], 5)
    for hx, hy in ((cx + arm_l[0], arm_l[1]), (cx + arm_r[0], arm_r[1])):
        _pell(s, int(hx) - 2, int(hy) - 2, 5, 5, st["limb"],
              st["limb_light"], st["limb_dark"])
        rect(s, int(hx) - 2, int(hy) + 1, 5, 2, st["armor_dark"]
             if hero != "wusong" else "leather")

    if hero == "wusong":
        tips = {
            0: ((cx - 19, 30), (cx + 19, 30)),
            1: ((cx - 20, 20), (cx + 20, 18)),
            2: ((cx - 24, 36), (cx + 16, 22)),
        }[weapon % 3]
        _mace(s, cx + arm_l[0], arm_l[1], *tips[0], r=5)
        _mace(s, cx + arm_r[0], arm_r[1], *tips[1], r=5)
    elif hero == "linchong":
        tips = {
            0: (cx + 22, 8),
            1: (cx + 26, 6),
            2: (cx + 30, 20),
        }[weapon % 3]
        _spear(s, cx - 4, 46, *tips, tip=8)
    else:
        tips = {
            0: ((cx - 20, 44), (cx + 20, 44)),
            1: ((cx - 18, 30), (cx + 18, 30)),
            2: ((cx - 24, 40), (cx + 14, 34)),
        }[weapon % 3]
        _axe(s, cx + arm_l[0], arm_l[1], *tips[0], flip=-1)
        _axe(s, cx + arm_r[0], arm_r[1], *tips[1], flip=1)

    if state in ("attack", "skill") and weapon == 2:
        _spark(s, cx + (18 if hero != "linchong" else 28), 24)
    if state == "march" and frame % 3 == 0:
        for dx in (-11, 9):
            rect(s, cx + dx, 58, 3, 1, "mist")
    if state == "hurt" and frame == 0:
        line(s, cx + 2, head_y - 8, cx + 12, head_y + 4, "vermilion", 2)
    return s


def _shield_big(s, cx, cy, r: int = 40):
    ellipse(s, cx - r - 2, cy - r - 2, r * 2 + 4, r * 2 + 4, "shadow")
    ellipse(s, cx - r, cy - r, r * 2, r * 2, "steel")
    ellipse(s, cx - r + 4, cy - r + 4, r * 2 - 8, r * 2 - 8, "jade")
    ellipse(s, cx - r + 12, cy - r + 12, r * 2 - 24, r * 2 - 24, "teal")
    ellipse(s, cx - 10, cy - 12, 14, 14, "teal_light")
    ellipse(s, cx - 8, cy - 8, 16, 16, "gold")
    ellipse(s, cx - 5, cy - 5, 10, 10, "red")
    line(s, cx - r + 4, cy, cx + r - 4, cy, "steel_dark", 2)
    line(s, cx, cy - r + 4, cx, cy + r - 4, "steel_dark", 2)


def _portrait_face(s, hero: str, cx: int, cy: int) -> None:
    st = HERO_STYLE[hero]
    rect(s, cx - 11, cy + 18, 22, 20, "shadow")
    rect(s, cx - 10, cy + 18, 20, 19, st["limb"])
    rect(s, cx - 10, cy + 18, 20, 3, st["limb_light"])
    _pell(s, cx - 21, cy - 23, 42, 46,
          st["face_col"], st["face_light"], st["face_dark"])
    _pell(s, cx - 25, cy - 4, 9, 15,
          st["face_col"], st["face_light"], st["face_dark"])
    eye_y = cy - 6

    if hero == "wusong":
        rect(s, cx - 17, eye_y - 2, 11, 9, "ink")
        rect(s, cx + 6, eye_y - 2, 11, 9, "ink")
        rect(s, cx - 13, eye_y + 1, 4, 6, "amber")
        rect(s, cx + 9, eye_y + 1, 4, 6, "amber")
        line(s, cx - 18, eye_y - 6, cx + 1, eye_y - 2, "ink", 4)
        line(s, cx + 2, eye_y - 2, cx + 18, eye_y - 7, "ink", 4)
        rect(s, cx - 22, cy - 23, 44, 7, "gold")
        rect(s, cx - 22, cy - 23, 44, 2, "gold_light")
        rect(s, cx - 22, cy - 18, 44, 2, "gold_dark")
        poly(s, [(cx, cy - 37), (cx - 8, cy - 28), (cx, cy - 22),
                 (cx + 8, cy - 28)], "amber")
        poly(s, [(cx - 16, cy + 11), (cx - 10, cy + 34), (cx - 2, cy + 23),
                 (cx + 7, cy + 35), (cx + 16, cy + 11)], "ink")
        for k in range(4):
            line(s, cx - 8 + k * 5, cy + 15, cx - 6 + k * 5, cy + 29,
                 "steel_dark", 1)
        line(s, cx - 4, cy - 23, cx - 31, cy - 48, "red", 4)
        line(s, cx + 1, cy - 24, cx - 18, cy - 51, "vermilion", 3)
        rect(s, cx - 33, cy - 50, 5, 5, "gold_light")
    elif hero == "linchong":
        for bx, by, bw, bh in ((cx - 17, cy + 4, 5, 6),
                               (cx + 9, cy + 7, 4, 5),
                               (cx - 8, cy - 16, 4, 4),
                               (cx + 14, cy - 9, 3, 4),
                               (cx + 3, cy + 15, 3, 3)):
            rect(s, bx, by, bw, bh, "ink")
        rect(s, cx - 17, eye_y - 2, 11, 9, "white")
        rect(s, cx + 6, eye_y - 2, 11, 9, "white")
        rect(s, cx - 13, eye_y, 4, 6, "ink")
        rect(s, cx + 9, eye_y, 4, 6, "ink")
        line(s, cx - 18, eye_y - 7, cx + 1, eye_y - 2, "ink", 4)
        line(s, cx + 2, eye_y - 2, cx + 18, eye_y - 7, "ink", 4)
        poly(s, [(cx - 26, cy - 18), (cx, cy - 42), (cx + 26, cy - 18)],
             "gold")
        line(s, cx - 26, cy - 18, cx + 26, cy - 18, "gold_dark", 3)
        line(s, cx - 20, cy - 20, cx, cy - 38, "gold_light", 2)
        poly(s, [(cx - 27, cy - 20), (cx - 18, cy - 32), (cx - 12, cy - 20)],
             "gold_dark")
        poly(s, [(cx + 27, cy - 20), (cx + 18, cy - 32), (cx + 12, cy - 20)],
             "gold_dark")
        rect(s, cx - 4, cy - 47, 8, 7, "red")
        line(s, cx, cy - 47, cx - 12, cy - 56, "red", 4)
        line(s, cx + 3, cy - 47, cx - 4, cy - 58, "vermilion", 3)
        line(s, cx - 12, cy + 15, cx + 12, cy + 15, "ink", 3)
        rect(s, cx - 4, cy + 18, 8, 8, "ink")
    else:
        ellipse(s, cx - 18, eye_y - 3, 13, 13, "steel")
        ellipse(s, cx + 6, eye_y - 3, 13, 13, "steel")
        ellipse(s, cx - 16, eye_y - 1, 9, 9, "amber")
        ellipse(s, cx + 8, eye_y - 1, 9, 9, "amber")
        rect(s, cx - 13, eye_y + 1, 4, 4, "white")
        rect(s, cx + 11, eye_y + 1, 4, 4, "white")
        line(s, cx - 20, eye_y - 8, cx + 1, eye_y - 2, "ink", 5)
        line(s, cx + 2, eye_y - 2, cx + 21, eye_y - 8, "ink", 5)
        rect(s, cx - 24, cy - 23, 48, 9, "red")
        rect(s, cx - 24, cy - 23, 48, 2, "red_light")
        rect(s, cx - 24, cy - 16, 48, 2, "red_dark")
        ellipse(s, cx - 1, cy - 31, 12, 9, "ink")
        line(s, cx - 24, cy - 19, cx - 41, cy - 35, "red", 4)
        line(s, cx - 24, cy - 14, cx - 42, cy - 24, "red_dark", 3)
        rect(s, cx - 43, cy - 38, 6, 6, "gold")
        poly(s, [(cx - 17, cy + 6), (cx - 13, cy + 42), (cx - 3, cy + 30),
                 (cx + 6, cy + 44), (cx + 17, cy + 6)], "ink")
        for k in range(5):
            line(s, cx - 10 + k * 5, cy + 12, cx - 8 + k * 5, cy + 36,
                 "steel", 1)
        rect(s, cx - 10, cy + 2, 20, 5, "deep_red")
        rect(s, cx - 8, cy + 2, 5, 2, "cream")
        rect(s, cx + 3, cy + 2, 5, 2, "cream")

    line(s, cx + 8, cy + 1, cx + 5, cy + 10, "skin_shadow", 2)
    if hero == "wusong":
        line(s, cx - 6, cy + 13, cx + 5, cy + 13, "deep_red", 2)
    elif hero == "linchong":
        line(s, cx - 5, cy + 13, cx + 5, cy + 13, "red_dark", 2)
    else:
        line(s, cx - 7, cy + 9, cx + 6, cy + 9, "red_dark", 2)


def draw_portrait(hero: str) -> pygame.Surface:
    """256×256 全身 3/4 定妆照，底部 24px 标注带；透明背景。"""
    s = surf(PORTRAIT_W, PORTRAIT_H)
    st = HERO_STYLE[hero]
    # 统一投影：左上光源 → 影子右下沉
    ellipse(s, 84, 206, 124, 24, "shadow")
    ellipse(s, 92, 208, 108, 19, "night")

    if hero == "linchong":
        _ppoly(s, [(112, 108), (76, 196), (104, 204), (150, 118)],
               "violet_dark", "purple", "shadow")
        _spear(s, 56, 214, 212, 42, tip=18)
    elif hero == "likui":
        _shield_big(s, 178, 128, 40)

    # 腿 + 靴（脚底 224；双腿留 8px 可见中缝，避免黑裤粘连）
    _ppoly(s, [(112, 148), (130, 150), (128, 216), (110, 218)],
           st["pants"], st["pants_light"], st["pants_dark"])
    _ppoly(s, [(142, 150), (158, 148), (162, 216), (144, 218)],
           st["pants"], st["pants_light"], st["pants_dark"])
    line(s, 110, 152, 110, 212, st["pants_light"], 1)
    line(s, 158, 152, 158, 212, st["pants_light"], 1)
    _ppoly(s, [(104, 212), (130, 212), (132, 224), (102, 224)],
           st["boot"], st["boot_light"], st["boot_dark"])
    _ppoly(s, [(142, 212), (162, 212), (168, 224), (142, 224)],
           st["boot"], st["boot_light"], st["boot_dark"])
    line(s, 106, 214, 130, 214, st["boot_light"], 2)
    line(s, 144, 214, 166, 214, st["boot_light"], 2)

    # 躯干
    _ppoly(s, [(106, 100), (162, 104), (158, 154), (110, 154)],
           st["vest"], st["vest_light"], st["vest_dark"])
    if hero == "wusong":
        _ppoly(s, [(118, 106), (152, 108), (149, 143), (121, 141)],
               "red_light", "vermilion", "red")
        line(s, 116, 124, 154, 126, "gold", 2)
    else:
        _ppoly(s, [(116, 106), (154, 108), (151, 146), (119, 144)],
               st["armor"], st["armor_light"], st["armor_dark"])
        line(s, 118, 118, 152, 120, st["trim"], 3)
        line(s, 118, 136, 152, 138, st["trim"], 2)
    # 腰带
    _box(s, 110, 146, 50, 10, st["trim"], st["trim_light"], st["trim_dark"])

    # 肩甲
    _pell(s, 92, 96, 30, 22,
          st["armor"], st["armor_light"], st["armor_dark"])
    _pell(s, 150, 98, 30, 22,
          st["armor"], st["armor_light"], st["armor_dark"])

    # 手臂（左手后、右手前）
    _plimb(s, [(108, 110), (98, 138), (94, 158)],
           st["limb"], st["limb_light"], st["limb_dark"], 12)
    _plimb(s, [(164, 112), (184, 140), (190, 158)],
           st["limb"], st["limb_light"], st["limb_dark"], 12)
    _box(s, 88, 148, 14, 8, st["armor"], st["armor_light"], st["armor_dark"])
    _box(s, 184, 148, 14, 8, st["armor"], st["armor_light"], st["armor_dark"])
    _pell(s, 86, 154, 14, 10,
          st["limb"], st["limb_light"], st["limb_dark"])
    _pell(s, 188, 154, 14, 10,
          st["limb"], st["limb_light"], st["limb_dark"])

    # 头/脸/盔缨
    _portrait_face(s, hero, 134, 68)

    # 前手武器
    if hero == "wusong":
        _mace(s, 190, 158, 222, 84, r=13)
        _mace(s, 94, 158, 52, 96, r=13)
    elif hero == "linchong":
        line(s, 176, 138, 192, 130, "gold", 3)
    else:
        _axe(s, 94, 158, 62, 124, flip=-1)
        _axe(s, 190, 158, 222, 126, flip=1)

    # 24px 标注带
    rect(s, 0, PORTRAIT_H - BAND_H, PORTRAIT_W, BAND_H, "night")
    rect(s, 0, PORTRAIT_H - BAND_H, PORTRAIT_W, 2, "gold")
    label = f"{st['name']} · {st['nick']} · {st['face']} · {st['kind_label']}"
    draw_label_cjk(s, label, PORTRAIT_W // 2, PORTRAIT_H - BAND_H + 2,
                   "amber", 10)
    draw_text5_center(s, st["latin"], PORTRAIT_W // 2,
                      PORTRAIT_H - 9, "cream")
    return s


STATE_ORDER = ("idle", "march", "attack", "hurt", "down", "skill")


def _scaled(img: pygame.Surface, k: int = 3) -> pygame.Surface:
    return pygame.transform.scale(img, (img.get_width() * k,
                                        img.get_height() * k))


def make_sheet(hero: str) -> pygame.Surface:
    """横排精灵表：22 帧、144×192 单元格、1px 帧格线 + 帧号。"""
    cell_w, cell_h = HERO_W * 3, HERO_H * 3
    gap, margin, top, footer = 4, 8, 14, 14
    total = sum(HERO_FRAMES_SPEC[s]["count"] for s in STATE_ORDER)
    width = margin * 2 + total * cell_w + (total - 1) * gap
    height = top + cell_h + footer + 8
    sheet = surf(width, height)
    rect(sheet, 0, 0, width, height, "night")
    rect(sheet, 0, 0, width, 2, "gold_dark")
    y = top
    i = 0
    for state in STATE_ORDER:
        count = HERO_FRAMES_SPEC[state]["count"]
        for f in range(count):
            x = margin + i * (cell_w + gap)
            sheet.blit(_scaled(draw_hero(hero, state, f)), (x, y))
            pygame.draw.rect(sheet, C["steel_dark"],
                             (x - 1, y - 1, cell_w + 1, cell_h + 1), 1)
            if f == 0:
                draw_text5(sheet, state.upper(), x + 2, 2, "amber")
                rect(sheet, x - 1, 12, cell_w + 1, 1, "gold_dark")
            draw_text5(sheet, f"{i:02d}", x + 2, y + cell_h + 3, "mist")
            i += 1
    return sheet


def make_preview(hero: str) -> tuple[str, list[int]]:
    """待机 4 + 行军 6 + 攻击 4，各走一遍；14 帧约 8.5s。"""
    try:
        from gif_writer import write_gif
    except ImportError:  # 作为包导入时
        from tools.gif_writer import write_gif

    seq = ([("idle", i, 900) for i in range(4)]
           + [("march", i, 450) for i in range(6)]
           + [("attack", i, 550) for i in range(4)])
    frames: list[pygame.Surface] = []
    delays: list[int] = []
    for state, idx, ms in seq:
        f = surf(HERO_W * 3, HERO_H * 3)
        rect(f, 0, 0, HERO_W * 3, HERO_H * 3, "night")
        rect(f, 0, HERO_BASE * 3, HERO_W * 3, HERO_H * 3 - HERO_BASE * 3,
             "tile")
        line(f, 0, HERO_BASE * 3, HERO_W * 3, HERO_BASE * 3, "steel_dark", 1)
        f.blit(_scaled(draw_hero(hero, state, idx)), (0, 0))
        draw_text5(f, state.upper(), 4, 4, "amber")
        draw_text5(f, f"F{idx + 1}", 4, 12, "mist")
        frames.append(f)
        delays.append(ms)
    rel = f"sprites/{hero}/{hero}_preview.gif"
    path = os.path.join(OUT, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    w, h = write_gif(path, frames, list(PALETTE.values()), delays)
    MANIFEST["animations"][hero] = {
        "path": rel, "size": [w, h], "frames": len(frames),
        "delays_ms": delays, "loop": 0,
    }
    return rel, delays


def make_lineup() -> pygame.Surface:
    """全员 lineup：三位横排 + 姓名（标注带）+ 一句定位；尺寸随内容。"""
    width, height = 864, 348
    s = surf(width, height)
    rect(s, 0, 0, width, height, "night")
    rect(s, 0, 0, width, height, "gold")
    rect(s, 2, 2, width - 4, height - 4, "night")
    draw_label_cjk(s, "梁山三好汉 · 定妆照", width // 2, 8, "amber", 17)
    draw_text5_center(s, "LIANGSHAN THREE / PIXEL PORTRAIT LINEUP",
                      width // 2, 27, "mist")
    for i, hero in enumerate(("wusong", "linchong", "likui")):
        st = HERO_STYLE[hero]
        x = 24 + i * 280
        s.blit(draw_portrait(hero), (x, 38))
        if i < 2:
            rect(s, x + 268, 48, 1, 236, "gold_dark")
        draw_label_cjk(s, st["tagline"], x + 128, 303, "cream", 11)
    draw_text5_center(s, "LINEUP / 3 HEROES / 256PX PORTRAIT / 40-COLOR PALETTE",
                      width // 2, 331, "steel")
    return s


def gen_heroes():
    for sub in ("heroes", "sprites", "portraits"):
        p = os.path.join(OUT, sub)
        if os.path.isdir(p):
            shutil.rmtree(p)
    frames_cfg = {
        "version": 2,
        "frame_size": [HERO_W * 3, HERO_H * 3],
        "baseline": HERO_BASE * 3,
        "palette_count": len(PALETTE),
        "heroes": {},
    }
    for hero, st in HERO_STYLE.items():
        entry = {"name": st["name"], "nick": st["nick"], "kind": st["kind"],
                 "face": st["face"], "role": st["role"],
                 "skill": st["skill"], "tagline": st["tagline"],
                 "frame_size": [HERO_W * 3, HERO_H * 3],
                 "baseline": HERO_BASE * 3, "frames": {}}
        for state, spec in HERO_FRAMES_SPEC.items():
            entry["frames"][state] = {
                "count": spec["count"],
                "durations_ms": list(spec["durations_ms"]),
                "peak": spec["peak"],
                "loop": spec["loop"],
                "cancelable": spec["cancelable"],
            }
            for i in range(spec["count"]):
                img = draw_hero(hero, state, i)
                save(img, f"sprites/{hero}/{hero}_{state}_{i}.png", 3,
                     "hero", HERO_BASE)
        # 斜俯视 3/4 版本：待机/行军/攻击/技能/受击/倒地
        entry["top_frames"] = {}
        for state, count in TOP_SPEC.items():
            entry["top_frames"][state] = count
            for i in range(count):
                img = draw_hero_top(hero, state, i)
                save(img, f"sprites/{hero}/top_{state}_{i}.png", 3,
                     "hero", HERO_BASE)
        portrait = draw_portrait(hero)
        save(portrait, f"portraits/{hero}.png", 1, "portrait", None)
        entry["portrait"] = f"portraits/{hero}.png"

        sheet = make_sheet(hero)
        rel = f"sprites/{hero}/{hero}_sheet.png"
        save(sheet, rel, 1, "sheet", None)
        MANIFEST["sheets"][hero] = {
            "path": rel, "size": list(sheet.get_size()),
            "cell": [HERO_W * 3, HERO_H * 3],
            "count": sum(HERO_FRAMES_SPEC[s]["count"] for s in STATE_ORDER),
        }
        entry["sheet"] = rel

        preview, delays = make_preview(hero)
        entry["preview"] = preview
        entry["preview_delays_ms"] = delays
        frames_cfg["heroes"][hero] = entry

    lineup = make_lineup()
    save(lineup, "portraits/lineup.png", 1, "portrait", None)

    cfg_path = os.path.join(ROOT, "config", "hero_frames.json")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(frames_cfg, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ 纵深档位预烘
# 运行时禁止任何缩放：每个 v 档位在这里一次性 nearest 缩好，渲染只按档挑图。
BAND_FACTORS = {"sprites": 0.625, "enemies": 0.75, "boss": 0.75, "props": 0.75}
SHADOW_EDGE = (30, 20, 26)
SHADOW_CORE = (52, 34, 36)


def _list_png(rel_dir: str, prefix: str = "") -> list[str]:
    base = os.path.join(OUT, *rel_dir.split("/"))
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if name.endswith(".png") and (not prefix or name.startswith(prefix)):
            out.append(f"{rel_dir}/{name}")
    return out


def _bake_one(src_rel: str, band: int, band_scale: float, factor: float) -> None:
    src = os.path.join(OUT, *src_rel.split("/"))
    img = pygame.image.load(src).convert_alpha()
    w = max(1, int(round(img.get_width() * factor * band_scale)))
    h = max(1, int(round(img.get_height() * factor * band_scale)))
    out = pygame.transform.scale(img, (w, h))
    rel = f"bands/b{band}/{src_rel}"
    path = os.path.join(OUT, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pygame.image.save(out, path)
    MANIFEST["bands"]["images"][rel] = {
        "path": rel,
        "band": band,
        "scale": round(band_scale, 4),
        "size": [w, h],
        "source_size": list(img.get_size()),
        "factor": factor,
    }


def _shadow_tile(w: int, h: int) -> pygame.Surface:
    """预烘阴影：棋盘抖动 + 两阶暗色，alpha 只有 0/255，无半透明灰边。"""
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    cx, cy = w / 2.0, h / 2.0
    for y in range(h):
        for x in range(w):
            if (x + y) & 1:
                continue
            nx = (x + 0.5 - cx) / max(1.0, cx)
            ny = (y + 0.5 - cy) / max(1.0, cy)
            r2 = nx * nx + ny * ny
            if r2 <= 1.0:
                col = SHADOW_CORE if r2 <= 0.40 else SHADOW_EDGE
                s.set_at((x, y), (*col, 255))
    return s


def gen_bands():
    """按 10 个“最终屏幕缩放”档位预烘角色 / 敌人 / Boss / 道具 / 阴影。"""
    bands_dir = os.path.join(OUT, "bands")
    if os.path.isdir(bands_dir):
        shutil.rmtree(bands_dir)
    MANIFEST["bands"] = {
        "count": p3d.BAND_COUNT,
        "scales": [round(s, 4) for s in p3d.band_scales()],
        "v_near": p3d.V_NEAR,
        "v_far": p3d.V_FAR,
        "factors": dict(BAND_FACTORS),
        "images": {},
        "shadows": {},
    }
    for band in range(p3d.BAND_COUNT):
        bs = p3d.band_scale(band)
        # 好汉 3/4 俯视帧
        hero_dirs = [d for d in sorted(os.listdir(os.path.join(OUT, "sprites")))
                     if os.path.isdir(os.path.join(OUT, "sprites", d))]
        for hero in hero_dirs:
            for rel in _list_png(f"sprites/{hero}", "top_"):
                _bake_one(rel, band, bs, BAND_FACTORS["sprites"])
        # 敌人
        enemy_dirs = [d for d in sorted(os.listdir(os.path.join(OUT, "enemies")))
                      if os.path.isdir(os.path.join(OUT, "enemies", d))]
        for kind in enemy_dirs:
            for rel in _list_png(f"enemies/{kind}"):
                _bake_one(rel, band, bs, BAND_FACTORS["enemies"])
        # Boss
        for rel in _list_png("boss/drumking"):
            _bake_one(rel, band, bs, BAND_FACTORS["boss"])
        # 道具（灯笼等）
        for rel in _list_png("props"):
            _bake_one(rel, band, bs, BAND_FACTORS["props"])
        # 阴影：尺寸与偏移随档变化，方向固定左下（按档中心绝对屏幕缩放）
        dx, dy, w, h = p3d.shadow_rect_band(band)
        rel = f"bands/b{band}/fx/shadow.png"
        path = os.path.join(OUT, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pygame.image.save(_shadow_tile(w, h), path)
        MANIFEST["bands"]["shadows"][rel] = {
            "path": rel, "band": band, "size": [w, h],
            "dx": dx, "dy": dy, "scale": round(bs, 4),
        }


def main():
    pygame.init()
    pygame.display.set_mode((1, 1))
    os.makedirs(OUT, exist_ok=True)
    gen_players()
    gen_enemies()
    gen_boss()
    gen_ui()
    gen_guide()
    gen_props()
    gen_env()
    gen_parallax()
    gen_heroes()
    gen_bands()
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, ensure_ascii=False, indent=2)
    print(f"GENERATED: {len(MANIFEST['images'])} images -> {OUT}")
    pygame.quit()


if __name__ == "__main__":
    main()
