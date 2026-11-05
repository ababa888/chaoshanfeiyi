"""分层离散换板与鼓点前瞻调度。

对应任务：T-A04（分层离散换板）、T-A02（前瞻调度）。

设计约束（来自 ADR-001 与详细设计文档）：
- 换板只在**小节边界**发生，且保持拍相位连续（不重置小节）
- 层内允许 ±8% 时间拉伸
- 移速阈值附近设 ±0.5 单位/秒迟滞，避免频繁换板
- 鼓点事件提前 150–250ms 排入音频队列
"""
from __future__ import annotations

from .audio import AudioEngine
from .config import DATA
from .synth import Bank


class MusicDirector:
    LOOKAHEAD_S = 0.20

    def __init__(self, audio: AudioEngine, bank: Bank):
        self.audio = audio
        self.bank = bank
        self.layers = DATA.layers
        self.bar_beats = DATA.bar_beats
        self.event_offsets = DATA.event_offsets
        self.n_events = len(self.event_offsets)
        self.hysteresis = float(DATA.transition["hysteresis_speed"])
        self.micro = 1.0 + float(DATA.transition["micro_adjust_pct"]) / 100.0

        self.layer_index = 0
        self.bpm = float(self.layers[0]["bpm"])
        self.beat_pos = 0.0
        self.last_t = audio.audio_time()
        self._last_bar = 0
        self._pending_layer: int | None = None
        self._ev_i = 0
        self._switch_flash_until = 0.0

    # ------------------------------------------------------------------ 重置
    def reset(self) -> None:
        self.layer_index = 0
        self.bpm = float(self.layers[0]["bpm"])
        self.beat_pos = 0.0
        self.last_t = self.audio.audio_time()
        self._last_bar = 0
        self._pending_layer = None
        self._ev_i = 0
        self._switch_flash_until = 0.0

    # ------------------------------------------------------------------ 每帧
    def update(self, player_speed: float) -> None:
        now = self.audio.audio_time()
        dt = now - self.last_t
        self.last_t = now
        if dt < 0.0:
            dt = 0.0
        if dt > 0.25:          # 暂停/卡顿后不追帧，避免判定点错位
            dt = 0.0
        self.beat_pos += dt * self.bpm / 60.0
        self._maybe_switch(player_speed, now)
        self._schedule(now)

    # ------------------------------------------------------------------ 换板
    def _layer_for_speed(self, speed: float) -> int:
        h = self.hysteresis
        cur = self.layer_index
        if cur == 0:
            if speed > 4.0 + h:
                return 2 if speed > 8.0 else 1
            return 0
        if cur == 1:
            if speed < 4.0 - h:
                return 0
            if speed > 8.0 + h:
                return 2
            return 1
        if cur == 2:
            if speed < 8.0 - h:
                return 1 if speed >= 4.0 - h else 0
            return 2
        return cur

    def _maybe_switch(self, speed: float, now: float) -> None:
        desired = self._layer_for_speed(speed)
        if desired != self.layer_index:
            self._pending_layer = desired
        bar = int(self.beat_pos // self.bar_beats)
        if bar != self._last_bar:
            self._last_bar = bar
            if self._pending_layer is not None and self._pending_layer != self.layer_index:
                self.layer_index = self._pending_layer
                self.bpm = float(self.layers[self.layer_index]["bpm"])
                self._switch_flash_until = now + 0.6
            self._pending_layer = None

    def force_layer(self, layer_id: str) -> None:
        """供调试面板强制指定板式（极板等 manual_only 板式靠此进入）。"""
        for i, l in enumerate(self.layers):
            if l["id"] == layer_id:
                self._pending_layer = i
                # 立刻在小节边界生效：把相位推到下一小节
                nxt = (int(self.beat_pos // self.bar_beats) + 1) * self.bar_beats
                self.beat_pos = max(self.beat_pos, nxt - 1e-3)
                self._last_bar = int(self.beat_pos // self.bar_beats)
                self._maybe_switch(0.0, self.audio.audio_time())
                return

    @property
    def switch_flashing(self) -> bool:
        return self.audio.audio_time() < self._switch_flash_until

    @property
    def layer_name(self) -> str:
        return self.layers[self.layer_index]["name"]

    # ------------------------------------------------------------------ 拍位
    def beat_at(self, t: float) -> float:
        return self.beat_pos + (t - self.audio.audio_time()) * self.bpm / 60.0

    def time_at_beat(self, abeat: float, now: float) -> float:
        """把绝对拍位换算为音频时间，正确处理下一小节边界的待切换板式。"""
        b0 = self.beat_pos
        if abeat <= b0:
            return now
        next_bar = (int(b0 // self.bar_beats) + 1) * self.bar_beats
        old_ms = 60000.0 / self.bpm
        if abeat <= next_bar or self._pending_layer is None:
            return now + (abeat - b0) * old_ms / 1000.0
        new_bpm = float(self.layers[self._pending_layer]["bpm"])
        t_bar = now + (next_bar - b0) * old_ms / 1000.0
        return t_bar + (abeat - next_bar) * (60000.0 / new_bpm) / 1000.0

    def _layer_for_beat(self, abeat: float) -> int:
        next_bar = (int(self.beat_pos // self.bar_beats) + 1) * self.bar_beats
        if abeat < next_bar:
            return self.layer_index
        if self._pending_layer is not None:
            return self._pending_layer
        return self.layer_index

    # ------------------------------------------------------------------ 调度
    def _schedule(self, now: float) -> None:
        horizon_beat = self.beat_pos + self.LOOKAHEAD_S * self.bpm / 60.0
        guard = 0
        while guard < 256:
            guard += 1
            k = self._ev_i
            bar = k // self.n_events
            off = self.event_offsets[k % self.n_events]
            abeat = bar * self.bar_beats + off
            if abeat > horizon_beat:
                break
            li = self._layer_for_beat(abeat)
            events = DATA.events_for(self.layers[li]["id"])
            ev = events[k % self.n_events]
            t = self.time_at_beat(abeat, now)
            is_judge = ev.get("judge", False)
            for inst in ev["inst"]:
                sample = self.bank.samples.get(inst)
                if sample is None:
                    continue
                g = 1.0
                if inst == "咚":
                    g = 1.0 if is_judge else 0.72
                elif inst == "匡":
                    g = 0.8 if is_judge else 0.6
                elif inst in ("才", "七", "台"):
                    g = 0.45
                elif inst == "嘟":
                    g = 0.5
                elif inst == "号角":
                    g = 0.35
                self.audio.schedule(t, sample, g)
            self._ev_i += 1

    # ------------------------------------------------------------------ 判定点
    def nearest_judge_beat(self, b: float) -> int:
        base = int(b // 1)
        cands = [c for c in (base - 2, base - 1, base, base + 1, base + 2)
                 if c % self.bar_beats in DATA.judge_offsets_in_bar]
        if not cands:
            return base
        return min(cands, key=lambda c: abs(b - c))

    def judge_delta_ms(self, b: float) -> tuple[int, float]:
        """给定绝对拍位，返回（最近判定点拍号, Δt 毫秒）。"""
        n = self.nearest_judge_beat(b)
        beat_ms = 60000.0 / self.bpm
        return n, (b - n) * beat_ms

    def beat_in_bar(self, b: float) -> float:
        return b % self.bar_beats