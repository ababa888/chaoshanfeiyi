"""英歌 × Patapon 原型渲染层（第三轮）。

- 素材只读 `prototype-yingge/assets_gen/`（tools/gen_assets.py 生成）。
- 角色动作相位绑定 `game.beat_pos`：同拍起步、行军按拍抬脚。
- 阵型切换按 0.12s 时间常数插值，不再是瞬间跳变。
- Fever：全队染红 + 外发光 + 残影；Boss 公示：图标 + 阵地高亮 + 4 拍进度。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import random

import pygame

import core
import pseudo3d as p3d
from core import (FORMATION_SLOTS, GROUND_SCREEN_Y, INTENTS, INTENT_ORDER,
                  PX_PER_UNIT, SCREEN_BASE_X, SLOPE, face_tier, tint_color,
                  unit_color)
from pixel_font import TIERS as FONT_TIERS
from pixel_font import PixelFont

# 逻辑视口 960×540（内部渲染），整数 2× 放大到 1920×1080 呈现。
# HUD 直接在 960×540 逻辑分辨率下原生排版：不再经过 1280×720 → 0.75 缩放的二次重采样。
VIEW_W, VIEW_H = 960, 540
PRESENT_SCALE = 2
W, H = VIEW_W, VIEW_H

# HUD 原生排版常量。全部为整数；1px 线只允许落在整数坐标，面板/分隔线统一 2px。
HUD_MIN_FONT = 16       # 输出像素最小字号（2× 呈现下 = 逻辑 8px）
HUD_PANEL = (12, 10, 238, 350)          # 左栏
HUD_BOSS_BAR = (290, 46, 380, 16)       # Boss 血条
HUD_READ_PANEL = (252, 74, 456, 92)     # 旧读招面板区域（现仅作补打环锚点，面板已并入谱面带）
# 横向滚动谱面带：四拍一组向右滚动，判定线固定在左 1/4
HUD_RIBBON = (272, 408, 660, 84)        # 谱面带外框
HUD_RIBBON_JUDGE_X = 437                # 判定线（≈ 左 1/4）
HUD_RIBBON_BASE_Y = 486                 # 格子底边
HUD_RIBBON_PITCH = 66                   # 每拍前进格距（整数）
HUD_RIBBON_CELL = 54                    # 格宽（整数）
HUD_RIBBON_CELLS = 8                    # 可见拍数（当前组 4 + 下一组 4）
HUD_RIBBON_STRONG_H = 48                # 强拍格高
HUD_RIBBON_WEAK_H = 34                  # 弱拍格高
HUD_TUTORIAL = (350, 356, 260, 34)      # 一次性教学条（上移，避开谱面带顶部公示文字）
HUD_RECTS = {"panel": HUD_PANEL, "boss_bar": HUD_BOSS_BAR,
             "tutorial": HUD_TUTORIAL, "ribbon": HUD_RIBBON}

# 全部 HUD 动效时长集中在这里（毫秒）；渲染/自测都只读这张表。
# 位移一律用 hud_step_px() 取整到整数像素，缩放只用字号整数跳档，
# 因此不会出现亚像素平移或半透明缩放造成的灰边。
HUD_TIMING = {
    "drum_press_ms": 70,        # 鼓/锣/镲按下下沉（1–2px + 暗一阶）
    "drum_rebound_ms": 110,     # 命中帧回弹（-1px 再落回）
    "drum_breathe_px": 1,       # 未按时随拍呼吸幅度
    "drum_spark_ms": 170,       # 边缘火星存活时长
    "perfect_glint_ms": 120,    # Perfect 金边闪
    "predict_flash_ms": 180,    # 满 4 拍后预测图标实色发亮
    "slot_pending_pulse_ms": 220,   # 待确认槽描边脉冲半周期
    "miss_slash_ms": 420,           # Miss 红斜杠停留
    "hp_ghost_ms": 200,         # 掉血残影
    "hp_low_threshold": 0.25,   # 低血阈值
    "hp_low_pulse_ms": 360,     # 低血边缘脉冲周期
    "gauge_wave_px": 2,         # 鼓劲槽液体波幅
    "gauge_glow_threshold": 0.80,   # 将满发光阈值
    "gauge_burst_ms": 220,      # 满槽涨破
    "combo_stamp_ms": 60,       # 连击敲印（3 帧内压回正常字号）
    "combo_gold_at": 40,        # 40 连以上金边
    "fever_in_ms": 400,         # Fever 进场
    "fever_out_ms": 250,        # Fever 退场
    "break_flash_frames": 3,    # 破阵白闪帧数（硬上限 3）
    "break_seal_ms": 320,       # 破字印章落下
    "result_in_ms": 300,        # 结算面板推入/淡入
    "result_out_ms": 300,       # 结算面板淡出
}

# 指令 → 预测图标：纯色 24×24（48→24 为整数 1/2 缩放）+ 两字短名
COMMAND_SHORT = {"attack": "攻", "march": "行", "defend": "守",
                 "fengshi": "锋矢", "guijia": "龟甲",
                 "shuanglong": "双龙", "menghu": "猛虎"}


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def hud_step_px(total: int, ratio: float) -> int:
    """阶梯式缓动：ease-out 后取整到整数像素（唯一允许的平移动画方式）。"""
    r = _clamp01(ratio)
    eased = 1.0 - (1.0 - r) * (1.0 - r)
    return int(round(eased * total))


def instrument_pose(age_ms: float, beat_pos: float) -> tuple[int, bool]:
    """乐器按压状态 → (整数像素 dy, 是否高亮)。未按时随拍呼吸 1px。

    按下当帧即下沉 1px 并提亮（保证 ≤1 帧可见），半程再落到 2px；
    位移只有 0/1/2 三档整数像素，颜色只有原图/亮一档。
    """
    press = float(HUD_TIMING["drum_press_ms"])
    rebound = float(HUD_TIMING["drum_rebound_ms"])
    breathe = float(HUD_TIMING["drum_breathe_px"])
    if age_ms < 0.0:
        return (-1 if math.sin(math.tau * beat_pos) > 0.35 else 0, False)
    if age_ms < press:
        return (2 if age_ms >= press * 0.5 else 1, True)
    if age_ms < press + rebound:
        mid = (age_ms - press) / rebound
        return (-1 if mid < 0.5 else 0, False)
    phase = math.sin(math.tau * beat_pos)
    return (-int(breathe) if phase > 0.35 else 0, False)


def predict_command(keys: str) -> tuple[str | None, bool]:
    """前三拍返回灰版预测指令；四拍返回实色指令（None=乱令）。"""
    if len(keys) not in (3, 4):
        return (None, False)
    for combo, (cmd, _name) in core.COMMANDS.items():
        hit = combo.startswith(keys) if len(keys) == 3 else combo == keys
        if hit:
            return (cmd, len(keys) == 3)
    return (None, len(keys) == 3)


def ribbon_cell_x(beat: int, beat_pos: float) -> int:
    """谱面格中心 x：判定线 + 整数像素滚动（每拍恰好 HUD_RIBBON_PITCH）。"""
    return HUD_RIBBON_JUDGE_X + int(
        round((beat - beat_pos) * HUD_RIBBON_PITCH))


def gauge_wave_px(now: float, beat_sec: float, x: int = 0) -> int:
    """鼓劲槽液体表面波：幅度 ±2px，相位跟 BPM。"""
    phase = math.tau * (now / max(1e-3, beat_sec)) + x * 0.35
    return int(round(math.sin(phase) * float(HUD_TIMING["gauge_wave_px"])))


def fever_level_step(level: float, active: bool, dt: float) -> float:
    """Fever 边框/压暗的 0..1 过渡；进 0.4s、退 0.25s，不做瞬切。"""
    key = "fever_in_ms" if active else "fever_out_ms"
    dur = max(1.0, float(HUD_TIMING[key])) / 1000.0
    d = max(0.0, float(dt)) / dur
    target = 1.0 if active else 0.0
    nxt = level + d if active else level - d
    if abs(target - nxt) <= d:      # 最后一步贴齐，避免多跑一帧
        return target
    return _clamp01(nxt)


def combo_stamp_size(age_sec: float) -> int:
    """连击敲印：22→16→12px 三档字号替换（像素级，无缩放重采样）。"""
    ms = age_sec * 1000.0
    if ms < HUD_TIMING["combo_stamp_ms"] / 3.0:
        return 22
    if ms < HUD_TIMING["combo_stamp_ms"] * 2.0 / 3.0:
        return 16
    return 12

# 三档真实焦距（Z 循环切换）：投影整体重算，只影响世界层，不动 HUD
ZOOM_ORDER = ("standard", "near", "far")
ZOOM_TRANSITION_SEC = 0.18      # 150–200ms 逐帧整档过渡（无 alpha/无亚像素）
DEFAULT_ZOOM = 1.0
SPRITE_SCALE = 0.75          # 4× 素材 → 逻辑视口内 0.75 倍（保持旧观感并拉远）
HERO_SPRITE_SCALE = 0.625    # 3× 好汉素材（144×192）→ 屏幕约 90×120，沿用旧身高
# 斜俯视 3/4 附加帧（待机/行军/攻击各 3 帧，其余 2 帧）；恒定 1× 不缩放。
TOP_COUNTS = {"idle": 3, "march": 3, "attack": 3, "skill": 3,
              "hurt": 2, "down": 2}

# 三层景深：横向视差系数（越大越靠近镜头），纵向按坡度偏移系数
PARALLAX = {
    "far": {"x": 0.24, "y": 0.30},
    "mid": {"x": 0.70, "y": 1.00},
    "near": {"x": 1.45, "y": 1.00},
}
# 背景地平线改为右上—左下轴（与 V 轴的屏幕斜率同向），近景不参与。
BG_TILT = {"far": -0.145, "mid": -0.070}
# 三段落地配色：林地 / 街市 / 广场。地面逐格填纯色，不贴拉伸纹理。
SEG_PALETTE = {
    "forest": {"a": (84, 82, 52), "b": (74, 72, 46), "edge": (40, 38, 26),
               "near": (52, 45, 32), "near2": (44, 38, 27), "rim": (170, 146, 82),
               "end": (36, 30, 22)},
    "market": {"a": (106, 88, 68), "b": (96, 80, 62), "edge": (50, 40, 30),
               "near": (60, 46, 34), "near2": (52, 40, 30), "rim": (206, 156, 96),
               "end": (42, 32, 26)},
    "plaza": {"a": (122, 110, 92), "b": (112, 100, 84), "edge": (58, 50, 40),
              "near": (68, 56, 44), "near2": (60, 50, 40), "rim": (224, 180, 116),
              "end": (48, 40, 32)},
}
LAYER_ORDER = ("far", "mid", "ground", "enemies", "squad",
               "effects", "near", "hud")
# 远景/中景变体：同一 seed 下按世界平铺序号确定，切换只发生在 960px 平铺边界。
DEFAULT_LAYER_VARIANT_SEED = 20261104
LAYER_VARIANT_COUNT = {"far": 2, "mid": 3, "near": 1}

# ---------------------------------------------------------------- HUD 原生层
# 世界层 960×540 → 整数 ×2；HUD 直接画在 1920×1080 输出层：
# 所有 HUD 代码仍用 960 逻辑坐标，HudSurface 在底层按 HUD_SCALE 落成输出像素，
# 字形/边框/圆角都是整数重画，不再经过「960 排版 → 整屏放大」的重采样。
HUD_SCALE = PRESENT_SCALE
_UPSCALE_CACHE: dict[int, tuple[pygame.Surface, pygame.Surface]] = {}


def _hud_up(src: pygame.Surface, s: int) -> pygame.Surface:
    """逻辑尺寸素材 → 输出像素（nearest，只做整数倍）。"""
    hit = _UPSCALE_CACHE.get(id(src))
    if hit is not None and hit[0] is src:
        return hit[1]
    out = pygame.transform.scale(src, (src.get_width() * s,
                                       src.get_height() * s))
    _UPSCALE_CACHE[id(src)] = (src, out)
    return out


class HudSurface(pygame.Surface):
    """逻辑尺寸（960 空间）与物理尺寸（×HUD_SCALE）分离的 HUD 图层。"""

    def __init__(self, w: int, h: int, flags: int = pygame.SRCALPHA,
                 scale: int = HUD_SCALE) -> None:
        s = max(1, int(scale))
        super().__init__((int(w) * s, int(h) * s), flags)
        self._hud_scale = s
        self._logical_size = (int(w), int(h))

    def get_size(self) -> tuple[int, int]:
        return self._logical_size

    def get_width(self) -> int:
        return self._logical_size[0]

    def get_height(self) -> int:
        return self._logical_size[1]

    def get_rect(self, **kwargs) -> pygame.Rect:
        r = pygame.Rect(0, 0, *self._logical_size)
        for k, v in kwargs.items():
            setattr(r, k, v)
        return r

    def fill(self, color, rect=None, special_flags: int = 0) -> pygame.Rect:
        s = self._hud_scale
        if rect is None:
            return pygame.Surface.fill(self, color, None, special_flags)
        r = pygame.Rect(int(rect[0]) * s, int(rect[1]) * s,
                        int(rect[2]) * s, int(rect[3]) * s)
        return pygame.Surface.fill(self, color, r, special_flags)

    def blit(self, source, dest=(0, 0), area=None, special_flags: int = 0):
        s = self._hud_scale
        dx, dy = int(dest[0]), int(dest[1])
        if isinstance(source, HudSurface):
            return pygame.Surface.blit(self, source, (dx * s, dy * s),
                                       area, special_flags)
        if area is not None:
            area = pygame.Rect(area[0] * s, area[1] * s,
                               area[2] * s, area[3] * s)
        return pygame.Surface.blit(self, _hud_up(source, s),
                                   (dx * s, dy * s), area, special_flags)


class _ScaledDraw:
    """pygame.draw 代理：对 HudSurface 的参数按 HUD_SCALE 放大。"""

    def __init__(self, real) -> None:
        object.__setattr__(self, "_real", real)

    def _s(self, surf) -> int:
        return getattr(surf, "_hud_scale", 1) if isinstance(surf, HudSurface) else 1

    @staticmethod
    def _rect(rect, s):
        return pygame.Rect(int(rect[0]) * s, int(rect[1]) * s,
                           int(rect[2]) * s, int(rect[3]) * s)

    @staticmethod
    def _pts(points, s):
        return [(int(p[0]) * s, int(p[1]) * s) for p in points]

    def rect(self, surf, color, rect, width=0, **kw):
        s = self._s(surf)
        if s == 1:
            return self._real.rect(surf, color, rect, width, **kw)
        return self._real.rect(surf, color, self._rect(rect, s),
                               width * s if width else 0, **kw)

    def line(self, surf, color, start, end, width=1):
        s = self._s(surf)
        if s == 1:
            return self._real.line(surf, color, start, end, width)
        return self._real.line(surf, color,
                               (int(start[0]) * s, int(start[1]) * s),
                               (int(end[0]) * s, int(end[1]) * s),
                               width * s)

    def circle(self, surf, color, center, radius, width=0, **kw):
        s = self._s(surf)
        if s == 1:
            return self._real.circle(surf, color, center, radius, width, **kw)
        return self._real.circle(surf, color,
                                 (int(center[0]) * s, int(center[1]) * s),
                                 radius * s, width * s if width else 0, **kw)

    def polygon(self, surf, color, points, width=0):
        s = self._s(surf)
        if s == 1:
            return self._real.polygon(surf, color, points, width)
        return self._real.polygon(surf, color, self._pts(points, s),
                                  width * s if width else 0)

    def ellipse(self, surf, color, rect, width=0):
        s = self._s(surf)
        if s == 1:
            return self._real.ellipse(surf, color, rect, width)
        return self._real.ellipse(surf, color, self._rect(rect, s),
                                  width * s if width else 0)

    def arc(self, surf, color, rect, start_angle, stop_angle, width=1):
        s = self._s(surf)
        if s == 1:
            return self._real.arc(surf, color, rect, start_angle, stop_angle,
                                  width)
        return self._real.arc(surf, color, self._rect(rect, s), start_angle,
                              stop_angle, width * s)

    def lines(self, surf, color, closed, points, width=1):
        s = self._s(surf)
        if s == 1:
            return self._real.lines(surf, color, closed, points, width)
        return self._real.lines(surf, color, closed, self._pts(points, s),
                                width * s)

    def aaline(self, surf, color, start, end, blend=1):
        s = self._s(surf)
        if s == 1:
            return self._real.aaline(surf, color, start, end, blend)
        return self._real.aaline(surf, color,
                                 (int(start[0]) * s, int(start[1]) * s),
                                 (int(end[0]) * s, int(end[1]) * s), blend)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_real"), name)


@contextlib.contextmanager
def hud_draw_scale():
    """在 HUD 构建期间把 pygame.draw 换成按层缩放的代理。"""
    real = pygame.draw
    pygame.draw = _ScaledDraw(real)
    try:
        yield
    finally:
        pygame.draw = real

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSET_ROOT = os.path.join(ROOT, "assets_gen")

PLAYER_FRAMES = ("idle_0", "idle_1", "march_0", "march_1",
                 "attack_0", "attack_1", "hurt_0", "down_0")
ENEMY_FRAMES = ("idle_0", "idle_1", "march_0", "march_1",
                "attack_0", "attack_1", "hurt_0", "down_0")
BOSS_FRAMES = ("idle_0", "idle_1", "telegraph_0", "attack_0",
               "roar_0", "hurt_0", "down_0")

TIER_TINTS = [tint_color(i) for i in range(6)]
FEVER_TINT = core.fever_tint()
GOLD = (238, 186, 88)
AMBER = (255, 216, 122)
CREAM = (255, 240, 206)
INK = (18, 14, 20)
RED = (184, 44, 40)
MUTED = (196, 176, 152)

INTENT_COLORS = {
    "slam": (255, 96, 64),
    "sweep": (255, 160, 60),
    "charge": (255, 110, 90),
    "grab": (200, 120, 255),
    "roar": (255, 200, 80),
}


def _path(*parts: str) -> str:
    return os.path.join(ASSET_ROOT, *parts)


def _load(path: str) -> pygame.Surface:
    try:
        return pygame.image.load(path).convert_alpha()
    except Exception:
        s = pygame.Surface((24, 32), pygame.SRCALPHA)
        s.fill((230, 120, 80))
        return s


def _tint(surf: pygame.Surface, color: tuple[int, int, int]) -> pygame.Surface:
    if color == (255, 255, 255):
        return surf
    out = surf.copy()
    out.fill(color, special_flags=pygame.BLEND_RGB_MULT)
    return out


def _additive(surf: pygame.Surface, color: tuple[int, int, int]) -> pygame.Surface:
    out = surf.copy()
    out.fill(color, special_flags=pygame.BLEND_RGB_ADD)
    return out


def _alpha(surf: pygame.Surface, a: int) -> pygame.Surface:
    out = surf.copy()
    out.set_alpha(a)
    return out


def _gray(surf: pygame.Surface) -> pygame.Surface:
    """灰版图标：只改 RGB，保留 0/255 alpha（不做任何插值）。"""
    out = surf.copy()
    for y in range(out.get_height()):
        for x in range(out.get_width()):
            r, g, b, a = out.get_at((x, y))
            if a:
                v = (r * 3 + g * 6 + b) // 10
                out.set_at((x, y), (v, v, v, a))
    return out


def _make_gong(size: int = 48) -> pygame.Surface:
    """无抗锯齿现画一面锣（青铜同心圆），坐标/半径全为整数。"""
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size // 2
    pygame.draw.circle(s, (20, 14, 12), (c, c), c - 1)
    pygame.draw.circle(s, (112, 74, 36), (c, c), c - 3)
    pygame.draw.circle(s, (188, 138, 66), (c, c), c - 6)
    pygame.draw.circle(s, (224, 176, 96), (c, c), c - 9)
    pygame.draw.circle(s, (146, 98, 46), (c, c), c - 14, 2)
    pygame.draw.circle(s, (92, 62, 30), (c, c), c - 19)
    pygame.draw.circle(s, (255, 226, 160), (c, c), 2)
    return s


FontBook = PixelFont


class AssetBank:
    """assets_gen 素材库；脸谱梯度与 Fever 红脸在启动期一次烘焙。"""

    def __init__(self) -> None:
        self.players: dict[str, dict[str, pygame.Surface]] = {}
        self.player_tint: dict[int, dict[str, dict[str, pygame.Surface]]] = {
            tier: {} for tier in range(6)
        }
        self.player_fever: dict[str, dict[str, pygame.Surface]] = {}
        for kind in ("shield", "drummer", "spear"):
            frames = {s: _load(_path("players", kind, s + ".png"))
                      for s in PLAYER_FRAMES}
            self.players[kind] = frames
            for tier in range(6):
                color = TIER_TINTS[tier]
                self.player_tint[tier][kind] = {
                    s: _tint(img, color) for s, img in frames.items()
                }
            self.player_fever[kind] = {
                s: _tint(img, FEVER_TINT) for s, img in frames.items()
            }
        self.player_ghost = {
            kind: _alpha(frames["march_0"], 74)
            for kind, frames in self.players.items()
        }

        # 水浒好汉帧库（48×64 base → 144×192）
        self.heroes: dict[str, dict[str, pygame.Surface]] = {}
        self.hero_fever: dict[str, dict[str, pygame.Surface]] = {}
        self.hero_top: dict[str, dict[str, pygame.Surface]] = {}
        self.hero_top_fever: dict[str, dict[str, pygame.Surface]] = {}
        for hid, spec in core.HEROES.items():
            frames = {}
            for state, fspec in spec["frames"].items():
                for i in range(int(fspec["count"])):
                    frames[f"{state}_{i}"] = _load(
                        _path("sprites", hid, f"{hid}_{state}_{i}.png"))
            self.heroes[hid] = frames
            self.hero_fever[hid] = {
                s: _tint(img, FEVER_TINT) for s, img in frames.items()
            }
            top = {}
            for state, count in TOP_COUNTS.items():
                for i in range(count):
                    top[f"{state}_{i}"] = _load(
                        _path("sprites", hid, f"top_{state}_{i}.png"))
            self.hero_top[hid] = top
            self.hero_top_fever[hid] = {
                s: _tint(img, FEVER_TINT) for s, img in top.items()
            }
        self.hero_for_kind = dict(core.HERO_FOR_KIND)
        self.portraits = {
            hid: _load(_path("portraits", f"{hid}.png"))
            for hid in core.HEROES
        }
        self.lineup = _load(_path("portraits", "lineup.png"))

        self.enemies: dict[str, dict[str, pygame.Surface]] = {}
        for kind in ("grunt", "brute"):
            self.enemies[kind] = {s: pygame.transform.flip(
                _load(_path("enemies", kind, s + ".png")), True, False)
                for s in ENEMY_FRAMES}
        self.boss = {s: _load(_path("boss", "drumking", s + ".png"))
                     for s in BOSS_FRAMES}

        # 96×96 素材按整数 2:1 缩到 48×48，保持像素硬边
        self.drum = pygame.transform.scale(_load(_path("ui", "drum.png")), (48, 48))
        self.cymbal = pygame.transform.scale(_load(_path("ui", "cymbal.png")),
                                             (48, 48))
        # 锣：素材库没有独立图，用无抗锯齿圆环现画（alpha 只 0/255）
        self.gong = _make_gong(48)
        # J/K/L → 鼓/锣/镲；24×24 为整数 1/2 缩放，暗版只做一次
        self.instrument = {"J": self.drum, "K": self.gong, "L": self.cymbal}
        self.instrument24 = {
            k: pygame.transform.scale(img, (24, 24))
            for k, img in self.instrument.items()
        }
        self.instrument_lit = {
            k: _additive(img, (44, 34, 22))    # 亮一档：按下当帧可见，alpha 不变
            for k, img in self.instrument24.items()
        }
        # 第十九轮新手引导重绘素材（gen_assets 输出 2× 整数像素，绘制按逻辑尺寸）
        self.guide_drum = _load(_path("ui", "guide_drum.png"))
        self.guide_gong = _load(_path("ui", "guide_gong.png"))
        self.guide_cymbal = _load(_path("ui", "guide_cymbal.png"))
        self.guide_ribbon = _load(_path("ui", "guide_ribbon.png"))
        self.guide_stamp = _load(_path("ui", "guide_stamp.png"))
        self.guide_boss = _load(_path("ui", "guide_boss.png"))
        # 指令预测图标：48×48 原图 → 24×24（整数 1/2）
        cmd_src = {
            "attack": self.drum, "march": self.gong, "defend": self.cymbal,
            "fengshi": _load(_path("ui", "form_fengshi.png")),
            "guijia": _load(_path("ui", "form_guijia.png")),
            "shuanglong": _load(_path("ui", "form_shuanglong.png")),
            "menghu": _load(_path("ui", "form_menghu.png")),
        }
        self.command_icon = {
            k: pygame.transform.scale(img, (24, 24))
            for k, img in cmd_src.items()
        }
        self.command_ghost = {k: _gray(img) for k, img in self.command_icon.items()}
        self.role = {
            kind: pygame.transform.scale(
                self.portraits[self.hero_for_kind[kind]].subsurface(
                    (86, 28, 96, 96)).copy(), (24, 24))
            for kind in ("drummer", "shield", "spear")
        }
        self.intent_icon = {k: _load(_path("ui", f"intent_{k}.png"))
                            for k in INTENT_ORDER}
        self.phase_icon = {i: _load(_path("ui", f"phase_{i}.png"))
                           for i in (1, 2, 3)}
        self.counter_mark = pygame.transform.scale(
            _load(_path("ui", "counter_mark.png")), (48, 48))
        self.form_icon = {k: pygame.transform.scale(
            _load(_path("ui", f"form_{k}.png")), (26, 26))
            for k in FORMATION_SLOTS}
        self.lantern = _load(_path("props", "lantern.png"))
        self.ground = _load(_path("environment", "ground.png"))
        self.far = _load(_path("environment", "far.png"))
        # 三层景深（gen_assets 生成的无缝平铺图）；远/中各带多套变体
        def _layer_file(name: str) -> pygame.Surface | None:
            p = _path("environment", name)
            return _load(p) if os.path.exists(p) else None

        self.layer_variants: dict[str, list[pygame.Surface]] = {
            "far": [s for s in (_layer_file("far_sky.png"),
                                _layer_file("far_sky_1.png")) if s],
            "mid": [s for s in (_layer_file("mid_street.png"),
                                _layer_file("mid_street_1.png"),
                                _layer_file("mid_street_2.png")) if s],
            "near": [s for s in (_layer_file("near_fg.png"),) if s],
        }
        self.layers: dict[str, pygame.Surface] = {}
        for key, variants in self.layer_variants.items():
            if variants:
                self.layers[key] = variants[0]
            else:
                self.layers[key] = self.far if key == "far" else \
                    pygame.Surface((VIEW_W, 40), pygame.SRCALPHA)

        self.enemy_flash = {k: {s: _additive(img, (150, 40, 10))
                                for s, img in frames.items()}
                            for k, frames in self.enemies.items()}
        self.boss_flash = _additive(self.boss["idle_0"], (180, 50, 10))

        # ---- 纵深档位预烘图（运行时只挑档、不 resize）
        self.band_manifest: dict = {}
        self.hero_bands: dict[str, dict[int, dict[str, pygame.Surface]]] = {}
        self.hero_band_fever: dict[str, dict[int, dict[str, pygame.Surface]]] = {}
        self.enemy_bands: dict[str, dict[int, dict[str, pygame.Surface]]] = {}
        self.enemy_band_flash: dict[str, dict[int, dict[str, pygame.Surface]]] = {}
        self.boss_bands: dict[int, dict[str, pygame.Surface]] = {}
        self.prop_bands: dict[int, dict[str, pygame.Surface]] = {}
        self.shadow_bands: dict[int, tuple[pygame.Surface, int, int]] = {}
        self._load_bands()

    # ------------------------------------------------------------------ 档位素材
    def _load_bands(self) -> None:
        """读 assets_gen/bands/b0..b6；缺图时各绘制点退回基图（仅启动期缩一次）。"""
        try:
            with open(_path("manifest.json"), "r", encoding="utf-8") as f:
                self.band_manifest = json.load(f).get("bands") or {}
        except Exception:
            self.band_manifest = {}
        count = int(self.band_manifest.get("count", p3d.BAND_COUNT))
        if count != p3d.BAND_COUNT:
            return
        for b in range(count):
            bd = _path("bands", f"b{b}")
            sprites_dir = os.path.join(bd, "sprites")
            if os.path.isdir(sprites_dir):
                for hid in sorted(os.listdir(sprites_dir)):
                    src = os.path.join(sprites_dir, hid)
                    if not os.path.isdir(src):
                        continue
                    self.hero_bands.setdefault(hid, {})[b] = {
                        name[:-4]: _load(os.path.join(src, name))
                        for name in sorted(os.listdir(src)) if name.endswith(".png")
                    }
            enemies_dir = os.path.join(bd, "enemies")
            if os.path.isdir(enemies_dir):
                for kind in sorted(os.listdir(enemies_dir)):
                    src = os.path.join(enemies_dir, kind)
                    if not os.path.isdir(src):
                        continue
                    self.enemy_bands.setdefault(kind, {})[b] = {
                        name[:-4]: pygame.transform.flip(
                            _load(os.path.join(src, name)), True, False)
                        for name in sorted(os.listdir(src)) if name.endswith(".png")
                    }
            boss_dir = os.path.join(bd, "boss", "drumking")
            if os.path.isdir(boss_dir):
                self.boss_bands[b] = {
                    name[:-4]: _load(os.path.join(boss_dir, name))
                    for name in sorted(os.listdir(boss_dir)) if name.endswith(".png")
                }
            props_dir = os.path.join(bd, "props")
            if os.path.isdir(props_dir):
                self.prop_bands[b] = {
                    name[:-4]: _load(os.path.join(props_dir, name))
                    for name in sorted(os.listdir(props_dir)) if name.endswith(".png")
                }
            sh_path = os.path.join(bd, "fx", "shadow.png")
            if os.path.exists(sh_path):
                dx, dy, _w, _h = p3d.shadow_rect(p3d.band_center(b))
                self.shadow_bands[b] = (_load(sh_path), dx, dy)
        for hid, bands in self.hero_bands.items():
            self.hero_band_fever[hid] = {
                b: {s: _tint(img, FEVER_TINT) for s, img in frames.items()}
                for b, frames in bands.items()
            }
        for kind, bands in self.enemy_bands.items():
            self.enemy_band_flash[kind] = {
                b: {s: _additive(img, (150, 40, 10)) for s, img in frames.items()}
                for b, frames in bands.items()
            }



class Renderer:
    def __init__(self, input_map=None) -> None:
        self.fonts = FontBook()
        self.bank = AssetBank()
        self.input_map = input_map
        self.hud_scale = HUD_SCALE
        self.hud_ui: pygame.Surface | None = None
        self.hud_fx: pygame.Surface | None = None
        self._panel_cache: dict[tuple, pygame.Surface] = {}
        self._hud_arena: dict[tuple[int, int, int], list[HudSurface]] = {}
        self._hud_arena_i: dict[tuple[int, int, int], int] = {}
        self._hud_reuse = False
        self.cam_x = 0.0
        self.cam_dip = 0.0
        self.zoom = DEFAULT_ZOOM
        # 焦距状态：zoom 只是 v=0 行的屏幕增益，档位选择一律按 p3d.band_index
        self.focal = p3d.ZOOM_FOCALS["standard"]
        self.focal_target = self.focal
        self.zoom_from = self.focal
        self._zoom_t = 0.0
        self.zoom_index = 0
        p3d.set_focal(self.focal)
        self.parallax_debug = 0       # 位掩码：1=隐藏远、2=隐藏中、4=隐藏近
        self.debug_persp = os.environ.get("DRUMBEAT_PERSPECTIVE_DEBUG") == "1"
        self.layer_variant_seed = DEFAULT_LAYER_VARIANT_SEED
        self._layer_variant_now: dict[str, tuple[int, int]] = {}
        self.near_occludes = False    # 近景是否遮住我方（截图/自测用）
        self._img_cache: dict[tuple[int, float], pygame.Surface] = {}
        self.trail: list[tuple[float, list[tuple[str, int, int]]]] = []
        self.slot_pos = [list(p) for p in FORMATION_SLOTS["changshe"]]
        self._squad_bob = 0.0
        self.dust: list[list] = []
        self.last_beat = -1
        self.bg_static = self._build_sky()
        self.shadow = pygame.Surface((104, 24), pygame.SRCALPHA)
        pygame.draw.ellipse(self.shadow, (0, 0, 0, 96), self.shadow.get_rect())
        self.small_shadow = pygame.Surface((66, 16), pygame.SRCALPHA)
        pygame.draw.ellipse(self.small_shadow, (0, 0, 0, 80),
                            self.small_shadow.get_rect())
        self.hero_shadow = pygame.Surface((118, 22), pygame.SRCALPHA)
        pygame.draw.ellipse(self.hero_shadow, (0, 0, 0, 96),
                            self.hero_shadow.get_rect())
        # ---- HUD 动效状态（全部在 draw() 里按 dt 推进，规则见 HUD_TIMING）
        self._fever_level = 0.0
        self._fever_prev = False
        self._gauge_burst_t = 99.0
        self._hp_state: list[dict] = []
        self._combo_last = -1
        self._combo_t = 99.0
        self._stagger_seen = -1
        self._seal_t = 99.0
        self._flash_frames = 0
        self._result_mode = ""          # "" / in / hold / out
        self._result_kind = ""
        self._result_t = 0.0
        self._result_last = "playing"

    def hit_effect_reset(self) -> None:
        self.trail.clear()
        self.dust.clear()

    # ------------------------------------------------------------------ 背景
    def _build_sky(self) -> pygame.Surface:
        bg = pygame.Surface((VIEW_W, VIEW_H)).convert()
        top = (24, 16, 40)
        bottom = (108, 42, 38)
        for y in range(bg.get_height()):
            k = y / bg.get_height()
            c = (int(top[0] * (1 - k) + bottom[0] * k),
                 int(top[1] * (1 - k) + bottom[1] * k),
                 int(top[2] * (1 - k) + bottom[2] * k))
            pygame.draw.line(bg, c, (0, y), (VIEW_W, y))
        rng = random.Random(7)
        for _ in range(80):
            x = rng.randint(0, VIEW_W)
            y = rng.randint(0, 230)
            pygame.draw.circle(bg, (210, 196, 168), (x, y), rng.choice((1, 1, 2)))
        pygame.draw.circle(bg, (232, 210, 160), (900, 52), 28)
        pygame.draw.circle(bg, (242, 224, 180), (907, 48), 7)
        return bg

    def _camera(self, game: core.Game, dt: float) -> None:
        """前视相机：朝行进方向多看 3.4–4.6 单位；下坡越快看得越远。"""
        k = min(1.0, dt * float(core.CAMERA["follow_k"]))
        streak = max(0.0, float(getattr(game.squad, "march_streak", 0)))
        lead = p3d.CAM_LEAD_MIN + 1.2 * min(1.0, streak / 6.0)
        if game.boss_active:
            lead = min(lead, 3.4)
        target = game.squad.x + lead
        self.cam_x += (target - self.cam_x) * k
        map_len = float(getattr(game, "map_len", 148.0))
        hi = max(0.0, map_len - p3d.CAM_END_MARGIN)
        self.cam_x = max(0.0, min(hi, self.cam_x))
        self.cam_dip = 0.0

    def world_px(self, zoom: float | None = None) -> float:
        """中性行逻辑像素/世界单位（v=0）。"""
        return p3d.KX

    def visible_units(self, zoom: float | None = None) -> float:
        """可视世界宽度（世界单位），供 README/自测统一引用。"""
        return VIEW_W / self.world_px(zoom)

    def sprite_scale(self, zoom: float | None = None) -> float:
        z = self.zoom if zoom is None else zoom
        return SPRITE_SCALE * z

    def hero_scale(self, zoom: float | None = None) -> float:
        z = self.zoom if zoom is None else zoom
        return HERO_SPRITE_SCALE * z

    def hud_pos(self, x: float, y: float) -> tuple[int, int]:
        """HUD 原生逻辑坐标（960×540），绘制前统一取整；与缩放档无关。"""
        return (int(round(x)), int(round(y)))

    def _scaled_world(self, img: pygame.Surface, base: float) -> pygame.Surface:
        """世界层贴图按 base×zoom 做 nearest 缩放并缓存（像素不糊）。"""
        s = base * self.zoom
        key = (id(img), s)
        out = self._img_cache.get(key)
        if out is None:
            nw = max(1, int(round(img.get_width() * s)))
            nh = max(1, int(round(img.get_height() * s)))
            out = pygame.transform.scale(img, (nw, nh))
            self._img_cache[key] = out
        return out

    def _wimg(self, img: pygame.Surface) -> pygame.Surface:
        return self._scaled_world(img, SPRITE_SCALE)

    def _himg(self, img: pygame.Surface) -> pygame.Surface:
        return self._scaled_world(img, HERO_SPRITE_SCALE)

    # ---- 纵深档位：只挑图，不缩放
    def band_for(self, v: float) -> int:
        """纵深 v → 预烘档号；档位表已按最终屏幕缩放（含焦距增益）分档。"""
        return p3d.band_index(v)

    def zoom_name(self) -> str:
        return ZOOM_ORDER[self.zoom_index]

    def cycle_zoom(self) -> str:
        """Z 键：标准 → 推近 → 拉远；投影参数逐帧重算，贴图只换档不 resize。"""
        self.zoom_index = (self.zoom_index + 1) % len(ZOOM_ORDER)
        self.zoom_from = self.focal
        self.focal_target = p3d.ZOOM_FOCALS[ZOOM_ORDER[self.zoom_index]]
        self._zoom_t = 0.0
        return ZOOM_ORDER[self.zoom_index]

    def _step_zoom(self, dt: float) -> bool:
        """150–200ms 线性过渡到目标焦距；每帧只按整档选图。"""
        if abs(self.focal - self.focal_target) <= 1e-9:
            return False
        self._zoom_t += max(0.0, float(dt))
        k = min(1.0, self._zoom_t / ZOOM_TRANSITION_SEC)
        self.focal = self.zoom_from + (self.focal_target - self.zoom_from) * k
        if k >= 1.0:
            self.focal = self.focal_target
        p3d.set_focal(self.focal)
        self.zoom = p3d.ZOOM_GAIN
        return True

    def band_scale(self, v: float) -> float:
        return p3d.band_scale(self.band_for(v))

    def hero_band_img(self, hero: str, v: float, state: str,
                      fever: bool = False) -> pygame.Surface:
        b = self.band_for(v)
        table = (self.bank.hero_band_fever if fever
                 else self.bank.hero_bands).get(hero, {})
        frames = table.get(b)
        if frames:
            if state in frames:
                return frames[state]
            if f"top_{state}" in frames:     # 预烘文件保留 top_ 前缀
                return frames[f"top_{state}"]
        return self._himg(self.bank.hero_top[hero].get(state,
                         self.bank.hero_top[hero]["idle_0"]))

    def enemy_band_img(self, kind: str, v: float, state: str,
                       flash: bool = False) -> pygame.Surface:
        b = self.band_for(v)
        table = (self.bank.enemy_band_flash if flash
                 else self.bank.enemy_bands).get(kind, {})
        frames = table.get(b)
        if frames and state in frames:
            return frames[state]
        src = self.bank.enemies[kind].get(state, self.bank.enemies[kind]["idle_0"])
        return self._wimg(src)

    def boss_band_img(self, v: float, state: str) -> pygame.Surface:
        b = self.band_for(v)
        frames = self.bank.boss_bands.get(b)
        if frames and state in frames:
            return frames[state]
        return self._wimg(self.bank.boss.get(state, self.bank.boss["idle_0"]))

    def _gy(self, px: float) -> float:
        """坡面中线（v=0）的屏幕 y（含镜头下压）。"""
        return p3d.VPY + p3d.Y_SPAN + self.cam_dip

    def _squad_px(self, game: core.Game) -> float:
        return p3d.u_to_screen_x(game.squad.x, 0.0, self.cam_x)

    def _enemy_px(self, game: core.Game, e: core.Enemy) -> float:
        return p3d.u_to_screen_x(e.x, e.v, self.cam_x)

    def _blit_tilted(self, surf: pygame.Surface, img: pygame.Surface,
                     deg: float, ax: float, ay: float) -> None:
        """绕贴图底边中点旋转后贴图：脚底锚点严格留在 (ax, ay) 的坡面上。"""
        if abs(deg) < 0.35:
            surf.blit(img, (int(ax) - img.get_width() // 2,
                            int(ay) - img.get_height()))
            return
        rot = pygame.transform.rotate(img, -float(deg))
        px, py, _rw, _rh = core.tilt_blit_pivot(
            img.get_width(), img.get_height(), float(deg))
        surf.blit(rot, (int(ax - px), int(ay - py)))


    def _draw_shadow(self, surf: pygame.Surface, sx: int, sy: int,
                     v: float = 0.0) -> None:
        """预烘阴影按档贴图：方向固定左下，近档长、远档短，不做 resize。"""
        b = self.band_for(v)
        entry = self.bank.shadow_bands.get(b)
        if entry is not None:
            img, dx, dy = entry
            surf.blit(img, (int(sx) - img.get_width() // 2 + dx,
                            int(sy) - img.get_height() // 2 + dy))
            return
        dx, dy, w, h = p3d.shadow_rect(v)
        pts = [(sx - w // 2 + dx, sy - h // 2 + dy),
               (sx + w // 2 + dx, sy - h // 2 + dy),
               (sx + w // 2 + dx, sy + h // 2 + dy),
               (sx - w // 2 + dx, sy + h // 2 + dy)]
        pygame.draw.polygon(surf, (52, 34, 30), pts)
        pygame.draw.polygon(surf, (92, 64, 46), pts, 1)

    def _update_formation(self, game: core.Game, dt: float) -> None:
        target = FORMATION_SLOTS[game.formation]
        k = 1.0 - math.exp(-dt / 0.10)
        for i, (tx, ty) in enumerate(target):
            if i >= len(self.slot_pos):
                self.slot_pos.append([tx, ty])
                continue
            self.slot_pos[i][0] += (tx - self.slot_pos[i][0]) * k
            self.slot_pos[i][1] += (ty - self.slot_pos[i][1]) * k

    # ------------------------------------------------------------------ 背景（三层景深）
    def _layer_off(self, factor: float) -> int:
        return int(self.cam_x * self.world_px() * factor)

    def _layer_variant(self, key: str, tile: int) -> tuple[pygame.Surface, int]:
        """世界平铺序号 → (变体图, 变体编号)。同 seed 同 tile 恒定，可复现。"""
        variants = self.bank.layer_variants.get(key) or [self.bank.layers[key]]
        if len(variants) <= 1:
            return variants[0], 0
        h = hashlib.sha1(
            f"{self.layer_variant_seed}:{key}:{int(tile)}".encode("utf-8")
        ).digest()
        idx = int.from_bytes(h[:4], "big") % len(variants)
        return variants[idx], idx

    def layer_spans(self, key: str, off: int, width: int | None = None
                    ) -> list[tuple[int, int, int, int, int]]:
        """把屏幕横向切成 (x, 宽, tile, tile 内偏移, 变体号)。

        段宽 ≤48 且不跨平铺边界：变体只可能在段与段之间切换。
        """
        variants = self.bank.layer_variants.get(key) or [self.bank.layers[key]]
        iw = variants[0].get_width()
        width = VIEW_W if width is None else int(width)
        spans: list[tuple[int, int, int, int, int]] = []
        x = 0
        while x < width:
            s = off + x
            tile = s // iw          # Python // 对负数向下取整，等价世界坐标
            local = int(s - tile * iw)
            seg = min(48, iw - local, width - x)
            _img, vi = self._layer_variant(key, tile)
            spans.append((x, seg, int(tile), local, vi))
            x += seg
        return spans

    def _draw_layer(self, surf: pygame.Surface, key: str, base_y: float,
                    sw: int = 48) -> None:
        """按视差横向滚动 + 按坡度纵向偏移，按 960px 平铺换变体整层平铺。"""
        if self.parallax_debug & {"far": 1, "mid": 2, "near": 4}[key]:
            self._layer_variant_now.pop(key, None)
            return
        variants = self.bank.layer_variants.get(key) or [self.bank.layers[key]]
        iw, ih = variants[0].get_size()
        p = PARALLAX[key]
        off = self._layer_off(p["x"])
        tilt = BG_TILT.get(key, 0.0)
        for x, seg, _tile, local, _vi in self.layer_spans(key, off, VIEW_W):
            img, _ = self._layer_variant(key, _tile)
            py = int(base_y + (x - SCREEN_BASE_X) * tilt * p["y"])
            surf.blit(img, (x, py), (local, 0, seg, ih))
        # 记录屏幕中心所在平铺的变体号，供 parallax_debug 标注
        mid_x = off + VIEW_W // 2
        _img, vi = self._layer_variant(key, mid_x // iw)
        self._layer_variant_now[key] = (vi, mid_x // iw)

    def _draw_far(self, surf: pygame.Surface, game: core.Game,
                  now: float) -> None:
        surf.blit(self.bg_static, (0, 0))
        if game.fever_active:
            warm = pygame.Surface((VIEW_W, int(GROUND_SCREEN_Y)), pygame.SRCALPHA)
            a = int(26 + 18 * math.sin(now * 8))
            warm.fill((255, 120, 40, max(0, a)))
            surf.blit(warm, (0, 0))
        # 远山/海平线：低饱和，横向 0.24、纵向 0.30 视差
        self._draw_layer(surf, "far", 64.0 + self.cam_dip * 0.30)

    def _draw_mid(self, surf: pygame.Surface, game: core.Game,
                  now: float) -> None:
        # 骑楼街景/屋脊剪影：贴在坡面上方，底部被地面盖住，不会悬空
        img = self.bank.layers["mid"]
        base_y = self._gy(SCREEN_BASE_X) - img.get_height() + 14.0
        self._draw_layer(surf, "mid", base_y)

    def _uv_poly(self, pts_uv, cam_x=None) -> list[tuple[int, int]]:
        return p3d.project_uv(
            pts_uv, self.cam_x if cam_x is None else cam_x, self.cam_dip)

    def _seg_palette(self, u: float) -> dict:
        seg = core.segment_at(u) if hasattr(core, "segment_at") else None
        key = (seg or {}).get("palette", "market")
        return SEG_PALETTE.get(key, SEG_PALETTE["market"])

    def _draw_ground(self, surf: pygame.Surface, game: core.Game,
                     now: float) -> None:
        """单点透视地形：逐格四边形 + 近侧厚边 + 坡底截面 + 远侧薄唇。

        长图按可视范围剔除：每一行 v 只遍历该行屏幕内的 u，绝不一次性画满 148 单位。
        """
        cam, dip = self.cam_x, self.cam_dip
        u0 = float(getattr(game, "map_u0", -12.0))
        u1 = float(getattr(game, "map_len", 148.0))
        th = int(p3d.SLAB["thickness_px"])
        v_near, v_far = p3d.V_NEAR, p3d.V_FAR
        step = p3d.CELL_U
        band_v = p3d.CELL_V
        rows = int(round((v_far - v_near) / band_v))

        na, nb = p3d.visible_u_range(v_near, cam, pad=24.0)
        na, nb = max(u0, na), min(u1, nb)
        if nb <= na:
            na, nb = u0, min(u1, u0 + step)
        p0 = p3d.world_to_screen(na, v_near, cam, dip)
        p1 = p3d.world_to_screen(nb, v_near, cam, dip)

        # 坡面以下：近黑虚空 + 棱柱落地暗影，读起来是“一块抬起的实心坡”。
        pygame.draw.polygon(surf, (13, 9, 14),
                            [p0, p1, (VIEW_W, VIEW_H), (0, VIEW_H)])
        pygame.draw.polygon(surf, (7, 5, 9),
                            [(p0[0], p0[1] + th), (p1[0], p1[1] + th),
                             (p1[0], p1[1] + th + 12),
                             (p0[0], p0[1] + th + 12)])

        # 顶面：逐格四边形。每个 v 行按自己的可见 u 范围裁剪，近大远小自然收敛。
        draw_cells = 0
        for row in range(rows):
            v0 = v_near + row * band_v
            v1 = v0 + band_v
            r0, r1 = p3d.visible_u_range((v0 + v1) * 0.5, cam, pad=12.0)
            r0 = max(u0, math.floor(r0 / step) * step)
            r1 = min(u1, math.ceil(r1 / step) * step)
            u = r0
            while u < r1:
                u_next = min(u + step, u1)
                quad = p3d.cell_quad(u, u_next, v0, v1, cam, dip)
                pal = self._seg_palette((u + u_next) * 0.5)
                xy = int(u / step) + row
                col = pal["a"] if xy % 2 == 0 else pal["b"]
                pygame.draw.polygon(surf, col, quad)
                pygame.draw.line(surf, pal["edge"], quad[3], quad[2], 1)
                pygame.draw.line(surf, pal["edge"], quad[0], quad[3], 1)
                draw_cells += 1
                u = u_next
        self.ground_cells = draw_cells

        # 远侧薄唇：顶面后沿的一线暗边，压住背景，提示坡面有厚度。
        fa, fb = p3d.visible_u_range(v_far, cam, pad=12.0)
        fa, fb = max(u0, fa), min(u1, fb)
        if fb > fa:
            lip = p3d.slab_far_lip(cam, dip, u0=fa, u1=fb)
            pygame.draw.polygon(surf, (54, 38, 32), lip)
            a = p3d.world_to_screen(fa, v_far, cam, dip)
            b = p3d.world_to_screen(fb, v_far, cam, dip)
            pygame.draw.line(surf, (134, 94, 62), a, b, 2)

        # 近侧厚边：砖石块面 + 竖缝/横缝；块面交替明暗，读得出厚度。
        u = na
        while u < nb:
            a = p3d.world_to_screen(u, v_near, cam, dip)
            b = p3d.world_to_screen(min(u + step, nb), v_near, cam, dip)
            pal = self._seg_palette(u)
            tone = pal["near"] if int(u / step) % 2 == 0 else pal["near2"]
            pygame.draw.polygon(surf, tone,
                                [a, b, (b[0], b[1] + th),
                                 (a[0], a[1] + th)])
            pygame.draw.line(surf, (27, 17, 16), a, (a[0], a[1] + th), 2)
            u += step
        for k in (0.34, 0.67):
            y = int(th * k)
            pygame.draw.line(surf, (30, 20, 18),
                             (p0[0], p0[1] + y), (p1[0], p1[1] + y), 1)
        rim = self._seg_palette((na + nb) * 0.5)["rim"]
        pygame.draw.line(surf, rim, p0, p1, 2)
        pygame.draw.line(surf, (8, 6, 9),
                         (p0[0], p0[1] + th), (p1[0], p1[1] + th), 3)

        # 坡底截面（u=map_len）：顶边高光 + 砖缝 + 底沿深色；随相机进出画面。
        end = p3d.slab_end_side(u1, cam, dip)
        if -60 <= end[0][0] <= VIEW_W + 60 or -60 <= end[1][0] <= VIEW_W + 60:
            pal = self._seg_palette(u1 - 0.1)
            pygame.draw.polygon(surf, pal["end"], end)
            pygame.draw.line(surf, pal["rim"], end[0], end[1], 2)
            for k in range(1, 4):
                y0 = end[0][1] + th * k // 4
                y1 = end[1][1] + th * k // 4
                pygame.draw.line(surf, (28, 18, 17),
                                 (end[0][0], y0), (end[1][0], y1), 1)
            pygame.draw.line(surf, (8, 6, 9), end[2], end[3], 3)

        # 坡沿随拍微亮：只叠在近棱线上，不改变几何。
        pulse = 0.0
        if game.clock.started:
            frac = game.beat_in_cycle
            pulse = math.exp(-frac * 6.0) if frac >= 0 else 0.0
        col = (min(255, int(206 + 30 * pulse)), int(150 + 30 * pulse),
               int(94 + 24 * pulse))
        pygame.draw.line(surf, col, p0, p1, 1)

        # 碎石/草丛：确定性世界坐标，只画当前可视 u。
        ga, gb = p3d.visible_u_range(0.0, cam, pad=40.0)
        for i in range(14):
            gu = math.floor(ga / 4.0) * 4.0 + i * 3.7
            if gu > gb:
                break
            for lane in (v_near + 0.7, v_near + 2.4, 0.4):
                gx, gy = p3d.world_to_screen(gu + (i % 3) * 0.4, lane, cam, dip)
                if not (-20 <= gx <= VIEW_W + 20):
                    continue
                pygame.draw.line(surf, (74, 110, 58), (gx, gy),
                                 (gx - 3, gy - 7), 2)
                pygame.draw.line(surf, (96, 136, 70), (gx + 2, gy),
                                 (gx + 4, gy - 9), 2)
                pygame.draw.rect(surf, (52, 40, 32), (gx + 7, gy - 2, 4, 3))


    def _draw_formation_marks(self, surf: pygame.Surface,
                              game: core.Game) -> None:
        """在斜面上画出阵型足迹：谁在前、谁在后，一眼可读。"""
        slots = self.slot_pos
        pts = [p3d.world_to_screen(game.squad.x + du, dv, self.cam_x,
                                   self.cam_dip) for du, dv in slots]
        # 连接线（队列的骨架）
        for a, b in zip(pts, pts[1:]):
            pygame.draw.line(surf, (60, 42, 32), a, b, 1)
        # 每个槽位的脚印菱形
        for x, y in pts:
            pygame.draw.polygon(surf, (78, 52, 38),
                                [(x, y - 4), (x + 9, y), (x, y + 5),
                                 (x - 9, y)])
            pygame.draw.line(surf, (150, 106, 70), (x - 9, y), (x, y + 5), 1)
        if game.formation == "guijia":
            # 3×3 方阵足迹：亮格线 + 两个空角，读得出“方阵”而不只是三人
            cu = game.squad.x + 0.05
            cv = 0.0
            cell = 1.10
            for i in range(-1, 2):
                for j in range(-1, 2):
                    c = [(cu + i * cell, cv + j * cell),
                         (cu + (i + 1) * cell, cv + j * cell),
                         (cu + (i + 1) * cell, cv + (j + 1) * cell),
                         (cu + i * cell, cv + (j + 1) * cell)]
                    shade = (74, 51, 38) if (i + j) % 2 else (64, 44, 33)
                    pygame.draw.polygon(surf, shade, self._uv_poly(c))
                    pygame.draw.polygon(surf, (140, 100, 66),
                                        self._uv_poly(c), 1)
            for dv in (-1.65, 1.65):
                ex, ey = p3d.world_to_screen(cu - 1.65, dv, self.cam_x,
                                             self.cam_dip)
                pygame.draw.polygon(surf, (58, 40, 30),
                                    [(ex, ey - 4), (ex + 9, ey), (ex, ey + 5),
                                     (ex - 9, ey)], 1)

    def _draw_near(self, surf: pygame.Surface, game: core.Game) -> None:
        """近景草丛/石栏/人物剪影：画在角色与特效之上，制造纵深遮挡。"""
        img = self.bank.layers["near"]
        base_y = self._gy(SCREEN_BASE_X) - img.get_height() + 42.0
        self._draw_layer(surf, "near", base_y)
        if self.parallax_debug & 4:
            self.near_occludes = False
        else:
            self.near_occludes = self._near_covers(game, base_y)

    def _near_covers(self, game: core.Game, base_y: float) -> bool:
        """采样近景 alpha，判断当前帧前景是否真的压住了我方。"""
        img = self.bank.layers["near"]
        iw, ih = img.get_size()
        off = self._layer_off(PARALLAX["near"]["x"]) % iw
        cx = self._squad_px(game)
        feet = self._gy(cx)
        for dx, dy in ((-30, -26), (0, -26), (0, -44), (32, -64),
                       (-12, -80), (44, -20)):
            x = cx + dx
            if not (0 <= x < VIEW_W):
                continue
            sx = (off + x) % iw
            py = base_y + (x - SCREEN_BASE_X) * SLOPE * PARALLAX["near"]["y"]
            iy = int(feet + dy - py)
            if 0 <= iy < ih and img.get_at((int(sx), iy))[3] > 110:
                return True
        return False

    def _draw_lanterns(self, surf: pygame.Surface, game: core.Game,
                       now: float, base_y: float) -> None:
        impulse = 0.0
        if game.clock.started:
            impulse = math.exp(-(max(0.0, game.beat_in_cycle)) * 5.0)
        img = self._wimg(self.bank.lantern)
        off = self._layer_off(PARALLAX["mid"]["x"])
        for i in range(5):
            base_x = (700 + i * 176 - off) % (VIEW_W + 240) - 120
            sway = math.sin(now * 2.2 + i * 1.6) * 4.0
            sway += math.sin(now * 8.0 + i) * 2.0 * impulse
            x = int(base_x + sway)
            if x < -60 or x > VIEW_W + 60:
                continue
            ly = int(base_y + 112 + (i % 2) * 20 +
                     (x - SCREEN_BASE_X) * BG_TILT["mid"] *
                     PARALLAX["mid"]["y"])
            pygame.draw.line(surf, (52, 32, 26), (base_x, 0), (x, ly + 4), 2)
            surf.blit(img, (x - img.get_width() // 2, ly))
            glow = pygame.Surface((64, 64), pygame.SRCALPHA)
            a = int(30 + 34 * impulse)
            pygame.draw.circle(glow, (255, 150, 60, a), (32, 32), 30)
            surf.blit(glow, (x - 32, ly + 8))

    # ------------------------------------------------------------------ 队伍
    def _march_phase(self, game: core.Game) -> float:
        frac = game.beat_in_cycle
        if frac < 0:
            frac = 0
        return frac % 1.0

    def _hero_state(self, hero: str, u: core.Unit, game: core.Game,
                    now: float, idx: int) -> str:
        if u.down or u.hp <= 0:
            return "down_1" if u.down_t > 0.2 else "down_0"
        if u.hurt_flash > 0:
            return "hurt_0" if u.hurt_flash > 0.18 else "hurt_1"
        if game.squad.attack_anim > 0:
            prog = 1.0 - game.squad.attack_anim / 0.45
            state, fi = core.hero_attack_frame(hero, prog)
            return f"{state}_{fi}"
        if game.defending:
            return "idle_0"
        if game.squad.walking:
            # 6 帧行军跨两拍：第 1 拍 0–2，第 2 拍 3–5，落脚对齐鼓点
            phase = self._march_phase(game)
            step = (game.beat_index % 2) * 0.5 + phase * 0.5
            return f"march_{int(step * 6) % 6}"
        # 4 帧待机：2s 一循环，三位错峰呼吸
        return f"idle_{int(now * 2.0 + idx * 0.45) % 4}"

    def _unit_pose(self, game: core.Game, i: int,
                   extra_u: float = 0.0) -> tuple[int, int, float]:
        """单位在 (u,v) 上的落点：整数屏幕坐标 + 深度 v。"""
        du, dv = self.slot_pos[i] if i < len(self.slot_pos) else (0.0, 0.0)
        sx, sy = p3d.world_to_screen(game.squad.x + du + extra_u, dv,
                                    self.cam_x, self.cam_dip)
        return (sx, sy, dv)

    def _unit_positions(self, game: core.Game) -> list[tuple[core.Unit, float, float, float]]:
        out = []
        for i, u in enumerate(game.squad.units):
            sx, sy, dv = self._unit_pose(game, i)
            out.append((u, float(sx), float(sy), dv))
        return out

    def _top_state(self, state: str) -> str:
        """把 4/6 帧状态压到俯视 3/4 的 2–3 帧（保持像素级帧替换）。"""
        base, _, tail = state.rpartition("_")
        if not base or not tail.isdigit():
            return state
        count = TOP_COUNTS.get(base)
        if not count:
            return state
        return f"{base}_{min(int(tail), count - 1)}"

    def _prepare_squad(self, surf: pygame.Surface, game: core.Game,
                       now: float) -> list[tuple[core.Unit, float, float, float]]:
        py_pulse = self._march_phase(game)
        bob = 0.0
        if game.squad.walking:
            bob = -abs(math.sin(py_pulse * math.pi)) * 2.6
        elif game.squad.walking is False and not game.defending:
            bob = math.sin(now * 1.8) * 0.8
        self._squad_bob = bob

        if game.squad.walking:
            self._spawn_dust(game, now)
        self._update_dust()

        poses = self._unit_positions(game)
        mid = sorted(poses, key=lambda p: p[1])[len(poses) // 2]
        game.squad_focus = (mid[1], mid[2])

        # 急停刹车痕：沿 (u,v) 斜面的两条擦痕
        if game.squad.brake_t > 0:
            a = min(1.0, game.squad.brake_t / 0.62)
            front = max(poses, key=lambda t: t[1])
            fx0, fy0 = int(front[1]), int(front[2])
            skid = pygame.Surface((70, 16), pygame.SRCALPHA)
            pygame.draw.polygon(skid, (26, 16, 14, int(150 * a)),
                                [(0, 8), (66, 2), (70, 7), (2, 14)])
            surf.blit(skid, (fx0 - 46, fy0 - 6))
        return poses

    def _all_actors(self, game: core.Game) -> list[tuple[float, float, str, object]]:
        """统一收集我方/敌人/Boss，按 v 从远到近排序（同 v 再按 u 倒序）。"""
        actors: list[tuple[float, float, str, object]] = []
        for i, u in enumerate(game.squad.units):
            du, dv = self.slot_pos[i] if i < len(self.slot_pos) else (0.0, 0.0)
            actors.append((dv, game.squad.x + du, "unit", (i, u)))
        for e in game.enemies:
            actors.append((e.v, e.x, "dead" if e.dead else "enemy", e))
        boss = game.boss
        if boss is not None and boss.active:
            actors.append((boss.v, boss.platform_x, "boss", boss))
        for prop in self._visible_props(game):
            actors.append((prop[1], prop[0], "prop", prop))
        actors.sort(key=lambda a: (-a[0], -a[1]))
        return actors

    # ------------------------------------------------------------- 世界道具（循环+变体）
    @staticmethod
    def _variant(u: float, n: int) -> int:
        h = hashlib.sha1(f"{int(round(u * 10))}:{n}".encode("utf-8")).digest()
        return int.from_bytes(h[:4], "big") % max(1, n)

    def _visible_props(self, game: core.Game) -> list[tuple[float, float, str, int, int]]:
        """按可视 u 范围生成命名道具（图块循环 + 变体），全部走预烘档位图。"""
        cam = self.cam_x
        a, b = p3d.visible_u_range(3.0, cam, pad=140.0)
        out: list[tuple[float, float, str, int, int]] = []
        mile_step = float(getattr(game, "mile_every", 10.0)) or 10.0
        for si, seg in enumerate(getattr(game, "segments", [])):
            u0 = float(seg.get("u0", 0.0))
            u1 = float(seg.get("u1", 0.0))
            lo, hi = max(u0, a), min(u1, b)
            pal = str(seg.get("palette", "market"))
            if hi > lo:
                # 灯笼：中景挂灯，鼓点整像素上下振动
                dens = float(seg.get("lantern_density", 0.7))
                sp = max(2.4, 5.2 / max(0.2, dens))
                u = math.ceil(lo / sp) * sp
                while u < hi:
                    out.append((u, 4.7, "lantern", self._variant(u, 3), si))
                    u += sp
                if pal == "forest":
                    # 后排林带（角色可遮树干）+ 前排近树（树冠可遮角色）
                    for pv, psp, off in ((5.0, 7.4, 1.0), (-4.4, 15.0, 4.0)):
                        u = math.ceil(lo / psp) * psp + off
                        while u < hi:
                            out.append((u, pv, "tree_0",
                                        self._variant(u + off, 3), si))
                            u += psp
                else:
                    # 街市/广场：旗阵分远、近两排
                    for pv, psp, off in ((5.0, 6.5, 2.0), (-4.6, 9.0, 3.5)):
                        u = math.ceil(lo / psp) * psp + off
                        while u < hi:
                            out.append((u, pv, "flag_0",
                                        self._variant(u + off, 2), si))
                            u += psp
            gate_u = u0
            if a - 8.0 <= gate_u <= b + 8.0:
                out.append((gate_u, 0.6, f"gate_{pal}", si, si))
        u = math.ceil(max(0.0, a) / mile_step) * mile_step
        top = min(b, float(getattr(game, "map_len", 148.0)))
        while u <= top:
            out.append((u, -5.35, "mile_0", int(round(u / mile_step)), -1))
            u += mile_step
        return [p for p in out if p3d.is_visible(p[0], p[1], cam, pad=90.0)]

    @staticmethod
    def _prop_vib(game: core.Game, amp: int) -> int:
        """鼓点振动：整张贴图按整数像素上下位移（同档幅度一致）。"""
        if not getattr(game.clock, "started", False):
            return 0
        return int(round(float(amp) * math.sin(math.tau * game.beat_pos)))

    def _draw_prop(self, surf: pygame.Surface, game: core.Game,
                   prop: tuple[float, float, str, int, int], now: float) -> None:
        u, v, kind, _variant, _si = prop
        sx, sy = p3d.world_to_screen(u, v, self.cam_x, self.cam_dip)
        if not (-100 <= sx <= VIEW_W + 100):
            return
        b = self.band_for(v)
        img = self.bank.prop_bands.get(b, {}).get(kind)
        vib = 0
        if kind == "flag_0":
            vib = self._prop_vib(game, 2)
        elif kind == "lantern":
            vib = self._prop_vib(game, 1)
        elif kind == "mile_0":
            vib = self._prop_vib(game, 1)
        if img is None:
            col = {"tree_0": (64, 90, 50), "flag_0": (168, 52, 44),
                   "lantern": (196, 58, 44), "mile_0": (146, 132, 108)}
            c = col.get(kind, (120, 96, 72))
            pygame.draw.rect(surf, c, (sx - 6, sy - 40, 12, 40))
            return
        if kind in ("tree_0", "flag_0", "mile_0"):
            self._draw_shadow(surf, sx, sy, v)
        w, h = img.get_size()
        if kind == "lantern":
            bs = p3d.band_scale(b)
            pygame.draw.line(surf, (58, 38, 28),
                             (sx, sy - int(14 * bs)), (sx, sy - int(34 * bs)), 1)
            pygame.draw.circle(surf, (255, 206, 120),
                               (sx, sy - int(10 * bs) + vib), 3)
            surf.blit(img, (sx - w // 2, sy - h - int(6 * bs) + vib))
            return
        surf.blit(img, (sx - w // 2, sy - h + vib))

    def _draw_actors(self, surf: pygame.Surface, game: core.Game,
                     now: float) -> None:
        poses = self._prepare_squad(surf, game, now)
        lunge_u = 0.0
        if game.squad.attack_anim > 0:
            lunge_u = math.sin(math.pi * (1.0 - game.squad.attack_anim / 0.45)) \
                * 0.45
        s = self.hero_scale()
        charging = game.squad.walking and game.squad.march_streak >= 2
        for dv, du, kind, ref in self._all_actors(game):
            if kind == "unit":
                i, u = ref
                extra_u = lunge_u
                if u.down or u.hp <= 0:
                    extra_u += core.down_roll_offset(u.down_t) / core.PX_PER_UNIT
                px, py, _ = self._unit_pose(game, i, extra_u)
                hero = self.bank.hero_for_kind[u.kind]
                state = self._top_state(self._hero_state(hero, u, game, now, i))
                img = self.hero_band_img(hero, dv, state, game.fever_active)
                x = int(px)
                y = int(py + 4 + self._squad_bob)
                if not p3d.on_screen(x, y, img.get_width(), img.get_height(),
                                     pad=32):
                    continue
                self._draw_shadow(surf, px, py, dv)
                if game.fever_active:
                    glow = pygame.Surface((int(150 * s), int(190 * s),
                                           ), pygame.SRCALPHA)
                    a = int(60 + 24 * math.sin(now * 10 + i))
                    pygame.draw.ellipse(glow, (255, 120, 60, a), glow.get_rect())
                    surf.blit(glow, (x - glow.get_width() // 2,
                                     y - img.get_height() + int(8 * s)))
                if charging and u.hp > 0:
                    sl = pygame.Surface((int(54 * s), int(44 * s)),
                                        pygame.SRCALPHA)
                    a = int(50 + 40 * math.sin(now * 12 + i))
                    pygame.draw.line(sl, (255, 210, 140, a),
                                     (int(6 * s), int(10 * s)),
                                     (int(52 * s), int(34 * s)), 2)
                    pygame.draw.line(sl, (255, 190, 120, a // 2),
                                     (int(10 * s), int(22 * s)),
                                     (int(50 * s), int(40 * s)), 2)
                    surf.blit(sl, (x - int(26 * s),
                                   y - img.get_height() + int(30 * s)))
                # 恒定 1× 贴图，不旋转、不缩放；脚底严格落在整数投影点
                surf.blit(img, (x - img.get_width() // 2, y - img.get_height()))
                if game.defending:
                    r = int((46 + 3 * math.sin(now * 10)) * s)
                    pygame.draw.arc(surf, (120, 210, 255),
                                    (x - r, y - int(100 * s), r * 2, int(70 * s)),
                                    -1.1, 1.1, 4)
                if state.startswith("skill"):
                    pygame.draw.circle(surf, (255, 240, 170),
                                       (x + int(50 * s), y - int(112 * s)),
                                       int(10 * s))
                    pygame.draw.circle(surf, (255, 150, 70),
                                       (x + int(50 * s), y - int(112 * s)),
                                       int(16 * s), 2)
            elif kind == "enemy":
                self._draw_one_enemy(surf, game, ref, now)
            elif kind == "dead":
                self._draw_dead_enemy(surf, game, ref)
            elif kind == "boss":
                self._draw_one_boss(surf, game, ref, now)
            elif kind == "prop":
                self._draw_prop(surf, game, ref, now)
        self._draw_hero_peak(surf, game, poses, now)

    def _draw_hero_peak(self, surf: pygame.Surface, game: core.Game,
                        poses, now: float) -> None:
        hero, life = game.hero_peak
        if not hero or life <= 0:
            return
        match = [p for p in poses if self.bank.hero_for_kind[p[0].kind] == hero]
        if not match:
            return
        _u, px, py, dv = match[0]
        game.peak_focus = (px, py)
        k = max(0.0, min(1.0, life / 0.55))
        label = core.HERO_SKILLS.get(hero, "")
        name = core.HERO_NAMES.get(hero, "")
        idx = min(core.hero_peak_index(hero, "skill"),
                  TOP_COUNTS["skill"] - 1)
        peak = self.hero_band_img(hero, dv, f"skill_{idx}")
        # 整数倍放大：只允许 1× / 2×，避免非整数重采样产生灰边
        mode = 2 if k > 0.5 else 1
        big = pygame.transform.scale(
            peak, (peak.get_width() * mode, peak.get_height() * mode))
        bx = int(px - big.get_width() // 2)
        by = int(py + 4 - big.get_height())
        # 聚焦暗角：压暗周围队友/敌人，让峰值技能帧读得出来
        vig = pygame.Surface((300, 300), pygame.SRCALPHA)
        for rr in range(148, 36, -8):
            a = int(62 * k * (rr - 36) / 112)
            pygame.draw.circle(vig, (8, 4, 8, a), (150, 150), rr)
        surf.blit(vig, (int(px) - 150, int(py) - 70 - 150))
        # 放大特效：金色底环 + 三圈冲击环 + 技能名，不压暗角色本体
        if k > 0.55:
            halo = pygame.Surface((big.get_width() + 36,
                                   big.get_height() + 36), pygame.SRCALPHA)
            pygame.draw.ellipse(halo, (255, 226, 150, int(70 * (k - 0.55))),
                                halo.get_rect())
            surf.blit(halo, (bx - 18, by - 18))
        surf.blit(big, (bx, by))
        r = int((40 + 90 * (1.0 - k)))
        for j, col in enumerate(((255, 240, 170), (255, 160, 80),
                                 (255, 90, 60))):
            rr = r - j * 12
            if rr > 4:
                pygame.draw.circle(surf, col, (int(px), int(py) - 70),
                                   rr, 3)
        ly = by - 20
        plate = pygame.Surface((260, 40), pygame.SRCALPHA)
        plate.fill((30, 10, 8, int(150 * k)))
        surf.blit(plate, (int(px) - 130, ly - 12))
        self.fonts.text(surf, f"{name} · {label}", 26, (255, 240, 180),
                        (int(px), ly), center=True, bold=True,
                        outline=(60, 10, 8), alpha=int(255 * k))

    def _spawn_dust(self, game: core.Game, now: float) -> None:
        bi = game.beat_index
        if bi == self.last_beat:
            return
        self.last_beat = bi
        if not game.squad.walking:
            return
        phase0 = self._march_phase(game)
        if phase0 > 0.5:
            return
        front = max((p for p in self._unit_positions(game)), key=lambda t: t[1])
        n = 3 + min(3, game.squad.march_streak // 2)
        for _ in range(n):
            self.dust.append([front[1] - 10 + random.uniform(-16, 10),
                              front[2] - 2 + random.uniform(-3, 3),
                              random.uniform(-18, -4), random.uniform(-26, -8),
                              random.uniform(0.3, 0.6), 0.6])

    def _update_dust(self) -> None:
        for p in self.dust:
            p[0] += p[2] * 0.20
            p[1] += p[3] * 0.20
            p[4] -= 0.20
        self.dust = [p for p in self.dust if p[4] > 0]

    def _draw_dust(self, surf: pygame.Surface) -> None:
        for x, y, _vx, _vy, life, maxlife in self.dust:
            a = int(90 * max(0.0, life / maxlife))
            g = pygame.Surface((26, 16), pygame.SRCALPHA)
            pygame.draw.ellipse(g, (206, 178, 128, a), g.get_rect())
            surf.blit(g, (int(x) - 13, int(y) - 8))

    # ------------------------------------------------------------------ 敌人
    def _draw_persp_debug(self, surf: pygame.Surface, game: core.Game) -> None:
        """透视调试：消失点、地平线、10 档边界与对象头顶档位号。"""
        if not self.debug_persp:
            return
        cam = self.cam_x
        cyan, mag = (0, 236, 255), (255, 64, 214)
        hy = p3d.horizon_y()
        pygame.draw.line(surf, mag, (0, hy), (VIEW_W, hy), 1)
        vx, vy = p3d.vp_point()
        pygame.draw.line(surf, cyan, (vx - 8, vy), (vx + 8, vy), 1)
        pygame.draw.line(surf, cyan, (vx, vy - 8), (vx, vy + 8), 1)
        for row in range(p3d.BAND_COUNT):
            v0, v1 = p3d.band_v_bounds(row)
            for v, col in ((v0, cyan), (v1, mag)):
                ua, ub = p3d.visible_u_range(v, cam, pad=8.0)
                a = p3d.world_to_screen(ua, v, cam, self.cam_dip)
                b = p3d.world_to_screen(ub, v, cam, self.cam_dip)
                pygame.draw.line(surf, col, a, b, 1)
            vc = p3d.band_v_center(row)
            ul, _ur = p3d.visible_u_range(vc, cam, pad=0.0)
            lx, ly = p3d.world_to_screen(ul, vc, cam, self.cam_dip)
            self.fonts.text(surf, f"b{row} ×{p3d.band_scale(row):.2f}", 10,
                            cyan, (lx + 4, ly - 12), bold=True,
                            outline=(8, 10, 20))
        for i, u in enumerate(getattr(game.squad, "units", [])):
            du, dv = self.slot_pos[i] if i < len(self.slot_pos) else (0.0, 0.0)
            sx, sy = p3d.world_to_screen(game.squad.x + du, dv, cam,
                                        self.cam_dip)
            self.fonts.text(surf, f"b{self.band_for(dv)}", 10, cyan,
                            (sx, sy - int(130 * p3d.band_scale(self.band_for(dv)))),
                            center=True, bold=True, outline=(8, 10, 20))
        for e in getattr(game, "enemies", []):
            sx, sy = self._enemy_pose(game, e)
            self.fonts.text(surf, f"b{self.band_for(e.v)}", 10, mag,
                            (sx, sy - int(130 * p3d.band_scale(self.band_for(e.v)))),
                            center=True, bold=True, outline=(8, 10, 20))
        boss = game.boss
        if boss is not None and boss.active:
            sx, sy = p3d.world_to_screen(boss.platform_x, boss.v, cam,
                                        self.cam_dip)
            top_y = sy - int(getattr(boss, "platform_h", 34))
            self.fonts.text(surf, f"b{self.band_for(boss.v)}", 10, mag,
                            (sx, top_y - int(190 * p3d.band_scale(self.band_for(boss.v)))),
                            center=True, bold=True, outline=(8, 10, 20))

    def _draw_segment_card(self, surf: pygame.Surface, game: core.Game) -> None:
        """段落入口卡：段名 / 坡度 / 推荐阵法 / BPM + 极简路线。"""
        segs = getattr(game, "segments", None)
        entry = getattr(game, "segment_entry", None)
        if not segs or not entry:
            return
        try:
            idx = int(entry[0])
            remaining = float(entry[1])
        except (TypeError, ValueError, IndexError):
            return
        if remaining <= 0:
            return
        seg = segs[idx] if 0 <= idx < len(segs) else None
        if seg is None:
            seg = next((s for s in segs
                        if int(s.get("index", -1)) == idx), None)
        if not seg:
            return
        w, h = 216, 84
        x, y = VIEW_W - w - 10, 10
        card = self._hs(w, h)
        card.fill((26, 18, 16, 224))
        pygame.draw.rect(card, (218, 164, 96), card.get_rect(), 1)
        self.fonts.text(card, str(seg.get("name", "")), 12, (255, 232, 178),
                        (10, 8), bold=True, outline=(50, 18, 10))
        self.fonts.text(card, f"坡度 {float(seg.get('slope_deg', 0)):.0f}°",
                        8, (220, 214, 196), (10, 26))
        rec = str(seg.get("recommend", ""))
        rec = core.FORMATIONS.get(rec, {}).get("name", rec)
        self.fonts.text(card, f"推荐 {rec}", 8, (220, 214, 196), (10, 38))
        bpm = int(round(float(seg.get("bpm", 0))))
        self.fonts.text(card, f"BPM {bpm}", 8, (220, 214, 196), (10, 50))
        # 极简路线：全段横向直线 + 3 个刻度 + 当前段高亮
        total0 = float(segs[0].get("u0", 0.0))
        total1 = float(segs[-1].get("u1", total0 + 1.0))
        span = max(1e-3, total1 - total0)
        lx, rx, ry = 12, w - 12, h - 12
        pygame.draw.line(card, (96, 82, 70), (lx, ry), (rx, ry), 1)
        a = lx + int(round((rx - lx) * _clamp01(
            (float(seg.get("u0", total0)) - total0) / span)))
        b = lx + int(round((rx - lx) * _clamp01(
            (float(seg.get("u1", total1)) - total0) / span)))
        pygame.draw.line(card, (238, 186, 88), (a, ry), (max(a, b), ry), 2)
        for t in (0.25, 0.5, 0.75):
            tx = lx + int(round((rx - lx) * t))
            pygame.draw.rect(card, (210, 184, 130), (tx - 1, ry - 2, 3, 5))
        card.set_alpha(255 if remaining >= 0.5 else max(0, int(255 * remaining / 0.5)))
        surf.blit(card, (x, y))

    def _draw_enemies(self, surf: pygame.Surface, game: core.Game) -> None:
        # 该方法的旧入口保留为空壳；实际绘制走 _draw_actors 的深度排序循环。
        return

    def _enemy_pose(self, game: core.Game, e: core.Enemy,
                    extra_u: float = 0.0) -> tuple[int, int]:
        return p3d.world_to_screen(e.x + extra_u, e.v,
                                   self.cam_x, self.cam_dip)

    def _draw_one_enemy(self, surf: pygame.Surface, game: core.Game,
                        e: core.Enemy, now: float) -> None:
        px, py = self._enemy_pose(game, e)
        frames = self.bank.enemies[e.kind]
        if e.attack_anim > 0:
            state = "attack_1" if (game.now * 18) % 2 > 1 else "attack_0"
        elif e.flash > 0.12:
            state = "hurt_0"
        elif abs(e.x - (game.squad.x + e.standoff)) > 0.1:
            state = "march_1" if game.beat_index % 2 == 0 else "march_0"
        else:
            state = "idle_1" if (game.now * 2.2) % 2 > 1 else "idle_0"
        img = self.enemy_band_img(e.kind, e.v, state)
        if not p3d.on_screen(px, py + 4, img.get_width(), img.get_height(),
                             pad=32):
            return
        s = self.band_scale(e.v)
        self._draw_shadow(surf, px, py, e.v)
        surf.blit(img, (px - img.get_width() // 2, py + 4 - img.get_height()))
        if e.flash > 0:
            f = self.enemy_band_img(e.kind, e.v, state, flash=True)
            f.set_alpha(int(160 * min(1.0, e.flash / 0.22)))
            surf.blit(f, (px - f.get_width() // 2,
                          py + 4 - f.get_height()))
            f.set_alpha(255)
        self._draw_enemy_bar(surf, e, px, py - int(132 * s))
        if e.attack_anim > 0:
            self.fonts.text(surf, "!", 24, (255, 90, 70),
                            (px, py - int(152 * s)),
                            center=True, bold=True, outline=(30, 0, 0))

    def _draw_dead_enemy(self, surf: pygame.Surface, game: core.Game,
                         e: core.Enemy) -> None:
        roll_u = core.down_roll_offset(e.down_t) / core.PX_PER_UNIT
        px, py = self._enemy_pose(game, e, roll_u)
        img = _alpha(self.enemy_band_img(e.kind, e.v, "down_0"), 130)
        if not p3d.on_screen(px, py + 4, img.get_width(), img.get_height(),
                             pad=32):
            return
        surf.blit(img, (px - img.get_width() // 2, py + 4 - img.get_height()))

    def _draw_enemy_bar(self, surf, e: core.Enemy, px: int, by: int) -> None:
        s = self.sprite_scale()
        bw, bh = int(60 * s), max(4, int(7 * s))
        pygame.draw.rect(surf, (30, 20, 20), (px - bw // 2, by, bw, bh))
        hpw = int(bw * max(0.0, e.hp) / e.max_hp)
        pygame.draw.rect(surf, (232, 92, 62), (px - bw // 2, by, hpw, bh))
        pygame.draw.rect(surf, (110, 70, 50), (px - bw // 2, by, bw, bh), 1)

    def _draw_boss_platform(self, surf: pygame.Surface, game: core.Game,
                            boss: core.Enemy) -> tuple[int, int]:
        """棱柱上的一座小台基：顶面 + 近侧/坡底侧厚度 + 台阶 + 垛口。"""
        s = self.sprite_scale()
        # 渲染高度放大到 34px，让“台下/台上”的遮挡与落差可读；
        # 战斗数值仍读 core.BOSS_PLATFORM["height_px"]。
        h = int(getattr(boss, "platform_h", 34))
        u0 = float(getattr(boss, "platform_u0", boss.platform_x - 1.55))
        u1 = float(getattr(boss, "platform_u1", boss.platform_x + 1.55))
        hv = float(getattr(boss, "platform_v_half", 1.75))
        v0, v1 = boss.v - hv, boss.v + hv
        steps_n = int(getattr(boss, "platform_steps", 3))
        base = [p3d.world_to_screen(u, v, self.cam_x, self.cam_dip)
                for u, v in ((u0, v1), (u1, v1), (u1, v0), (u0, v0))]
        top = [(x, y - h) for x, y in base]
        # 台基底部阴影，避免“浮在半空”
        self._draw_shadow(surf, base[2][0], base[2][1] + 2, boss.v)
        # 近侧（v0）与坡底侧（u1）厚度
        pygame.draw.polygon(surf, (72, 48, 37),
                            [top[2], top[3], base[3], base[2]])
        pygame.draw.polygon(surf, (58, 39, 32),
                            [top[1], top[2], base[2], base[1]])
        pygame.draw.polygon(surf, (142, 100, 68), top)
        pygame.draw.line(surf, (204, 152, 98), top[0], top[1], 2)
        pygame.draw.line(surf, (80, 54, 40), top[3], top[2], 2)
        pygame.draw.line(surf, (22, 15, 16), base[2], base[1], 2)
        # 近侧砖缝：横向分层 + 竖缝，读得出台基厚度
        for k in (0.4, 0.75):
            y = int(h * k)
            pygame.draw.line(surf, (48, 32, 27),
                             (top[3][0], top[3][1] + y),
                             (top[2][0], top[2][1] + y), 1)
        # 台面石缝
        for k in range(1, 4):
            uu = u0 + (u1 - u0) * k / 4.0
            pygame.draw.line(surf, (98, 68, 48),
                             p3d.world_to_screen(uu, v0, self.cam_x,
                                                 self.cam_dip),
                             p3d.world_to_screen(uu, v1, self.cam_x,
                                                 self.cam_dip), 1)
        # 近侧砖缝
        for k in range(1, 5):
            uu = u0 + (u1 - u0) * k / 5.0
            p = p3d.world_to_screen(uu, v0, self.cam_x, self.cam_dip)
            pygame.draw.line(surf, (40, 27, 23), (p[0], p[1] - h),
                             (p[0], p[1]), 1)
        # 台阶：沿上坡侧按 steps_n 均分，向下坡方向接回坡面
        steps = max(1, steps_n)
        sw = max(0.18, 0.40 * 3.0 / steps)
        rise = max(2, h // (steps + 2))
        for i in range(steps):
            su = u0 - 0.28 * (i + 1)
            pa = p3d.world_to_screen(su, v0, self.cam_x, self.cam_dip)
            pb = p3d.world_to_screen(su + sw, v0, self.cam_x, self.cam_dip)
            yy = pa[1] - i * rise
            pygame.draw.polygon(surf, (156, 110, 74), [
                (pa[0], yy), (pb[0], yy - 3),
                (pb[0], yy - 3 + 6), (pa[0], yy + 6)])
            pygame.draw.line(surf, (214, 164, 108), (pa[0], yy),
                             (pb[0], yy - 3), 1)
            pygame.draw.line(surf, (66, 44, 34), (pa[0], yy + 6),
                             (pb[0], yy + 3), 1)
        # 远侧垛口：提示台基边界
        for k in range(int(core.BOSS_PLATFORM["wall_merlons"])):
            uu = u0 + (u1 - u0) * (0.25 + 0.25 * k)
            mx, my = p3d.world_to_screen(uu, v1, self.cam_x, self.cam_dip)
            pygame.draw.rect(surf, (176, 126, 84), (mx - 3, my - h - 7, 6, 8))
            pygame.draw.rect(surf, (70, 46, 34), (mx - 3, my - h - 7, 6, 8), 1)
            pygame.draw.line(surf, (222, 172, 112), (mx - 3, my - h - 7),
                             (mx + 3, my - h - 7), 1)
        px, py = p3d.world_to_screen(boss.platform_x, boss.v,
                                    self.cam_x, self.cam_dip)
        self.fonts.text(surf, "石 台", 10, (196, 158, 118),
                        (px, py + 16), center=True, bold=True)
        return (px, py - h)

    def _draw_one_boss(self, surf: pygame.Surface, game: core.Game,
                       boss: core.Enemy, now: float) -> None:
        s = self.sprite_scale()
        top_px, top_y = self._draw_boss_platform(surf, game, boss)
        on_platform = game.boss_on_platform
        px, py = p3d.world_to_screen(
            boss.platform_x if on_platform else boss.x, boss.v,
            self.cam_x, self.cam_dip)
        anchor_y = top_y if on_platform else py
        if not on_platform and not boss.dead:
            # 被拽下台：台边留尘，Boss 落在台面同层的坡面上
            dx = int(top_px + 84)
            g = pygame.Surface((70, 28), pygame.SRCALPHA)
            pygame.draw.ellipse(g, (198, 168, 120, 80), g.get_rect())
            surf.blit(g, (dx - 20, int(py) - 10))
        if boss.dead:
            img = _alpha(self.boss_band_img(boss.v, "down_0"), 150)
            surf.blit(img, (px - img.get_width() // 2,
                            anchor_y + 4 - img.get_height()))
            return
        if game.boss_staggered:
            state = "hurt_0"
        elif boss.attack_anim > 0:
            state = "attack_0"
        elif boss.flash > 0.12:
            state = "hurt_0"
        elif game.boss_input_window or game.intent:
            state = "telegraph_0" if (game.intent or {}).get("kind") != "aoe" else "roar_0"
        else:
            state = "idle_1" if (now * 2.0) % 2 > 1 else "idle_0"
        img = self.boss_band_img(boss.v, state)
        shake = 0
        if game.boss_staggered:
            shake = int(4 * math.sin(now * 26) * s)
        self._draw_shadow(surf, px, anchor_y + 2, boss.v)
        surf.blit(img, (px + shake - img.get_width() // 2,
                        anchor_y + 4 - img.get_height()))
        if boss.flash > 0:
            f = _additive(img, (180, 50, 10))
            f.set_alpha(int(170 * min(1.0, boss.flash / 0.22)))
            surf.blit(f, (px + shake - f.get_width() // 2,
                          anchor_y + 4 - f.get_height()))
            f.set_alpha(255)
        # 台上/落台状态标签：让“他在上面 / 被拽下来”直接可读
        if on_platform:
            self.fonts.text(surf, "台上 · 近战 ×1.35", 11, (255, 206, 132),
                            (int(px), int(top_y) - int(128 * s)), center=True, bold=True,
                            outline=(40, 10, 6))
        else:
            self.fonts.text(surf, "落 台 · 长硬直", 12, (255, 176, 104),
                            (int(px), int(py) - int(148 * s)), center=True, bold=True,
                            outline=(40, 10, 6))
        intent = game.intent
        if intent and game.boss_telegraph_active:
            self._draw_target_highlight(surf, game, intent, now)
        if intent and game.boss_input_window:
            cx = int(px)
            cy = int(anchor_y) - 142
            r = 54 + int(8 * math.sin(now * 9))
            pygame.draw.circle(surf, INTENT_COLORS.get(game.intent_key, RED),
                               (cx, cy), r, 3)
            if game.intent_variant == "long":
                pygame.draw.circle(surf, (255, 126, 70), (cx, cy), r + 10, 2)
                self.fonts.text(surf, "长 蓄", 12, (255, 160, 110),
                                (cx, cy - r - 16), center=True, bold=True)
            self.fonts.text(surf, "！", 30, (255, 220, 140),
                            (cx, cy), center=True, bold=True,
                            outline=(80, 10, 10))
        if game.counter_pop[1] > 0:
            text, life = game.counter_pop
            cx = int(px)
            cy = int(anchor_y) - 198
            a = int(255 * min(1.0, life / 0.35))
            grow = int(18 * (1.0 - min(1.0, life / 0.60)))
            surf.blit(self.bank.counter_mark,
                      (cx - 24 - grow // 2, cy - 24 - grow // 2))
            pygame.draw.circle(surf, (255, 196, 96, a),
                               (cx, cy), 30 + grow, 3)
            self.fonts.text(surf, text, 30 if text == "克" else 22,
                            (255, 214, 120) if text == "克" else (255, 120, 96),
                            (cx, cy), center=True, bold=True,
                            outline=(60, 8, 8), alpha=a)
        if game.boss_staggered:
            for k in range(3):
                a = now * 5 + k * 2.1
                sx = int(px + 50 * math.cos(a))
                sy = int(anchor_y) - 170 + 12 * math.sin(a)
                self.fonts.text(surf, "★", 18, (255, 226, 120), (sx, sy),
                                center=True, bold=True)

    def _draw_target_highlight(self, surf, game: core.Game,
                               intent: dict, now: float) -> None:
        """阵地高亮：AOE 标全队，单体标前卫，抓取标中军。"""
        poses = self._unit_positions(game)
        if intent["aoe"]:
            marks = poses
        elif intent["kind"] == "grab" and len(poses) > 1:
            marks = [poses[1]]
        else:
            marks = poses[:1]
        col = INTENT_COLORS.get(game.intent_key, RED)
        pulse = 0.55 + 0.45 * math.sin(now * 8)
        for u, px, py, _wy in marks:
            r = int(40 + 6 * pulse)
            s = pygame.Surface((r * 2, 30), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (*col, int(70 * pulse)), s.get_rect())
            pygame.draw.ellipse(s, (*col, 220), s.get_rect(), 2)
            surf.blit(s, (int(px) - r, int(py) - 12))

    # ------------------------------------------------------------------ 特效
    def _record_trail(self, game: core.Game) -> None:
        if game.trail_t <= 0 and not game.fever_active:
            return
        self.trail.append((game.now, [(p[0].kind, p[1], p[2]) for p in
                                      self._unit_positions(game)]))
        cutoff = game.now - 0.45
        self.trail = [t for t in self.trail if t[0] >= cutoff][-14:]

    def _draw_trail(self, surf: pygame.Surface, game: core.Game) -> None:
        for t, poses in self.trail:
            age = game.now - t
            if age <= 0.0 or age > 0.45:
                continue
            a = int(150 * (1.0 - age / 0.45))
            for kind, px, py in poses:
                hero = self.bank.hero_for_kind[kind]
                img = _alpha(self._himg(self.bank.hero_top[hero]["march_0"]), a)
                surf.blit(img, (int(px) - img.get_width() // 2,
                                int(py) + 4 - img.get_height()))

    def _draw_sparks(self, surf: pygame.Surface, game: core.Game) -> None:
        for p in game.sparks.parts:
            life, maxlife = p[4], p[5]
            a = int(255 * max(0.0, life / maxlife))
            r = max(1, int(3 * max(0.0, life / maxlife)))
            col = p[6]
            s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (col[0], col[1], col[2], a), (r, r), r)
            surf.blit(s, (int(p[0]) - r, int(p[1]) - r))

    # ------------------------------------------------------------------ 顶栏
    def _draw_banner(self, surf, game: core.Game) -> None:
        if game.banner[1] <= 0:
            return
        a = min(1.0, game.banner[1] * 1.6)
        col = (255, 196, 90) if game.fever_active else CREAM
        self.fonts.text(surf, game.banner[0], 12, col, (VIEW_W // 2, 16),
                        center=True, bold=True, outline=(40, 8, 8),
                        alpha=int(255 * a))

    def _draw_tutorial_hint(self, surf: pygame.Surface, game: core.Game) -> None:
        """一次性招式提示：首次出现时短暂显示，结束即消失。"""
        text, life = game.tutorial_hint
        if not text or life <= 0:
            return
        alpha = int(255 * min(1.0, life / 0.45))
        x, y, w, h = HUD_TUTORIAL
        plate = self._hs(w, h)
        plate.fill((30, 18, 12))
        plate.set_alpha(alpha)
        pygame.draw.rect(plate, (240, 186, 92), plate.get_rect(), 2)
        surf.blit(plate, (x, y))
        self.fonts.text(surf, "教学", 8, (255, 210, 130), (x + 8, y + 8),
                        bold=True, alpha=alpha)
        self.fonts.text(surf, text, 10, (255, 236, 190),
                        (x + w // 2 + 10, y + h // 2), center=True,
                        bold=True, alpha=alpha)

    def _draw_boss_hud(self, surf, game: core.Game) -> None:
        if not game.boss_active:
            return
        b = game.boss
        bx, by, bw, bh = HUD_BOSS_BAR
        pygame.draw.rect(surf, (28, 18, 20), (bx - 2, by - 2, bw + 4, bh + 4))
        hp = max(0.0, b.hp) / b.max_hp
        col = (232, 84, 54)
        if game.boss_staggered:
            col = (255, 196, 70)
        pygame.draw.rect(surf, col, (bx, by, int(bw * hp), bh))
        pygame.draw.rect(surf, (120, 70, 60), (bx, by, bw, bh), 2)
        self.fonts.text(surf, f"鼓王 {int(max(0.0, b.hp))}/{int(b.max_hp)}",
                        10, CREAM, (VIEW_W // 2, by + bh // 2), center=True,
                        outline=(30, 8, 6))
        if game.boss_on_platform:
            tag, tc = "石台 · 台上×1.35 / 仰攻×0.85", (255, 206, 132)
        else:
            tag, tc = "已落台 · 高度加成失效", (255, 150, 104)
        tw = self.fonts.measure(tag, 8)[0]
        self.fonts.text(surf, tag, 8, tc, (bx + bw - tw, 62), bold=True,
                        outline=(30, 8, 6))
        if game.combo > 0:
            # 敲印：22→16→12px 三档字号替换（3 帧内压回），40 连以上金边
            size = combo_stamp_size(self._combo_t)
            gold = game.combo >= int(HUD_TIMING["combo_gold_at"])
            col = (255, 214, 130) if (gold or game.combo >= 4) else MUTED
            self.fonts.text(surf, f"连击 ×{game.combo}", size, col,
                            (VIEW_W // 2, 30), center=True, bold=True,
                            outline=GOLD if gold else (30, 8, 6))

    # ------------------------------------------------------------------ 左栏
    def _panel_key(self, game: core.Game) -> tuple:
        """左栏缓存键：只含会改变面板像素的量（鼓劲槽液面另画，不进键）。"""
        units = []
        for i, u in enumerate(game.squad.units):
            frac = max(0.0, u.hp) / u.max_hp
            shown, ghost = self._hp_view(i, frac)
            units.append((u.kind, int(max(0.0, u.hp)), int(u.max_hp),
                          int(round(shown * 90)), int(round(ghost * 90))))
        low = any(u.hp < u.max_hp * 0.3 for u in game.squad.units)
        pulse = int(game.now * 1000.0 // 300.0) % 2 if low else 0
        return (self.hud_scale, game.diff["name"], int(round(game.clock.bpm)),
                bool(game.fever_active), game.formation, tuple(units), pulse)

    def _draw_panel(self, surf, game: core.Game) -> None:
        """左栏：整块缓存成一张 HUD 图，只有血条/阵型/档位变化时重绘；
        鼓劲槽液面与读数每帧单独重画。"""
        px, py, pw, ph = HUD_PANEL
        key = self._panel_key(game)
        panel = self._panel_cache.get(key)
        if panel is None:
            panel = HudSurface(pw, ph, pygame.SRCALPHA, self.hud_scale)
            self._draw_panel_body(panel, game)
            if len(self._panel_cache) > 4:
                self._panel_cache.pop(next(iter(self._panel_cache)))
            self._panel_cache[key] = panel
        surf.blit(panel, (px, py))
        burst = _clamp01(self._gauge_burst_t
                         / (HUD_TIMING["gauge_burst_ms"] / 1000.0))
        gauge = draw_fever_gauge(surf, game, px + 10, py + 278, 200, 12,
                                 self.fonts, burst=burst
                                 if self._gauge_burst_t < 99.0 else 1.0)
        self.fonts.text(surf, gauge, 10,
                        (255, 190, 90) if game.fever_active else (220, 200, 170),
                        (px + 10, py + 294), bold=game.fever_active)

    def _draw_panel_body(self, panel, game: core.Game) -> None:
        pw, ph = panel.get_size()
        panel.fill((18, 14, 20))
        pygame.draw.rect(panel, (96, 70, 58), panel.get_rect(), 2)
        self.fonts.text(panel, "踏鼓", 15, GOLD, (10, 4),
                        bold=True, outline=(60, 20, 4))
        self.fonts.text(panel, "潮汕英歌 · 八拍鼓阵", 8, MUTED,
                        (56, 12))
        bpm = int(round(game.clock.bpm))
        tag = "极板" if game.fever_active else "常速"
        self.fonts.text(panel, f"{game.diff['name']}档 · {tag} BPM {bpm}",
                        10, AMBER if game.fever_active else MUTED,
                        (10, 26))

        # 兵种血条（名字 + 数值直接压在条右侧，去掉状态小字）
        for i, u in enumerate(game.squad.units):
            uy = 44 + i * 26
            panel.blit(self.bank.role[u.kind], (10, uy))
            col = unit_color(u.kind)
            hero = self.bank.hero_for_kind[u.kind]
            self.fonts.text(panel, core.HERO_NAMES[hero], 10,
                            (235, 225, 210), (34, uy - 2), bold=True)
            bx, by, bw, bh = 92, uy + 5, 96, 8
            frac = max(0.0, u.hp) / u.max_hp
            shown, ghost = self._hp_view(i, frac)
            self._draw_drum_bar(panel, bx, by, bw, bh, frac, shown, ghost,
                                col, game.now)
            self.fonts.text(panel, f"{int(max(0.0, u.hp))}/{int(u.max_hp)}",
                            8, CREAM, (192, uy + 3),
                            outline=(30, 10, 10))

        pygame.draw.line(panel, (80, 46, 40), (10, 128), (pw - 10, 128), 2)

        spec = game.formation_spec
        fy = 134
        icon = self.bank.form_icon[game.formation]
        panel.blit(icon, (10, fy))
        self.fonts.text(panel, spec["name"], 12, (255, 214, 140),
                        (36, fy - 2), bold=True)
        self.fonts.text(panel, spec["desc"], 10, MUTED, (36, fy + 18))
        line = (f"攻 ×{spec['atk']:.2f} 减伤 {spec['dr'] * 100:+.0f}% "
                f"行军 ×{spec['march']:.2f}")
        self.fonts.text(panel, line, 10, (220, 204, 180), (10, fy + 34))

        pygame.draw.line(panel, (80, 46, 40), (10, 184), (pw - 10, 184), 2)

        # 四阵速查（名称与定位合并为一行）
        self.fonts.text(panel, "阵法速查（四拍成令）", 10, (200, 160, 120),
                        (10, 190))
        rows = [
            ("J K J K", "锋矢", "攻高 · 守弱"),
            ("L K L K", "龟甲", "减伤 · 缓行"),
            ("J J K K", "双龙", "行军最快"),
            ("K L K L", "猛虎", "强攻 · 硬直降防"),
        ]
        for i, (keys, name, desc) in enumerate(rows):
            yy = 208 + i * 15
            cur = name == spec["name"]
            col = (240, 210, 150) if cur else (198, 184, 160)
            self.fonts.text(panel, keys, 10, col, (10, yy), bold=cur)
            self.fonts.text(panel, name, 10, col, (62, yy), bold=cur)
            self.fonts.text(panel, desc, 10, MUTED, (110, yy))

        pygame.draw.line(panel, (80, 46, 40), (10, 272), (pw - 10, 272), 2)
        # 鼓劲槽液面与读数由 _draw_panel 每帧单独绘制（不进缓存）
        self.fonts.text(panel, "J 鼓 · K 锣 · L 镲 · R 重开", 8,
                        (170, 150, 138), (10, 313))
        self.fonts.text(panel, "M 克制矩阵 · P 定妆", 8,
                        (170, 150, 138), (10, 325))

    def _draw_drum_bar(self, surf, bx: int, by: int, bw: int, bh: int,
                       frac: float, shown: float, ghost: float,
                       col: tuple[int, int, int], now: float) -> None:
        """鼓皮血条：两端鼓钉 + 上亮下暗；掉血残影 0.2s；低血脉冲/裂纹。"""
        inner_x, inner_w = bx + 3, bw - 6
        pygame.draw.rect(surf, (24, 16, 18), (bx, by, bw, bh))
        # 残影（掉出的旧血量）：不透明暗红块，不做逐帧 alpha
        if ghost > shown + 1e-4:
            gx = inner_x + int(round(inner_w * shown))
            gw = int(round(inner_w * (ghost - shown)))
            if gw > 0:
                pygame.draw.rect(surf, (122, 44, 40), (gx, by, gw, bh))
        w = int(round(inner_w * max(0.0, min(1.0, shown))))
        if w > 0:
            pygame.draw.rect(surf, col, (inner_x, by, w, bh))
            light = tuple(min(255, c + 38) for c in col)
            dark = tuple(max(0, c - 52) for c in col)
            pygame.draw.line(surf, light, (inner_x, by), (inner_x + w - 1, by))
            pygame.draw.line(surf, dark, (inner_x, by + bh - 1),
                             (inner_x + w - 1, by + bh - 1))
        # 两端鼓钉（2×3 铜色 + 1px 暗边）
        for sx in (bx, bx + bw - 2):
            pygame.draw.rect(surf, (196, 150, 72), (sx, by + 2, 2, 3))
            pygame.draw.rect(surf, (90, 58, 32), (sx, by + 2, 1, 3))
        pygame.draw.rect(surf, (100, 74, 62), (bx, by, bw, bh), 1)
        if frac < float(HUD_TIMING["hp_low_threshold"]):
            # 低血：边缘脉冲红（按固定周期在两种实色间切换）+ 轻微裂纹
            on = int(now * 1000.0 / (HUD_TIMING["hp_low_pulse_ms"] / 2.0)) % 2
            edge = (255, 78, 64) if on else (132, 30, 28)
            pygame.draw.rect(surf, edge, (bx, by, bw, bh), 1)
            for cx, cy in ((14, 1), (30, 3), (52, 1), (68, 4)):
                if 3 <= cx < inner_w:
                    pygame.draw.line(surf, (150, 44, 40),
                                     (inner_x + cx, by + cy),
                                     (inner_x + cx + 2, by + cy + 1))

    # ------------------------------------------------------------------ 底栏
    def _draw_beat_ui(self, surf, game: core.Game) -> None:
        slots_view = game.cycle_slots
        beat_sec = game.clock.beat_sec
        # 乐器架（鼓/锣/镲）：按 J/K/L 按压下沉、回弹、随拍呼吸
        for j, key in enumerate(("J", "K", "L")):
            px = 36 + j * 36
            py = 434
            age_ms = (game.now - game.press_times.get(key, -99.0)) * 1000.0
            dy, lit = instrument_pose(age_ms, game.beat_pos)
            pygame.draw.rect(surf, (24, 18, 20), (px - 1, py - 1, 26, 26))
            pygame.draw.rect(surf, (74, 54, 42), (px - 1, py - 1, 26, 26), 1)
            img = self.bank.instrument_lit[key] if lit \
                else self.bank.instrument24[key]
            surf.blit(img, (px, py + dy))
            self.fonts.text(surf, f"{key}", 8, (200, 176, 150),
                            (px + 12, py + 30), center=True)
            if game.press_grades.get(key) == "perfect" and \
                    0.0 <= age_ms < HUD_TIMING["perfect_glint_ms"]:
                pygame.draw.rect(surf, (255, 226, 150),
                                 (px - 2, py + dy - 2, 28, 28), 1)

        self._draw_beat_ribbon(surf, game)

        # 预测指令：第 3 拍灰版幽灵 → 第 4 拍实色并短暂发亮
        keys = "".join((s.key or "") for s in slots_view[:core.INPUT_BEATS])
        if len(keys) >= 3:
            cmd, ghost = predict_command(keys)
            chip = pygame.Rect(140, 434, 100, 54)
            pygame.draw.rect(surf, (20, 16, 20), chip)
            pygame.draw.rect(surf, (70, 54, 46), chip, 1)
            flash = False
            last = next((s for s in reversed(slots_view) if s.key), None)
            if len(keys) >= 4 and last is not None:
                age = max(0.0, (game.beat_pos - last.beat) * beat_sec)
                flash = age * 1000.0 < HUD_TIMING["predict_flash_ms"]
            if cmd is not None:
                icon = self.bank.command_ghost[cmd] if ghost \
                    else self.bank.command_icon[cmd]
                surf.blit(icon, (chip.x + 8, chip.y + 8))
                self.fonts.text(surf, "预测" if ghost else "成令", 8,
                                (150, 136, 124), (chip.x + 38, chip.y + 5))
                name = COMMAND_SHORT.get(cmd, cmd)
                self.fonts.text(surf, name, 10,
                                (150, 146, 140) if ghost else (255, 214, 130),
                                (chip.x + 38, chip.y + 18), bold=not ghost)
                if flash:
                    pygame.draw.rect(surf, (255, 226, 150), chip, 1)
                    pygame.draw.rect(surf, (255, 226, 150),
                                     (chip.x - 1, chip.y - 1,
                                      chip.w + 2, chip.h + 2), 1)
            elif len(keys) >= 4:
                self.fonts.text(surf, "乱令", 10, (230, 80, 70),
                                (chip.x + 40, chip.y + 18), bold=True)

        if game.input_phase:
            hint = "输入拍 · J/K/L 四拍成令"
            col = AMBER
        elif game.boss_active:
            hint = "行动拍 · 按公示化解，全 Perfect 破阵"
            col = (255, 150, 110)
        else:
            hint = "行动拍 · 踏点行军，队伍自动前压"
            col = (255, 150, 110)
        self.fonts.text(surf, hint, 10, col, (14, 512), bold=True)

    def _draw_key_symbol(self, surf, key: str, rect: pygame.Rect, col,
                         solid: bool = True) -> None:
        """谱面格乐器符号：鼓=实心圆 / 锣=方框 / 镲=斜杠。"""
        cx, cy = rect.center
        if key == "J":
            pygame.draw.circle(surf, col, (cx, cy), 9)
            if not solid:
                pygame.draw.circle(surf, (20, 16, 18), (cx, cy), 4)
        elif key == "K":
            box = pygame.Rect(0, 0, 18, 18)
            box.center = (cx, cy)
            pygame.draw.rect(surf, col, box, 3 if solid else 2)
        else:
            pygame.draw.line(surf, col, (cx - 9, cy + 9), (cx + 9, cy - 9), 3)

    def _draw_beat_ribbon(self, surf, game: core.Game) -> None:
        """方案 A：横向滚动谱面带。

        判定线固定在左 1/4；每拍前进一格（整数像素），强拍更高更亮。
        同一块带同时承载：本组输入状态 / 下一组预排 / Boss 公示 6 拍预警。
        """
        rx, ry, rw, rh = HUD_RIBBON
        base_y = HUD_RIBBON_BASE_Y
        cell_w = HUD_RIBBON_CELL
        judge = HUD_RIBBON_JUDGE_X
        beat_pos = game.beat_pos
        cur = int(math.floor(beat_pos))
        pygame.draw.rect(surf, (16, 12, 18), (rx, ry, rw, rh))
        pygame.draw.rect(surf, (92, 68, 56), (rx, ry, rw, rh), 1)
        pygame.draw.line(surf, (58, 44, 38), (rx + 3, ry + rh - 4),
                         (rx + rw - 3, ry + rh - 4), 2)

        intent = game.intent
        att = game.attempt if game.boss_active else None
        band = None
        if game.boss_active and intent and att is not None:
            first = (cur // core.CYCLE_BEATS) * core.CYCLE_BEATS \
                + core.INPUT_BEATS
            x0 = ribbon_cell_x(first, beat_pos) - cell_w // 2 - 4
            x1 = ribbon_cell_x(first + 3, beat_pos) + cell_w // 2 + 4
            band = pygame.Rect(x0, ry + 4, max(24, x1 - x0), rh - 8)
            pygame.draw.rect(surf, (126, 92, 62), band, 2)
            # 替代旧读招面板：招式名与化解键位压在带内顶部（不与教学条重叠）
            self.fonts.text(surf, f"{intent['name']} · 化解 "
                            + " ".join(intent["keys"]), 8,
                            (255, 152, 112), (band.centerx, ry + 14),
                            center=True, bold=True)

        # 判定线 + 顶部倒三角
        pygame.draw.rect(surf, (255, 214, 130), (judge - 2, ry + 2, 4, rh - 4))
        pygame.draw.polygon(surf, (255, 214, 130),
                            [(judge - 6, ry - 3), (judge + 6, ry - 3),
                             (judge, ry + 6)])

        for k in range(HUD_RIBBON_CELLS):
            b = cur + k
            xc = ribbon_cell_x(b, beat_pos)
            if xc + cell_w // 2 < rx + 2 or xc - cell_w // 2 > rx + rw - 2:
                continue
            strong = b % 2 == 0          # 四拍组内第 1/3 拍强
            h = HUD_RIBBON_STRONG_H if strong else HUD_RIBBON_WEAK_H
            rect = pygame.Rect(xc - cell_w // 2, base_y - h, cell_w, h)
            cycle = b // core.CYCLE_BEATS
            idx = b % core.CYCLE_BEATS
            cur_group = cycle == cur // core.CYCLE_BEATS

            if idx < core.INPUT_BEATS:
                slot = (game._group(cycle).slots[idx]
                        if cycle >= 0 else None)
                if slot is not None and slot.key:
                    self._draw_ribbon_slot(surf, rect, slot, b, game)
                    continue
                edge = (110, 84, 64) if cur_group else (64, 52, 44)
            else:
                edge = (110, 84, 64) if cur_group else (64, 52, 44)
            pygame.draw.rect(surf, (28, 22, 20), rect)
            pygame.draw.rect(surf, edge, rect, 2 if strong else 1)
            if idx >= core.INPUT_BEATS and game.boss_active and intent \
                    and att is not None:
                ai = idx - core.INPUT_BEATS
                if 0 <= ai < len(intent["keys"]):
                    done = ai < len(att.slots) and att.slots[ai].key
                    col = (255, 214, 120) if done else (255, 120, 80)
                    pygame.draw.rect(surf, (44, 24, 20), rect)
                    pygame.draw.rect(surf, col, rect, 2)
                    self._draw_key_symbol(surf, intent["keys"][ai], rect, col)
            else:
                self.fonts.text(surf, str(idx + 1), 8,
                                (150, 128, 108) if cur_group else (96, 82, 72),
                                (xc, base_y + 12), center=True)

    def _draw_ribbon_slot(self, surf, rect: pygame.Rect, slot,
                          beat: int, game: core.Game) -> None:
        """单格状态机：待确认（半格+脉冲）→ Perfect/Good/Miss 落定。"""
        lock_t = game.clock.beat_time(beat)
        age_ms = (game.now - lock_t) * 1000.0
        if age_ms < 0.0:
            phase = int(game.now * 1000.0
                        // HUD_TIMING["slot_pending_pulse_ms"]) % 2
            pygame.draw.rect(surf, (40, 30, 22), rect)
            pygame.draw.rect(surf, (168, 126, 62),
                             (rect.x, rect.y, rect.w // 2, rect.h))
            pygame.draw.rect(surf, (255, 212, 120) if phase else (132, 100, 56),
                             rect, 1)
            self._draw_key_symbol(surf, slot.key, rect, (255, 238, 190))
            return
        grade = slot.grade or ""
        if grade == "perfect":
            edge = (255, 214, 120)
            pygame.draw.rect(surf, (52, 42, 18), rect)
            if age_ms < HUD_TIMING["perfect_glint_ms"]:
                pygame.draw.rect(surf, (255, 238, 176), rect.inflate(4, 4), 1)
        elif grade == "good":
            edge = (140, 220, 170)
            pygame.draw.rect(surf, (26, 40, 30), rect)
        elif grade == "miss":
            edge = (226, 70, 62)
            pygame.draw.rect(surf, (46, 18, 18), rect)
            if age_ms < HUD_TIMING["miss_slash_ms"]:
                pygame.draw.line(surf, (255, 76, 64), rect.topleft,
                                 rect.bottomright, 2)
                pygame.draw.line(surf, (255, 76, 64), rect.bottomleft,
                                 rect.topright, 2)
        else:
            edge = (205, 172, 120)
            pygame.draw.rect(surf, (40, 34, 26), rect)
        pygame.draw.rect(surf, edge, rect, 2)
        self._draw_key_symbol(surf, slot.key, rect, edge)

    def _draw_instrument_sparks(self, surf, game: core.Game) -> None:
        """按压边缘溅出的 2–4 颗 1px 火星；Perfect 用金色且多一颗。"""
        dirs = ((1, -1), (1, 1), (-1, -1), (1, 0))
        for j, key in enumerate(("J", "K", "L")):
            age = (game.now - game.press_times.get(key, -99.0)) * 1000.0
            if not (0.0 <= age < HUD_TIMING["drum_spark_ms"]):
                continue
            perfect = game.press_grades.get(key) == "perfect"
            n = 4 if perfect else 3
            p = age / float(HUD_TIMING["drum_spark_ms"])
            reach = 4 + hud_step_px(6, p)
            cx, cy = 48 + j * 36, 446
            col = (255, 232, 150) if perfect else (255, 150, 70)
            for d in range(n):
                vx, vy = dirs[d]
                sx = cx + vx * reach + (0 if d < 2 else 2)
                sy = cy + vy * reach
                surf.fill(col, (sx, sy, 1, 1))

    def _draw_fever_frame(self, surf, game: core.Game) -> None:
        """Fever 外框：金红描边按 0/1/2/3/4 档阶梯切换，四拍槽加流光。"""
        level = self._fever_level
        if level <= 0.0:
            return
        step = int(level * 4.0 + 0.999)
        if step <= 1:
            pygame.draw.rect(surf, (120, 30, 22),
                             (0, 0, VIEW_W, VIEW_H), 1)
        elif step == 2:
            pygame.draw.rect(surf, (190, 54, 30),
                             (0, 0, VIEW_W, VIEW_H), 2)
        elif step == 3:
            pygame.draw.rect(surf, (255, 186, 72),
                             (0, 0, VIEW_W, VIEW_H), 2)
            pygame.draw.rect(surf, (150, 34, 28),
                             (2, 2, VIEW_W - 4, VIEW_H - 4), 1)
        else:
            pygame.draw.rect(surf, (255, 196, 88),
                             (0, 0, VIEW_W, VIEW_H), 2)
            pygame.draw.rect(surf, (184, 44, 40),
                             (2, 2, VIEW_W - 4, VIEW_H - 4), 1)
            # 谱面带流光：单像素高光沿带顶整数步进
            rx, ry, rw, _rh = HUD_RIBBON
            pos = int((game.now * 46.0) % max(1, rw - 4))
            surf.fill((255, 232, 150), (rx + 2 + pos, ry + 2, 2, 1))

    # ------------------------------------------------------------------ 状态
    def _draw_status(self, surf, game: core.Game, now: float) -> None:
        """胜负结算：面板自底部推入，胜暖金 / 败冷灰，淡入淡出 0.3s。"""
        p = self._result_progress(game)
        if p <= 0.0:
            return
        step = min(4, int(p * 4.0))
        shade = self._hs(VIEW_W, VIEW_H)
        shade.fill((10, 4, 8, [0, 56, 112, 168, 168][step]))
        surf.blit(shade, (0, 0))
        kind = self._result_kind or game.status
        win = kind == "cleared"
        pw, ph = 560, 180
        px = (VIEW_W - pw) // 2
        py = VIEW_H - hud_step_px(VIEW_H - 224, p)
        alpha = 255 if p >= 1.0 else [0, 85, 170, 255][min(3, int(p * 4.0))]
        panel = self._hs(pw, ph)
        if win:
            bg, edge, title, sub = ((48, 32, 16), (238, 186, 88),
                                    (255, 214, 110), (255, 236, 200))
        else:
            bg, edge, title, sub = ((28, 30, 34), (150, 160, 170),
                                    (208, 216, 226), (176, 186, 198))
        panel.fill(bg)
        pygame.draw.rect(panel, edge, panel.get_rect(), 2)
        pygame.draw.line(panel, edge, (16, 10), (pw - 16, 10), 1)
        pygame.draw.line(panel, edge, (16, ph - 11), (pw - 16, ph - 11), 1)
        self.fonts.text(panel, "鼓王伏诛" if win else "全军覆灭", 30,
                        title, (pw // 2, 38), center=True, bold=True,
                        outline=(40, 12, 6) if win else (12, 14, 18))
        self.fonts.text(panel, "满堂彩 · 英歌得胜" if win else "鼓点散了，阵也散了",
                        12, sub, (pw // 2, 88), center=True)
        self.fonts.text(panel, "按 R 重整旗鼓", 12,
                        (255, 214, 130) if win else (176, 186, 198),
                        (pw // 2, 126), center=True, bold=True)
        panel.set_alpha(alpha)
        surf.blit(panel, (px, py))

    def _draw_break_fx(self, surf, game: core.Game) -> None:
        """破阵：全屏白闪（≤3 帧，固定 alpha 整块）+「破」字印章落下。"""
        if self._flash_frames > 0:
            alpha = {3: 220, 2: 140, 1: 64}.get(self._flash_frames, 0)
            if alpha:
                flash = self._hs(VIEW_W, VIEW_H)
                flash.fill((255, 250, 240, alpha))
                surf.blit(flash, (0, 0))
        dur = HUD_TIMING["break_seal_ms"] / 1000.0
        if self._seal_t >= dur:
            return
        p = self._seal_t / dur
        sy = -46 + hud_step_px(58, p)      # 从屏外落到 y=12
        stamp = self._hs(46, 46)
        stamp.fill((176, 36, 30))
        pygame.draw.rect(stamp, (255, 214, 120), stamp.get_rect(), 2)
        self.fonts.text(stamp, "破", 28, (255, 242, 208),
                        (23, 23), center=True, bold=True, outline=(70, 12, 8))
        surf.blit(stamp, (VIEW_W - 96, sy))

    def _draw_result_pop(self, surf, game: core.Game) -> None:
        """判定字单独走瞬态层：不参与相机/缩放插值。"""
        text, life = game.result_pop
        if not text or life <= 0:
            return
        a = int(255 * min(1.0, life / 0.3))
        col = (255, 226, 140)
        if "补 打 成 功" in text or "补打成功" in text:
            col = (130, 240, 160)
        elif "补 打 失 败" in text or "补打失败" in text:
            col = (255, 110, 96)
        self.fonts.text(surf, text, 12, col,
                        (VIEW_W // 2, 186), center=True, bold=True,
                        outline=(50, 10, 8), alpha=a)

    def _draw_makeup_fx(self, surf, game: core.Game) -> None:
        """补打倒计时环与成功/失败角标，画在瞬态层（不影响静态 HUD 像素）。"""
        att = game.attempt
        if att is None:
            return
        px, py, _pw, ph = HUD_READ_PANEL
        cx, cy = px + 26, py + 24
        beat = max(1e-3, game.clock.beat_sec)
        if att.makeup_state == "pending":
            remain = game.makeup_remain
            frac = max(0.0, min(1.0, remain / beat))
            rect = pygame.Rect(cx - 21, cy - 21, 42, 42)
            pygame.draw.arc(surf, (255, 172, 80), rect,
                            -math.pi / 2, -math.pi / 2 + math.tau * frac, 3)
            self.fonts.text(surf, f"{remain / beat:.1f}拍", 10,
                            (255, 200, 110), (cx, py + ph + 3), center=True,
                            bold=True, outline=(50, 16, 6))
        elif att.makeup_state in ("ok", "failed") and game.result_pop[1] > 0:
            ok = att.makeup_state == "ok"
            col = (120, 240, 150) if ok else (255, 96, 84)
            pygame.draw.circle(surf, col, (cx, cy), 22, 2)
            # 成功打勾 / 失败打叉
            if ok:
                pygame.draw.line(surf, col, (cx - 7, cy), (cx - 2, cy + 6), 2)
                pygame.draw.line(surf, col, (cx - 2, cy + 6), (cx + 8, cy - 7), 2)
            else:
                pygame.draw.line(surf, col, (cx - 7, cy - 7), (cx + 7, cy + 7), 2)
                pygame.draw.line(surf, col, (cx + 7, cy - 7), (cx - 7, cy + 7), 2)

    def _draw_variant_debug(self, surf, game: core.Game) -> None:
        """parallax_debug 打开时，标出屏幕中心所在平铺的变体号与平铺序号。"""
        if not self.parallax_debug:
            return
        parts = []
        for key, label in (("far", "远景"), ("mid", "中景"), ("near", "近景")):
            if self.parallax_debug & {"far": 1, "mid": 2, "near": 4}[key]:
                parts.append(f"{label} 关")
            else:
                vi, tile = self._layer_variant_now.get(key, (0, 0))
                parts.append(f"{label} v{vi} t{tile}")
        self.fonts.text(surf, " · ".join(parts), 8, (200, 240, 255),
                        (8, 516), bold=True, outline=(8, 10, 20))

    # ------------------------------------------------------------ HUD 动效状态
    def _update_hud_motion(self, game: core.Game, dt: float) -> None:
        """按帧推进 HUD 动效状态；只由 draw() 调用，保证同帧重绘结果一致。"""
        dt = max(0.0, min(0.1, float(dt)))
        active = bool(game.fever_active)
        if active and not self._fever_prev:
            self._gauge_burst_t = 0.0
        self._fever_prev = active
        self._fever_level = fever_level_step(self._fever_level, active, dt)
        self._gauge_burst_t += dt

        # 连击敲印：只在连击增加时触发
        if game.combo != self._combo_last:
            if game.combo > self._combo_last:
                self._combo_t = 0.0
            self._combo_last = game.combo
        self._combo_t += dt

        # 破阵印章 / 白闪：last_stagger_cycle 变化即一次极限破阵
        if game.last_stagger_cycle != self._stagger_seen:
            self._stagger_seen = game.last_stagger_cycle
            if game.last_stagger_cycle >= 0:
                self._seal_t = 0.0
                self._flash_frames = int(HUD_TIMING["break_flash_frames"])
        self._seal_t += dt

        # 结算面板：playing→结果 = 推入；结果→playing(R 重开) = 退出
        status = game.status
        if status != "playing" and self._result_last == "playing":
            self._result_mode, self._result_t = "in", 0.0
            self._result_kind = status
        elif status == "playing" and self._result_last != "playing":
            self._result_mode, self._result_t = "out", 0.0
        elif status != "playing":
            self._result_kind = status
        if self._result_mode == "in":
            self._result_t += dt
            if self._result_t >= HUD_TIMING["result_in_ms"] / 1000.0:
                self._result_mode, self._result_t = "hold", 0.0
        elif self._result_mode == "out":
            self._result_t += dt
            if self._result_t >= HUD_TIMING["result_out_ms"] / 1000.0:
                self._result_mode = ""
        self._result_last = status

        # HP 条：显示值带惯性追目标，掉出的部分留 0.2s 残影
        while len(self._hp_state) < len(game.squad.units):
            self._hp_state.append({"shown": None, "vel": 0.0, "target": None,
                                   "ghost": 0.0, "ghost_t": 0.0})
        for i, u in enumerate(game.squad.units):
            st = self._hp_state[i]
            target = max(0.0, u.hp) / max(1.0, u.max_hp)
            if st["shown"] is None:
                st["shown"] = target
                st["target"] = target
                continue
            shown = float(st["shown"])
            if target > shown + 0.12:       # 重开/回血：直接归位
                st.update(shown=target, vel=0.0, target=target,
                          ghost=0.0, ghost_t=0.0)
                continue
            if st["target"] is not None and target < float(st["target"]) - 1e-6:
                # 仅在“新掉血”那一下记残影；显示值带惯性回缩
                st["ghost"] = max(float(st["ghost"]), shown)
                st["ghost_t"] = float(HUD_TIMING["hp_ghost_ms"]) / 1000.0
            st["target"] = target
            diff = target - shown
            st["vel"] = float(st["vel"]) + diff * 90.0 * dt
            st["vel"] = float(st["vel"]) * max(0.0, 1.0 - 9.0 * dt)
            shown += float(st["vel"]) * dt
            if abs(target - shown) < 0.003 and abs(st["vel"]) < 0.02:
                shown, st["vel"] = target, 0.0
            st["shown"] = max(0.0, min(1.15, shown))
            if st["ghost_t"] > 0.0:
                st["ghost_t"] = max(0.0, st["ghost_t"] - dt)
                if st["ghost_t"] <= 0.0:
                    st["ghost"] = 0.0

    def _result_progress(self, game: core.Game) -> float:
        if self._result_mode == "in":
            return _clamp01(self._result_t
                            / (HUD_TIMING["result_in_ms"] / 1000.0))
        if self._result_mode == "hold":
            return 1.0
        if self._result_mode == "out":
            return 1.0 - _clamp01(self._result_t
                                  / (HUD_TIMING["result_out_ms"] / 1000.0))
        return 1.0 if game.status != "playing" else 0.0

    def _hp_view(self, i: int, frac: float) -> tuple[float, float]:
        if i < len(self._hp_state):
            st = self._hp_state[i]
            if st["shown"] is not None:
                return float(st["shown"]), float(st["ghost"])
        return frac, 0.0

    def _hs(self, w: int, h: int) -> HudSurface:
        """HUD 临时层。实战帧走尺寸池复用（1920×1080 新建一次约 2.3ms）。"""
        if not self._hud_reuse:
            return HudSurface(w, h, pygame.SRCALPHA, self.hud_scale)
        key = (w, h, self.hud_scale)
        bucket = self._hud_arena.get(key)
        if bucket is None:
            bucket = self._hud_arena[key] = []
        i = self._hud_arena_i.get(key, 0)
        if i < len(bucket):
            surf = bucket[i]
            pygame.Surface.fill(surf, (0, 0, 0, 0))
        else:
            surf = HudSurface(w, h, pygame.SRCALPHA, self.hud_scale)
            bucket.append(surf)
        self._hud_arena_i[key] = i + 1
        return surf

    def _build_hud(self, game: core.Game, now: float
                   ) -> tuple[pygame.Surface, pygame.Surface]:
        """返回 (静态 HUD, 瞬态 HUD)。逻辑坐标不变，底层按 hud_scale 落成输出像素。"""
        self.fonts.rects = []
        with hud_draw_scale():
            ui = self._hs(VIEW_W, VIEW_H)
            self._draw_boss_hud(ui, game)
            # 读招面板已并入谱面带（Boss 公示段叠在带上方），不再单开面板
            self._draw_panel(ui, game)
            self._draw_beat_ui(ui, game)
            self._draw_fever_frame(ui, game)
            self._draw_segment_card(ui, game)

            fx = self._hs(VIEW_W, VIEW_H)
            self._draw_banner(fx, game)
            self._draw_tutorial_hint(fx, game)
            self._draw_result_pop(fx, game)
            self._draw_makeup_fx(fx, game)
            self._draw_instrument_sparks(fx, game)
            if game.count_in > 0 and game.status == "playing":
                n = int(math.ceil(game.count_in / (game.clock.beat_sec)))
                self.fonts.text(fx, str(max(1, n)), 40, (255, 210, 120),
                                (VIEW_W // 2, 240), center=True, bold=True,
                                outline=(60, 14, 6))
                self.fonts.text(fx, "起鼓", 10, CREAM, (VIEW_W // 2, 276),
                                center=True, bold=True)
            if self._fever_level > 0.0:
                self._draw_fever_overlay(fx, game, now)
            self._draw_lineup_overlay(fx, game)
            self._draw_matrix_overlay(fx, game)
            self._draw_status(fx, game, now)
            self._draw_break_fx(fx, game)
            self._draw_variant_debug(fx, game)
        return ui, fx

    # ------------------------------------------------------------------ 主绘制
    def draw(self, screen: pygame.Surface, game: core.Game, now: float,
             dt: float) -> None:
        self._step_zoom(dt)
        p3d.set_focal(self.focal)
        self._camera(game, dt)
        self._update_formation(game, dt)
        self._record_trail(game)
        game.cam_x = self.cam_x

        # 世界层：960×540 逻辑视口，按固定顺序分层
        self.world = pygame.Surface((VIEW_W, VIEW_H)).convert()
        self._draw_far(self.world, game, now)
        self._draw_mid(self.world, game, now)
        self._draw_ground(self.world, game, now)
        self._draw_formation_marks(self.world, game)
        self._draw_trail(self.world, game)
        self._draw_actors(self.world, game, now)
        self._draw_dust(self.world)
        self._draw_sparks(self.world, game)
        self._draw_persp_debug(self.world, game)
        self._draw_near(self.world, game)

        if screen.get_width() >= VIEW_W and screen.get_height() >= VIEW_H:
            self.hud_scale = max(1, min(screen.get_width() // VIEW_W,
                                        screen.get_height() // VIEW_H))
        self._update_hud_motion(game, dt)
        self._hud_arena_i.clear()
        self._hud_reuse = True
        try:
            ui, fx = self._build_hud(game, now)
        finally:
            self._hud_reuse = False
        self.hud_ui = ui
        self.hud_fx = fx

        # 只抖动世界层；HUD 固定在输出坐标原点，相机小数位移不会带动 HUD。
        s = self.hud_scale
        off = game.shake.offset(16)
        screen.fill((12, 8, 12))
        if s == 1:
            screen.blit(self.world, off)
        else:
            world_out = pygame.transform.scale(
                self.world, (VIEW_W * s, VIEW_H * s))
            screen.blit(world_out, (off[0] * s, off[1] * s))
        screen.blit(ui, (0, 0))
        screen.blit(fx, (0, 0))
        if self._flash_frames > 0:
            self._flash_frames -= 1     # 白闪最多 3 帧，逐帧消耗

    def layer_breakdown(self, game: core.Game, now: float
                        ) -> list[tuple[str, pygame.Surface]]:
        """同一时刻的远/中/近三层拆解（用于截图与调试）。"""
        layers = []
        for key, draw in (("far", self._draw_far),
                          ("mid", self._draw_mid),
                          ("near", self._draw_near)):
            s = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
            if key == "far":
                draw(s, game, now)
            elif key == "mid":
                draw(s, game, now)
            else:
                draw(s, game)
            layers.append((key, s))
        comp = pygame.Surface((VIEW_W, VIEW_H)).convert()
        self._draw_far(comp, game, now)
        self._draw_mid(comp, game, now)
        self._draw_ground(comp, game, now)
        self._draw_formation_marks(comp, game)
        self._draw_actors(comp, game, now)
        self._draw_dust(comp)
        self._draw_sparks(comp, game)
        self._draw_near(comp, game)
        layers.append(("composite", comp))
        return layers

    def _draw_lineup_overlay(self, surf, game: core.Game) -> None:
        """P 键 / 截图：三好汉定妆照横排。864×348 原尺寸直接贴，不再放大。"""
        if not game.show_lineup:
            return
        dim = self._hs(VIEW_W, VIEW_H)
        dim.fill((8, 6, 10, 176))
        surf.blit(dim, (0, 0))
        img = self.bank.lineup
        x = (VIEW_W - img.get_width()) // 2
        y = (VIEW_H - img.get_height()) // 2
        surf.blit(img, (x, y))
        pygame.draw.rect(surf, (238, 186, 88), (x, y, img.get_width(),
                                                img.get_height()), 2)
        self.fonts.text(surf, "梁山三好汉 · 兵种分工", 12, AMBER,
                        (VIEW_W // 2, y - 14), center=True, bold=True,
                        outline=(50, 12, 8))
        self.fonts.text(surf, "P 关闭", 8, MUTED,
                        (VIEW_W // 2, y + img.get_height() + 10), center=True)

    def _draw_matrix_overlay(self, surf, game: core.Game) -> None:
        """M 键速查：5 阵 × 5 招的克制矩阵。680×396 原生面板。"""
        if not game.show_matrix:
            return
        x0, y0, w, h = 140, 84, 680, 396
        panel = self._hs(w, h)
        panel.fill((18, 12, 20))
        pygame.draw.rect(panel, (128, 78, 52), panel.get_rect(), 2)
        surf.blit(panel, (x0, y0))
        self.fonts.text(surf, "阵法 × 鼓王招式 · 克制矩阵", 12, GOLD,
                        (x0 + w // 2, y0 + 12), center=True, bold=True,
                        outline=(50, 10, 8))
        self.fonts.text(surf, ">1 克：破绽增益 · <1 被克：伤害衰减 · 1 中性",
                        8, MUTED, (x0 + w // 2, y0 + 32), center=True)
        label_w, cell_w, row_h = 86, 96, 52
        hx = x0 + (w - len(INTENT_ORDER) * cell_w) // 2
        hy = y0 + 66
        for j, key in enumerate(INTENT_ORDER):
            cx = hx + j * cell_w + cell_w // 2
            ic = pygame.transform.scale(self.bank.intent_icon[key], (24, 24))
            surf.blit(ic, (cx - 12, hy - 8))
            self.fonts.text(surf, INTENTS[key]["name"][:4], 8, MUTED,
                            (cx, hy + 18), center=True)
        for i, form in enumerate(FORMATION_SLOTS):
            ry = hy + 38 + i * row_h
            is_row = form == game.formation
            if is_row:
                pygame.draw.rect(surf, (58, 40, 26), (x0 + 12, ry - 6,
                                                      w - 24, 46))
            self.fonts.text(surf, core.FORMATIONS[form]["name"],
                            10, GOLD if is_row else (225, 210, 190),
                            (x0 + 16, ry + 8), bold=is_row)
            for j, key in enumerate(INTENT_ORDER):
                cx = hx + j * cell_w
                mult = game.counter_mult(form, key)
                is_col = key == game.intent_key
                if is_col:
                    pygame.draw.rect(surf, (46, 34, 32),
                                     (cx + 2, ry - 4, cell_w - 4, 42))
                if mult > 1.0:
                    txt, col = f"克 ×{mult:.2f}", (255, 202, 104)
                elif mult < 1.0:
                    txt, col = f"被克 ×{mult:.2f}", (255, 118, 96)
                else:
                    txt, col = "—", (140, 126, 116)
                self.fonts.text(surf, txt, 8, col,
                                (cx + cell_w // 2, ry + 10), center=True,
                                bold=mult != 1.0)
            pygame.draw.line(surf, (70, 44, 40), (x0 + 14, ry + 40),
                             (x0 + w - 14, ry + 40), 1)
        self.fonts.text(surf, "当前阵 / 当前招已高亮 · 按 M 关闭", 8,
                        (170, 150, 138), (x0 + w // 2, y0 + h - 16),
                        center=True)

    def _draw_fever_overlay(self, surf, game: core.Game, now: float) -> None:
        """Fever 压暗一档：整块固定 alpha，按 4 档切换（不逐帧插值）。"""
        step = max(1, int(self._fever_level * 4.0 + 0.999))
        alpha = (32, 64, 96, 120)[min(3, step - 1)]
        shade = self._hs(VIEW_W, VIEW_H)
        shade.fill((10, 4, 8, alpha))
        surf.blit(shade, (0, 0))
        if step >= 3:
            self.fonts.text(surf, "满堂彩", 12, (255, 210, 120),
                            (VIEW_W // 2, 214), center=True, bold=True,
                            outline=(80, 20, 4))
            self.fonts.text(surf,
                            f"伤害 ×2 · 判定放宽 · 剩余 {game.fever_remain:.1f}s",
                            8, (255, 190, 130), (VIEW_W // 2, 232),
                            center=True)


def draw_fever_gauge(surf: pygame.Surface, game: core.Game, x: int, y: int,
                     w: int, h: int, fonts: FontBook, burst: float = 1.0) -> str:
    """鼓劲槽液体：液面高度随充能上升，表面 2px 波浪跟 BPM；满槽涨破。"""
    if game.fever_active:
        frac = min(1.0, game.fever_remain / game.diff["fever_sec"]) \
            if game.diff["fever_sec"] > 0 else 0.0
        label = f"满堂彩 {game.fever_remain:.1f}s"
    elif game.now < game.fever_cd_until:
        frac = 0.0
        label = f"冷却 {game.fever_cd_until - game.now:.1f}s"
    else:
        frac = game.fever_ratio
        label = f"鼓劲槽 {game.fever_gauge}/{game.diff['fever_gauge']}"
    inner_x, inner_w, inner_h = x + 2, w - 4, h - 4
    pygame.draw.rect(surf, (22, 16, 20), (x, y, w, h))
    pygame.draw.rect(surf, (96, 68, 50), (x, y, w, h), 1)
    level = int(round(inner_h * max(0.0, min(1.0, frac))))
    top = y + 2 + inner_h - level
    body = (255, 120, 56) if game.fever_active else (238, 170, 64)
    if level > 0:
        pygame.draw.rect(surf, body, (inner_x, top, inner_w, level))
        # 液面波浪：每 2px 一柱，幅度 ±2px（整数），相位跟 BPM
        beat = max(1e-3, game.clock.beat_sec)
        for sx in range(0, inner_w, 2):
            off = gauge_wave_px(game.now, beat, sx)
            wy = max(y + 1, min(y + h - 2, top + off))
            surf.fill((255, 228, 150), (inner_x + sx, wy, 2, 1))
    # 刻度（25/50/75%）
    for k in (1, 2, 3):
        tx = inner_x + inner_w * k // 4
        pygame.draw.line(surf, (86, 58, 40), (tx, y + 1), (tx, y + h - 2))
    if game.fever_ratio >= float(HUD_TIMING["gauge_glow_threshold"]) \
            and not game.fever_active:
        pygame.draw.rect(surf, (255, 226, 150), (x - 1, y - 1, w + 2, h + 2), 1)
    if 0.0 <= burst < 1.0:
        # 涨破：整数像素扩散的 1px 金环 + 3 颗上溅液滴
        r = hud_step_px(9, burst)
        pygame.draw.rect(surf, (255, 232, 150),
                         (x - r, y - r, w + r * 2, h + r * 2), 1)
        for dx, dy in ((w // 4, -7), (w // 2, -11), (w * 3 // 4, -6)):
            surf.fill((255, 236, 170),
                      (x + dx, y + dy - hud_step_px(7, burst), 2, 2))
    return label


