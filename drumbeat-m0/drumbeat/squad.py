"""Patapon 阵列指挥模式：四拍指令编排（逻辑层）。

「鼓点即步伐，节奏即动作」：J/K/L/S 击鼓，输入小节内连续敲出 4 拍组合并踩准鼓点
（perfect ±40ms / good ±80ms，窗口取自 DATA.judgement），相位循环 输入 → 应答唱和
→ 执行；错序 / 脱拍 / 缺拍 / 同拍连点 → 乱阵一小节（急停 + 散射 + 闪烁 + 破音）。
判定 / 指令表 / 行军 / 相位零件复用工程根目录 sandbox_patapon.py（无头沙盒 S1–S4
已验证）；judgement.py 未被触碰，CLASSIC 单角色模式原样保留（config.MODE 切换）。
视图由 hud.SquadView 注入，本模块不含任何绘制代码。

S5 关卡与战斗（数据驱动 drumbeat/data/patapon_stage.json，语义同 sandbox S3/S4）：
  - 站桩敌人：attack4 执行小节逐拍结算，攻击范围锚点 -0.5~+2.5；阵型数值仅在
    完整度 ≥0.9 且非乱阵时激活（长蛇穿透全线 / 猛虎 AOE 半径 / 其余单体最近）；
  - 成长：击杀数解锁阵型（sandbox_formations.json growth.unlock_kills），
    变阵指令只在已解锁阵型间循环；
  - 行军速度 = 指令倍率 × 阵型速度（长蛇 1.5 / 猛虎 0.9 / 铁壁 0.6，完整度门控）；
  - Boss 破阵：逼近触发预警并停军（freeze 拍位冻结），激活拍结算 —— 铁壁阵且
    完整度 ≥0.9 → 破阵（Boss -60 HP），否则队伍受击 + 击退；击破后放行收阵；
  - 队伍 HP 归零 → 全军覆灭（R 重开）。
"""
from __future__ import annotations

import json
import math
import os
import sys

import pygame

from .config import app_dir, data_dir

_root = app_dir()                           # sandbox_patapon.py 位于工程根目录
if _root not in sys.path:
    sys.path.insert(0, _root)

import sandbox_patapon as sp                # noqa: E402  无头沙盒：判定/指令/行军/战斗均已验证

KEY_SAMPLE = {"J": "咚", "K": "台", "L": "才", "S": "号角"}   # 击键即击鼓
CMD_BANNER = {"attack4": "猛虎下山！", "stride": "长蛇突进！",
              "defend": "铁壁阵！", "morph": "变阵！"}
UNLOCK_BANNER = {"tiebi": "解锁 · 铁壁阵！", "menghu": "解锁 · 猛虎阵！"}
FORMATION_ORDER = ["changshe", "tiebi", "menghu"]
FEVER_STREAK = 2                            # 连续全 PERFECT 小节数 → 满堂彩
N_UNITS = 8                                 # 编队人数（与 hud.SquadView 同一常量源）
MORPH_STAGGER = 0.07                        # 变阵交错窗口（秒/人，视图 lerp 同参）
MORPH_WINDOW = 0.55
ATTACK_DMG = 25.0                           # 基础伤害（× 阵型 damage_mult）
ATTACK_RANGE = (-0.5, 2.5)                  # 攻击窗口（锚点相对，沙盒 S3 语义）
BOSS_WARN_BEATS = 10                        # Boss 预警提前拍数（2.5 小节，够一次变阵）
SQUAD_HP = 100.0

_DRUM_KEYS = {pygame.K_j: "J", pygame.K_k: "K", pygame.K_l: "L", pygame.K_s: "S"}


def _load_stage() -> dict:
    with open(os.path.join(data_dir(), "patapon_stage.json"), "r", encoding="utf-8") as f:
        return json.load(f)


class StageEnemy(sp.Enemy):
    """沙盒站桩敌人 + 视图字段（max_hp / 受击闪）。"""

    def __init__(self, x: float, hp: float) -> None:
        super().__init__(x, hp)
        self.max_hp = hp
        self.flash = 0.0


class StageBoss(sp.Boss):
    def __init__(self, spec: dict) -> None:
        super().__init__(float(spec["x"]), spec["breakable_by"],
                         hp=float(spec["hp"]), dmg=float(spec["dmg"]), kb=float(spec["kb"]))
        self.max_hp = self.hp
        self.approach = float(spec["approach"])
        self.dead = False


class PataponGame:
    """阵列模式编排器：输入缓冲 → 踩点判定 → 四相相位机 → 指令执行 → 战斗/视效钩子。"""

    def __init__(self, audio, bank, view) -> None:
        self.audio = audio
        self.bank = bank
        self.view = view
        self.chant = bank.samples.get("台")
        if self.chant is None:                          # numpy 数组不可用 or 判空
            self.chant = next(iter(bank.samples.values()))
        self.stage = _load_stage()
        self.goal_units = float(self.stage["goal_units"])
        self.paused = False
        self.show_help = True
        self._fresh_state()
        self.music = sp.SandboxMusic(audio, bank, phase_fn=lambda: self.phase)
        self.reset()

    # ------------------------------------------------------------------ 状态
    def _fresh_state(self) -> None:
        self.phase = "input"                    # input / echo / execute / luan
        self.status = "playing"                 # playing / cleared / defeated
        self.anchor = sp.MarchAnchor()
        self.bar = 0
        self.fid = 0
        self.command: str | None = None
        self.cmd_all_perfect = False
        self.hud_presses: list = []
        self.last_ab = -10                      # 上一有效按键的绝对拍（拒绝同拍连点）
        self.last_grade = ("", 0.0)             # 即时判定反馈（文字, ttl）
        self.banner = ("", 0.0)
        self.perfect_streak = 0
        self.fever = False
        self.attack_beat: float | None = None
        self.stride_until = -1.0
        self.defend_until = -1.0
        self.timeline: list[list] = []          # 执行小节拍调度 [abeat, action]
        self.stats = {"perfect": 0, "good": 0, "off": 0,
                      "cmd_ok": 0, "cmd_fail": 0, "attacks": 0,
                      "break_ok": 0, "break_fail": 0}
        # ---- S5：关卡 / 战斗 / 成长
        self.elapsed = 0.0
        self.enemies = [StageEnemy(float(e["x"]), float(e["hp"]))
                        for e in self.stage["enemies"]]
        self.boss = StageBoss(self.stage["boss"]) if self.stage.get("boss") else None
        self.squad_hp = SQUAD_HP
        self.kills = 0
        self.unlocked = {"changshe"}
        self.integrity = 1.0                    # 完整度（乱阵 0 / 变阵中就位比例）
        self.cmd_mult = 1.0                     # 指令层提速（KKKK），× 阵型速度
        self.morph_start: float | None = None   # 变阵起始时刻（elapsed 秒）

    def reset(self) -> None:
        self._fresh_state()
        self.music.reset()
        self.commander = sp.RhythmCommander(self.music)
        self.view.reset()

    # ------------------------------------------------------------------ 视图查询
    @property
    def beat(self) -> float:
        return self.music.beat_pos

    @property
    def bpm(self) -> float:
        return self.music.bpm

    @property
    def layer_name(self) -> str:
        return self.music.layer_name

    @property
    def formation(self) -> str:
        return FORMATION_ORDER[self.fid]

    @property
    def fstats(self) -> dict:
        """阵型数值门控（沙盒 §6.1）：完整度 ≥0.9 且非乱阵才激活，否则全队缺省。"""
        if self.phase != "luan" and self.integrity >= sp.SKILL_ON:
            return sp.FSTATS[self.formation]
        return sp.DEFAULT_STATS

    # ------------------------------------------------------------------ 输入
    def handle_event(self, ev) -> None:
        """KEYDOWN：R 重开 / P 暂停 / F3 帮助 / J/K/L/S 击鼓进缓冲池并即时判定。"""
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_r:
            self.reset()
            return
        if ev.key == pygame.K_p:
            self.paused = not self.paused
            return
        if ev.key == pygame.K_F3:
            self.show_help = not self.show_help
            return
        key = _DRUM_KEYS.get(ev.key)
        if key is None or self.paused or self.status != "playing":
            return
        t = self.audio.audio_time()                 # 判定锚点 = 按键时刻的音频时钟
        self.audio.schedule(t + 0.005, self.bank.samples[KEY_SAMPLE[key]], 0.85)
        ab = round(self.music.beat_at(t))
        if self.phase == "input" and len(self.commander.presses) < 4 and ab > self.last_ab:
            self.last_ab = ab
            self.commander.on_press(key, t)
            grade = self.commander.presses[-1][1]
            self.stats[grade] += 1
            self.last_grade = (grade.upper() + ("!" if grade == "perfect" else ""), 0.45)
            if grade == "off":                      # 脱拍闷音
                self.audio.schedule(t + 0.03, self.bank.feedback["off"], 0.5)

    # ------------------------------------------------------------------ 推进
    def update(self, dt: float) -> None:
        if self.paused or self.status != "playing":
            return
        self.elapsed += dt
        self.music.update(0.0)                      # 恒定慢板（90BPM），判定与渲染同一拍相位
        beat = self.music.beat_pos
        cur_bar = int(beat // self.music.bar_beats)
        if cur_bar != self.bar:
            self.bar = cur_bar
            self._enter_bar(cur_bar)

        # 执行小节：拍点触发攻击结算 / 收提速
        due = [e for e in self.timeline if e[0] <= beat + 1e-6]
        self.timeline = [e for e in self.timeline if e[0] > beat + 1e-6]
        for ab, act in due:
            if act == "attack":
                self.attack_beat = ab
                self.stats["attacks"] += 1
                self._resolve_attack()
            elif act == "stride_end":
                self.cmd_mult = 1.0
        if self.attack_beat is not None and beat - self.attack_beat >= 1.0:
            self.attack_beat = None

        # 完整度：乱阵 0；变阵中 = 逐人就位比例；其余 1（主项目无 UnitBody，闭式近似）
        if self.phase == "luan":
            self.integrity = 0.0
        elif self.morph_start is not None:
            p = self.elapsed - self.morph_start
            prog = [max(0.0, min(1.0, (p - i * MORPH_STAGGER) / MORPH_WINDOW))
                    for i in range(N_UNITS)]
            self.integrity = sum(prog) / N_UNITS
            if self.integrity >= 1.0:
                self.morph_start = None
        else:
            self.integrity = 1.0

        # 行军速度 = 指令倍率 × 阵型速度（完整度门控，沙盒 tick 同构）
        want = self.cmd_mult * self.fstats["speed_mult"]
        if abs(want - self.anchor.mult) > 1e-9:
            self.anchor.set_mult(want, beat)
        self.anchor.step(beat)

        for e in self.enemies:                      # 受击闪衰减
            e.flash = max(0.0, e.flash - dt * 6.0)
        self._update_boss(beat)

        self.last_grade = (self.last_grade[0], max(0.0, self.last_grade[1] - dt))
        self.banner = (self.banner[0], max(0.0, self.banner[1] - dt))
        if self.anchor.x >= self.goal_units and (self.boss is None or self.boss.dead):
            self.status = "cleared"
            self.anchor.freeze(beat)
            self.banner = ("收 阵", 3.0)

    # ------------------------------------------------------------------ 相位机
    def _enter_bar(self, b: int) -> None:
        """小节边界：input→(判定)→echo→execute→input；失误→luan→input。"""
        now = self.audio.audio_time()
        if self.phase == "input":
            self.hud_presses = list(self.commander.presses)
            self.cmd_all_perfect = (len(self.commander.presses) == 4
                                    and all(g == "perfect" for _, g, _, _ in self.commander.presses))
            self.command = self.commander.evaluate()        # 错序/脱拍/缺拍 → None
            self.commander.clear()
            if self.command is None:                                     # —— 乱阵
                self.phase = "luan"
                self.anchor.freeze(self.music.beat_pos)                  # 急停（拍位冻结）
                self.perfect_streak = 0
                self.fever = False
                self.stats["cmd_fail"] += 1
                self.view.trigger_luan()                                 # 散射 + 震屏 + 红闪
                self.audio.schedule(now + 0.01, self.bank.feedback["hurt"], 0.8)   # 破音
                self.audio.schedule(now + 0.14, self.bank.feedback["off"], 0.7)
                self.banner = ("乱 阵 ！", 1.2)
            else:                                                        # —— 应答唱和
                self.phase = "echo"
                self.stats["cmd_ok"] += 1
                self.perfect_streak = self.perfect_streak + 1 if self.cmd_all_perfect else 0
                if self.perfect_streak >= FEVER_STREAK and not self.fever:
                    self.audio.schedule(now + 0.01, self.bank.samples["号角"], 0.5)
                self.fever = self.perfect_streak >= FEVER_STREAK
                for k in range(4):                                       # 本小节 4 拍唱和
                    self.audio.schedule(self.music.time_at_beat(b * 4 + k, now),
                                        self.chant, sp.CHANT_GAIN)
                self.banner = (CMD_BANNER[self.command], 1.4)
        elif self.phase == "echo":
            self.phase = "execute"
            b0 = float(b * self.music.bar_beats)
            if self.command == "attack4":                                # 猛虎下山：4 拍连劈
                for k in range(4):
                    self.timeline.append([b0 + k, "attack"])
            elif self.command == "stride":                               # 长蛇突进：本小节指令倍率 1.5×
                self.cmd_mult = 1.5
                self.stride_until = b0 + 4
                self.timeline.append([b0 + 4, "stride_end"])
                self.audio.schedule(now + 0.01, self.bank.samples["嘟"], 0.7)
            elif self.command == "defend":                               # 铁壁：整小节马步盾墙
                self.defend_until = b0 + 4
                self.audio.schedule(now + 0.01, self.bank.samples["匡"], 0.7)
            elif self.command == "morph":                                # 变阵：已解锁阵型间循环
                order = [f for f in FORMATION_ORDER if f in self.unlocked]
                cur = FORMATION_ORDER[self.fid]
                nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
                self.fid = FORMATION_ORDER.index(nxt)
                self.morph_start = self.elapsed                          # 完整度下探起点
                self.view.morph_to_key(nxt)
                self.audio.schedule(now + 0.01, self.bank.samples["号角"], 0.6)
        elif self.phase in ("execute", "luan"):
            if self.phase == "luan":
                self.anchor.resume(self.music.beat_pos)                  # 复阵（位置连续）
            self.phase = "input"
            self.hud_presses.clear()
            self.last_ab = -10

    # ------------------------------------------------------------------ S5 战斗
    def _resolve_attack(self) -> None:
        """攻击结算：长蛇穿透全线 / 猛虎 AOE 半径 / 其余单体最近（沙盒 S3 技能表）。"""
        st = self.fstats
        lo, hi = ATTACK_RANGE
        ahead = sorted((e for e in self.enemies
                        if not e.dead and self.anchor.x + lo <= e.x <= self.anchor.x + hi),
                       key=lambda e: e.x)
        self.view.on_attack(self.view.front_x(), perfect=self.cmd_all_perfect)
        self.audio.schedule(self.audio.audio_time() + 0.005, self.bank.feedback["hit"], 0.8)
        if not ahead:
            return
        dmg = ATTACK_DMG * st["damage_mult"]
        if st["aoe_radius"] > 0.0:
            c = ahead[0].x
            targets = [e for e in self.enemies if not e.dead and abs(e.x - c) <= st["aoe_radius"]]
        elif st["pierce"]:
            targets = ahead
        else:
            targets = [ahead[0]]
        for e in targets:
            e.hp -= dmg
            e.flash = 0.15
            killed = e.hp <= 0.0 and not e.dead
            if killed:
                e.dead = True
                self.kills += 1
            self.view.on_enemy_hit(e.x, killed, self.anchor.x)
        self._check_unlock()

    def _check_unlock(self) -> None:
        for fid, need in sp.GROWTH["unlock_kills"].items():
            if self.kills >= need and fid not in self.unlocked:
                self.unlocked.add(fid)
                self.banner = (UNLOCK_BANNER.get(fid, f"解锁 · {fid}"), 1.6)
                self.audio.schedule(self.audio.audio_time() + 0.01, self.bank.samples["嘟"], 0.7)

    def squad_hit(self, dmg: float, kb: float) -> None:
        """受击：铁壁减伤且免疫击退（阵型数值门控）；HP 归零 → 全军覆灭。"""
        self.squad_hp -= dmg * self.fstats["damage_taken_mult"]
        if kb > 0.0 and not self.fstats["knockback_immune"]:
            self.anchor.x0 -= kb                      # 击退位移（有意打破连续性）
        self.view.on_squad_hit()
        self.audio.schedule(self.audio.audio_time() + 0.01, self.bank.feedback["hurt"], 0.8)
        if self.squad_hp <= 0.0:
            self.squad_hp = 0.0
            self.status = "defeated"
            if self.anchor.frozen_beat is None:
                self.anchor.freeze(self.music.beat_pos)
            self.banner = ("全 军 覆 灭", 3.0)

    def _update_boss(self, b: float) -> None:
        """Boss 破阵（沙盒 S3 同构 + 停军/重预警）：预警 → 停军 → 激活拍结算 → 击破放行。"""
        boss = self.boss
        if boss is None or boss.dead:
            return
        now = self.audio.audio_time()
        if boss.state == "idle":
            if self.anchor.x >= boss.x - boss.approach:
                boss.state = "startup"
                boss.active_beat = math.ceil(b / 4) * 4 + BOSS_WARN_BEATS
                self.anchor.freeze(b)                                # 停军列阵（原地踏步）
                self.banner = ("破阵预警 · 铁壁迎击！", 2.0)
                self.audio.schedule(now + 0.01, self.bank.samples["号角"], 0.6)
        elif boss.state == "startup" and b >= boss.active_beat:
            if self.formation in boss.breakable_by and self.integrity >= sp.SKILL_ON:
                boss.hp -= 60.0
                self.stats["break_ok"] += 1
                self.view.on_boss_break(boss.x, True, self.anchor.x)
                self.audio.schedule(now + 0.01, self.bank.feedback["parry"], 0.9)
                if boss.hp <= 0.0:
                    boss.hp = 0.0
                    boss.dead = True
                    boss.state = "done"
                    self.anchor.resume(b)                            # 放行（位置连续）
                    self.banner = ("渠 魁 授 首 ！", 2.2)
                else:
                    boss.active_beat = math.ceil(b / 4) * 4 + BOSS_WARN_BEATS   # 再预警
                    self.banner = ("破 阵 ！", 1.4)
            else:
                self.stats["break_fail"] += 1
                self.view.on_boss_break(boss.x, False, self.anchor.x)
                self.squad_hit(boss.dmg, boss.kb)
                if self.status == "playing":                         # 未团灭 → 再预警
                    boss.active_beat = math.ceil(b / 4) * 4 + BOSS_WARN_BEATS
                    self.banner = ("阵型被破！", 1.4)
