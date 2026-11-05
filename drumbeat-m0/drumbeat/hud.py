"""渲染层：世界、HUD、节拍可视化、判定调试面板与手感调节面板。

对应任务：T-D03（节拍可视化与合拍反馈）、T-E01（判定调试面板）、T-B03（手感面板的显示部分）。
M1 改造：M1-2 接入像素素材（缺图回退程序绘制）、M1-4 接入视差背景。
"""
from __future__ import annotations

import math
import random
import sys

import pygame

from .assets import Assets
from .config import DATA, PIXELS_PER_UNIT, SCREEN_H, SCREEN_W, app_dir
from .squad import MORPH_STAGGER, MORPH_WINDOW, N_UNITS     # 变阵参数/人数的单一事实源在逻辑层

# 英歌脸谱配色：红 / 黑 / 白 / 金
RED = (200, 16, 46)
DARK = (18, 18, 20)
INK = (26, 26, 30)
WHITE = (242, 240, 230)
GOLD = (184, 134, 11)
GREY = (150, 150, 150)
DIM = (96, 96, 104)
ORANGE = (230, 110, 40)
BLUE = (70, 130, 180)
GREEN = (60, 160, 90)

GROUND_SCREEN_Y = SCREEN_H * 0.76

# 视差层配置：(素材键, 视差系数, 缩放, 锚点模式, 锚点参数, 平铺间距 px)
#   锚点 top  ：参数 = 内容顶部距屏幕顶的比例（0–1）
#   锚点 ground：参数 = 内容底部相对地面线的偏移（世界单位，正值抬高）
#   间距 None = 按自身宽度连续平铺
PARALLAX_LAYERS = [
    ("cloud1", 0.06, 1.00, "top", 0.06, None),
    ("far_new", 0.30, 0.50, "top", -0.50, None),
    ("mid", 0.55, 1.15, "ground", 0.35, None),
]
# L2「双龙出海」环境：far_L2 整幅暮色天空（走 far* 不裁剪分支）+ 抠天后的骑楼中景
PARALLAX_LAYERS_L2 = [
    ("far_L2", 0.30, 0.50, "top", -0.50, None),
    ("mid_L2", 0.55, 0.39, "ground", 0.35, None),
]
FOREGROUND_LAYER = ("fore", 1.35, 0.20, "top", 0.02, 760)


def load_font(size: int) -> pygame.font.Font:
    for name in ("microsoftyaheiui", "microsoftyahei", "simhei", "simsun", "notosanscjksc", "arialunicodems"):
        path = pygame.font.match_font(name)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.SysFont(None, size)


class Camera:
    def __init__(self) -> None:
        self.x = 0.0

    def update(self, player, ratio: float) -> None:
        target = player.x + player.vx * ratio
        self.x += (target - self.x) * 0.12

    def to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        return int((wx - self.x) * PIXELS_PER_UNIT + SCREEN_W / 2), int(GROUND_SCREEN_Y - wy * PIXELS_PER_UNIT)


class Renderer:
    def __init__(self) -> None:
        self.font_s = load_font(16)
        self.font_m = load_font(20)
        self.font_l = load_font(30)
        self.font_xl = load_font(46)
        self.cam = Camera()
        self.assets = Assets()
        self._sky: pygame.Surface | None = None
        self._layers: dict[str, tuple | None] = {}
        self._anim_dist = 0.0
        self._last_px = 0.0

    # ------------------------------------------------------------------ 世界
    def draw_world(self, surf: pygame.Surface, level, player, combat) -> None:
        surf.fill((16, 14, 18))                       # 兜底底色：地平线以下与关卡范围外不留黑
        surf.blit(self._sky_surface(), (0, 0))
        layers = PARALLAX_LAYERS_L2 if getattr(level, "raw", {}).get("env") == "L2" else PARALLAX_LAYERS
        for cfg in layers:
            self._blit_layer(surf, self._prep_layer(*cfg))

        self._draw_tiled_solids(surf, level.ground_rects + level.platform_rects)
        for r in level.low_wall_rects:
            self._rect(surf, r.x, r.y, r.w, r.h, (120, 44, 40), (190, 70, 60))
        for r in level.hazard_rects:
            self._draw_spikes(surf, r)

        # 终点
        gx, gy = self.cam.to_screen(level.goal_x, 0.0)
        pygame.draw.rect(surf, GOLD, pygame.Rect(gx - 6, gy - 180, 12, 180))
        pygame.draw.polygon(surf, RED, [(gx + 6, gy - 180), (gx + 66, gy - 156), (gx + 6, gy - 132)])

        for e in level.enemies:
            self._draw_enemy(surf, e)
        self._draw_player(surf, player, combat)

        # 前景层画在角色之后，形成纵深遮挡
        self._blit_layer(surf, self._prep_layer(*FOREGROUND_LAYER))

    # ------------------------------------------------------------------ 背景
    def _sky_surface(self) -> pygame.Surface:
        """用天空素材的取色生成整屏竖直渐变（素材本身只有中间一条带）。"""
        if self._sky is not None:
            return self._sky
        h = int(GROUND_SCREEN_Y) + 4
        s = pygame.Surface((SCREEN_W, h))
        base = self.assets.env("sky")
        if base is None:
            s.fill((30, 30, 36))
            self._sky = s
            return s
        box = base.get_bounding_rect(1)
        top = self._row_color(base, box.top + 3, box)
        bot = self._row_color(base, box.bottom - 3, box)
        for y in range(h):
            t = y / max(1, h - 1)
            col = (int(top[0] + (bot[0] - top[0]) * t),
                   int(top[1] + (bot[1] - top[1]) * t),
                   int(top[2] + (bot[2] - top[2]) * t))
            pygame.draw.line(s, col, (0, y), (SCREEN_W, y))
        self._sky = s
        return s

    @staticmethod
    def _row_color(surf: pygame.Surface, y: int, box: pygame.Rect) -> tuple[int, int, int]:
        n = 5
        r = g = b = 0
        for i in range(n):
            x = box.left + int((i + 0.5) * box.width / n)
            c = surf.get_at((x, y))
            r += c[0]
            g += c[1]
            b += c[2]
        return (r // n, g // n, b // n)

    def _prep_layer(self, key: str, factor: float, scale: float, mode: str, param: float, spacing=None):
        """裁剪到内容范围并按需缩放，结果缓存（只在首次调用时计算）。"""
        if key in self._layers:
            return self._layers[key]
        rec = None
        src = self.assets.env(key)
        if src is not None:
            if key.startswith("far"):
                # 远景层是带透明天空的整幅背景，保留原画布位置，避免裁剪后变成浮空横条
                box = src.get_rect()
                crop = src
            else:
                box = src.get_bounding_rect(1)
                crop = src.subsurface(box) if box.width > 0 and box.height > 0 else None
            if crop is not None and box.width > 0 and box.height > 0:
                tile = self.assets.scaled(crop, int(crop.get_width() * scale), int(crop.get_height() * scale))
                if mode == "top":
                    y = int(param * SCREEN_H)
                else:
                    y = int(GROUND_SCREEN_Y - tile.get_height() + param * PIXELS_PER_UNIT)
                step = int(spacing) if spacing else tile.get_width()
                rec = (tile, y, factor, max(1, step))
        self._layers[key] = rec
        return rec

    def _blit_layer(self, surf: pygame.Surface, rec) -> None:
        """按视差滚动绘制背景层。

        相邻瓦片左右镜像拼接：拼接处两列像素来自同一图像数据，内容连续，因此看不出接缝。
        镜像奇偶用「世界锚定的瓦片序号」判断，保证镜头移动时不会突然翻转。
        """
        if rec is None:
            return
        tile, y, factor, step = rec
        if tile.get_width() < 1:
            return
        flip = self.assets.flipped(tile)
        off = self.cam.x * PIXELS_PER_UNIT * factor      # 该层对应的世界坐标偏移
        x = int((-off) % step) - step
        while x < SCREEN_W:
            k = math.floor((off + x) / step)
            surf.blit(flip if k % 2 else tile, (x, y))
            x += step

    def _draw_tiled_solids(self, surf: pygame.Surface, rects) -> None:
        tile = self.assets.env("ground")
        for r in rects:
            x, y = self.cam.to_screen(r.x, r.y + r.h)
            w = int(r.w * PIXELS_PER_UNIT)
            h = int(r.h * PIXELS_PER_UNIT)
            if w <= 0 or h <= 0:
                continue
            if tile is None:
                pygame.draw.rect(surf, (54, 48, 44), pygame.Rect(x, y, w, h))
                pygame.draw.rect(surf, (86, 76, 66), pygame.Rect(x, y, w, h), 2)
                continue
            tw = max(1, int(tile.get_width() * h / tile.get_height()))
            t = self.assets.scaled(tile, tw, h)
            clip = surf.get_clip()
            surf.set_clip(pygame.Rect(x, y, w, h))
            tx = x
            while tx < x + w:
                surf.blit(t, (tx, y))
                tx += tw
            surf.set_clip(clip)
            pygame.draw.rect(surf, (96, 120, 140), pygame.Rect(x, y, w, 3))

    def _rect(self, surf, wx, wy, ww, wh, fill, edge) -> None:
        x, y = self.cam.to_screen(wx, wy + wh)
        pygame.draw.rect(surf, fill, pygame.Rect(x, y, int(ww * PIXELS_PER_UNIT), int(wh * PIXELS_PER_UNIT)))
        pygame.draw.rect(surf, edge, pygame.Rect(x, y, int(ww * PIXELS_PER_UNIT), int(wh * PIXELS_PER_UNIT)), 2)

    def _draw_spikes(self, surf, r) -> None:
        n = max(2, int(r.w / 0.4))
        step = r.w / n
        for i in range(n):
            x0, y0 = self.cam.to_screen(r.x + i * step, r.y)
            x1, y1 = self.cam.to_screen(r.x + (i + 0.5) * step, r.y + r.h)
            x2, y2 = self.cam.to_screen(r.x + (i + 1) * step, r.y)
            pygame.draw.polygon(surf, ORANGE, [(x0, y0), (x1, y1), (x2, y2)])

    # ------------------------------------------------------------------ 角色
    def _blit_actor(self, surf: pygame.Surface, spr, x: int, y: int,
                    facing: int = 1, yscale: float = 1.0, tint=None) -> bool:
        """以「脚底中心」对齐绘制角色贴图；返回是否成功（False 表示缺图，需回退）。"""
        if spr is None:
            return False
        img = spr
        if yscale != 1.0:
            img = self.assets.scaled(img, img.get_width(), int(img.get_height() * yscale))
        if facing < 0:
            img = self.assets.flipped(img)
        if tint is not None:
            img = self.assets.tinted(img, tint)
        surf.blit(img, img.get_rect(midbottom=(x, y)))
        return True

    def _player_state(self, player, combat) -> tuple[str | None, int]:
        if player.dead:
            return "death", 0
        if combat.attack_id:
            return "attack", 0
        if not player.on_ground:
            return "air", 0
        if player.sliding:
            return "run", 0
        self._anim_dist += abs(player.x - self._last_px)
        self._last_px = player.x
        if abs(player.vx) > 0.4:
            return "run", int(self._anim_dist / 0.45) % 4
        return "run", 0        # 缺 idle 素材，暂以跑动首帧站立

    def _draw_player(self, surf: pygame.Surface, player, combat) -> None:
        x, y = self.cam.to_screen(player.x, player.y)
        state, frame = self._player_state(player, combat)
        spr = self.assets.player(state, frame) if state else None
        tint = (70, 55, 0) if player.invincible else None
        yscale = 0.55 if player.sliding else 1.0
        if not self._blit_actor(surf, spr, x, y, player.facing, yscale, tint):
            self._draw_player_fallback(surf, player)

        # 攻击判定框提示（便于调参）
        if combat.attack_id and combat.phase in ("active", "startup"):
            box = combat.hitbox(player)
            bx, by = self.cam.to_screen(box.x, box.y + box.h)
            color = GOLD if combat.phase == "active" else DIM
            pygame.draw.rect(surf, color, pygame.Rect(bx, by, int(box.w * PIXELS_PER_UNIT), int(box.h * PIXELS_PER_UNIT)), 2)

    def _draw_player_fallback(self, surf: pygame.Surface, player) -> None:
        x, y = self.cam.to_screen(player.x, player.y + player.height)
        w = int(player.WIDTH * PIXELS_PER_UNIT)
        h = int(player.height * PIXELS_PER_UNIT)
        body = WHITE
        if player.invincible:
            body = (255, 230, 160) if int(player.invincible_t * 20) % 2 == 0 else WHITE
        pygame.draw.rect(surf, body, pygame.Rect(x - w // 2, y, w, h), border_radius=4)
        pygame.draw.rect(surf, DARK, pygame.Rect(x - w // 2, y, w, h), 2, border_radius=4)
        pygame.draw.rect(surf, RED, pygame.Rect(x - w // 2, y, w, int(h * 0.22)))
        f = 1 if player.facing > 0 else -1
        pygame.draw.circle(surf, GOLD, (x + f * int(w * 0.22), y + int(h * 0.38)), 3)

    def _draw_enemy(self, surf: pygame.Surface, e) -> None:
        x, y = self.cam.to_screen(e.x, e.y)
        if e.dead:
            if e.death_t > 0.8:
                return
            self._blit_actor(surf, self.assets.enemy("defeat", int(e.death_t / 0.12)), x, y, e.facing)
            return

        state = {"patrol": "walk", "startup": "attack1", "active": "attack2",
                 "recovery": "attack1", "stun": "block"}.get(e.state)
        tint = (140, 20, 20) if e.hit_flash_t > 0 else None
        if not self._blit_actor(surf, self.assets.enemy(state) if state else None, x, y, e.facing, 1.0, tint):
            self._draw_enemy_fallback(surf, e)

        w = int(e.w * PIXELS_PER_UNIT)
        # 血条
        bw = w + 12
        pygame.draw.rect(surf, (60, 20, 20), pygame.Rect(x - bw // 2, y - 160, bw, 5))
        pygame.draw.rect(surf, RED, pygame.Rect(x - bw // 2, y - 160, int(bw * e.hp / e.max_hp), 5))
        # 攻击前摇警示
        if e.state == "startup":
            prog = e.t / max(1e-6, e.startup_s)
            pygame.draw.rect(surf, ORANGE, pygame.Rect(x - 16, y - 186, int(32 * prog), 4))
            pygame.draw.circle(surf, ORANGE, (x, y - 196), 5)
        elif e.state == "active":
            hb = e.attack_hitbox()
            hx, hy = self.cam.to_screen(hb.x, hb.y + hb.h)
            pygame.draw.rect(surf, ORANGE, pygame.Rect(hx, hy, int(hb.w * PIXELS_PER_UNIT), int(hb.h * PIXELS_PER_UNIT)), 2)

    def _draw_enemy_fallback(self, surf: pygame.Surface, e) -> None:
        x, y = self.cam.to_screen(e.x, e.y + e.h)
        w = int(e.w * PIXELS_PER_UNIT)
        h = int(e.h * PIXELS_PER_UNIT)
        col = (200, 60, 60) if e.hit_flash_t > 0 else (168, 168, 172)
        if e.state == "stun":
            col = (120, 120, 200)
        pygame.draw.rect(surf, col, pygame.Rect(x - w // 2, y, w, h), border_radius=4)
        pygame.draw.rect(surf, DARK, pygame.Rect(x - w // 2, y, w, h), 2, border_radius=4)

    # ------------------------------------------------------------------ HUD
    def draw_hud(self, surf, player, energy, judgement, combat, music, elapsed, level) -> None:
        self._bar(surf, 24, 24, 240, 16, player.hp / float(DATA.combat["player_hp"]), RED, "生命")
        self._bar(surf, 24, 54, 240, 16, energy.ratio, GOLD, "鼓劲")
        if energy.full:
            pygame.draw.rect(surf, GOLD, pygame.Rect(22, 52, 244, 20), 2)

        t1 = self.font_m.render(f"槌花 {combat.hit_count}", True, WHITE)
        surf.blit(t1, (SCREEN_W - 40 - t1.get_width(), 24))
        t2 = self.font_m.render(f"用时 {elapsed:5.1f}s / 目标 {level.target_time_s:.0f}s", True, WHITE)
        surf.blit(t2, (SCREEN_W - 40 - t2.get_width(), 52))

        # 板式与合拍连段
        lay = self.font_m.render(f"{music.layer_name}  {music.bpm:.0f} BPM", True, GOLD if music.switch_flashing else WHITE)
        surf.blit(lay, (SCREEN_W - 40 - lay.get_width(), 80))
        st = self.font_m.render(f"合拍连段 {judgement.streak}", True, GOLD if judgement.streak >= 4 else GREY)
        surf.blit(st, (SCREEN_W - 40 - st.get_width(), 108))

        if energy.can_finish(judgement.streak):
            hint = self.font_m.render("满堂彩就绪 — 按 F", True, GOLD)
            surf.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, 92))

        self._draw_beat_strip(surf, music)
        self._draw_judge_circle(surf, music, judgement)

    def _bar(self, surf, x, y, w, h, ratio, color, label) -> None:
        pygame.draw.rect(surf, (40, 40, 44), pygame.Rect(x, y, w, h), border_radius=3)
        pygame.draw.rect(surf, color, pygame.Rect(x, y, int(w * max(0.0, min(1.0, ratio))), h), border_radius=3)
        pygame.draw.rect(surf, (90, 90, 96), pygame.Rect(x, y, w, h), 1, border_radius=3)
        lab = self.font_s.render(label, True, WHITE)
        surf.blit(lab, (x + w + 10, y))

    def _draw_beat_strip(self, surf, music) -> None:
        """小节内 4 拍指示：第 1、3 拍为判定点（描金）。"""
        cx = SCREEN_W // 2
        y = 28
        gap = 46
        b = music.beat_in_bar(music.beat_pos)
        for i in range(DATA.bar_beats):
            x = cx - gap * 1.5 + i * gap
            is_judge = i in DATA.judge_offsets_in_bar
            near = abs(b - i) < 0.5 or abs(b - i - DATA.bar_beats) < 0.5
            r = 13 if is_judge else 9
            col = GOLD if is_judge else DIM
            if near:
                col = WHITE
                r += 3
            pygame.draw.circle(surf, col, (int(x), y), r, 2 if is_judge else 1)
            if is_judge:
                pygame.draw.circle(surf, GOLD, (int(x), y), 3)

    def _draw_judge_circle(self, surf, music, judgement) -> None:
        """锣钹形判定圈：随鼓点收缩，命中时闪反馈色。"""
        b = music.beat_pos
        beat_ms = 60000.0 / music.bpm
        base = int(b)
        cands = [c for c in (base, base + 1, base + 2, base + 3) if c % DATA.bar_beats in DATA.judge_offsets_in_bar]
        nxt = min(cands) if cands else base
        if nxt < b:
            nxt += DATA.bar_beats
        t_to = (nxt - b) * beat_ms / 1000.0
        interval = beat_ms * 2 / 1000.0
        prog = max(0.0, min(1.0, 1.0 - t_to / interval))

        cx, cy = SCREEN_W // 2, int(SCREEN_H * 0.62)
        r_out = 78
        r = int(r_out - (r_out - 26) * prog)
        col = GOLD
        flash = getattr(judgement, "_flash", None)
        if flash and flash[0] > 0:
            col = {"perfect": GOLD, "good": WHITE, "off": ORANGE}.get(flash[1], GOLD)
        pygame.draw.circle(surf, col, (cx, cy), r, 3)
        pygame.draw.circle(surf, DIM, (cx, cy), 22, 2)
        pygame.draw.circle(surf, col, (cx, cy), 8)

        if judgement.last is not None and getattr(judgement, "_flash", None) and judgement._flash[0] > 0:
            txt = {"perfect": "完美合拍", "good": "合拍", "off": "未合拍"}[judgement.last.grade]
            lab = self.font_l.render(txt, True, col)
            surf.blit(lab, (cx - lab.get_width() // 2, cy + 96))

    # ------------------------------------------------------------------ 面板
    def draw_debug_panel(self, surf, lines: list[str], title: str = "判定调试面板") -> None:
        pad = 10
        w = 470
        h = 24 + len(lines) * 20
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 185))
        surf.blit(panel, (16, SCREEN_H - h - 16))
        t = self.font_m.render(title, True, GOLD)
        surf.blit(t, (16 + pad, SCREEN_H - h - 16 + 4))
        for i, ln in enumerate(lines):
            s = self.font_s.render(ln, True, WHITE)
            surf.blit(s, (16 + pad, SCREEN_H - h - 16 + 26 + i * 20))

    def draw_feel_panel(self, surf, rows: list[tuple[str, str]], selected: int) -> None:
        w = 430
        h = 30 + len(rows) * 22
        x = SCREEN_W - w - 16
        y = 140
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 190))
        surf.blit(panel, (x, y))
        t = self.font_m.render("手感参数面板  [↑↓ 选择  ←→ 调整]", True, GOLD)
        surf.blit(t, (x + 10, y + 6))
        for i, (name, val) in enumerate(rows):
            col = WHITE if i == selected else GREY
            mark = "▶" if i == selected else " "
            s = self.font_s.render(f"{mark} {name:<22} {val}", True, col)
            surf.blit(s, (x + 10, y + 32 + i * 22))

    def draw_center_text(self, surf, main: str, sub: str = "", color=WHITE) -> None:
        m = self.font_xl.render(main, True, color)
        surf.blit(m, (SCREEN_W // 2 - m.get_width() // 2, SCREEN_H // 2 - 60))
        if sub:
            s = self.font_m.render(sub, True, GREY)
            surf.blit(s, (SCREEN_W // 2 - s.get_width() // 2, SCREEN_H // 2 + 6))

    def draw_help(self, surf, lines: list[str]) -> None:
        for i, ln in enumerate(lines):
            s = self.font_s.render(ln, True, GREY)
            surf.blit(s, (16, 150 + i * 20))


# ================================================================== Patapon 阵列渲染系统
# 与上方单角色渲染（Renderer）并存，由 config.MODE 切换：PATAPON 模式走 SquadView，
# CLASSIC 模式仍走 Renderer（逐行保留，供回滚对比）。
# 视觉内核复用工程根目录 advanced_squad_renderer.py（沙盒已验证：变阵插值 / 震屏 /
# 火花 / 残影 / 满堂彩 / 铁壁姿态），本类负责装配与阵列 HUD（输入槽 / 横幅 / 进度 / 结算）。
FORMATION_NAMES = {"changshe": "长蛇阵", "tiebi": "铁壁阵", "menghu": "猛虎阵"}
PHASE_NAMES = {"input": "输入·请击鼓", "echo": "应答唱和", "execute": "执行", "luan": "乱阵"}
GRADE_COLORS = {"perfect": (90, 255, 130), "good": (255, 220, 90), "off": (255, 85, 70)}
CMD_HINT = "JJJJ 猛虎下山 · KKKK 长蛇突进 · LLLL 铁壁防守 · KLKL 变阵"
SQUAD_ANCHOR_X = 400            # 队伍锚点屏幕 x（与沙盒 300/960 等比 → 1280 宽）
SQUAD_N = N_UNITS               # 编队人数


class SquadView:
    """Patapon 阵列模式视图层。逻辑状态由 squad.PataponGame 持有，本类只读不写。"""

    def __init__(self) -> None:
        root = app_dir()
        if root not in sys.path:
            sys.path.insert(0, root)
        import advanced_squad_renderer as sr      # 工程根目录的可视化沙盒内核
        self._sr = sr
        self.core = sr.AdvancedSquadRenderer((SCREEN_W, SCREEN_H))
        self.font_s = load_font(16)
        self.font_m = load_font(24)
        self.font_xl = load_font(44)
        self.utypes = ["chui"] * 4 + ["luo"] * 2 + ["dun"] * 2
        self._flash_steps = []                    # 乱阵红闪：预烘焙多级透明度，渲染零 set_alpha
        for i in range(1, 7):
            s = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            s.fill((200, 30, 30, int(105 * i / 6)))
            self._flash_steps.append(s)
        self.reset()

    # ------------------------------------------------------------------ 装配与钩子
    def reset(self) -> None:
        sr = self._sr
        self.formation = "changshe"
        self.lerp = sr.FormationLerp(sr.FORMATION_SLOTS[self.formation](SQUAD_N),
                                     stagger=MORPH_STAGGER, window=MORPH_WINDOW)
        self.scatter = [[0.0, 0.0] for _ in range(SQUAD_N)]
        self.luan_flash = 0.0
        self.hurt_flash = 0.0                   # S5 队伍受击红闪
        self.core.trail = sr.AfterimageTrail()
        self.core.sparks = sr.SparkPool()

    def morph_to_key(self, key: str) -> None:
        self.formation = key
        self.lerp.morph_to(self._sr.FORMATION_SLOTS[key](SQUAD_N))

    def front_x(self) -> float:
        slots = self._sr.FORMATION_SLOTS[self.formation](SQUAD_N)
        return SQUAD_ANCHOR_X + max(x for x, _ in slots) + 46

    def world_sx(self, wx: float, anchor_wx: float) -> float:
        """世界坐标 → 屏幕 x（与渲染器地面刻度同一变换）。"""
        return SQUAD_ANCHOR_X + (wx - anchor_wx) * self._sr.PX_PER_UNIT

    def on_attack(self, x: float, perfect: bool) -> None:
        self.core.on_attack(x, self.core.ground_y - 30, perfect=perfect)

    def on_enemy_hit(self, wx: float, killed: bool, anchor_wx: float) -> None:
        """S5 命中反馈：敌人位置火花；击杀加震屏。"""
        sx = self.world_sx(wx, anchor_wx)
        self.core.sparks.burst(sx, self.core.ground_y - 20,
                               n=14 if killed else 6, color=(255, 120, 90))
        if killed:
            self.core.shake.add(0.35)

    def on_squad_hit(self) -> None:
        """S5 队伍受击：红闪 + 震屏。"""
        self.hurt_flash = 0.5
        self.core.shake.add(0.6)

    def on_boss_break(self, wx: float, ok: bool, anchor_wx: float) -> None:
        """S5 破阵结算：Boss 位置大火花（成功金色 / 失败暗红）。"""
        sx = self.world_sx(wx, anchor_wx)
        self.core.sparks.burst(sx, self.core.ground_y - 60,
                               n=26 if ok else 12,
                               color=(255, 210, 90) if ok else (160, 40, 40))
        self.core.shake.add(0.7 if ok else 0.4)

    def trigger_luan(self) -> None:
        rng = random.Random()
        for s in self.scatter:                    # 散射（draw 中指数衰减归位）
            s[0] = rng.uniform(-30.0, 30.0)
            s[1] = rng.uniform(-22.0, 8.0)
        self.luan_flash = 1.0
        self.core.shake.add(0.85)

    # ------------------------------------------------------------------ 帧绘制
    def draw(self, surf: pygame.Surface, game, dt: float, fps: float = 0.0) -> None:
        self.lerp.now += dt
        damp = math.exp(-6.0 * dt)
        for s in self.scatter:
            s[0] *= damp
            s[1] *= damp
        self.luan_flash = max(0.0, self.luan_flash - dt * 1.4)
        self.hurt_flash = max(0.0, self.hurt_flash - dt * 2.0)

        positions = [(ox + s[0], oy + s[1]) for (ox, oy), s in zip(self.lerp.positions(), self.scatter)]
        idx = list(range(SQUAD_N))
        if game.phase == "luan":                  # 乱阵闪烁：逐帧抽半数单位
            idx = [i for i in idx if (int(self.core.now * 12) + i) % 2 == 0]
        beat = game.beat
        # S5 敌人 / Boss 渲染数据（世界坐标直传，渲染器内部做滚屏变换）
        enemies = [(e.x, e.hp / e.max_hp, min(1.0, e.flash / 0.15))
                   for e in game.enemies if not e.dead]
        boss = None
        if game.boss is not None and not game.boss.dead:
            boss = (game.boss.x, game.boss.hp / game.boss.max_hp, game.boss.state)
        self.core.render(surf,
                         [positions[i] for i in idx], [self.utypes[i] for i in idx],
                         anchor=(SQUAD_ANCHOR_X, self.core.ground_y), beat=beat, bpm=game.bpm,
                         fever=game.fever, dashing=beat < game.stride_until,
                         attack_beat=game.attack_beat, dt=dt,
                         defend=beat < game.defend_until, world_x=game.anchor.x,
                         enemies=enemies, boss=boss)

        if self.luan_flash > 0.0:
            surf.blit(self._flash_steps[min(5, int(self.luan_flash * 6))], (0, 0))
        elif self.hurt_flash > 0.0:
            surf.blit(self._flash_steps[min(5, int(self.hurt_flash * 4))], (0, 0))
        self._draw_hud(surf, game, fps)

    # ------------------------------------------------------------------ 阵列 HUD
    def _draw_hud(self, surf: pygame.Surface, game, fps: float) -> None:
        info = (f"{game.layer_name} {game.bpm:.0f} BPM   阵型 {FORMATION_NAMES[self.formation]}   "
                f"相位 {PHASE_NAMES[game.phase]}   连Perfect {game.perfect_streak}   "
                f"满堂彩 {'ON' if game.fever else 'off'}   FPS {fps:.0f}")
        surf.blit(self.font_s.render(info, True, WHITE), (12, 10))
        surf.blit(self.font_s.render(CMD_HINT + "   [R]重开 [P]暂停 [F3]帮助 [Esc]退出", True, GREY), (12, 32))

        # 赛段进度（世界锚点 → 收阵点）
        prog = max(0.0, min(1.0, game.anchor.x / game.goal_units))
        pygame.draw.rect(surf, (40, 40, 44), pygame.Rect(12, 56, 240, 8), border_radius=3)
        pygame.draw.rect(surf, GOLD, pygame.Rect(12, 56, int(240 * prog), 8), border_radius=3)

        # S5 队伍 HP + 击杀 / 解锁
        hp_ratio = max(0.0, game.squad_hp / 100.0)
        pygame.draw.rect(surf, (40, 36, 40), pygame.Rect(12, 70, 240, 8), border_radius=3)
        pygame.draw.rect(surf, RED, pygame.Rect(12, 70, int(240 * hp_ratio), 8), border_radius=3)
        unlocked_txt = " / ".join(FORMATION_NAMES[f] for f in
                                  ("changshe", "tiebi", "menghu") if f in game.unlocked)
        surf.blit(self.font_s.render(
            f"队伍HP {game.squad_hp:.0f}   击杀 {game.kills}   已解锁 {unlocked_txt}",
            True, GREY), (12, 84))

        # S5 Boss 血条（顶部居中，预警/交战中显示）
        if game.boss is not None and not game.boss.dead and game.boss.state != "idle":
            bw = 420
            bx = SCREEN_W // 2 - bw // 2
            pygame.draw.rect(surf, (40, 36, 40), pygame.Rect(bx, 44, bw, 12), border_radius=4)
            pygame.draw.rect(surf, (200, 50, 40),
                             pygame.Rect(bx, 44, int(bw * game.boss.hp / game.boss.max_hp), 12),
                             border_radius=4)
            t = self.font_s.render("渠魁 · 破阵窗口 = 铁壁阵 + 阵型齐整", True, (255, 160, 140))
            surf.blit(t, t.get_rect(center=(SCREEN_W // 2, 64)))

        # 4 拍输入槽：圈 = 拍点（输入小节随拍相位脉冲），敲入后显示按键 + 评级色
        slots = game.commander.presses if game.phase == "input" else game.hud_presses
        bib = game.beat % DATA.bar_beats
        for i in range(DATA.bar_beats):
            cx = SCREEN_W // 2 - 90 + i * 60
            cy = SCREEN_H - 54
            pulse = max(0.0, 1.0 - abs(bib - i) * 2.0) if game.phase == "input" else 0.0
            pygame.draw.circle(surf, (66, 62, 78), (cx, cy), 16)
            pygame.draw.circle(surf, (240, 210, 120) if pulse > 0.3 else (110, 106, 125),
                               (cx, cy), 16 + int(3 * pulse), 2)
            if i < len(slots):
                k, g, _, _ = slots[i]
                pygame.draw.circle(surf, GRADE_COLORS[g], (cx, cy), 12)
                t = self.font_s.render(k, True, (12, 12, 16))
                surf.blit(t, t.get_rect(center=(cx, cy)))
            else:
                t = self.font_s.render(str(i + 1), True, (96, 92, 110))
                surf.blit(t, t.get_rect(center=(cx, cy)))

        if game.last_grade[1] > 0.0 and game.last_grade[0]:
            col = GRADE_COLORS.get(game.last_grade[0].rstrip("!").lower(), WHITE)
            t = self.font_m.render(game.last_grade[0], True, col)
            surf.blit(t, t.get_rect(center=(SCREEN_W // 2, SCREEN_H - 96)))
        if game.banner[1] > 0.0 and game.banner[0]:
            col = (255, 92, 72) if "乱" in game.banner[0] else (255, 220, 90)
            t = self.font_xl.render(game.banner[0], True, col)
            surf.blit(t, t.get_rect(center=(SCREEN_W // 2, 118)))

        if game.status == "cleared":
            st = game.stats
            total = max(1, st["perfect"] + st["good"] + st["off"])
            self._center(surf, "收 阵", GOLD)
            lines = [f"指令成功 {st['cmd_ok']}   失误 {st['cmd_fail']}   攻击 {st['attacks']}   "
                     f"击杀 {game.kills}   破阵 {st['break_ok']}",
                     f"完美 {st['perfect'] / total * 100:.0f}%   合拍 {st['good'] / total * 100:.0f}%   "
                     f"未合拍 {st['off'] / total * 100:.0f}%",
                     "按 R 重开"]
            for i, ln in enumerate(lines):
                s = self.font_s.render(ln, True, WHITE)
                surf.blit(s, (SCREEN_W // 2 - s.get_width() // 2, SCREEN_H // 2 + 10 + i * 24))
        elif game.status == "defeated":
            st = game.stats
            self._center(surf, "全 军 覆 灭", (255, 92, 72))
            lines = [f"击杀 {game.kills}   破阵 {st['break_ok']}   被破 {st['break_fail']}",
                     "按 R 重开"]
            for i, ln in enumerate(lines):
                s = self.font_s.render(ln, True, WHITE)
                surf.blit(s, (SCREEN_W // 2 - s.get_width() // 2, SCREEN_H // 2 + 10 + i * 24))
        elif game.paused:
            self._center(surf, "暂 停", GREY)
        elif game.show_help:
            for i, ln in enumerate([
                    "J/K/L/S 击鼓：输入小节内连续敲出 4 拍组合并踩准鼓点（±40ms 完美 / ±80ms 合拍）",
                    "JJJJ 猛虎下山 · KKKK 长蛇突进 · LLLL 铁壁防守 · KLKL 变阵；敲错或脱拍会乱阵一小节",
                    "击杀 5 敌解锁铁壁阵、12 敌解锁猛虎阵；长蛇穿透 · 猛虎溅射 · 铁壁减伤免击退",
                    "渠魁拦路时站好【铁壁阵】且阵型齐整才能破阵；连续 2 小节全 PERFECT 触发满堂彩"]):
                s = self.font_s.render(ln, True, GREY)
                surf.blit(s, (16, 150 + i * 20))

    def _center(self, surf: pygame.Surface, text: str, color) -> None:
        t = self.font_xl.render(text, True, color)
        surf.blit(t, (SCREEN_W // 2 - t.get_width() // 2, SCREEN_H // 2 - 60))
