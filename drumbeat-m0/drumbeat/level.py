"""赛段、障碍与敌人。

对应任务：T-C04。
"""
from __future__ import annotations

from .config import DATA, FRAME_MS
from .motion import Rect


class Enemy:
    """巡逻兵：直线巡逻 + 近战挥砍。攻击有明确前摇，支持对击弹反。"""

    def __init__(self, spec: dict):
        self.x = float(spec["x"])
        self.y = 0.0
        self.w, self.h = 0.9, 1.8
        self.left = float(spec["patrol_left"])
        self.right = float(spec["patrol_right"])
        self.facing = -1
        self.speed = 1.6
        self.hp = 40.0
        self.max_hp = 40.0
        self.damage = 10.0

        af = {"startup_f": 20, "active_f": 5, "recovery_f": 20}
        self.startup_s = af["startup_f"] * FRAME_MS / 1000.0
        self.active_s = af["active_f"] * FRAME_MS / 1000.0
        self.recovery_s = af["recovery_f"] * FRAME_MS / 1000.0

        self.state = "patrol"
        self.t = 0.0
        self.stun_t = 0.0
        self.hit_flash_t = 0.0
        self.dead = False
        self.death_t = 0.0          # 阵亡后经过的时间，用于播放倒地动画
        self.attack_cooldown = 0.6
        self._cd = 0.6
        self.last_attack_time = -99.0

    # ------------------------------------------------------------------ 查询
    def aabb(self) -> Rect:
        return Rect(self.x - self.w / 2, self.y, self.w, self.h)

    def attack_hitbox(self) -> Rect:
        reach = 1.5
        if self.facing > 0:
            return Rect(self.x + 0.3, self.y + 0.5, reach, 1.2)
        return Rect(self.x - 0.3 - reach, self.y + 0.5, reach, 1.2)

    @property
    def is_attacking(self) -> bool:
        return self.state in ("startup", "active", "recovery")

    @property
    def startup_time(self) -> float:
        """进入 active 之前的前摇起始时刻（用于对击窗口与视觉提示）。"""
        return self.t - self.startup_s if self.state != "patrol" else 0.0

    # ------------------------------------------------------------------ 更新
    def update(self, dt: float, player, audio_time: float) -> dict:
        """返回事件：{'hit_player': dmg} / {'attacked_at': t} 等。"""
        ev: dict = {}
        if self.dead:
            self.death_t += dt
            return ev

        self.hit_flash_t = max(0.0, self.hit_flash_t - dt)
        self._cd = max(0.0, self._cd - dt)

        if self.stun_t > 0.0:
            self.stun_t -= dt
            self.state = "stun"
            return ev

        if self.state == "patrol":
            if self._cd <= 0.0 and self._in_range(player):
                self.state = "startup"
                self.t = 0.0
                self.last_attack_time = audio_time
                self.facing = 1 if player.x > self.x else -1
                ev["attacked_at"] = audio_time
            else:
                self._patrol(dt, player)
        elif self.state == "startup":
            self.t += dt
            if self.t >= self.startup_s:
                self.state = "active"
                self.t = 0.0
        elif self.state == "active":
            self.t += dt
            if self.attack_hitbox().overlaps(player.aabb()) and not player.invincible:
                ev["hit_player"] = self.damage
                self.state = "recovery"
                self.t = 0.0
            elif self.t >= self.active_s:
                self.state = "recovery"
                self.t = 0.0
        elif self.state == "recovery":
            self.t += dt
            if self.t >= self.recovery_s:
                self.state = "patrol"
                self.t = 0.0
                self._cd = self.attack_cooldown
        return ev

    def _in_range(self, player) -> bool:
        return abs(player.x - self.x) < 1.9 and abs(player.y - self.y) < 1.4

    def _patrol(self, dt: float, player) -> None:
        self.x += self.speed * self.facing * dt
        if self.x <= self.left:
            self.x = self.left
            self.facing = 1
        elif self.x >= self.right:
            self.x = self.right
            self.facing = -1
        if abs(player.x - self.x) < 6.0:
            self.facing = 1 if player.x > self.x else -1

    def take_damage(self, amount: float) -> None:
        self.hp -= amount
        self.hit_flash_t = 0.15
        if self.hp <= 0.0:
            self.hp = 0.0
            self.death_t = 0.0
            self.dead = True
            self.state = "dead"

    def stun(self, seconds: float) -> None:
        self.stun_t = seconds
        self.state = "stun"
        self.t = 0.0


class Level:
    def __init__(self) -> None:
        d = DATA.level
        self.raw = d
        self.world = d["world"]
        self.start_x = float(self.world["start_x"])
        self.goal_x = float(self.world["goal_x"])
        self.checkpoint_x = float(self.world["checkpoint_x"])
        self.fall_death_y = float(self.world["fall_death_y"])
        self.target_time_s = float(self.world["target_time_s"])

        self.ground_rects = [Rect(s["x"], s["y"], s["w"], s["h"]) for s in d["solids"] if s["kind"] == "ground"]
        self.platform_rects = [Rect(s["x"], s["y"], s["w"], s["h"]) for s in d["solids"] if s["kind"] == "platform"]
        self.low_wall_rects = [Rect(s["x"], s["y"], s["w"], s["h"]) for s in d["low_walls"]]
        self.solid_rects = self.ground_rects + self.low_wall_rects
        self.hazard_rects = [Rect(s["x"], s["y"], s["w"], s["h"]) for s in d["hazards"]]

        self.enemy_specs = d["enemies"]
        self.enemies: list[Enemy] = []
        self.reset()

    def reset(self) -> None:
        self.enemies = [Enemy(s) for s in self.enemy_specs]

    @property
    def total_enemies(self) -> int:
        return len(self.enemies)

    @property
    def killed_enemies(self) -> int:
        return sum(1 for e in self.enemies if e.dead)