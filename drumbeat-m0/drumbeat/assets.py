"""贴图素材加载层（M1-2）。

约定：像素素材放在 `assets/` 下，按「角色 / 敌人 / 环境 / UI」分类。
任一素材缺失或加载失败都返回 None，由 hud.py 回退到程序化绘制——**缺图不崩**。

对应策划案步骤：M1-2（贴图加载 + 缺图回退）。
"""
from __future__ import annotations

import os

import pygame

from .config import asset_dir

# 逻辑状态 → 素材文件名（按状态可多帧）
PLAYER_FILES = {
    "run": ["run_0.png", "run_1.png", "run_2.png", "run_3.png"],
    "air": ["jump.png"],
    "attack": ["charge.png"],
    "death": ["death.png"],
}
ENEMY_FILES = {
    "walk": ["walk.png"],
    "idle": ["idle.png"],
    "attack1": ["attack1.png"],
    "attack2": ["attack2.png"],
    "block": ["block.png"],
    "defeat": ["defeat_0.png", "defeat_1.png", "defeat_2.png"],
}
ENV_FILES = {
    "sky": "天空.png",
    "cloud1": "云朵_2.png",
    "cloud2": "云朵_3.png",
    "far": "远景层_1.png",
    "far2": "远景层_2.png",
    "far3": "远景层_3.png",
    "far4": "远景层_4.png",
    "far_new": "far_new.png",
    "far_L2": "far_L2.png",
    "mid": "level_map.png",
    "mid_L2": "level_map_L2.png",
    "fore": "前景层_1.png",
    "fore2": "前景层_2.png",
    "fore3": "前景层_3.png",
    "fore4": "前景层_4.png",
    "ground": "ground_tile.png",
}
UI_FILES = {"win": "win.png", "win_alt": "win_alt.png", "lose": "lose.png"}


class Assets:
    def __init__(self) -> None:
        self._raw: dict[str, pygame.Surface | None] = {}
        self._scaled: dict[tuple, pygame.Surface] = {}
        self._flipped: dict[int, pygame.Surface] = {}
        self._tinted: dict[tuple, pygame.Surface] = {}
        self.loaded = 0
        self.missing = 0
        self._preload()

    # ------------------------------------------------------------------ 加载
    def _load(self, rel: str) -> None:
        if rel in self._raw:
            return
        surf = None
        path = os.path.join(asset_dir(), rel)
        if os.path.isfile(path):
            try:
                img = pygame.image.load(path)
                if pygame.display.get_surface() is not None:
                    img = img.convert_alpha()
                surf = img
                self.loaded += 1
            except Exception:
                surf = None
        if surf is None:
            self.missing += 1
        self._raw[rel] = surf

    def _preload(self) -> None:
        for files in PLAYER_FILES.values():
            for f in files:
                self._load(f"characters/player/{f}")
        for files in ENEMY_FILES.values():
            for f in files:
                self._load(f"characters/enemy/{f}")
        for name in ENV_FILES.values():
            self._load(f"environment/{name}")
        for name in UI_FILES.values():
            self._load(f"ui/{name}")

    # ------------------------------------------------------------------ 查询
    def player(self, state: str, frame: int = 0):
        files = PLAYER_FILES.get(state)
        if not files:
            return None
        return self._raw.get(f"characters/player/{files[frame % len(files)]}")

    def enemy(self, state: str, frame: int = 0):
        files = ENEMY_FILES.get(state)
        if not files:
            return None
        return self._raw.get(f"characters/enemy/{files[frame % len(files)]}")

    def env(self, key: str):
        name = ENV_FILES.get(key)
        return self._raw.get(f"environment/{name}") if name else None

    def ui(self, key: str):
        name = UI_FILES.get(key)
        return self._raw.get(f"ui/{name}") if name else None

    # ------------------------------------------------------------------ 变换（带缓存）
    def scaled(self, surf: pygame.Surface, w: int, h: int) -> pygame.Surface:
        key = (id(surf), max(1, int(w)), max(1, int(h)))
        s = self._scaled.get(key)
        if s is None:
            s = pygame.transform.scale(surf, key[1:])   # 最近邻式缩放，保住像素边缘
            self._scaled[key] = s
        return s

    def flipped(self, surf: pygame.Surface) -> pygame.Surface:
        key = id(surf)
        s = self._flipped.get(key)
        if s is None:
            s = pygame.transform.flip(surf, True, False)
            self._flipped[key] = s
        return s

    def tinted(self, surf: pygame.Surface, color) -> pygame.Surface:
        """叠色版本（用于受击闪红），按 (表面, 颜色) 缓存。"""
        key = (id(surf), tuple(color))
        s = self._tinted.get(key)
        if s is None:
            s = surf.copy()
            s.fill(color, special_flags=pygame.BLEND_RGB_ADD)
            self._tinted[key] = s
        return s
