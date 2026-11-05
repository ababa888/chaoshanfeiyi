"""统一输入抽象层。

对应任务：T-B02。

把键鼠 / 手柄 / 触屏映射到同一套动作语义（移动 / 跳 / 攻击 / 抢步 / 下蹲），
并在**按键发生的那一刻**记录音频时钟时间戳——这是按键帧锚点判定的前提。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pygame

ACTIONS = ("left", "right", "up", "down", "jump", "attack", "dash", "finisher")


@dataclass
class Press:
    action: str
    audio_time: float


@dataclass
class InputFrame:
    held: dict[str, bool] = field(default_factory=dict)
    presses: list[Press] = field(default_factory=list)
    releases: list[str] = field(default_factory=list)
    quit_requested: bool = False

    def just_pressed(self, action: str) -> bool:
        return any(p.action == action for p in self.presses)

    def first_press_time(self, action: str) -> float | None:
        for p in self.presses:
            if p.action == action:
                return p.audio_time
        return None

    def axis_x(self) -> float:
        return (1.0 if self.held.get("right") else 0.0) - (1.0 if self.held.get("left") else 0.0)


_KEYMAP = {
    pygame.K_a: "left", pygame.K_LEFT: "left",
    pygame.K_d: "right", pygame.K_RIGHT: "right",
    pygame.K_w: "up", pygame.K_UP: "up",
    pygame.K_s: "down", pygame.K_DOWN: "down",
    pygame.K_SPACE: "jump", pygame.K_k: "jump",
    pygame.K_j: "attack", pygame.K_l: "dash",
    pygame.K_LSHIFT: "dash", pygame.K_RSHIFT: "dash",
    pygame.K_f: "finisher", pygame.K_e: "finisher",
}

_PAD_BUTTONS = {0: "jump", 1: "dash", 2: "attack", 3: "finisher"}


class InputManager:
    def __init__(self) -> None:
        self.frame = InputFrame()
        self.joysticks: list[pygame.joystick.Joystick] = []
        self.last_device = "keyboard"
        self._init_joysticks()

    def _init_joysticks(self) -> None:
        try:
            pygame.joystick.init()
            for i in range(pygame.joystick.get_count()):
                js = pygame.joystick.Joystick(i)
                js.init()
                self.joysticks.append(js)
        except Exception:
            self.joysticks = []

    def refresh_joysticks(self) -> None:
        self.joysticks = []
        self._init_joysticks()

    def poll(self, audio_time: float) -> InputFrame:
        """读取本帧事件并给每个按键打上音频时间戳。"""
        f = InputFrame(held=dict(self.frame.held))
        for event in pygame.event.get():
            self._handle(event, f, audio_time)
        self._poll_joystick_axes(f)
        self.frame = f
        return f

    def _handle(self, event: pygame.event.Event, f: InputFrame, t: float) -> None:
        if event.type == pygame.QUIT:
            f.quit_requested = True
        elif event.type == pygame.KEYDOWN:
            action = _KEYMAP.get(event.key)
            if action:
                self.last_device = "keyboard"
                if not f.held.get(action):
                    f.presses.append(Press(action, t))
                f.held[action] = True
        elif event.type == pygame.KEYUP:
            action = _KEYMAP.get(event.key)
            if action:
                f.held[action] = False
                f.releases.append(action)
        elif event.type == pygame.JOYBUTTONDOWN:
            action = _PAD_BUTTONS.get(event.button)
            if action:
                self.last_device = "gamepad"
                if not f.held.get(action):
                    f.presses.append(Press(action, t))
                f.held[action] = True
        elif event.type == pygame.JOYBUTTONUP:
            action = _PAD_BUTTONS.get(event.button)
            if action:
                f.held[action] = False
                f.releases.append(action)
        elif event.type == pygame.JOYHATMOTION:
            self.last_device = "gamepad"
            x, y = event.value
            self._set_axis(f, "left", x < 0, t)
            self._set_axis(f, "right", x > 0, t)
            self._set_axis(f, "down", y < 0, t)
            self._set_axis(f, "up", y > 0, t)
        elif event.type == pygame.JOYDEVICEADDED:
            self.refresh_joysticks()

    def _set_axis(self, f: InputFrame, action: str, active: bool, t: float) -> None:
        if active and not f.held.get(action):
            f.presses.append(Press(action, t))
        f.held[action] = active

    def _poll_joystick_axes(self, f: InputFrame) -> None:
        if not self.joysticks:
            return
        try:
            ax = self.joysticks[0].get_axis(0)
        except Exception:
            return
        dead = 0.35
        if abs(ax) > dead:
            self._set_axis(f, "left", ax < 0, self.frame_audio_time)
            self._set_axis(f, "right", ax > 0, self.frame_audio_time)

    @property
    def frame_audio_time(self) -> float:
        return getattr(self, "_frame_t", 0.0)

    def set_frame_time(self, t: float) -> None:
        self._frame_t = t