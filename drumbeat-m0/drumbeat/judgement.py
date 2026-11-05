"""合拍判定核心（按键帧锚点）。

对应任务：T-A03。

决策依据（ADR-001）：默认以**按键帧**为锚点——按键即取音频时钟时间戳并判定。
命中生效帧锚点仅作为硬核模式可选，供原型内 A/B 对比。

窗口：完美 ±40ms / 合拍 ±80ms；节奏辅助模式放宽至 ±120ms；移动端额外放宽 20ms。
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import DATA
from .tempo import MusicDirector


@dataclass
class JudgeResult:
    grade: str          # perfect / good / off
    dt_ms: float
    judge_beat: int
    audio_time: float
    beat_pos: float


class Judgement:
    def __init__(self, music: MusicDirector):
        self.music = music
        self.perfect_ms = float(DATA.judgement["perfect_ms"])
        self.good_ms = float(DATA.judgement["good_ms"])
        self.assist_ms = float(DATA.judgement["assist_window_ms"])
        self.mobile_extra_ms = float(DATA.judgement["mobile_extra_ms"])
        self.user_offset_ms = float(DATA.judgement["user_offset_ms"])
        self.anchor = DATA.judgement["anchor"]
        self.assist_enabled = False
        self.mobile = False

        self.streak = 0
        self.best_streak = 0
        self.counts = {"perfect": 0, "good": 0, "off": 0}
        self.last: JudgeResult | None = None
        self.history: list[tuple[float, float, str]] = []   # (audio_time, dt_ms, grade)

    # ------------------------------------------------------------------ 配置
    def effective_perfect_ms(self) -> float:
        return self.perfect_ms + (self.mobile_extra_ms if self.mobile else 0.0)

    def effective_good_ms(self) -> float:
        if self.assist_enabled:
            return self.assist_ms + (self.mobile_extra_ms if self.mobile else 0.0)
        return self.good_ms + (self.mobile_extra_ms if self.mobile else 0.0)

    def set_anchor(self, anchor: str) -> None:
        if anchor in DATA.judgement["anchor_options"]:
            self.anchor = anchor

    def set_offset_ms(self, ms: float) -> None:
        self.user_offset_ms = max(-150.0, min(150.0, float(ms)))

    def reset_run(self) -> None:
        self.streak = 0
        self.counts = {"perfect": 0, "good": 0, "off": 0}
        self.last = None

    # ------------------------------------------------------------------ 判定
    def judge(self, audio_time: float) -> JudgeResult:
        t = audio_time - self.user_offset_ms / 1000.0
        b = self.music.beat_at(t)
        beat, dt_ms = self.music.judge_delta_ms(b)
        adt = abs(dt_ms)
        if adt <= self.effective_perfect_ms():
            grade = "perfect"
        elif adt <= self.effective_good_ms():
            grade = "good"
        else:
            grade = "off"

        if grade == "off":
            self.streak = 0
        else:
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
        self.counts[grade] += 1

        res = JudgeResult(grade=grade, dt_ms=dt_ms, judge_beat=beat, audio_time=audio_time, beat_pos=b)
        self.last = res
        self.history.append((audio_time, dt_ms, grade))
        if len(self.history) > 4000:
            del self.history[:2000]
        return res

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict:
        total = sum(self.counts.values())
        if total == 0:
            return {"total": 0, "perfect_rate": 0.0, "good_rate": 0.0, "off_rate": 0.0,
                    "mean_dt_ms": 0.0, "std_dt_ms": 0.0, "streak": self.streak, "best_streak": self.best_streak}
        import statistics
        dts = [h[1] for h in self.history]
        return {
            "total": total,
            "perfect_rate": self.counts["perfect"] / total,
            "good_rate": self.counts["good"] / total,
            "off_rate": self.counts["off"] / total,
            "mean_dt_ms": statistics.fmean(dts) if dts else 0.0,
            "std_dt_ms": statistics.pstdev(dts) if len(dts) > 1 else 0.0,
            "streak": self.streak,
            "best_streak": self.best_streak,
        }