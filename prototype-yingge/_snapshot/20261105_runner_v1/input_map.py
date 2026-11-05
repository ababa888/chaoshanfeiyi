"""输入路由：键盘 + 手柄统一映射到三条鼓令。

配置在 `prototype-yingge/config/controls.json`，可改键；手柄按钮号同样配置化。
键盘按键按「最近整拍吸附」由 core.press 完成，属于输入缓冲。
"""
from __future__ import annotations

import json
import os

import pygame

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(ROOT, "config", "controls.json")

DEFAULT = {
    "keyboard": {"attack": "j", "march": "k", "defend": "l"},
    "gamepad": {"attack": 0, "march": 1, "defend": 2, "restart": 3},
    "gamepad_axis": {"attack": 5, "march": 2, "defend": 4},
}


def _key_const(name: str) -> int | None:
    """把 'j' / 'space' / 'left' 之类的名字转成 pygame 键值。"""
    if not name:
        return None
    name = str(name).lower().strip()
    if name in ("space", "spacebar"):
        return pygame.K_SPACE
    if len(name) == 1:
        return getattr(pygame, "K_" + name, None)
    return getattr(pygame, "K_" + name.upper(), None)


class InputMap:
    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = path
        self.cfg = dict(DEFAULT)
        self.error = ""
        self._load()
        self.keyboard: dict[int, str] = {}
        for action, name in self.cfg["keyboard"].items():
            code = _key_const(name)
            if code is not None:
                self.keyboard[code] = action
        self.pad_buttons: dict[int, str] = {}
        for action, btn in self.cfg["gamepad"].items():
            try:
                self.pad_buttons[int(btn)] = action
            except (TypeError, ValueError):
                pass
        self.pad_axes: dict[int, str] = {}
        for action, axis in self.cfg.get("gamepad_axis", {}).items():
            try:
                self.pad_axes[int(axis)] = action
            except (TypeError, ValueError):
                pass
        self.joysticks: list[pygame.joystick.Joystick] = []
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            js = pygame.joystick.Joystick(i)
            js.init()
            self.joysticks.append(js)
        self._axis_prev: dict[tuple[int, int], float] = {}

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT.items()}
            for section, value in data.items():
                if isinstance(value, dict) and section in merged:
                    merged[section].update(value)
                else:
                    merged[section] = value
            self.cfg = merged
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    # -------------------------------------------------------------- 事件
    def action_from_key(self, key: int) -> str | None:
        return self.keyboard.get(key)

    def action_from_button(self, button: int) -> str | None:
        return self.pad_buttons.get(button)

    def poll_axes(self) -> list[str]:
        """扳机/摇杆轴越过阈值时也映射成指令（手柄接口预留）。"""
        out: list[str] = []
        for ji, js in enumerate(self.joysticks):
            for axis, action in self.pad_axes.items():
                try:
                    val = js.get_axis(axis)
                except Exception:
                    continue
                key = (ji, axis)
                prev = self._axis_prev.get(key, 0.0)
                if abs(val) >= 0.65 and abs(prev) < 0.35:
                    out.append(action)
                self._axis_prev[key] = val
        return out

    def key_label(self, action: str) -> str:
        name = str(self.cfg["keyboard"].get(action, "?")).upper()
        return name

    def pad_label(self, action: str) -> str:
        btn = self.cfg["gamepad"].get(action)
        return f"手柄 {btn}" if btn is not None else "手柄 —"

    def hint(self, action: str) -> str:
        if self.joysticks:
            return f"{self.key_label(action)} / {self.pad_label(action)}"
        return self.key_label(action)

    def has_gamepad(self) -> bool:
        return bool(self.joysticks)
