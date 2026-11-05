"""固定步长运动系统。

对应任务：T-B01。

自研固定步长运动与 AABB 碰撞（不依赖通用刚体），保证确定性与手感可控。
跑酷态与战斗态共享同一套位移参数，切换时不重置速度——「跑打无缝」的技术前提。
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import DATA


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y

    @property
    def top(self) -> float:
        return self.y + self.h

    def overlaps(self, o: "Rect") -> bool:
        return (self.left < o.right and self.right > o.left
                and self.bottom < o.top and self.top > o.bottom)


class PlayerBody:
    STAND_H = 1.8
    SLIDE_H = 0.9
    WIDTH = 0.9

    def __init__(self, level) -> None:
        self.level = level
        w = level.world
        self.x = float(w["start_x"])
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.facing = 1
        self.gravity, self.jump_v = DATA.jump_physics()

        self.dash_t = 0.0
        self.dash_cd = 0.0
        self.invincible_t = 0.0
        self.coyote_t = 0.0
        self.jump_buffer_t = 0.0
        self.jumps_used = 0
        self.sliding = False
        self.slide_t = 0.0
        self.speed_boost_t = 0.0
        self.speed_boost = 1.0
        self.dead = False
        self.hp = float(DATA.combat["player_hp"])

        self._jump_held = False

    # ------------------------------------------------------------------ 查询
    @property
    def height(self) -> float:
        return self.SLIDE_H if self.sliding else self.STAND_H

    def aabb(self) -> Rect:
        return Rect(self.x - self.WIDTH / 2, self.y, self.WIDTH, self.height)

    @property
    def speed(self) -> float:
        return abs(self.vx)

    @property
    def invincible(self) -> bool:
        return self.invincible_t > 0.0

    def max_speed(self) -> float:
        base = float(DATA.motion["max_speed"])
        return base * self.speed_boost

    # ------------------------------------------------------------------ 动作
    def request_jump(self) -> None:
        self.jump_buffer_t = float(DATA.assist["jump_buffer_ms"]) / 1000.0

    def request_dash(self) -> bool:
        if self.dash_cd > 0.0 or self.dead:
            return False
        self.dash_t = float(DATA.motion["dash_duration_ms"]) / 1000.0
        self.dash_cd = float(DATA.motion["dash_cooldown_s"])
        self.invincible_t = max(self.invincible_t, float(DATA.motion["dash_invincible_ms"]) / 1000.0)
        return True

    def apply_boost(self, mult: float, seconds: float) -> None:
        self.speed_boost = max(self.speed_boost, mult)
        self.speed_boost_t = max(self.speed_boost_t, seconds)

    def take_damage(self, amount: float) -> bool:
        if self.invincible or self.dead:
            return False
        self.hp -= amount
        self.invincible_t = float(DATA.assist["hurt_invincible_ms"]) / 1000.0
        if self.hp <= 0.0:
            self.hp = 0.0
            self.dead = True
        return True

    def respawn(self, x: float) -> None:
        self.x = x
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.dead = False
        self.hp = float(DATA.combat["player_hp"])
        self.invincible_t = 1.0
        self.dash_t = 0.0
        self.dash_cd = 0.0
        self.sliding = False
        self.jumps_used = 0

    # ------------------------------------------------------------------ 步进
    def step(self, dt: float, dir_x: float, jump_held: bool, down_held: bool, dash_lock: bool) -> None:
        if self.dead:
            return

        m = DATA.motion
        # 计时器
        self.dash_cd = max(0.0, self.dash_cd - dt)
        self.invincible_t = max(0.0, self.invincible_t - dt)
        self.jump_buffer_t = max(0.0, self.jump_buffer_t - dt)
        self.speed_boost_t = max(0.0, self.speed_boost_t - dt)
        if self.speed_boost_t <= 0.0:
            self.speed_boost = 1.0

        if dir_x > 0.05:
            self.facing = 1
        elif dir_x < -0.05:
            self.facing = -1

        # 抢步
        if self.dash_t > 0.0:
            self.dash_t = max(0.0, self.dash_t - dt)
            self.vx = float(m["dash_speed"]) * self.facing
        elif not dash_lock:
            target = dir_x * self.max_speed()
            if abs(dir_x) > 0.05:
                self.vx += (target - self.vx) * min(1.0, float(m["acceleration_per_s2"]) * dt / max(1.0, self.max_speed()))
            else:
                fr = float(m["friction_per_s2"]) * dt
                if abs(self.vx) <= fr:
                    self.vx = 0.0
                else:
                    self.vx -= fr * (1 if self.vx > 0 else -1)

        # 矮子步
        if down_held and self.on_ground and not self.sliding:
            self.sliding = True
            self.slide_t = float(m["slide_duration_ms"]) / 1000.0
        if self.sliding:
            self.slide_t -= dt
            if self.slide_t <= 0.0 or not self.on_ground:
                if not self._blocked_when_standing():
                    self.sliding = False

        # 跳跃
        if jump_held and not self._jump_held:
            self.request_jump()
        self._jump_held = jump_held

        if self.jump_buffer_t > 0.0:
            if self.on_ground or self.coyote_t > 0.0:
                self.vy = self.jump_v
                self.jumps_used = 1
                self.jump_buffer_t = 0.0
                self.coyote_t = 0.0
                self.on_ground = False
                if self.sliding:
                    self.sliding = False
            elif self.jumps_used < 2:
                self.vy = self.jump_v * float(m["second_jump_ratio"])
                self.jumps_used = 2
                self.jump_buffer_t = 0.0

        # 重力
        self.vy -= self.gravity * dt
        self.vy = max(self.vy, -60.0)

        # 积分与碰撞
        self._move_and_collide(self.vx * dt, self.vy * dt)

        # 坑洞坠落
        if self.y < float(self.level.world["fall_death_y"]):
            self.hp = 0.0
            self.dead = True

    # ------------------------------------------------------------------ 碰撞
    def _blocked_when_standing(self) -> bool:
        probe = Rect(self.x - self.WIDTH / 2, self.y, self.WIDTH, self.STAND_H)
        for s in self.level.solid_rects:
            if probe.overlaps(s):
                return True
        return False

    def _move_and_collide(self, dx: float, dy: float) -> None:
        # 水平
        self.x += dx
        box = self.aabb()
        for s in self.level.solid_rects:
            if box.overlaps(s):
                if dx > 0:
                    self.x = s.left - self.WIDTH / 2
                elif dx < 0:
                    self.x = s.right + self.WIDTH / 2
                self.vx = 0.0
                box = self.aabb()

        # 垂直
        prev_bottom = self.y
        self.y += dy
        box = self.aabb()
        self.on_ground = False
        for s in self.level.solid_rects:
            if box.overlaps(s):
                if dy <= 0:
                    self.y = s.top
                    self.vy = 0.0
                    self.on_ground = True
                    self.jumps_used = 0
                else:
                    self.y = s.bottom - self.height
                    self.vy = 0.0
                box = self.aabb()

        # 单向平台：仅下落时、且上一帧脚底在平台面之上才落地
        for p in self.level.platform_rects:
            if dy <= 0 and prev_bottom >= p.top - 0.02 and self.y <= p.top:
                box = self.aabb()
                if box.right > p.left and box.left < p.right and self.y < p.top:
                    self.y = p.top
                    self.vy = 0.0
                    self.on_ground = True
                    self.jumps_used = 0

        if self.on_ground:
            self.coyote_t = float(DATA.assist["coyote_ms"]) / 1000.0
        else:
            self.coyote_t = max(0.0, self.coyote_t - 1.0 / 120.0)