"""帧数据驱动的战斗状态机、命中结算与对击弹反。

对应任务：T-C01（帧数据战斗）、T-C03（对击弹反）。

帧数据以 60fps 为参考；startup / active / recovery 为秒。取消窗口位于 recovery 的后 40%。
判定锚点默认按键帧；命中生效帧锚点作为硬核模式可选，供原型内 A/B 对比（ADR-001）。
"""
from __future__ import annotations

from .config import DATA, FRAME_MS
from .motion import Rect


def _durs(attack: dict) -> tuple[float, float | None, float]:
    s = attack["startup_f"] * FRAME_MS / 1000.0
    act = None if attack["active_f"] == "until_land" else attack["active_f"] * FRAME_MS / 1000.0
    r = attack["recovery_f"] * FRAME_MS / 1000.0
    return s, act, r


GRADE_MULT = {"perfect": 1.5, "good": 1.3, "off": 1.0}


class PlayerCombat:
    def __init__(self, judgement, energy) -> None:
        self.judgement = judgement
        self.energy = energy
        self.attack_id: str | None = None
        self.t = 0.0
        self.phase = "none"
        self.grade: str | None = None
        self.dt_ms = 0.0
        self.hit_set: set[int] = set()
        self.land_t: float | None = None
        self.aoe_done = False
        self.lock_t = 0.0            # 对击失败破绽
        self.hit_count = 0
        self.hit_count_t = 0.0
        self.last_event: dict = {}

    # ------------------------------------------------------------------ 查询
    @property
    def busy(self) -> bool:
        return self.attack_id is not None

    def can_cancel(self) -> bool:
        if self.attack_id is None:
            return False
        a = DATA.attacks[self.attack_id]
        s, act, r = _durs(a)
        if act is None:
            if self.land_t is None:
                return False
            rec_start = self.land_t + s
        else:
            rec_start = s + act
        if self.t < rec_start + r * 0.6:
            return False
        return a.get("next") is not None

    def hitbox(self, player) -> Rect:
        reach = 1.6
        if self.attack_id == "dive":
            reach = float(DATA.attacks["dive"].get("aoe_radius_units", 2.5))
            return Rect(player.x - reach, player.y, reach * 2, player.height + 0.5)
        if player.facing > 0:
            return Rect(player.x + 0.2, player.y + 0.3, reach, player.height * 0.8)
        return Rect(player.x - 0.2 - reach, player.y + 0.3, reach, player.height * 0.8)

    def _phase_of(self, player) -> str:
        if self.attack_id is None:
            return "none"
        a = DATA.attacks[self.attack_id]
        s, act, r = _durs(a)
        if self.t < s:
            return "startup"
        if act is None:                     # 劈山：判定持续至落地
            if self.land_t is None:
                return "active"
            if self.t < self.land_t + r:
                return "recovery"
            return "done"
        if self.t < s + act:
            return "active"
        if self.t < s + act + r:
            return "recovery"
        return "done"

    # ------------------------------------------------------------------ 起手
    def _start(self, attack_id: str, t_audio: float, player) -> None:
        self.attack_id = attack_id
        self.t = 0.0
        self.hit_set = set()
        self.land_t = None
        self.aoe_done = False
        self.grade = None
        self.dt_ms = 0.0
        self.phase = "startup"
        if self.judgement.anchor == "keydown":
            res = self.judgement.judge(t_audio)
            self.grade = res.grade
            self.dt_ms = res.dt_ms

    def _find_parry_target(self, level, player) -> tuple[object | None, float]:
        """返回（目标, 距其判定帧的剩余秒数）。"""
        window = float(DATA.combat["parry_window_ms"]) / 1000.0
        best = None
        best_rem = 9.9
        for e in level.enemies:
            if e.dead or e.state != "startup":
                continue
            if abs(player.x - e.x) > 3.2:
                continue
            rem = e.startup_s - e.t
            if 0.0 <= rem <= window and rem < best_rem:
                best = e
                best_rem = rem
        return best, best_rem

    # ------------------------------------------------------------------ 按键
    def press_attack(self, t_audio: float, player, down_held: bool, level) -> dict:
        ev: dict = {}
        if player.dead:
            return ev
        if self.lock_t > 0.0:
            return ev

        target, rem = self._find_parry_target(level, player)
        window = float(DATA.combat["parry_window_ms"]) / 1000.0
        if target is not None:
            res = self.judgement.judge(t_audio)
            perfect = res.grade != "off"
            target.stun(float(DATA.combat["parry_stun_ms"]) / 1000.0)
            self.energy.add_parry(perfect)
            self.hit_count += 1
            self.hit_count_t = 0.0
            ev.update({"parry": True, "parry_perfect": perfect, "judge": res, "target": target,
                       "hitstop_ms": float(DATA.assist["hitstop_max_ms"]), "sfx": "parry"})
            return ev

        # 过早按键：进入对击后摇，暴露破绽
        for e in level.enemies:
            if e.dead or e.state != "startup":
                continue
            if abs(player.x - e.x) > 3.2:
                continue
            if 0.0 <= (e.startup_s - e.t) <= window * 3.0:
                self.lock_t = float(DATA.combat["parry_fail_penalty_f"]) * FRAME_MS / 1000.0
                ev.update({"parry_fail": True, "sfx": "off"})
                return ev

        if self.attack_id is not None:
            if self.can_cancel():
                nxt = DATA.attacks[self.attack_id].get("next")
                if nxt:
                    self._start(nxt, t_audio, player)
                    ev["chain"] = nxt
            return ev

        if down_held and not player.on_ground:
            self._start("dive", t_audio, player)
        elif player.on_ground:
            self._start("atk_g1", t_audio, player)
        else:
            self._start("atk_a1", t_audio, player)
        ev["started"] = self.attack_id
        if self.grade is not None:
            ev["judge"] = self.judgement.last
        return ev

    # ------------------------------------------------------------------ 步进
    def update(self, dt: float, player, level, t_audio: float) -> dict:
        ev: dict = {}
        self.lock_t = max(0.0, self.lock_t - dt)
        self.hit_count_t += dt
        if self.hit_count_t > float(DATA.combat["hit_count_reset_s"]):
            self.hit_count = 0

        if self.attack_id is None:
            self.last_event = ev
            return ev

        prev_phase = self.phase
        self.t += dt
        if self.attack_id == "dive" and player.on_ground and self.land_t is None:
            self.land_t = self.t
        phase = self._phase_of(player)

        if phase == "active" and prev_phase != "active":
            if self.judgement.anchor == "active_frame" and self.grade is None:
                res = self.judgement.judge(t_audio)
                self.grade = res.grade
                self.dt_ms = res.dt_ms
                ev["judge"] = res

        if phase == "active":
            self._resolve_hits(player, level, ev)

        if phase == "recovery" and self.attack_id == "dive" and not self.aoe_done:
            self._resolve_aoe(player, level, ev)
            self.aoe_done = True

        if phase == "done":
            self.attack_id = None
            self.phase = "none"
        else:
            self.phase = phase

        self.last_event = ev
        return ev

    # ------------------------------------------------------------------ 结算
    def _resolve_hits(self, player, level, ev: dict) -> None:
        box = self.hitbox(player)
        a = DATA.attacks[self.attack_id]
        mult = GRADE_MULT.get(self.grade or "off", 1.0)
        for e in level.enemies:
            if e.dead or id(e) in self.hit_set:
                continue
            if box.overlaps(e.aabb()):
                e.take_damage(float(a["damage"]) * mult)
                self.hit_set.add(id(e))
                self.hit_count += 1
                self.hit_count_t = 0.0
                self.energy.add_hit(self.hit_count)
                ev.setdefault("hits", []).append(e)
                stop = float(DATA.assist["hitstop_max_ms"]) if self.grade == "perfect" else float(DATA.assist["hitstop_min_ms"])
                ev["hitstop_ms"] = max(ev.get("hitstop_ms", 0.0), stop)
                ev.setdefault("sfx", "hit")

    def _resolve_aoe(self, player, level, ev: dict) -> None:
        radius = float(DATA.attacks["dive"].get("aoe_radius_units", 2.5))
        mult = GRADE_MULT.get(self.grade or "off", 1.0)
        for e in level.enemies:
            if e.dead:
                continue
            if abs(e.x - player.x) <= radius and abs(e.y - player.y) <= 2.0:
                e.take_damage(float(DATA.attacks["dive"]["damage"]) * mult)
                ev.setdefault("hits", []).append(e)
        ev["aoe"] = True
        ev["hitstop_ms"] = float(DATA.assist["hitstop_max_ms"])

    # ------------------------------------------------------------------ 满堂彩
    def release_finisher(self, player, level) -> dict:
        ev: dict = {}
        if not self.energy.can_finish(self.judgement.streak):
            ev["rejected"] = True
            return ev
        dmg = self.energy.finisher_damage(self.judgement.streak)
        radius = float(DATA.energy["finisher_aoe_radius"])
        for e in level.enemies:
            if e.dead:
                continue
            if abs(e.x - player.x) <= radius:
                e.take_damage(dmg)
                ev.setdefault("hits", []).append(e)
        self.energy.consume()
        player.apply_boost(float(DATA.energy["finisher_speed"]) / max(1e-6, float(DATA.motion["max_speed"])),
                           float(DATA.energy["finisher_speed_ms"]) / 1000.0)
        player.invincible_t = max(player.invincible_t, float(DATA.energy["finisher_invincible_ms"]) / 1000.0)
        ev["finisher"] = True
        ev["damage"] = dmg
        ev["hitstop_ms"] = float(DATA.assist["hitstop_max_ms"])
        ev["sfx"] = "parry"
        return ev