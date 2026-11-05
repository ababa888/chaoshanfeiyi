"""程序化锣鼓/铜镲音效（只依赖 pygame 与标准库，不使用 numpy）。

用 44100Hz / 单声道 / 16bit 的原始 PCM 拼 Sound(buffer=...)，启动时一次性合成。
音频只是气氛层：mixer 初始化失败时自动静音，不影响判定与画面。
"""
from __future__ import annotations

import array
import math
import random

import pygame

SR = 44100


def _pcm(duration: float, fn) -> bytes:
    n = int(SR * duration)
    buf = array.array("h")
    for i in range(n):
        t = i / SR
        v = fn(t)
        v = max(-1.0, min(1.0, v))
        buf.append(int(v * 32767))
    return buf.tobytes()


def _drum(duration=0.40, base=82.0, amp=0.95, seed=1) -> bytes:
    rng = random.Random(seed)

    def fn(t):
        env = math.exp(-t / 0.075)
        f = base * (1.0 + 1.8 * math.exp(-t / 0.045))
        body = math.sin(2 * math.pi * f * t) * 0.72
        click = rng.uniform(-1, 1) * math.exp(-t / 0.012) * 0.28
        return (body + click) * env * amp

    return _pcm(duration, fn)


def _cymbal(duration=0.34, amp=0.62, seed=2) -> bytes:
    rng = random.Random(seed)

    def fn(t):
        env = math.exp(-t / 0.09)
        noise = rng.uniform(-1, 1) * 0.55
        shimmer = math.sin(2 * math.pi * 3150 * t) * 0.20
        return (noise + shimmer) * env * amp

    return _pcm(duration, fn)


def _gong(duration=0.55, amp=0.55, seed=3) -> bytes:
    def fn(t):
        env = math.exp(-t / 0.22)
        p = (math.sin(2 * math.pi * 196 * t) * 0.40
             + math.sin(2 * math.pi * 294 * t) * 0.24
             + math.sin(2 * math.pi * 415 * t) * 0.14)
        attack = min(1.0, t / 0.01)
        return p * env * amp * attack

    return _pcm(duration, fn)


def _deep_gong(duration=0.85, amp=0.52) -> bytes:
    """同类型连续招式的第二招：更低、更长的锣声，作为「长蓄」听感差异。"""
    def fn(t):
        env = math.exp(-t / 0.34)
        p = (math.sin(2 * math.pi * 130 * t) * 0.42
             + math.sin(2 * math.pi * 196 * t) * 0.26
             + math.sin(2 * math.pi * 277 * t) * 0.16)
        attack = min(1.0, t / 0.02)
        return p * env * amp * attack

    return _pcm(duration, fn)


def _thud(duration=0.20, amp=0.55) -> bytes:
    def fn(t):
        env = math.exp(-t / 0.045)
        return math.sin(2 * math.pi * 140 * t) * env * amp

    return _pcm(duration, fn)


def _muted(duration=0.28, amp=0.45, seed=4) -> bytes:
    rng = random.Random(seed)

    def fn(t):
        env = math.exp(-t / 0.10)
        return (math.sin(2 * math.pi * 70 * t) * 0.4
                + rng.uniform(-1, 1) * 0.25) * env * amp

    return _pcm(duration, fn)


class Audio:
    """极小音效封装；任何失败都降级为静音。"""

    def __init__(self) -> None:
        self.ok = False
        self.sounds: dict[str, pygame.mixer.Sound] = {}

    def init(self) -> bool:
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=SR, size=-16, channels=1, buffer=512)
            pygame.mixer.set_num_channels(16)
            self.sounds = {
                "dong": pygame.mixer.Sound(buffer=_drum()),
                "cai": pygame.mixer.Sound(buffer=_cymbal()),
                "tai": pygame.mixer.Sound(buffer=_gong()),
                "hit": pygame.mixer.Sound(buffer=_thud()),
                "fail": pygame.mixer.Sound(buffer=_muted()),
                "j": pygame.mixer.Sound(buffer=_drum(duration=0.24, base=96.0, amp=0.75, seed=11)),
                "k": pygame.mixer.Sound(buffer=_gong(duration=0.30, amp=0.45, seed=12)),
                "l": pygame.mixer.Sound(buffer=_cymbal(duration=0.22, amp=0.42, seed=13)),
                "read": pygame.mixer.Sound(buffer=_gong(duration=0.40, amp=0.50, seed=21)),
                "read_long": pygame.mixer.Sound(buffer=_deep_gong()),
                "counter": pygame.mixer.Sound(buffer=_cymbal(duration=0.20, amp=0.55, seed=22)),
            }
            self.ok = True
        except Exception:
            self.ok = False
            self.sounds = {}
        return self.ok

    def play(self, name: str) -> None:
        if not self.ok:
            return
        snd = self.sounds.get(name)
        if snd is not None:
            try:
                snd.play()
            except Exception:
                pass

    def beat(self, strong: bool) -> None:
        self.play("dong" if strong else "cai")

    def key(self, key: str) -> None:
        self.play({"J": "j", "K": "k", "L": "l"}.get(key, "hit"))

    def grade(self, grade: str | None) -> None:
        if grade == "perfect":
            self.play("tai")
        elif grade == "good":
            self.play("hit")
        else:
            self.play("fail")

    def fail(self) -> None:
        self.play("fail")
