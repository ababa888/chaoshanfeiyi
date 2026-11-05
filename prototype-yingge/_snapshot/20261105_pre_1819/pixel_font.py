"""HUD 位图字体：Fusion Pixel 开源像素字库 + 原生输出分辨率排版。

字库（`assets_gen/fonts/`，均为 SIL OFL 1.1，来源见 README 第十五轮）：
- fusion-pixel-8px-monospaced-zh_hans.ttf
- fusion-pixel-10px-monospaced-zh_hans.ttf
- fusion-pixel-12px-monospaced-zh_hans.ttf

设计约束：
- 字号阶梯按**输出像素**：16 / 20 / 24 / 30（逻辑字号 8/10/12/≥14 × 呈现倍率）。
  原生网格 × 整数倍渲染，运行期不做任何插值/缩放。
- ASCII 与中文同库：等宽（monospaced）版保证数字等宽、大小写齐全，不再把小写映射成大写。
- 所有字形 alpha 只有 0/255；中文四周留 1 个原生像素内边距（2× 输出下为 2px），
  既把墨迹覆盖率压到 12%–45%，也保证相邻笔画至少 1px 间隙。
- 硬投影为纯色不透明，偏移 1 个原生像素（2× 输出下为 2px）。
- 中文标点（，。、；：！？ 及收括号）按半宽推进，避免出现方框或撑开版面。
"""
from __future__ import annotations

import os

import pygame

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets_gen", "fonts")
FONT_FILES = {
    8: "fusion-pixel-8px-monospaced-zh_hans.ttf",
    10: "fusion-pixel-10px-monospaced-zh_hans.ttf",
    12: "fusion-pixel-12px-monospaced-zh_hans.ttf",
}
LICENSE_FILE = "OFL.txt"
FONT_SOURCE = ("Fusion Pixel Font v2026.10.25 · TakWolf · "
               "SIL Open Font License 1.1")
LICENSE_SPDX = "OFL-1.1"

# 输出像素字号阶梯（2× 呈现）。1× 测试/调试时为 8/10/12/12。
TIERS = (16, 20, 24, 30)
MIN_SIZE = 8            # 逻辑字号下限（2× 输出 = 16px）
LINE_RATIO = 1.3        # 行高 = 字号 × 1.3 后取整

_SHADOW = (10, 6, 12, 255)
_CACHE_LIMIT = 900

# 半宽标点：全角字形只占左半格，推进也减半。
_HALF_PUNCT = set("，。、；：！？）】」』〉》…")


def _is_ascii(ch: str) -> bool:
    return ord(ch) < 128


def _spec(size: float, scale: int) -> tuple[int, int]:
    """逻辑字号 + 呈现倍率 → (原生网格, 整数倍率)。"""
    size = int(round(size))
    if scale == 2:
        if size <= 8:
            return 8, 2
        if size <= 11:
            return 10, 2
        if size <= 13:
            return 12, 2
        return 10, 3
    if scale == 1:
        if size >= 14:          # 世界层大号标记：12px 网格 ×2（逻辑 24px）
            return 12, 2
        if size <= 9:
            return 8, 1
        if size <= 11:
            return 10, 1
        return 12, 1
    if size <= 8:
        return 8, scale
    if size <= 11:
        return 10, scale
    return 12, scale


def font_path(grid: int) -> str:
    return os.path.join(FONT_DIR, FONT_FILES[grid])


def license_present() -> bool:
    return os.path.exists(os.path.join(FONT_DIR, LICENSE_FILE))


class PixelFont:
    """位图字体 + 内容寻址缓存；接口与旧 FontBook 兼容。"""

    def __init__(self) -> None:
        self._fonts: dict[tuple[int, int], pygame.font.Font] = {}
        self._masks: dict[tuple[str, int, int], pygame.Surface] = {}
        self._tints: dict[tuple[int, tuple], pygame.Surface] = {}
        self.cache: dict[tuple, pygame.Surface] = {}
        self.rects: list[pygame.Rect] = []
        self.used_sizes: set[int] = set()
        self.missing: set[str] = set()
        self.source = FONT_SOURCE
        self.license = LICENSE_SPDX

    # ---------------------------------------------------------------- 字体
    def _font(self, grid: int, mult: int) -> pygame.font.Font:
        key = (grid, mult)
        f = self._fonts.get(key)
        if f is None:
            path = font_path(grid)
            if os.path.exists(path):
                f = pygame.font.Font(path, grid * mult)
            else:                      # 兜底：缺字库时退回系统等宽字体
                f = pygame.font.SysFont("Consolas", grid * mult, bold=False)
            self._fonts[key] = f
        return f

    # ---------------------------------------------------------------- 字形
    def _mask(self, ch: str, grid: int, mult: int) -> pygame.Surface:
        """单字硬边白色掩码：0/255 alpha + 中文 1 原生像素内边距。"""
        key = (ch, grid, mult)
        hit = self._masks.get(key)
        if hit is not None:
            return hit
        f = self._font(grid, mult)
        try:
            raw = f.render(ch, False, (255, 255, 255))
        except Exception:
            raw = f.render("?", False, (255, 255, 255))
        ck = raw.get_at((0, 0))
        img = pygame.Surface(raw.get_size(), pygame.SRCALPHA)
        raw.set_colorkey(ck)
        img.blit(raw, (0, 0))
        if not _is_ascii(ch):
            pad = mult               # 1 个原生像素
            cell = pygame.Surface((img.get_width() + pad * 2,
                                   img.get_height() + pad * 2),
                                  pygame.SRCALPHA)
            cell.blit(img, (pad, pad))
            img = cell
        self._masks[key] = img
        return img

    def _tint(self, cell: pygame.Surface, col) -> pygame.Surface:
        """白色掩码 → 指定纯色（alpha 保持 0/255，无灰阶）。"""
        col = tuple(col)[:3]
        key = (id(cell), col)
        hit = self._tints.get(key)
        if hit is not None:
            return hit
        out = cell.copy()
        out.fill(col + (255,), special_flags=pygame.BLEND_RGBA_MULT)
        if len(self._tints) > 4096:
            self._tints.clear()
        self._tints[key] = out
        return out

    def glyph(self, ch: str, size: float, scale: int = 2
              ) -> tuple[pygame.Surface, int]:
        """返回 (字形格子, 推进宽度)，供自测直接检查 alpha/覆盖率/间隙。"""
        grid, mult = _spec(size, scale)
        cell = self._mask(ch, grid, mult)
        adv = cell.get_width()
        if ch in _HALF_PUNCT:
            adv = max(1, adv // 2)
        return cell, adv

    def advance(self, ch: str, size: float, scale: int = 2) -> int:
        return self.glyph(ch, size, scale)[1]

    # ---------------------------------------------------------------- 排版
    def _line_h(self, size: float, scale: int) -> int:
        grid, mult = _spec(size, scale)
        out = grid * mult
        return int(round(out * LINE_RATIO))

    def measure(self, s: str, size: int) -> tuple[int, int]:
        """返回逻辑像素宽高（HUD 布局与旧调用兼容）。"""
        scale = 2
        grid, mult = _spec(size, scale)
        w = sum(self.advance(ch, size, scale) for ch in s)
        h = self._line_h(size, scale)
        return (w + scale - 1) // scale, (h + scale - 1) // scale

    def _compose(self, s: str, size: float, color, bold: bool,
                 shadow: bool, outline) -> pygame.Surface:
        grid, mult = _spec(size, 2)
        color = tuple(color)
        line_h = self._line_h(size, 2)
        cells = []
        w = 0
        for ch in s:
            cell, adv = self.glyph(ch, size, 2)
            cells.append((cell, w, adv))
            w += adv
        pad = 2 if shadow else 0    # 2× 输出下投影偏移 2px
        width = max(1, w + pad)
        img = pygame.Surface((width, line_h + pad), pygame.SRCALPHA)

        def paint(dx: int, dy: int, col) -> None:
            for cell, x, _adv in cells:
                # 字格垂直居中：行高 > 字高时上下各让一半
                gy = (line_h - cell.get_height()) // 2
                img.blit(self._tint(cell, col), (x + dx, gy + dy))

        if shadow:                       # 纯色不透明硬投影，2× 下偏移 2px
            paint(2, 2, _SHADOW[:3])
        if outline:
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                           (-1, -1), (1, -1), (-1, 1), (1, 1)):
                paint(ox, oy, tuple(outline))
        paint(0, 0, color)
        return img

    # ---------------------------------------------------------------- 绘制
    def text(self, surf: pygame.Surface, s: str, size: int, color, pos,
             center: bool = False, bold: bool = False, outline=None,
             alpha: int = 255, shadow: bool = True) -> pygame.Rect:
        scale = int(getattr(surf, "_hud_scale", 1) or 1)
        target = getattr(surf, "_phys", surf)
        size = max(MIN_SIZE, int(round(size)))
        grid, mult = _spec(size, scale)
        if scale >= 2:               # 只统计 HUD 原生输出层的字号
            self.used_sizes.add(grid * mult)
        key = (s, size, scale, tuple(color), bool(shadow),
               tuple(outline) if outline else None)
        img = self.cache.get(key)
        if img is None:
            if scale == 2:
                img = self._compose(s, size, color, bold, shadow, outline)
            else:
                # 仅测试/调试用的 1× 原生路径
                img = self._compose_scaled(s, size, scale, color,
                                           shadow, outline)
            if len(self.cache) >= _CACHE_LIMIT:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = img
        if alpha < 255:
            img.set_alpha(max(0, int(alpha)))
        rect = img.get_rect()
        x = int(round(pos[0] * scale))
        y = int(round(pos[1] * scale))
        if center:
            rect.center = (x, y)
        else:
            rect.topleft = (x, y)
        pygame.Surface.blit(target, img, rect)
        if alpha < 255:
            img.set_alpha(255)
        r = pygame.Rect(rect.x // scale, rect.y // scale,
                        rect.w // scale, rect.h // scale)
        self.rects.append(r)
        return r

    def _compose_scaled(self, s: str, size: int, scale: int, color,
                        shadow: bool, outline) -> pygame.Surface:
        """1× / 3× 等非 2× 输出时的原生排版（网格 × scale）。"""
        grid, mult = _spec(size, scale)
        line_h = int(round(grid * mult * LINE_RATIO))
        cells = []
        w = 0
        for ch in s:
            cell = self._mask(ch, grid, mult)
            adv = cell.get_width()
            if ch in _HALF_PUNCT:
                adv = max(1, adv // 2)
            cells.append((cell, w))
            w += adv
        pad = scale if shadow else 0
        img = pygame.Surface((max(1, w + pad), line_h + pad), pygame.SRCALPHA)

        def paint(dx: int, dy: int, col) -> None:
            for cell, x in cells:
                gy = (line_h - cell.get_height()) // 2
                img.blit(self._tint(cell, col), (x + dx, gy + dy))

        if shadow:
            paint(scale, scale, _SHADOW[:3])
        if outline:
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                paint(ox, oy, tuple(outline))
        paint(0, 0, tuple(color))
        return img

    def clear(self) -> None:
        """缓存失效：重开 / 换语言时整表清空。"""
        self.cache.clear()


# 自测/工具用的模块级便捷入口（共享一个默认实例）
_DEFAULT = PixelFont()


def glyph(ch: str, size: float, scale: int = 2
          ) -> tuple[pygame.Surface, int]:
    return _DEFAULT.glyph(ch, size, scale)


def advance(ch: str, size: float, scale: int = 2) -> int:
    return _DEFAULT.advance(ch, size, scale)


def measure(s: str, size: int) -> tuple[int, int]:
    return _DEFAULT.measure(s, size)


def _compose(s: str, size: float, color, bold: bool,
             shadow: bool, outline) -> pygame.Surface:
    return _DEFAULT._compose(s, size, color, bold, shadow, outline)
