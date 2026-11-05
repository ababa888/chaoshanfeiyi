"""鼓劲槽与满堂彩。

对应任务：T-C02。
来源：疾行基础速率、槌花每命中 +3、合拍倍率、对击弹反 +25。
衰减：停止进攻 3 秒后以 2/秒 衰减。
终结技：鼓劲满槽且合拍连段 ≥ 4 时可释放。
"""
from __future__ import annotations

from .config import DATA


class DrumEnergy:
    def __init__(self) -> None:
        e = DATA.energy
        self.max = float(e["gauge_max"])
        self.value = 0.0
        self.run_gain_per_s = float(e["run_gain_per_s"])
        self.run_ref = float(e["run_gain_speed_ref"])
        self.hit_gain = float(e["hit_gain"])
        self.decay_per_s = float(e["decay_per_s"])
        self.decay_grace_s = float(e["decay_grace_s"])
        self.streak_required = int(e["streak_required"])
        self._idle_t = 0.0
        self.last_gain_mult = 1.0

    def reset(self) -> None:
        self.value = 0.0
        self._idle_t = 0.0
        self.last_gain_mult = 1.0

    def add_run(self, dt: float, speed: float) -> None:
        if speed <= 0.1:
            return
        ratio = min(1.6, speed / self.run_ref)
        self._add(self.run_gain_per_s * ratio * dt, mark_activity=True)

    def add_hit(self, combo: int) -> float:
        bonus = 1.0 + min(1.0, combo * 0.05)
        return self._add(self.hit_gain * bonus, mark_activity=True)

    def add_judged(self, grade: str) -> float:
        mult = {"perfect": 1.8, "good": 1.5, "off": 1.0}[grade]
        self.last_gain_mult = mult
        return mult

    def add_parry(self, perfect: bool) -> float:
        amount = float(DATA.combat["parry_energy_gain"]) * (2.0 if perfect else 1.0)
        return self._add(amount, mark_activity=True)

    def _add(self, amount: float, mark_activity: bool = False) -> float:
        if mark_activity:
            self._idle_t = 0.0
        self.value = min(self.max, self.value + amount)
        return amount

    def update(self, dt: float) -> None:
        self._idle_t += dt
        if self._idle_t > self.decay_grace_s:
            self.value = max(0.0, self.value - self.decay_per_s * dt)

    @property
    def ratio(self) -> float:
        return self.value / self.max

    @property
    def full(self) -> bool:
        return self.value >= self.max - 1e-6

    def can_finish(self, streak: int) -> bool:
        return self.full and streak >= self.streak_required

    def consume(self) -> None:
        self.value = 0.0
        self._idle_t = 0.0

    def finisher_damage(self, streak: int) -> float:
        base = float(DATA.energy["finisher_damage"])
        if streak >= 16:
            return base * 1.30
        if streak >= 12:
            return base * 1.20
        if streak >= 8:
            return base * 1.10
        return base