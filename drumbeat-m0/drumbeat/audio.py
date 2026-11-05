"""音频时钟与混音引擎。

对应任务：T-A01（音频时钟判定底座）、T-A02（鼓点事件前瞻调度，调度逻辑在 tempo.py）。

核心要求（来自详细设计文档 10_technical 与判定表 technical_implementation）：
判定必须由音频时钟驱动，不使用帧时间；帧率波动不得影响判定结果。

实现方式：sounddevice 输出流回调中累加已送出的帧数作为音频时钟，
并在回调之间用 perf_counter 做亚块插值，得到连续、单调、锁定音频的时钟。
"""
from __future__ import annotations

import threading
import time

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - 仅在无音频后端时触发
    sd = None


class AudioEngine:
    def __init__(self, samplerate: int = 44100, blocksize: int = 512, gain: float = 0.85):
        self.sr = int(samplerate)
        self.blocksize = int(blocksize)
        self.gain = float(gain)
        self._clock = (0, time.perf_counter())  # (已送出帧数, 该值写入时的 perf_counter)
        self._voices: list[list] = []           # [start_frame, np.ndarray(float32)]
        self._lock = threading.Lock()
        self._stream = None
        self.output_latency = 0.0
        self.started = False
        self.available = sd is not None

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> bool:
        if not self.available:
            return False
        try:
            self._stream = sd.OutputStream(
                samplerate=self.sr,
                blocksize=self.blocksize,
                channels=1,
                dtype="float32",
                latency="low",
                callback=self._callback,
            )
            self._stream.start()
            try:
                lat = self._stream.latency
                self.output_latency = float(lat[1] if isinstance(lat, (tuple, list)) else lat)
            except Exception:
                self.output_latency = 0.0
            self.started = True
            return True
        except Exception:
            self._stream = None
            self.started = False
            self.available = False
            return False

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.started = False

    # ------------------------------------------------------------------ 回调
    def _callback(self, outdata, frames, time_info, status):  # noqa: ARG002
        buf = np.zeros(frames, dtype=np.float32)
        start = self._clock[0]
        end = start + frames
        with self._lock:
            keep: list[list] = []
            for voice in self._voices:
                v_start, data = voice
                if v_start >= end:
                    keep.append(voice)
                    continue
                if v_start <= start:
                    skip = start - v_start
                    if skip >= len(data):
                        continue
                    seg = data[skip:]
                    off = 0
                else:
                    seg = data
                    off = v_start - start
                n = min(len(seg), frames - off)
                if n > 0:
                    buf[off:off + n] += seg[:n]
                    rest = seg[n:]
                    if rest.size:
                        keep.append([end, rest])
                # n <= 0 表示该声部完全落在本块之后，理论上不会走到
            self._voices = keep
            self._clock = (end, time.perf_counter())
        np.clip(buf * self.gain, -1.0, 1.0, out=buf)
        outdata[:, 0] = buf

    # ------------------------------------------------------------------ 时钟
    def audio_time(self) -> float:
        """玩家此刻「听到」的音频时间（秒）。已扣除设备输出延迟。

        帧 0 对应 audio_time == 0，因此调度时需加上延迟帧数。
        """
        frames, perf = self._clock
        lat_frames = self.output_latency * self.sr
        return (frames - lat_frames) / self.sr + (time.perf_counter() - perf)

    def _frame_for(self, t: float) -> int:
        return int(round(t * self.sr)) + int(round(self.output_latency * self.sr))

    # ------------------------------------------------------------------ 调度
    def schedule(self, t: float, data: np.ndarray, gain: float = 1.0) -> None:
        """在音频时间 t 处触发一个样本。"""
        if data is None:
            return
        f = self._frame_for(t)
        with self._lock:
            self._voices.append([f, (data * gain).astype(np.float32)])

    def pending_voices(self) -> int:
        with self._lock:
            return len(self._voices)


class NullAudioEngine(AudioEngine):
    """无音频设备时的降级实现：用 perf_counter 提供时钟，仍可跑通逻辑与渲染。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.available = False
        self._t0 = time.perf_counter()

    def start(self) -> bool:
        self.started = True
        self._t0 = time.perf_counter()
        return True

    def stop(self) -> None:
        self.started = False

    def audio_time(self) -> float:
        return time.perf_counter() - self._t0

    def schedule(self, t: float, data: np.ndarray, gain: float = 1.0) -> None:
        return None