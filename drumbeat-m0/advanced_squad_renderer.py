"""AdvancedSquadRenderer —— Patapon 阵列高完成度渲染层（独立沙盒）。

纪律：独立文件，不 import / 不修改 app.py / hud.py；逻辑层（beat_pos、阵型槽位、
Fever、攻击事件）全部通过 RenderState 依赖注入，日后可直接对接
MusicDirector.beat_pos 与 sandbox_patapon.SquadGame。

性能策略：
  1. 贴图变体预热 —— base / ghost(残影 30%) / glow(金色加法剪影) 启动期一次性烘焙，
     渲染循环内零 transform / 零逐帧 alpha 计算；
  2. 震屏 = 最终 blit 偏移（世界画到整屏 world surface，一次性位移上屏），
     不改任何实体坐标；
  3. SRCALPHA 覆盖层仅 2 层：粒子层 + 满堂彩滤镜层（报告 §7.4 预算）；
  4. 火花/光环用 pygame.draw 矢量图元，无贴图开销；粒子数量硬上限。

运行：py advanced_squad_renderer.py   （需要 pygame；无贴图时自动生成程序化后备帧）
      有音频设备时鼓点/唱和/反馈音真实发声，无设备自动降级虚拟时钟（逻辑不变）
玩法：J/K/L/S 击鼓 —— 输入小节内连续敲出 4 拍组合并踩准鼓点（perfect ±40ms /
      good ±80ms，DATA.judgement）：JJJJ 猛虎下山 / KKKK 长蛇突进 /
      LLLL 铁壁防守 / KLKL 变阵。输入 → 应答唱和 → 执行；错序/脱拍/缺拍
      → 乱阵一小节（急停+散射+闪烁+破音）。连续 2 小节全 PERFECT → 满堂彩。
      没有任何直切阵型/出招的调试键 —— 鼓点即步伐，节奏即动作。
"""
from __future__ import annotations

import math
import os
import random
import sys

import pygame

# 复用无头沙盒已验证的判定/指令/相位/行军零件（SANDBOX_HANDOFF §4）；其一行未改
from sandbox_patapon import CHANT_GAIN, MarchAnchor, RhythmCommander, SandboxMusic
from drumbeat.audio import AudioEngine, NullAudioEngine
from drumbeat.synth import Bank

SCREEN_W, SCREEN_H = 960, 540
GROUND_Y = 430
MAX_SPARKS = 220
GHOST_INTERVAL = 0.055          # 残影快照间隔（秒）
GHOST_TTL = 0.30                # 残影存活（秒）
PX_PER_UNIT = 40.0              # MarchAnchor 世界单位 → 地面刻度像素


# ================================================================== 工具
def ease_out_cubic(p: float) -> float:
    """变阵缓动：慢蓄快发后缓冲（报告 §7.3 发力感）。"""
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


def leap_y(p: float, h: float = 26.0) -> float:
    """跃起劈山：闭式抛物线（像素），p∈[0,1] 一个动作拍，落地精确卡拍。"""
    p = max(0.0, min(1.0, p))
    return 4.0 * h * p * (1.0 - p)


def march_bob(beat: float, amp: int = 3) -> int:
    """行军摆动：三角波，整数拍归零；整数像素输出（保护 transform 缓存）。"""
    frac = beat % 1.0
    return int(round(amp * (1.0 - abs(2.0 * frac - 1.0))))


# ================================================================== 贴图库
class SpriteBank:
    """真实贴图优先，失败则程序化生成后备帧；所有变体启动期预烘焙。

    贴图约定：assets/characters/player/{unit_type}_{frame}.png
    frame ∈ {run_0, run_1, attack}
    """

    FRAMES = ("run_0", "run_1", "attack")
    TYPES = {"chui": (205, 60, 60),       # 槌手 · 红
             "luo": (230, 180, 60),       # 锣鼓手 · 金
             "dun": (80, 120, 220)}       # 盾手 · 蓝
    SIZE = (28, 40)

    def __init__(self, asset_dir: str = "assets/characters/player") -> None:
        self._cache: dict[tuple[str, str, str], pygame.Surface] = {}
        for utype, color in self.TYPES.items():
            for frame in self.FRAMES:
                base = self._load_or_generate(asset_dir, utype, frame, color)
                self._cache[(utype, frame, "base")] = base
                ghost = base.copy()
                ghost.set_alpha(78)                       # 残影：30% 不透明
                self._cache[(utype, frame, "ghost")] = ghost
                glow = base.copy()
                glow.fill((255, 150, 40, 0), special_flags=pygame.BLEND_RGBA_MULT)
                self._cache[(utype, frame, "glow")] = glow   # 满堂彩加法剪影
                guard = base.copy()
                guard.fill((70, 140, 255, 0), special_flags=pygame.BLEND_RGBA_MULT)
                self._cache[(utype, frame, "guard")] = guard  # 铁壁加法微光

    def _load_or_generate(self, asset_dir: str, utype: str, frame: str,
                          color: tuple) -> pygame.Surface:
        path = os.path.join(asset_dir, f"{utype}_{frame}.png")
        try:
            img = pygame.image.load(path).convert_alpha()
            return pygame.transform.smoothscale(img, self.SIZE)
        except Exception:
            return self._generate(color, frame)

    def _generate(self, color: tuple, frame: str) -> pygame.Surface:
        """程序化英歌武士后备帧：头 + 身 + 双槌，帧间差异在手臂/步伐角度。"""
        w, h = self.SIZE
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        dark = tuple(max(0, c - 70) for c in color)
        pygame.draw.circle(s, (240, 220, 200), (w // 2, 8), 6)            # 头
        pygame.draw.rect(s, color, (w // 2 - 6, 14, 12, 16))              # 身
        pygame.draw.rect(s, dark, (w // 2 - 6, 14, 12, 4))                # 腰带
        swing = {"run_0": 7, "run_1": -7, "attack": -13}[frame]           # 手臂相位
        pygame.draw.line(s, dark, (w // 2 - 5, 17), (w // 2 - 11, 17 + swing), 3)
        pygame.draw.line(s, dark, (w // 2 + 5, 17), (w // 2 + 11, 17 - swing), 3)
        leg = {"run_0": 4, "run_1": -4, "attack": 2}[frame]               # 步伐相位
        pygame.draw.line(s, dark, (w // 2 - 3, 30), (w // 2 - 3 - leg, h - 2), 4)
        pygame.draw.line(s, dark, (w // 2 + 3, 30), (w // 2 + 3 + leg, h - 2), 4)
        return s

    def get(self, utype: str, frame: str, variant: str = "base") -> pygame.Surface:
        return self._cache[(utype, frame, variant)]


# ================================================================== 敌方贴图库（S5）
class EnemyBank:
    """站桩敌人 / Boss 程序化精灵：base / flash(白热加法) 变体启动期预烘焙。

    渲染循环零 transform / 零 set_alpha / 零新 Surface（与 SpriteBank 同纪律）。
    """

    PATROL_SIZE = (28, 40)
    BOSS_SIZE = (64, 88)

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], pygame.Surface] = {}
        for kind, size, color in (("patrol", self.PATROL_SIZE, (110, 60, 140)),
                                  ("boss", self.BOSS_SIZE, (160, 40, 40))):
            base = self._generate(size, color, boss=(kind == "boss"))
            self._cache[(kind, "base")] = base
            flash = base.copy()
            flash.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_MULT)
            self._cache[(kind, "flash")] = flash

    def _generate(self, size: tuple, color: tuple, boss: bool) -> pygame.Surface:
        """程序化敌方武士：头 + 身 + 武器；Boss 大体型 + 双角。"""
        w, h = size
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        dark = tuple(max(0, c - 60) for c in color)
        hr = max(5, w // 5)
        hy = hr + 2
        pygame.draw.circle(s, (230, 205, 185), (w // 2, hy), hr)              # 头
        pygame.draw.rect(s, color, (w // 2 - w // 5, hy + hr, 2 * (w // 5), h // 2))   # 身
        pygame.draw.rect(s, dark, (w // 2 - w // 5, hy + hr, 2 * (w // 5), max(3, h // 12)))
        pygame.draw.line(s, dark, (w // 2 - w // 5, hy + hr + 4), (4, hy + hr + h // 6), 3)  # 左臂
        pygame.draw.line(s, dark, (w // 2 + w // 5, hy + hr + 4), (w - 4, hy + hr), 3)       # 右臂持械
        pygame.draw.line(s, (200, 200, 210), (w - 4, hy + hr), (w - 4, hy - hr), 3)          # 长刀
        pygame.draw.line(s, dark, (w // 2 - 3, hy + hr + h // 2), (w // 2 - 4, h - 2), 4)    # 腿
        pygame.draw.line(s, dark, (w // 2 + 3, hy + hr + h // 2), (w // 2 + 4, h - 2), 4)
        if boss:
            pygame.draw.polygon(s, (240, 200, 80), [(w // 2 - hr, hy - hr + 2),  # 双角
                                                    (w // 2 - hr - 6, hy - hr - 10),
                                                    (w // 2 - hr + 4, hy - hr)])
            pygame.draw.polygon(s, (240, 200, 80), [(w // 2 + hr, hy - hr + 2),
                                                    (w // 2 + hr + 6, hy - hr - 10),
                                                    (w // 2 + hr - 4, hy - hr)])
        return s

    def get(self, kind: str, variant: str = "base") -> pygame.Surface:
        return self._cache[(kind, variant)]


# ================================================================== 阵型插值
FORMATION_SLOTS = {
    "changshe": lambda n: [(-34.0 * i, 0.0) for i in range(n)],
    "tiebi": lambda n: [(-30.0 * (i % 4) - 15.0 * (i // 4), -30.0 * (i // 4)) for i in range(n)],
    "menghu": lambda n: ([(10.0, 0.0)] + sum(
        ([(10.0 - 30.0 * k, 24.0 * k), (10.0 - 30.0 * k, -24.0 * k)] for k in range(1, n)), [])
    )[:n],
}


class FormationLerp:
    """变阵插值：交错窗口 + ease-out-cubic（报告 §7.3：波浪式逐人就位）。"""

    def __init__(self, slots: list, stagger: float = 0.07, window: float = 0.55) -> None:
        self.from_slots = list(slots)
        self.to_slots = list(slots)
        self.t0 = -1e9
        self.stagger = stagger
        self.window = window
        self.now = 0.0

    def morph_to(self, new_slots: list) -> None:
        self.from_slots = self.positions()
        self.to_slots = list(new_slots)
        self.t0 = self.now

    def positions(self) -> list:
        out = []
        for i, (tx, ty) in enumerate(self.to_slots):
            fx, fy = self.from_slots[i]
            p = (self.now - self.t0 - i * self.stagger) / self.window
            u = ease_out_cubic(p)
            out.append((fx + (tx - fx) * u, fy + (ty - fy) * u))
        return out


# ================================================================== VFX 组件
class ScreenShake:
    """震屏：trauma² 衰减模型，渲染循环只读偏移量（0.1~0.2s 手感）。"""

    def __init__(self) -> None:
        self.trauma = 0.0

    def add(self, amount: float) -> None:
        self.trauma = min(1.0, self.trauma + amount)

    def update(self, dt: float) -> None:
        self.trauma = max(0.0, self.trauma - dt * 5.0)      # ≈0.2s 衰减完

    def offset(self) -> tuple[int, int]:
        m = 14.0 * self.trauma * self.trauma
        return (random.randint(-int(m), int(m)), random.randint(-int(m), int(m))) if m >= 1 else (0, 0)


class AfterimageTrail:
    """残影拖尾：高速/突进时按固定间隔快照全队位置，渲染预烘焙 ghost 变体。"""

    def __init__(self) -> None:
        self.snaps: list[tuple[float, list]] = []

    def maybe_push(self, now: float, positions: list, active: bool) -> None:
        self.snaps = [(t, p) for t, p in self.snaps if now - t < GHOST_TTL]
        if active and (not self.snaps or now - self.snaps[-1][0] >= GHOST_INTERVAL):
            self.snaps.append((now, list(positions)))

    def draw(self, surf: pygame.Surface, bank: SpriteBank, now: float,
             frames: list, utypes: list, anchor: tuple) -> None:
        for t, positions in self.snaps:
            for (ox, oy), frame, utype in zip(positions, frames, utypes):
                surf.blit(bank.get(utype, frame, "ghost"),
                          (anchor[0] + ox - 14, anchor[1] + oy - 40))


class SparkPool:
    """打击火花：纯色圆点粒子，速度衰减 + 透明度降低，数量硬上限。"""

    def __init__(self) -> None:
        self.parts: list[list] = []        # [x, y, vx, vy, life, max_life, color]

    def burst(self, x: float, y: float, n: int = 12,
              color: tuple = (255, 210, 90)) -> None:
        for _ in range(n):
            a = random.uniform(0, math.tau)
            v = random.uniform(60, 240)
            life = random.uniform(0.25, 0.45)
            self.parts.append([x, y, math.cos(a) * v, math.sin(a) * v - 60, life, life, color])
        del self.parts[:-MAX_SPARKS]

    def update(self, dt: float) -> None:
        alive = []
        for p in self.parts:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= 0.90                            # 速度衰减
            p[3] = p[3] * 0.90 + 320 * dt           # 微重力
            p[4] -= dt
            if p[4] > 0:
                alive.append(p)
        self.parts = alive

    def draw(self, layer: pygame.Surface) -> None:
        for x, y, _, _, life, max_life, color in self.parts:
            a = int(255 * life / max_life)          # 透明度降低
            pygame.draw.circle(layer, (*color, a), (int(x), int(y)), 3)


class FeverFX:
    """满堂彩滤镜系统：径向红晕（预烘焙）+ 队伍光环 + BLEND_ADD 金色剪影。"""

    def __init__(self, size: tuple = (SCREEN_W, SCREEN_H)) -> None:
        w, h = size
        self.ground_y = int(h * GROUND_Y / SCREEN_H)   # 地面线随画布等比
        self.vignette = pygame.Surface(size, pygame.SRCALPHA)
        cx, cy = w // 2, h // 2
        max_r = int(math.hypot(cx, cy))
        for i in range(36, 0, -1):                  # 一次性烘焙径向渐变
            r = int(max_r * i / 36)
            alpha = int(150 * (1 - i / 36) ** 2)
            pygame.draw.circle(self.vignette, (190, 20, 20, alpha), (cx, cy), r)
        self.ring_t = 0.0

    def draw_vignette(self, overlay: pygame.Surface) -> None:
        overlay.blit(self.vignette, (0, 0))

    def draw_ring(self, overlay: pygame.Surface, x: float, beat: float) -> None:
        """队伍脚下冲击波：每个整数拍扩散一圈（半径 = 拍相位函数）。"""
        frac = beat % 1.0
        r = int(20 + 90 * frac)
        a = int(160 * (1 - frac))
        pygame.draw.ellipse(overlay, (255, 120, 40, a), (x - r, self.ground_y + 6 - r // 6, 2 * r, max(4, r // 3)), 3)


# ================================================================== 主渲染器
class AdvancedSquadRenderer:
    """阵列渲染器：残影 → 光环 → 单位 → 火花 → 满堂彩滤镜，震屏整体偏移上屏。

    输入（依赖注入，对接 MusicDirector / SquadGame 时零改动）：
      positions  槽位空间坐标 [(ox, oy)]；utypes  兵种；beat  拍相位；bpm；
      fever  满堂彩；dashing  高速/突进（残影开关）；attack_beat  攻击拍号或 None；
      defend  铁壁防守姿态（扎马步+盾墙）；world_x  锚点世界坐标（地面刻度滚屏）；
      enemies  S5 站桩敌人 [(world_x, hp_ratio, flash01)]；boss  None 或
      (world_x, hp_ratio, state) —— state=="startup" 画预警圈
    """

    def __init__(self, screen_size: tuple = (SCREEN_W, SCREEN_H)) -> None:
        self.w, self.h = screen_size
        self.ground_y = int(self.h * GROUND_Y / SCREEN_H)   # 画布等比（默认 960×540 → 430）
        self.bank = SpriteBank()
        self.enemy_bank = EnemyBank()
        self.shake = ScreenShake()
        self.trail = AfterimageTrail()
        self.sparks = SparkPool()
        self.fever_fx = FeverFX(screen_size)
        self.world = pygame.Surface(screen_size)
        self.overlay = pygame.Surface(screen_size, pygame.SRCALPHA)     # 粒子+滤镜层
        self.now = 0.0

    def on_attack(self, x: float, y: float, perfect: bool) -> None:
        """外部事件钩子：攻击/Perfect → 火花 + 震屏。"""
        self.sparks.burst(x, y, n=16 if perfect else 8)
        self.shake.add(0.55 if perfect else 0.3)

    def render(self, screen: pygame.Surface, positions: list, utypes: list,
               anchor: tuple, beat: float, bpm: float,
               fever: bool, dashing: bool, attack_beat: float | None,
               bg: tuple = (18, 18, 26), dt: float = 1 / 60,
               defend: bool = False, world_x: float = 0.0,
               enemies: list = (), boss: tuple | None = None) -> None:
        self.now += dt
        self.shake.update(dt)
        self.sparks.update(dt)
        self.world.fill(bg)

        # 地面
        pygame.draw.rect(self.world, (36, 30, 30), (0, self.ground_y + 8, self.w, self.h - self.ground_y))
        pygame.draw.line(self.world, (90, 70, 60), (0, self.ground_y + 8), (self.w, self.ground_y + 8), 2)
        # 地面刻度（行军滚屏参考：每拍 1 格、每小节长格；急停/提速肉眼可见）
        k0 = math.floor(world_x - anchor[0] / PX_PER_UNIT) - 1
        k1 = math.floor(world_x + (self.w - anchor[0]) / PX_PER_UNIT) + 1
        for k in range(k0, k1 + 1):
            sx = int(anchor[0] + (k - world_x) * PX_PER_UNIT)
            bar_tick = (k % 4 == 0)
            pygame.draw.line(self.world, (105, 82, 70) if bar_tick else (58, 46, 42),
                             (sx, self.ground_y + 8), (sx, self.ground_y + (20 if bar_tick else 14)), 1)

        # S5 站桩敌人 / Boss（世界坐标 → 屏幕，随世界层参加震屏；画在队伍底层）
        for wx, hp_ratio, flash in enemies:
            sx = anchor[0] + (wx - world_x) * PX_PER_UNIT
            if sx < -60 or sx > self.w + 60:
                continue
            spr = self.enemy_bank.get("patrol", "base")
            self.world.blit(spr, (int(sx) - 14, self.ground_y + 8 - 40))
            if hp_ratio < 1.0:                              # 头顶血条（矢量，零贴图）
                pygame.draw.rect(self.world, (40, 36, 40), (int(sx) - 14, self.ground_y - 48, 28, 4))
                pygame.draw.rect(self.world, (220, 70, 60),
                                 (int(sx) - 14, self.ground_y - 48, int(28 * hp_ratio), 4))
            if flash > 0.0:                                 # 受击白热（预烘焙加法变体）
                self.world.blit(self.enemy_bank.get("patrol", "flash"),
                                (int(sx) - 14, self.ground_y + 8 - 40),
                                special_flags=pygame.BLEND_ADD)
        if boss is not None:
            bx, bhp_ratio, bstate = boss
            bsx = anchor[0] + (bx - world_x) * PX_PER_UNIT
            if -100 <= bsx <= self.w + 100:
                bspr = self.enemy_bank.get("boss", "base")
                self.world.blit(bspr, (int(bsx) - 32, self.ground_y + 8 - 88))
                pygame.draw.rect(self.world, (40, 36, 40), (int(bsx) - 32, self.ground_y - 96, 64, 6))
                pygame.draw.rect(self.world, (220, 70, 60),
                                 (int(bsx) - 32, self.ground_y - 96, int(64 * bhp_ratio), 6))

        # 帧选择：拍相位驱动 —— run 帧每个整数拍切换（踩点），攻击拍内用 attack 帧；
        # 防守姿态定帧 run_0（扎马步，停摆动）
        beat_frame = "run_0" if int(beat) % 2 == 0 else "run_1"
        attack_p = (beat - attack_beat) if attack_beat is not None and 0.0 <= beat - attack_beat < 1.0 else None
        frames = ["attack" if attack_p is not None else ("run_0" if defend else beat_frame)
                  for _ in positions]

        # 残影（长蛇突进 / 满堂彩时启用）
        self.trail.maybe_push(self.now, positions, active=(dashing or fever))
        self.trail.draw(self.world, self.bank, self.now, frames, utypes, anchor)

        # 覆盖层开篇清零（粒子 + 满堂彩光环/红晕共用此层）
        self.overlay.fill((0, 0, 0, 0))

        # 满堂彩：队伍脚下光环（矢量，零贴图）
        if fever:
            self.fever_fx.draw_ring(self.overlay, anchor[0], beat)

        # 铁壁防守：队前盾墙（矢量椭圆，随拍相位呼吸）
        if defend and positions:
            front = max(ox for ox, _ in positions)
            cx = anchor[0] + front + 30
            sa = 150 + int(60 * (1.0 - beat % 1.0))
            pygame.draw.ellipse(self.overlay, (120, 200, 255, sa),
                                (int(cx) - 14, self.ground_y - 64, 28, 72), 3)

        # S5 Boss 预警圈：脚下红环随拍相位收缩（激活拍逼近的压迫感）
        if boss is not None and boss[2] == "startup":
            bsx = anchor[0] + (boss[0] - world_x) * PX_PER_UNIT
            if -100 <= bsx <= self.w + 100:
                frac = beat % 1.0
                r = int(70 - 30 * frac)
                pygame.draw.ellipse(self.overlay, (255, 60, 40, 200),
                                    (int(bsx) - r, self.ground_y + 4 - r // 5, 2 * r, max(6, r // 2)), 3)
                pygame.draw.circle(self.overlay, (255, 120, 60, int(90 + 100 * frac)),
                                   (int(bsx), self.ground_y - 100), 6)

        # 单位：行军 bob（整数像素）+ 攻击跃起抛物线；防守 = 压身位停摆动
        for (ox, oy), frame, utype in zip(positions, frames, utypes):
            x = anchor[0] + ox - 14
            if defend:
                y = anchor[1] + oy - 40 + 5                     # 马步下沉（整数像素）
            else:
                y = anchor[1] + oy - 40 - march_bob(beat)
                if attack_p is not None:
                    y -= leap_y(attack_p)
            self.world.blit(self.bank.get(utype, frame, "base"), (x, y))
            if defend:                                          # 铁壁蓝色微光（预烘焙变体）
                self.world.blit(self.bank.get(utype, frame, "guard"), (x, y),
                                special_flags=pygame.BLEND_ADD)
            if fever:
                self.world.blit(self.bank.get(utype, frame, "glow"), (x, y),
                                special_flags=pygame.BLEND_ADD)

        # 粒子 + 满堂彩径向红晕（共用覆盖层，一次性合成；SRCALPHA 层数预算 ≤2）
        self.sparks.draw(self.overlay)
        if fever:
            self.fever_fx.draw_vignette(self.overlay)
        self.world.blit(self.overlay, (0, 0))

        # 震屏：整体偏移上屏
        sx, sy = self.shake.offset()
        screen.fill((0, 0, 0))
        screen.blit(self.world, (sx, sy))


# ================================================================== 4 拍指令输入层
# 「鼓点即步伐，节奏即动作」：J/K/L/S 即四面乐器，唯一玩法输入 = 一小节内连续
# 敲出 4 拍组合并踩准系统鼓点（perfect ±40ms / good ±80ms，DATA.judgement）。
# 相位循环：输入 → 应答唱和 → 执行 → 输入…；错序 / 脱拍 / 缺拍 / 同拍连点
# → 乱阵一小节（急停 + 散射 + 闪烁 + 破音），下一小节边界复阵（ADR-001 惯用法）。
# 判定 / 指令表 / 相位机全部复用 sandbox_patapon 已验证路径，本层只绑定视效音效。
KEYMAP = {pygame.K_j: "J", pygame.K_k: "K", pygame.K_l: "L", pygame.K_s: "S"}
KEY_SAMPLE = {"J": "咚", "K": "台", "L": "才", "S": "号角"}       # 击键即击鼓
CMD_BANNER = {"attack4": "猛虎下山！", "stride": "长蛇突进！",
              "defend": "铁壁阵！", "morph": "变阵！"}
CMD_HINT = "JJJJ 猛虎下山 · KKKK 长蛇突进 · LLLL 铁壁防守 · KLKL 变阵"
FORMATION_NAMES = {"changshe": "长蛇阵", "tiebi": "铁壁阵", "menghu": "猛虎阵"}
PHASE_NAMES = {"input": "输入·请击鼓", "echo": "应答唱和", "execute": "执行", "luan": "乱阵"}
GRADE_COLORS = {"perfect": (90, 255, 130), "good": (255, 220, 90), "off": (255, 85, 70)}
FEVER_STREAK = 2                  # 连续全 PERFECT 小节数 → 满堂彩


def _make_flash_steps(steps: int = 6) -> list:
    """乱阵红闪：启动期预烘焙多级透明度全屏层，渲染循环零 set_alpha。"""
    out = []
    for i in range(1, steps + 1):
        s = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        s.fill((200, 30, 30, int(105 * i / steps)))
        out.append(s)
    return out


def main() -> int:
    pygame.init()
    pygame.display.set_caption("踏鼓 · Patapon 阵列沙盒 —— 4 拍指令输入")
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    clock = pygame.time.Clock()
    try:
        font = pygame.font.SysFont("simhei", 16)
        mid = pygame.font.SysFont("simhei", 24)
        big = pygame.font.SysFont("simhei", 44)
    except Exception:
        font = mid = big = pygame.font.Font(None, 18)

    # ---- 拍源：真实音频设备优先（鼓点/唱和/反馈音可闻），失败降级虚拟时钟
    bank = Bank()
    audio = AudioEngine()
    if not audio.start():
        audio = NullAudioEngine()
        audio.start()
    chant = bank.samples.get("台")
    if chant is None:                               # numpy 数组不可用 or 判空
        chant = next(iter(bank.samples.values()))

    state = {"phase": "input"}                      # input / echo / execute / luan
    music = SandboxMusic(audio, bank, phase_fn=lambda: state["phase"])  # 输入小节背景鼓静音
    commander = RhythmCommander(music)              # 输入缓冲池 + 逐拍判定（沙盒已验证）

    renderer = AdvancedSquadRenderer()
    n = 8
    utypes = ["chui"] * 4 + ["luo"] * 2 + ["dun"] * 2
    forder = ["changshe", "tiebi", "menghu"]
    fid = 0
    lerp = FormationLerp(FORMATION_SLOTS[forder[fid]](n))
    anchor = MarchAnchor()                          # 世界坐标行军 → 地面刻度滚屏

    bar = 0
    command: str | None = None
    cmd_all_perfect = False
    hud_presses: list = []                          # 最近输入小节的按键快照（含失败）
    last_ab = -10                                   # 上一有效按键的绝对拍（拒绝同拍连点）
    last_grade = ("", 0.0)                          # 即时判定反馈（文字, ttl）
    banner = ("", 0.0)
    perfect_streak = 0
    fever = False
    attack_beat: float | None = None
    stride_until = -1.0
    defend_until = -1.0
    timeline: list[list] = []                       # 执行小节拍调度 [abeat, action]
    scatter = [[0.0, 0.0] for _ in range(n)]        # 乱阵散射偏移（像素，指数衰减归位）
    luan_flash = 0.0
    flash_steps = _make_flash_steps()

    def enter_bar(b: int) -> None:
        """小节边界相位机（与 sandbox_patapon.SquadGame.on_bar 同构）。"""
        nonlocal command, cmd_all_perfect, perfect_streak, fever, fid
        nonlocal stride_until, defend_until, luan_flash, banner, last_ab
        phase = state["phase"]
        now = audio.audio_time()
        if phase == "input":
            hud_presses[:] = commander.presses
            cmd_all_perfect = (len(commander.presses) == 4
                               and all(g == "perfect" for _, g, _, _ in commander.presses))
            command = commander.evaluate()          # 错序 / 脱拍(off) / 缺拍 → None
            commander.clear()
            if command is None:                                  # —— 乱阵
                state["phase"] = "luan"
                anchor.freeze(music.beat_pos)                    # 急停（拍位冻结）
                perfect_streak = 0
                fever = False
                rng = random.Random(b * 7919)
                for s in scatter:                                # 散射（随后指数衰减归位）
                    s[0] = rng.uniform(-30.0, 30.0)
                    s[1] = rng.uniform(-22.0, 8.0)
                luan_flash = 1.0
                renderer.shake.add(0.85)
                audio.schedule(now + 0.01, bank.feedback["hurt"], 0.8)   # 破音
                audio.schedule(now + 0.14, bank.feedback["off"], 0.7)
                banner = ("乱 阵 ！", 1.2)
            else:                                                # —— 应答唱和
                state["phase"] = "echo"
                perfect_streak = perfect_streak + 1 if cmd_all_perfect else 0
                if perfect_streak >= FEVER_STREAK and not fever:
                    audio.schedule(now + 0.01, bank.samples["号角"], 0.5)
                fever = perfect_streak >= FEVER_STREAK
                for k in range(4):                               # 本小节 4 拍唱和
                    audio.schedule(music.time_at_beat(b * 4 + k, now), chant, CHANT_GAIN)
                banner = (CMD_BANNER[command], 1.4)
        elif phase == "echo":
            state["phase"] = "execute"
            b0 = float(b * music.bar_beats)
            if command == "attack4":                             # 猛虎下山：执行小节 4 拍连劈
                for k in range(4):
                    timeline.append([b0 + k, "attack"])
            elif command == "stride":                            # 长蛇突进：本小节 1.5× 行军
                anchor.set_mult(1.5, music.beat_pos)             # 重定基 → 位置连续
                stride_until = b0 + 4
                timeline.append([b0 + 4, "stride_end"])
                audio.schedule(now + 0.01, bank.samples["嘟"], 0.7)
            elif command == "defend":                            # 铁壁：整小节马步盾墙
                defend_until = b0 + 4
                audio.schedule(now + 0.01, bank.samples["匡"], 0.7)
            elif command == "morph":                             # 变阵：交错插值逐人就位
                fid = (fid + 1) % len(forder)
                lerp.morph_to(FORMATION_SLOTS[forder[fid]](n))
                audio.schedule(now + 0.01, bank.samples["号角"], 0.6)
        elif phase in ("execute", "luan"):
            if phase == "luan":
                anchor.resume(music.beat_pos)                    # 复阵（位置连续）
            state["phase"] = "input"
            hud_presses.clear()
            last_ab = -10

    while True:
        dt = min(clock.tick(60) / 1000.0, 0.05)

        # ---- 击鼓输入：落缓冲池 + 立即判定反馈（锚点 = 事件处理时刻的音频时钟）
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                audio.stop()
                pygame.quit()
                return 0
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    audio.stop()
                    pygame.quit()
                    return 0
                key = KEYMAP.get(ev.key)
                if key is not None:
                    t = audio.audio_time()
                    audio.schedule(t + 0.005, bank.samples[KEY_SAMPLE[key]], 0.85)
                    ab = round(music.beat_at(t))
                    if (state["phase"] == "input" and len(commander.presses) < 4
                            and ab > last_ab):
                        last_ab = ab
                        commander.on_press(key, t)
                        grade = commander.presses[-1][1]
                        last_grade = (grade.upper() + ("!" if grade == "perfect" else ""), 0.45)
                        if grade == "off":                       # 脱拍闷音
                            audio.schedule(t + 0.03, bank.feedback["off"], 0.5)

        # ---- 拍源推进（tempo.py 原路径；dt>0.25 卡顿守卫生效）
        music.update(0.0)
        beat = music.beat_pos
        cur_bar = int(beat // music.bar_beats)
        if cur_bar != bar:
            bar = cur_bar
            enter_bar(bar)

        # ---- 执行小节：拍点触发攻击特效 / 收提速
        due = [e for e in timeline if e[0] <= beat + 1e-6]
        timeline[:] = [e for e in timeline if e[0] > beat + 1e-6]
        for ab, act in due:
            if act == "attack":
                attack_beat = ab
                front = max(x for x, _ in FORMATION_SLOTS[forder[fid]](n))
                renderer.on_attack(300 + front + 46, GROUND_Y - 30, perfect=cmd_all_perfect)
                audio.schedule(audio.audio_time() + 0.005, bank.feedback["hit"], 0.8)
            elif act == "stride_end":
                anchor.set_mult(1.0, music.beat_pos)
        if attack_beat is not None and beat - attack_beat >= 1.0:
            attack_beat = None

        # ---- 行军 / 散射衰减 / 计时器
        anchor.step(beat)
        damp = math.exp(-6.0 * dt)
        for s in scatter:
            s[0] *= damp
            s[1] *= damp
        luan_flash = max(0.0, luan_flash - dt * 1.4)
        last_grade = (last_grade[0], max(0.0, last_grade[1] - dt))
        banner = (banner[0], max(0.0, banner[1] - dt))
        lerp.now += dt

        # ---- 渲染（乱阵闪烁 = 逐帧抽半数单位）
        positions = [(ox + s[0], oy + s[1]) for (ox, oy), s in zip(lerp.positions(), scatter)]
        idx = list(range(n))
        if state["phase"] == "luan":
            idx = [i for i in idx if (int(renderer.now * 12) + i) % 2 == 0]
        renderer.render(screen,
                        [positions[i] for i in idx], [utypes[i] for i in idx],
                        anchor=(300, GROUND_Y), beat=beat, bpm=music.bpm,
                        fever=fever, dashing=beat < stride_until,
                        attack_beat=attack_beat, dt=dt,
                        defend=beat < defend_until, world_x=anchor.x)

        # ---- 乱阵红闪（预烘焙层级，零 set_alpha）
        if luan_flash > 0.0:
            screen.blit(
                flash_steps[min(len(flash_steps) - 1, int(luan_flash * len(flash_steps)))],
                (0, 0))

        # ---- HUD
        layer = music.layers[music.layer_index]
        info = (f"{layer.get('name', layer.get('id', '?'))} BPM {music.bpm:.0f}   "
                f"阵型 {FORMATION_NAMES[forder[fid]]}   相位 {PHASE_NAMES[state['phase']]}   "
                f"连Perfect {perfect_streak}   满堂彩 {'ON' if fever else 'off'}   "
                f"FPS {clock.get_fps():.0f}")
        screen.blit(font.render(info, True, (230, 230, 230)), (12, 10))
        screen.blit(font.render(CMD_HINT + "   [Esc] 退出", True, (150, 150, 160)), (12, 32))

        # 4 拍输入槽：圈 = 拍点（输入小节随拍相位脉冲），敲入后显示按键 + 评级色
        slots = commander.presses if state["phase"] == "input" else hud_presses
        bib = beat % music.bar_beats
        for i in range(4):
            cx = SCREEN_W // 2 - 90 + i * 60
            cy = SCREEN_H - 54
            pulse = max(0.0, 1.0 - abs(bib - i) * 2.0) if state["phase"] == "input" else 0.0
            pygame.draw.circle(screen, (66, 62, 78), (cx, cy), 16)
            pygame.draw.circle(screen, (240, 210, 120) if pulse > 0.3 else (110, 106, 125),
                               (cx, cy), 16 + int(3 * pulse), 2)
            if i < len(slots):
                k, g, _, _ = slots[i]
                pygame.draw.circle(screen, GRADE_COLORS[g], (cx, cy), 12)
                t = font.render(k, True, (12, 12, 16))
                screen.blit(t, t.get_rect(center=(cx, cy)))
            else:
                t = font.render(str(i + 1), True, (96, 92, 110))
                screen.blit(t, t.get_rect(center=(cx, cy)))

        if last_grade[1] > 0.0 and last_grade[0]:
            col = GRADE_COLORS.get(last_grade[0].rstrip("!").lower(), (255, 255, 255))
            t = mid.render(last_grade[0], True, col)
            screen.blit(t, t.get_rect(center=(SCREEN_W // 2, SCREEN_H - 96)))
        if banner[1] > 0.0 and banner[0]:
            col = (255, 92, 72) if "乱" in banner[0] else (255, 220, 90)
            t = big.render(banner[0], True, col)
            screen.blit(t, t.get_rect(center=(SCREEN_W // 2, 118)))
        pygame.display.flip()


if __name__ == "__main__":
    sys.exit(main())
