"""程序化锣鼓合成。

M0 不依赖外部音频素材：用 numpy 现场合成锣鼓经所需的六件乐器与反馈音，
保证 exe 自包含、且判定点音色清晰可辨（大鼓重拍必须突出）。

对应任务：T-D01（分层锣鼓乐素材，占位）。
"""
from __future__ import annotations

import numpy as np

SR = 44100


def _norm(x: np.ndarray, amp: float) -> np.ndarray:
    m = float(np.max(np.abs(x)))
    if m > 1e-9:
        x = x / m
    return (x * amp).astype(np.float32)


def _decay(n: int, tau: float) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SR
    return np.exp(-t / tau)


def _lp(x: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """一阶低通（单极点）。仅在合成期调用，样本量小，循环开销可接受。"""
    a = float(np.exp(-2.0 * np.pi * cutoff_hz / SR))
    b = 1.0 - a
    y = np.empty_like(x)
    prev = 0.0
    for i in range(len(x)):
        prev = b * x[i] + a * prev
        y[i] = prev
    return y


def _hp(x: np.ndarray, cutoff_hz: float) -> np.ndarray:
    return x - _lp(x, cutoff_hz)


def big_drum(rng: np.random.Generator, dur: float = 0.50, freq: float = 68.0, amp: float = 0.95) -> np.ndarray:
    """咚：大鼓。低音主拍，节奏骨架，判定点落在这里。"""
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float64) / SR
    f = freq * (1.0 + 1.7 * np.exp(-t / 0.030))
    phase = 2.0 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * _decay(n, 0.17)
    click = _lp(rng.uniform(-1.0, 1.0, n), 3200.0) * _decay(n, 0.010)
    return _norm(body * 0.92 + click * 0.55, amp)


def big_gong(rng: np.random.Generator, dur: float = 1.50, base: float = 178.0, amp: float = 0.62) -> np.ndarray:
    """匡：大锣。强拍强调，合拍成功的主反馈音。"""
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float64) / SR
    partials = [(1.00, 1.00, 0.95), (2.37, 0.55, 0.62), (3.41, 0.40, 0.46), (5.13, 0.24, 0.30), (7.20, 0.14, 0.20)]
    x = np.zeros(n, dtype=np.float64)
    for ratio, a, tau in partials:
        ph = rng.uniform(0.0, 2.0 * np.pi)
        x += a * np.sin(2.0 * np.pi * base * ratio * t + ph) * _decay(n, tau)
    x += _lp(rng.uniform(-1.0, 1.0, n), 7000.0) * _decay(n, 0.018) * 0.35
    return _norm(x, amp)


def cymbal(rng: np.random.Generator, dur: float = 0.60, bright: float = 7000.0, tau: float = 0.17, amp: float = 0.48) -> np.ndarray:
    """才 / 七：大钹与小钹。八分填充，提示节奏密度，不作判定点。"""
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float64) / SR
    x = _hp(rng.uniform(-1.0, 1.0, n), bright)
    x = _hp(x, bright * 0.45)
    x *= _decay(n, tau)
    for f, a in [(4300.0, 0.14), (6400.0, 0.10), (9200.0, 0.06)]:
        x += a * np.sin(2.0 * np.pi * f * t) * _decay(n, tau * 0.8)
    return _norm(x, amp)


def small_gong(rng: np.random.Generator, dur: float = 0.45, base: float = 620.0, amp: float = 0.34) -> np.ndarray:
    """台：小锣。点描，细碎高音。"""
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float64) / SR
    x = np.zeros(n, dtype=np.float64)
    for ratio, a, tau in [(1.0, 1.0, 0.28), (2.71, 0.45, 0.18), (4.62, 0.22, 0.11)]:
        ph = rng.uniform(0.0, 2.0 * np.pi)
        x += a * np.sin(2.0 * np.pi * base * ratio * t + ph) * _decay(n, tau)
    x += _hp(rng.uniform(-1.0, 1.0, n), 9000.0) * _decay(n, 0.010) * 0.30
    return _norm(x, amp)


def drum_roll(rng: np.random.Generator, dur: float = 0.55, amp: float = 0.42) -> np.ndarray:
    """嘟：鼓滚奏。过门与转场。"""
    n = int(SR * dur)
    out = np.zeros(n, dtype=np.float64)
    hit_len = int(SR * 0.05)
    step = int(SR * 0.028)
    i = 0
    while i + hit_len < n:
        hit = big_drum(rng, dur=0.05, freq=95.0, amp=1.0) * (0.55 + 0.45 * (i / n))
        out[i:i + hit_len] += hit[:hit_len]
        i += step
    return _norm(out, amp)


def muted(rng: np.random.Generator, dur: float = 0.22, amp: float = 0.42) -> np.ndarray:
    """闷：未合拍的提示音。与清亮的大鼓可区分。"""
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float64) / SR
    body = np.sin(2.0 * np.pi * 92.0 * t) * _decay(n, 0.055)
    thud = _lp(rng.uniform(-1.0, 1.0, n), 420.0) * _decay(n, 0.030)
    return _norm(body * 0.8 + thud * 0.7, amp)


class Bank:
    """合成样本库。启动时一次性生成，运行期只做混音。"""

    def __init__(self, seed: int = 20261012):
        rng = np.random.default_rng(seed)
        self.samples: dict[str, np.ndarray] = {
            "咚": big_drum(rng),
            "匡": big_gong(rng),
            "才": cymbal(rng, dur=0.60, bright=7000.0, tau=0.17, amp=0.48),
            "七": cymbal(rng, dur=0.32, bright=11000.0, tau=0.075, amp=0.34),
            "台": small_gong(rng),
            "嘟": drum_roll(rng),
            "号角": self._horn(rng),
        }
        self.feedback: dict[str, np.ndarray] = {
            # 完美合拍：锣 + 钹双响
            "perfect": self._mix(self.samples["匡"], self.samples["才"], 0.85),
            # 合拍：钹单音
            "good": self.samples["才"].copy(),
            # 未合拍：闷音
            "off": muted(rng),
            # 命中 / 受击
            "hit": self._mix(big_drum(rng, dur=0.18, freq=120.0, amp=0.55), cymbal(rng, dur=0.18, bright=9000.0, tau=0.06, amp=0.30), 0.8),
            "hurt": muted(rng, dur=0.3, amp=0.55),
            "parry": self._mix(big_gong(rng, dur=0.9, base=240.0, amp=0.6), cymbal(rng, dur=0.4, bright=8000.0, tau=0.12, amp=0.4), 0.9),
        }

    @staticmethod
    def _horn(rng: np.random.Generator, dur: float = 0.9, amp: float = 0.34) -> np.ndarray:
        n = int(SR * dur)
        t = np.arange(n, dtype=np.float64) / SR
        x = np.zeros(n, dtype=np.float64)
        for f, a in [(233.0, 1.0), (349.0, 0.5), (466.0, 0.32), (699.0, 0.16)]:
            x += a * np.sin(2.0 * np.pi * f * t + rng.uniform(0, 6.28))
        env = np.minimum(1.0, t / 0.06) * np.exp(-np.maximum(0.0, t - 0.35) / 0.35)
        return _norm(x * env, amp)

    @staticmethod
    def _mix(a: np.ndarray, b: np.ndarray, amp: float) -> np.ndarray:
        n = max(len(a), len(b))
        out = np.zeros(n, dtype=np.float64)
        out[:len(a)] += a
        out[:len(b)] += b
        return _norm(out, amp)