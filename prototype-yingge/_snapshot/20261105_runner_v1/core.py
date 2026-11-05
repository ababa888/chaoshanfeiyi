"""英歌 × Patapon 原型逻辑核心（第三轮）。

不 import pygame：判定、8 拍循环、三兵种、四阵、自动行军、鼓劲槽/Fever、
Boss 四拍破阵、极限破阵与难度分支全部可用虚拟时钟在无显示器环境跑通。

时间基准 = 高精度计时器。BPM 默认 132（快板）。
8 拍一个循环：前 4 拍收令，后 4 拍行动/结算。
自动行军：每拍判定一次，保持合拍就自动前压；不打指令也不会站桩。
Boss 抬手卡在循环第 5 拍（行动拍 1）并公示招式，玩家有 4 拍（54 / 55 / 56 / 57）
输入化解令；全 Perfect 触发「极限破阵」硬直。
"""
from __future__ import annotations

import copy
import json
import math
import os
import random
from dataclasses import dataclass, field

import pseudo3d as p3d

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "config")


def _load_json_config(name: str, default: dict) -> dict:
    """读 config/*.json；缺失或损坏时退回内置表，保证原型仍可跑。"""
    path = os.path.join(CONFIG_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = copy.deepcopy(default)
        merged.update(data)
        return merged
    except Exception:
        return copy.deepcopy(default)

# ---------------------------------------------------- 长关卡表（读取失败时的兜底）
LEVEL_DEFAULT = {
    "length_units": 148.0,
    "u_min": -12.0,
    "wake_units": 12.0,
    "march_boost": 1.45,
    "wave_clear_heal": 0.55,
    "wave_clear_revive": 0.40,
    "segments": [
        {"index": 1, "name": "坡上林地", "u0": 0.0, "u1": 44.0,
         "slope_deg": 8.0, "bpm": 126.0, "lantern_density": 0.55,
         "recommend": "changshe", "gate": "石阶", "palette": "forest",
         "march_boost": 1.45,
         "waves": [{"u": 16.0, "grunt": 2, "brute": 0},
                   {"u": 30.0, "grunt": 3, "brute": 0},
                   {"u": 40.0, "grunt": 2, "brute": 1}]},
        {"index": 2, "name": "坡中街市", "u0": 44.0, "u1": 98.0,
         "slope_deg": 10.0, "bpm": 132.0, "lantern_density": 1.0,
         "recommend": "fengshi", "gate": "牌坊", "palette": "market",
         "march_boost": 1.45,
         "waves": [{"u": 52.0, "grunt": 3, "brute": 0},
                   {"u": 64.0, "grunt": 3, "brute": 0},
                   {"u": 76.0, "grunt": 4, "brute": 0},
                   {"u": 86.0, "grunt": 3, "brute": 1}]},
        {"index": 3, "name": "坡底广场", "u0": 98.0, "u1": 148.0,
         "slope_deg": 12.0, "bpm": 138.0, "lantern_density": 0.35,
         "recommend": "menghu", "gate": "石阶", "palette": "plaza",
         "march_boost": 1.45,
         "waves": [{"u": 106.0, "grunt": 3, "brute": 0},
                   {"u": 118.0, "grunt": 4, "brute": 0},
                   {"u": 128.0, "grunt": 3, "brute": 1},
                   {"u": 136.0, "grunt": 3, "brute": 0}]},
    ],
    "boss": {"u": 142.5, "platform_u0": 139.5, "platform_u1": 147.5,
             "platform_v_half": 3.2, "thickness_px": 30, "steps": 3},
    "props": {"mile_every": 10.0, "lane_spacing": 5.0},
}
LEVEL = _load_json_config("level_long.json", LEVEL_DEFAULT)


def segment_index_at(u: float) -> int:
    """u 落在 [u0, u1) 的段序号；越界时取最近的段。"""
    segs = LEVEL["segments"]
    if not segs:
        return 0
    best, best_dist = 0, math.inf
    for i, seg in enumerate(segs):
        if float(seg["u0"]) <= float(u) < float(seg["u1"]):
            return i
        dist = min(abs(float(u) - float(seg["u0"])),
                   abs(float(u) - float(seg["u1"])))
        if dist < best_dist:
            best, best_dist = i, dist
    return best


def segment_at(u: float) -> dict:
    """u 所属段落配置（读取 LEVEL，不在代码里硬编码关卡数据）。"""
    segs = LEVEL["segments"]
    return segs[segment_index_at(u)] if segs else {}


# ------------------------------------------------------------------ 常量表
BPM = 132.0
BEAT_MS = 60000.0 / BPM
CYCLE_BEATS = 8
INPUT_BEATS = 4

# 判定窗口（毫秒，标准档）。操练档按 DIFFICULTIES.window_scale 放宽。
PERFECT_MS = 45.0
GOOD_MS = 100.0
MISS_MS = 160.0
# Fever 期间判定窗口适度放宽：Perfect +20ms、Good +30ms（见 FEVER_WINDOW_ADD）
FEVER_WINDOW_ADD = {"perfect": 20.0, "good": 30.0}

GRADES = ("perfect", "good", "miss")

# 自动行军：每拍在窗口内合拍就前压一小步；连续合拍加成
AUTO_MARCH = {
    "step": 0.52,            # 每拍基础前压（世界单位）
    "max_step": 0.92,        # 连击拉满时的单拍前压
    "streak_step": 0.055,    # 每多一拍合拍的增量
    "window_ms": 110.0,      # 合拍窗口（比 Good 略宽，避免严苛）
    "stall_dust": 0.26,      # 脱拍时扬尘强度
}
# 自动行军节奏：强拍抬脚、弱拍落步
MARCH_PHASE = {"strong": "march_1", "weak": "march_0"}

# 难度：窗口宽容、敌伤、Boss 血量、鼓劲槽、Fever 时长与冷却
DIFFICULTIES = {
    "drill": {"name": "操练", "window_scale": 1.35, "enemy_dmg": 0.70,
              "boss_hp": 420.0, "fever_gauge": 10, "fever_sec": 12.0,
              "fever_cd_sec": 3.0},
    "standard": {"name": "标准", "window_scale": 1.00, "enemy_dmg": 1.00,
                 "boss_hp": 600.0, "fever_gauge": 14, "fever_sec": 10.0,
                 "fever_cd_sec": 4.0},
}

# 极板：Fever 期 BPM 提升，上限 150 BPM（见 README 的理由）
FEVER_BPM = 150.0
FEVER_BPM_CEIL = 150.0
FEVER_DAMAGE = 2.0
STAGGER_SEC = 1.9

# 补打：仅二/三阶段，每招一次；错令或窗口内漏拍后 1 拍内补上正确序列 → 伤害减半。
# 补打不给 Perfect（按 Good 计）、不累积鼓劲槽、不清连击；奖励小于一次干净破阵。
MAKEUP = {
    "phases": (2, 3),
    "window_beats": 1.0,
    "damage_mult": 0.5,
}

# 四拍命令：J=鼓 / K=锣 / L=镲
COMMANDS = {
    "JJJJ": ("attack", "猛虎下山"),
    "KKKK": ("march", "长蛇突进"),
    "LLLL": ("defend", "铁壁守阵"),
    "JKJK": ("fengshi", "锋矢阵"),
    "LKLK": ("guijia", "龟甲阵"),
    "JJKK": ("shuanglong", "双龙出海"),
    "KLKL": ("menghu", "猛虎下山阵"),
}
COMMAND_NAMES = {cmd[0]: cmd[1] for cmd in COMMANDS.values()}
# 指令 → 四拍键位（补打/教学提示用）
COMMAND_KEYS = {cmd[0]: keys for keys, cmd in COMMANDS.items()}
COMMAND_HINTS = {
    "attack": "J J J J  攻",
    "march": "K K K K  行",
    "defend": "L L L L  守",
    "fengshi": "J K J K  锋矢",
    "guijia": "L K L K  龟甲",
    "shuanglong": "J J K K  双龙",
    "menghu": "K L K L  猛虎",
}

# 兵种：承伤顺序 shield → drummer → spear
UNIT_TYPES = {
    "shield": {"name": "盾兵", "max_hp": 46.0, "atk": 10.0,
               "armor": 0.35, "range": 1.6, "color": (92, 178, 138),
               "fever": "护阵：全队减伤加深"},
    "drummer": {"name": "鼓手", "max_hp": 34.0, "atk": 18.0,
                "armor": 0.05, "range": 1.3, "color": (232, 80, 46),
                "fever": "双击：追加一次鼓击"},
    "spear": {"name": "矛兵", "max_hp": 30.0, "atk": 14.0,
              "armor": 0.05, "range": 2.4, "color": (154, 108, 188),
              "fever": "穿阵：无视护甲并延长射程"},
}
FRONT_ORDER = ("shield", "drummer", "spear")

# 阵法：持续 buff + 代价。4 阵克制关系写在 README。
# atk 攻击倍率 / dr 减伤 / march 行军倍率 / lag 连击容错（-1 表示错一拍断档）
FORMATIONS = {
    "changshe": {"name": "长蛇阵", "atk": 1.00, "dr": 0.00, "march": 1.00,
                 "lag": 0, "desc": "纵深一列，均衡"},
    "fengshi": {"name": "锋矢阵", "atk": 1.30, "dr": -0.10, "march": 1.15,
                "lag": 0, "desc": "箭簇展开，攻强守弱"},
    "guijia": {"name": "龟甲阵", "atk": 0.80, "dr": 0.40, "march": 0.75,
               "lag": 1, "desc": "缩成一团，坚守缓行"},
    "shuanglong": {"name": "双龙出海", "atk": 1.10, "dr": 0.05, "march": 1.45,
                   "lag": 0, "split": True,
                   "desc": "左右两列并进，机动极高"},
    "menghu": {"name": "猛虎下山阵", "atk": 1.75, "dr": -0.30, "march": 0.60,
               "lag": -1, "stun_sec": 2.0,
               "desc": "一字横排强攻，攻击后硬直 2 秒、减伤 -30%"},
}

# 阵型站位：世界平面 (u, v)。u 沿下坡向敌阵（越大越前），v 横跨坡宽
# （正 v 更远、屏幕偏上左）。五阵都有明确的前后排差异，槽位彼此不重叠。
FORMATION_SLOTS = {
    "changshe": [(0.00, 0.00), (-1.45, 0.00), (-2.90, 0.00)],
    "fengshi": [(0.45, 0.00), (-0.85, -2.20), (-0.85, 2.20)],
    "guijia": [(0.85, -1.65), (0.85, 1.65), (-0.75, 0.00)],
    "shuanglong": [(0.30, -2.30), (0.30, 2.30), (-1.25, 0.00)],
    "menghu": [(0.85, -3.00), (0.85, 3.00), (0.00, 0.00)],
}

# 阵型地面足迹（用于画“队列站在斜面上”的格线；3×3 仅龟甲铺满）。
FORMATION_FOOTPRINT = {
    "changshe": (1, 3),      # 1 列 × 3 排
    "fengshi": (3, 2),       # 前 1 + 后 2 的箭簇
    "guijia": (3, 3),        # 3×3 方阵足迹（单位占其中三格）
    "shuanglong": (2, 3),    # 左右两列
    "menghu": (3, 2),        # 宽 V
}

# 命令 → 目标阵型（attack / defend 是临时状态，不改变阵型）
COMMAND_FORMATION = {"fengshi": "fengshi", "guijia": "guijia",
                     "shuanglong": "shuanglong", "menghu": "menghu"}

# Boss 招式：固定节奏型（两拍蓄力 + 一拍起手 + 一拍落下；公示文里 4 个拍位）
# counter 固定 4 拍全同键：AOE→L、单体重击→K、抓取→J；双龙/猛虎以加伤方式参与。
INTENTS = {
    "slam": {"name": "裂地重砸", "icon": "slam", "kind": "heavy",
             "keys": "KKKK", "counter": "march", "tell": "后撤：K K K K",
             "rhythm": (0.55, 0.80, 1.15, 1.45), "dmg": 20.0, "aoe": False},
    "sweep": {"name": "横扫千军", "icon": "sweep", "kind": "aoe",
              "keys": "LLLL", "counter": "defend", "tell": "架挡：L L L L",
              "rhythm": (0.85, 1.10, 1.15, 1.30), "dmg": 15.0, "aoe": True},
    "charge": {"name": "鼓王冲锋", "icon": "charge", "kind": "heavy",
               "keys": "KKKK", "counter": "march", "tell": "侧闪：K K K K",
               "rhythm": (0.30, 0.50, 1.20, 1.60), "dmg": 18.0, "aoe": False},
    "grab": {"name": "勾魂鼓爪", "icon": "grab", "kind": "grab",
             "keys": "JJJJ", "counter": "attack", "tell": "突击：J J J J",
             "rhythm": (0.45, 0.70, 0.95, 1.35), "dmg": 22.0, "aoe": False},
    "roar": {"name": "震天鼓吼", "icon": "roar", "kind": "aoe",
             "keys": "LLLL", "counter": "defend", "tell": "架挡：L L L L",
             "rhythm": (1.00, 1.10, 1.05, 1.15), "dmg": 12.0, "aoe": True},
}
INTENT_ORDER = ("slam", "sweep", "charge", "grab", "roar")
AOE_INTENTS = tuple(k for k, v in INTENTS.items() if v.get("aoe"))


def tutorial_hint_text(key: str) -> str:
    """一次性教程提示文案，例如「对 AOE 打 L-L-L-L」。"""
    intent = INTENTS[key]
    if intent.get("aoe"):
        label = "AOE"
    elif intent.get("kind") == "grab":
        label = "抓取"
    else:
        label = "单体重击"
    return f"对 {label} 打 {'-'.join(intent['keys'])}"


# ---------------------------------------------------- Boss 意图权重谱（可 seed）
BOSS_SCORE_DEFAULT = {
    "version": 1,
    "grace_beats": 2,
    "max_repeat": 2,
    "aoe_gap_beats": 6,
    "phase_open_min_reveal_beats": 4,
    "reveal_beats": 4,
    "phases": [
        {"id": 1, "name": "起势", "hp_min": 0.66, "hp_max": 1.01,
         "pool": {"slam": 30, "sweep": 18, "grab": 34, "roar": 18},
         "open_pool": ["sweep", "slam"]},
        {"id": 2, "name": "翻江", "hp_min": 0.33, "hp_max": 0.66,
         "pool": {"slam": 22, "sweep": 18, "charge": 26, "grab": 24,
                  "roar": 10},
         "open_pool": ["charge", "slam"]},
        {"id": 3, "name": "绝命", "hp_min": 0.0, "hp_max": 0.33,
         "pool": {"slam": 16, "sweep": 12, "charge": 30, "grab": 22,
                  "roar": 20},
         "open_pool": ["roar", "charge"]},
    ],
}
BOSS_SCORE = _load_json_config("boss_score.json", BOSS_SCORE_DEFAULT)
PHASE_NAMES = {p["id"]: p["name"] for p in BOSS_SCORE["phases"]}

# ---------------------------------------------------- Boss 石台高度优势
BOSS_PLATFORM = {
    "height_px": 18.0,            # 石台台面比坡面高 18px（约 0.23 世界单位）
    "boss_damage_mult": 1.35,     # 台上 Boss 对台下近战伤害 ×1.35
    "player_damage_mult": 0.85,   # 台下仰攻台上 Boss（命中率 85%，伤害 ×0.85）
    "knockdown_stagger_sec": 3.4, # 破阵击落台下的更长硬直（普通硬直 1.9s）
    "wall_h": 16,                 # 台边矮墙高度（px）
    "wall_merlons": 3,
}
BOSS_PLATFORM = {**BOSS_PLATFORM, **BOSS_SCORE.get("platform", {})}

# ---------------------------------------------------- 新手渐进引导
TUTORIAL = {
    "grace_attacks": 3,       # 前 3 次 Boss 出招为教学招
    "damage_mult": 0.0,       # 教学招只公示、不结算伤害（也不清连击/鼓劲槽）
    "hint_sec": 2.8,          # 每条招式提示只出现一次，2.8s 后自动消失
}
TUTORIAL = {**TUTORIAL, **BOSS_SCORE.get("tutorial", {})}

# ---------------------------------------------------- 阵法 × 招式克制矩阵
COUNTER_MATRIX_DEFAULT = {
    "version": 1,
    "bonus_kind": "damage_multiplier",
    "matrix": {
        "changshe": {"slam": 1.25, "sweep": 0.90, "charge": 1.00,
                     "grab": 1.30, "roar": 1.00},
        "fengshi": {"slam": 0.95, "sweep": 0.85, "charge": 1.10,
                    "grab": 1.35, "roar": 0.90},
        "guijia": {"slam": 1.10, "sweep": 1.35, "charge": 0.80,
                   "grab": 0.85, "roar": 1.30},
        "shuanglong": {"slam": 1.20, "sweep": 1.00, "charge": 1.35,
                       "grab": 1.05, "roar": 0.85},
        "menghu": {"slam": 1.15, "sweep": 0.80, "charge": 1.35,
                   "grab": 1.30, "roar": 0.85},
    },
}
COUNTER_CONFIG = _load_json_config("counter_matrix.json", COUNTER_MATRIX_DEFAULT)
COUNTER_MATRIX = COUNTER_CONFIG["matrix"]

# 克制关系（给 README/Panel 用）：阵 → 最擅长的破阵招式（矩阵 >1 的列）
FORMATION_COUNTERS = {
    form: tuple(k for k, v in row.items() if float(v) > 1.0)
    for form, row in COUNTER_MATRIX.items()
}

# 渲染层与逻辑层共用的近似屏幕映射（火花定位 / 手势）
# 逻辑视口 960×540：队伍锚点左移，px/单位由 78 降到 48（可视世界 20 单位）
SCREEN_BASE_X = 360.0
PX_PER_UNIT = 48.0

# 相机跟随死区（世界单位）与跟随刚度；死区内不追，避免站桩抖动
CAMERA = {
    "deadzone_units": 0.35,
    "follow_k": 5.2,
}

# ------------------------------------------------------------ 下坡地形
# 10° 斜坡向敌阵（屏幕右方）下降；屏幕斜率直接用 tan(10°)。
# 脚底基线：y = GROUND_SCREEN_Y + SLOPE*(px - SCREEN_BASE_X) + local_offset
TERRAIN = {
    "slope_deg": 10.0,          # 8–12° 可调
    "down_gain": 0.28,          # 下坡速度加成上限 +28%
    "up_cost": 1.35,            # 上坡/逆坡代价 ×1.35（速度 ≈0.74）
    "accel_start": 0.40,        # 起步加速度（首拍只吃到 40% 加成）
    "accel_per_beat": 0.14,     # 每多一拍合拍，加速度上浮
    "knock_down_gain": 1.45,    # 下坡击退距离 ×1.45
    "knock_up_cost": 1.50,      # 上坡击退距离 ×0.67（1.5 倍代价）
    "camera_dip_max": 22.0,     # 镜头随队伍下压的最大像素（540 高视口）
    "visual_tilt": True,        # 视觉倾斜开关（关掉后直立贴地，便于接骨骼对照）
    "tilt_deg": 10.0,           # 身体沿坡倾斜角 ≈ 坡度（8–12° 可调）
    "tilt_charge_max": 6.0,     # 下坡冲锋按加速度叠加的额外前倾上限（0–6°）
    "tilt_hurt_back": 6.0,      # 受击短暂后仰（从坡面倾斜里减去）
    "down_roll_px": 30.0,       # 倒地顺坡滚动最大像素
    "down_roll_sec": 0.55,      # 倒地滚动到停的时长
}
SLOPE = math.tan(math.radians(TERRAIN["slope_deg"]))
GROUND_SCREEN_Y = 392.0          # 队伍锚点处的坡面高度（540 高视口）
DEPTH_X_PX = 58.0                # 阵型纵深 → 沿坡面的水平铺开像素


def ground_screen_y(px: float, local_offset: float = 0.0) -> float:
    """坡面脚底基线；任意屏幕 x 都在可视区内，不悬空、不穿地。"""
    return GROUND_SCREEN_Y + SLOPE * (float(px) - SCREEN_BASE_X) \
        + float(local_offset)


def slope_march_factor(direction: float, streak: int = 0) -> float:
    """沿坡行军速度系数：下坡加速（随连拍爬升），上坡按 1.35 倍代价减速。"""
    if direction >= 0:
        return 1.0 + TERRAIN["down_gain"] * march_accel(streak)
    return 1.0 / TERRAIN["up_cost"]


def march_accel(streak: int = 0) -> float:
    """当前下坡加速度 0–1：起步 0.40，每多一拍合拍 +0.14，5 拍左右拉满。"""
    return min(1.0, float(TERRAIN["accel_start"])
               + float(TERRAIN["accel_per_beat"]) * max(0, int(streak) - 1))


def charge_tilt_deg(streak: int = 0) -> float:
    """下坡冲锋额外前倾：按当前加速度给 0–6°。"""
    return float(TERRAIN["tilt_charge_max"]) * march_accel(streak)


def unit_tilt_deg(walking: bool, streak: int = 0, direction: float = 1.0,
                  hurt_ratio: float = 0.0,
                  visual_tilt: bool | None = None) -> float:
    """身体沿坡法线的视觉倾斜角（正值 = 顺坡前倾，顺时针）。

    - 基准 = 坡度（默认 10°，落在 8–12° 区间）；
    - 下坡行军按加速度叠加 0–6°；
    - 急停/待机回到基准；
    - 受击按 `hurt_ratio` 短暂后仰，最多减 6°。
    `visual_tilt=False` 时返回 0（直立贴地）。
    """
    enabled = TERRAIN["visual_tilt"] if visual_tilt is None else bool(visual_tilt)
    if not enabled:
        return 0.0
    deg = float(TERRAIN["tilt_deg"])
    if walking and direction >= 0:
        deg += charge_tilt_deg(streak)
    deg -= float(TERRAIN["tilt_hurt_back"]) * max(0.0, min(1.0, hurt_ratio))
    return deg


def tilt_blit_pivot(width: int, height: int, deg: float,
                    feet_y: float | None = None) -> tuple[float, float, int, int]:
    """绕脚底锚点旋转后的落位参数：返回 (pivot_x, pivot_y, rot_w, rot_h)。

    旋转角 `deg` 以“顺坡前倾为正”（屏幕顺时针）；pygame 逆时针为正，
    渲染层取 `-deg`。脚底锚点取贴图底边中点（与现有 blit 口径一致）。
    """
    w, h = float(width), float(height)
    fy = h if feet_y is None else float(feet_y)
    th = math.radians(float(deg))
    rw = int(abs(w * math.cos(th)) + abs(h * math.sin(th)))
    rh = int(abs(w * math.sin(th)) + abs(h * math.cos(th)))
    vy = fy - h / 2.0
    # 屏幕坐标 y 向下，顺时针旋转：x' = vy·sin，y' = vy·cos
    px = rw / 2.0 + vy * math.sin(th)
    py = rh / 2.0 + vy * math.cos(th)
    return px, py, rw, rh


def down_roll_offset(down_t: float) -> float:
    """倒地顺坡滚动位移（px）：前 0.55s 缓出滚 30px 后停，不原地躺平。"""
    k = max(0.0, min(1.0, float(down_t) / float(TERRAIN["down_roll_sec"])))
    return float(TERRAIN["down_roll_px"]) * (1.0 - (1.0 - k) ** 3)


def slope_knock_scale(direction: float) -> float:
    """击退沿坡修正：下坡更远，上坡更短。"""
    if direction >= 0:
        return float(TERRAIN["knock_down_gain"])
    return 1.0 / float(TERRAIN["knock_up_cost"])


def slope_knock_distance(base: float, direction: float) -> float:
    return float(base) * slope_knock_scale(direction)


# ------------------------------------------------------------ 水浒英雄帧表
_STATE_SPEC_22 = {
    "idle": {"count": 4, "durations_ms": [520, 520, 520, 520],
             "peak": -1, "loop": "loop", "cancelable": True},
    "march": {"count": 6, "durations_ms": [140, 140, 150, 150, 140, 140],
              "peak": -1, "loop": "loop", "cancelable": True},
    "attack": {"count": 4, "durations_ms": [90, 110, 130, 150],
               "peak": 2, "loop": "once", "cancelable": False},
    "hurt": {"count": 2, "durations_ms": [120, 220],
             "peak": -1, "loop": "once", "cancelable": False},
    "down": {"count": 2, "durations_ms": [200, 800],
             "peak": -1, "loop": "hold", "cancelable": False},
    "skill": {"count": 4, "durations_ms": [100, 130, 140, 180],
              "peak": 2, "loop": "once", "cancelable": False},
}

HERO_FRAMES_DEFAULT = {
    "version": 2,
    "frame_size": [144, 192],
    "baseline": 180,
    "palette_count": 40,
    "heroes": {
        "wusong": {"name": "武松", "nick": "行者", "kind": "drummer",
                   "face": "赤面", "role": "鼓手 · 赤手重击",
                   "skill": "双抛槌", "weapon": "双槌",
                   "tagline": "赤面金睛，领鼓开阵",
                   "frames": _STATE_SPEC_22},
        "linchong": {"name": "林冲", "nick": "豹子头", "kind": "spear",
                     "face": "白面豹纹", "role": "矛兵 · 枪棒突刺",
                     "skill": "回马枪", "weapon": "长枪",
                     "tagline": "枪出如龙，回马封喉",
                     "frames": _STATE_SPEC_22},
        "likui": {"name": "李逵", "nick": "黑旋风", "kind": "shield",
                  "face": "黑面环眼", "role": "盾兵 · 双斧横扫",
                  "skill": "旋风劈", "weapon": "双斧",
                  "tagline": "双斧开路，黑塔承伤",
                  "frames": _STATE_SPEC_22},
    },
}
HERO_FRAMES = _load_json_config("hero_frames.json", HERO_FRAMES_DEFAULT)
HEROES = HERO_FRAMES["heroes"]
HERO_FOR_KIND = {spec["kind"]: hid for hid, spec in HEROES.items()}
HERO_NAMES = {hid: spec["name"] for hid, spec in HEROES.items()}
HERO_SKILLS = {hid: spec.get("skill", "") for hid, spec in HEROES.items()}
HERO_PEAK_PROGRESS = 0.42          # 攻击动画到达峰值帧的进度


def hero_frame_spec(hero: str, state: str) -> dict:
    return HEROES[hero]["frames"][state]


def hero_peak_index(hero: str, state: str) -> int:
    return int(hero_frame_spec(hero, state).get("peak", -1))


def hero_state_frame(hero: str, state: str, progress: float) -> int:
    """按持续时间把 0–1 进度映射到帧号。"""
    spec = hero_frame_spec(hero, state)
    durs = spec["durations_ms"]
    total = float(sum(durs)) or 1.0
    t = max(0.0, min(1.0, float(progress))) * total
    acc = 0.0
    for i, d in enumerate(durs):
        if t <= acc + float(d):
            return i
        acc += float(d)
    return len(durs) - 1


def hero_attack_frame(hero: str, progress: float) -> tuple[str, int]:
    """攻击收放映射：峰值帧换成该英雄的独有技能帧。"""
    idx = hero_state_frame(hero, "attack", progress)
    if idx == hero_peak_index(hero, "attack"):
        return "skill", max(0, hero_peak_index(hero, "skill"))
    return "attack", idx


def judge_press(dt_ms: float, scale: float = 1.0,
                bonus: dict | None = None) -> str | None:
    """单拍判定；scale>1 放宽（操练档）；bonus 给 Fever 期额外毫秒。"""
    a = abs(float(dt_ms))
    bp = (bonus or {}).get("perfect", 0.0)
    bg = (bonus or {}).get("good", 0.0)
    if a <= (PERFECT_MS + bp) * scale:
        return "perfect"
    if a <= (GOOD_MS + bg) * scale:
        return "good"
    if a <= MISS_MS * scale:
        return "miss"
    return None


@dataclass
class BossPick:
    """一次公示：招式、阶段、可读性变体与公示拍数。"""
    beat: int
    intent: str
    phase: int
    phase_name: str
    variant: str = "normal"       # normal / long / phase_open
    windup: float = 0.0           # 额外前摇（仅表现层，不改变 4 拍输入窗口）
    reveal_beats: int = 4


class BossScore:
    """可复现的三阶段加权意图谱。

    规则：
    - 开战前 grace_beats 拍不出招；
    - 同一招式不得连续出现 max_repeat+1 次（默认 3 连禁）；
    - AOE 同阶段两次公示至少间隔 aoe_gap_beats 拍；
    - 进入新阶段的首招从 open_pool 抽（必须是可 4 拍化解的公示招）；
    - 连续两招同类型时第二招标 long（更长前摇/不同音色），避免同型连打变盲猜。
    """

    RNG_SALT = 0x5EEDB055

    def __init__(self, seed: int = 20261104, config: dict | None = None):
        self.config = config or BOSS_SCORE
        self.phases = sorted(self.config["phases"],
                             key=lambda p: float(p["hp_min"]), reverse=True)
        self.grace = int(self.config.get("grace_beats", 2))
        self.aoe_gap = int(self.config.get("aoe_gap_beats", 6))
        self.max_repeat = int(self.config.get("max_repeat", 2))
        self.reveal_beats = int(self.config.get("reveal_beats", 4))
        self.reset(seed)

    def reset(self, seed: int) -> None:
        self.rng = random.Random(int(seed) ^ self.RNG_SALT)
        self.history: list[str] = []
        self.last_aoe_beat = -999
        self.phase_id = self.phases[-1]["id"]  # 最低阶段，首次 pick 视为切阶段

    def phase_for_hp(self, hp_ratio: float) -> dict:
        ratio = max(0.0, min(1.0, float(hp_ratio)))
        for p in self.phases:
            if ratio >= float(p["hp_min"]):
                return p
        return self.phases[-1]

    def _weighted(self, pool: dict) -> str:
        items = [(k, float(w)) for k, w in pool.items()
                 if k in INTENTS and float(w) > 0]
        total = sum(w for _, w in items)
        r = self.rng.random() * total
        acc = 0.0
        for key, w in items:
            acc += w
            if r <= acc:
                return key
        return items[-1][0]

    def _violates(self, key: str, beat: int) -> bool:
        if len(self.history) >= 2 and self.history[-1] == key \
                and self.history[-2] == key:
            return True
        if key in AOE_INTENTS and (beat - self.last_aoe_beat) < self.aoe_gap:
            return True
        return False

    def pick(self, beat: int, hp_ratio: float) -> BossPick | None:
        beat = int(beat)
        if beat < self.grace:
            return None
        phase = self.phase_for_hp(hp_ratio)
        changed = phase["id"] != self.phase_id
        pool = {k: float(w) for k, w in phase["pool"].items() if k in INTENTS}
        if changed:
            open_pool = [k for k in phase.get("open_pool", []) if k in pool]
            pool = {k: pool[k] for k in open_pool} or pool

        chosen = None
        for _ in range(48):
            cand = self._weighted(pool)
            if not self._violates(cand, beat):
                chosen = cand
                break
        if chosen is None:
            for cand in INTENT_ORDER:
                if not self._violates(cand, beat):
                    chosen = cand
                    break
        if chosen is None:
            chosen = INTENT_ORDER[0]

        prev_kind = INTENTS[self.history[-1]]["kind"] if self.history else ""
        kind = INTENTS[chosen]["kind"]
        if changed:
            variant = "phase_open"
        elif prev_kind and kind == prev_kind:
            variant = "long"
        else:
            variant = "normal"
        windup = 0.5 if variant == "long" else 0.0

        self.history.append(chosen)
        self.history = self.history[-4:]
        if chosen in AOE_INTENTS:
            self.last_aoe_beat = beat
        self.phase_id = phase["id"]
        reveal = int(phase.get("reveal_beats", self.reveal_beats))
        if changed:
            reveal = max(reveal, int(self.config.get("phase_open_min_reveal_beats",
                                                       self.reveal_beats)))
        return BossPick(beat=beat, intent=chosen, phase=phase["id"],
                        phase_name=phase["name"], variant=variant,
                        windup=windup, reveal_beats=reveal)

    def reveal_for_hp(self, hp_ratio: float) -> int:
        """当前阶段公示拍数：第一阶段 6 拍，二/三阶段回落 4 拍。"""
        phase = self.phase_for_hp(hp_ratio)
        return int(phase.get("reveal_beats", self.reveal_beats))

    def preview(self, beat: int, hp_ratio: float, n: int = 4,
                cycle_beats: int = 8) -> list[str]:
        """不改状态地预演后续 n 个公示（UI 用）。"""
        state = self.rng.getstate()
        history = list(self.history)
        phase_id = self.phase_id
        last_aoe = self.last_aoe_beat
        out: list[str] = []
        for i in range(n):
            p = self.pick(beat + i * cycle_beats, hp_ratio)
            out.append(p.intent if p else INTENT_ORDER[0])
        self.rng.setstate(state)
        self.history = history
        self.phase_id = phase_id
        self.last_aoe_beat = last_aoe
        return out


def face_tier(combo: int) -> int:
    """连击 → 脸谱染色梯度（0 原色 … 5 紫红）。"""
    if combo <= 0:
        return 0
    if combo <= 1:
        return 1
    if combo <= 2:
        return 2
    if combo <= 4:
        return 3
    if combo <= 7:
        return 4
    return 5


def tint_color(tier: int) -> tuple[int, int, int]:
    return [
        (255, 255, 255),
        (255, 234, 178),
        (255, 188, 112),
        (255, 118, 86),
        (255, 82, 168),
        (224, 116, 255),
    ][max(0, min(5, tier))]


def fever_tint() -> tuple[int, int, int]:
    """Fever 期脸谱转红。"""
    return (255, 96, 96)


# ------------------------------------------------------------------ 时钟
class BeatClock:
    """鼓点时钟；Fever 时目标 BPM 升高，按连续相位积分，避免跳拍。"""

    def __init__(self, bpm: float = BPM, start_time: float = 0.0) -> None:
        self.base_bpm = float(bpm)
        self.bpm = float(bpm)
        self.start_time = float(start_time)
        # 起手前为负数，start_time 时正好到第 0 拍
        self.beat_pos = -float(start_time) * float(bpm) / 60.0
        self._now = 0.0

    @property
    def beat_sec(self) -> float:
        return 60.0 / self.bpm

    def target_bpm(self, fever: bool) -> float:
        if not fever:
            return self.base_bpm
        return min(FEVER_BPM_CEIL, FEVER_BPM,
                   max(self.base_bpm, self.base_bpm * 1.12))

    def update(self, now: float, fever: bool = False, dt: float | None = None) -> float:
        now = float(now)
        target = self.target_bpm(fever)
        if dt is None:
            dt = max(0.0, now - self._now)
        self._now = now
        # 平滑追速（0.25s 时间常数），Fever 进/出都不跳拍
        k = 0.0 if dt <= 0 else (1.0 - math.exp(-dt / 0.25))
        self.bpm += (target - self.bpm) * k
        self.beat_pos += dt * self.bpm / 60.0
        return self.beat_pos

    def beat_at(self, now: float, fever: bool = False) -> float:
        """仅用于按键吸附：按当前速度外推，不修改相位。"""
        return self.beat_pos + max(0.0, float(now) - self._now) * self.bpm / 60.0

    def beat_time(self, beat: float) -> float:
        """近似反解（等速）；判定用 beat_at 的实时相位。"""
        return self.start_time + float(beat) * (60.0 / self.bpm)

    @property
    def started(self) -> bool:
        return self.beat_pos >= 0.0


# ------------------------------------------------------------------ 四拍数据
@dataclass
class Slot:
    key: str | None = None
    grade: str | None = None
    dt_ms: float = 0.0
    beat: int = 0


@dataclass
class GroupResult:
    group: int
    keys: str
    command: str | None
    grade: str | None
    success: bool
    reason: str


@dataclass
class Group:
    index: int
    start_beat: int
    slots: list[Slot] = field(default_factory=lambda: [
        Slot() for _ in range(INPUT_BEATS)])
    settled: bool = False
    result: GroupResult | None = None


@dataclass
class BossAttempt:
    """一次破阵尝试：第 5 拍公示，第 6~9 拍（4 个拍位）收令。"""
    cycle: int
    intent_key: str
    slots: list[Slot] = field(default_factory=list)
    resolved: bool = False
    perfect: bool = False
    avoided: bool = False
    variant: str = "normal"     # normal / long / phase_open
    phase: int = 1
    windup: float = 0.0
    # 补打：none / pending / ok / failed；每招只开一次
    makeup_state: str = "none"
    makeup_deadline: float = -1.0
    makeup_keys: list[str] = field(default_factory=list)
    makeup_used: bool = False

    @property
    def keys(self) -> str:
        return "".join(s.key or "·" for s in self.slots)

    @property
    def complete(self) -> bool:
        return len(self.slots) >= INPUT_BEATS

    @property
    def all_perfect(self) -> bool:
        return self.complete and all(s.grade == "perfect" for s in self.slots)


@dataclass
class PressView:
    key: str
    grade: str
    dt_ms: float
    slot: int
    beat: int


# ------------------------------------------------------------------ 实体
class Unit:
    def __init__(self, kind: str) -> None:
        spec = UNIT_TYPES[kind]
        self.kind = kind
        self.name = spec["name"]
        self.max_hp = spec["max_hp"]
        self.hp = spec["max_hp"]
        self.atk = spec["atk"]
        self.armor = spec["armor"]
        self.range = spec["range"]
        self.hurt_flash = 0.0
        self.attack_anim = 0.0
        self.down = False
        self.down_t = 0.0        # 倒地后计时：顺坡滚一小段再停

    @property
    def alive(self) -> bool:
        return not self.down and self.hp > 0.0


class Squad:
    def __init__(self) -> None:
        self.x = 0.0
        self.units = [Unit(k) for k in FRONT_ORDER]
        self.hurt_flash = 0.0
        self.attack_anim = 0.0
        self.march_anim = 0.0
        # 姿态：march / halt / defend / attack / idle
        self.stance = "march"
        self.walking = True
        self.march_streak = 0
        self.march_pulse = 0.0
        self.march_step = 0
        self.brake_t = 0.0          # 急停刹车痕计时

    @property
    def alive_units(self) -> list[Unit]:
        return [u for u in self.units if u.alive]

    @property
    def front(self) -> Unit | None:
        for u in self.units:
            if u.alive:
                return u
        return None

    @property
    def hp(self) -> float:
        return sum(u.hp for u in self.units)

    @property
    def max_hp(self) -> float:
        return sum(u.max_hp for u in self.units)

    @property
    def wiped(self) -> bool:
        return not self.alive_units


class Enemy:
    def __init__(self, kind: str, x: float, index: int,
                 v: float = 0.0, wave: int = 0,
                 dormant: bool = False) -> None:
        self.kind = kind
        self.index = index
        self.is_boss = kind == "boss"
        self.wave = int(wave)
        self.dormant = bool(dormant)
        self.v = float(v)          # 横跨坡宽的世界坐标（深度排序用）
        if kind == "boss":
            self.max_hp = 600.0
            self.hp = self.max_hp
            self.atk = 0.0
            self.armor = 0.15
            self.standoff = 7.2
            self.atk_every = 4
            self.speed = 0.1
        elif kind == "brute":
            self.max_hp = 96.0
            self.hp = self.max_hp
            self.atk = 6.5
            self.armor = 0.25
            self.standoff = 2.45 + 0.2 * index
            self.atk_every = 11
            self.speed = 0.55
        else:
            self.max_hp = 56.0
            self.hp = self.max_hp
            self.atk = 3.5
            self.armor = 0.0
            self.standoff = 1.55 + 0.35 * index
            self.atk_every = 8
            self.speed = 0.9
        self.x = float(x)
        self.flash = 0.0
        self.attack_anim = 0.0
        self.timer = 0.0
        self.active = not self.is_boss
        self.dead = False
        self.next_attack_beat = 4
        self.lunge = 0.0
        self.down_t = 0.0                    # 倒地顺坡滚动计时
        self.on_platform = self.is_boss       # Boss 初始站在石台上
        self.platform_x = float(x)            # 石台锚点（击落后台子不跟着走）
        # 石台几何（普通敌人也带默认值，渲染层统一 getattr 读取）
        self.platform_h = int(BOSS_PLATFORM["wall_h"])
        self.platform_u0 = float(x) - 1.55
        self.platform_u1 = float(x) + 1.55
        self.platform_v_half = 1.75
        self.platform_steps = 3


# ------------------------------------------------------------------ VFX（纯数据）
class Shake:
    """trauma² 驱动震屏。"""

    def __init__(self) -> None:
        self.trauma = 0.0

    def add(self, amount: float) -> None:
        self.trauma = min(1.0, self.trauma + float(amount))

    def update(self, dt: float) -> None:
        self.trauma = max(0.0, self.trauma - dt * 4.6)

    def offset(self, max_px: int = 18) -> tuple[int, int]:
        m = max_px * self.trauma * self.trauma
        if m < 0.6:
            return (0, 0)
        return (random.randint(-int(m), int(m)),
                random.randint(-int(m), int(m)))


class SparkPool:
    """火花粒子池：1280×720 参考画布坐标。"""

    MAX = 240

    def __init__(self, rng: random.Random | None = None) -> None:
        self.parts: list[list] = []
        self.rng = rng or random.Random(2026)

    def burst(self, x: float, y: float, n: int = 12,
              color: tuple[int, int, int] = (255, 210, 90)) -> None:
        for _ in range(n):
            a = self.rng.uniform(0, math.tau)
            v = self.rng.uniform(60, 260)
            life = self.rng.uniform(0.22, 0.5)
            self.parts.append([float(x), float(y), math.cos(a) * v,
                               math.sin(a) * v - 80, life, life, color])
        del self.parts[:-self.MAX]

    def update(self, dt: float) -> None:
        alive = []
        for p in self.parts:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= 0.90
            p[3] = p[3] * 0.90 + 340 * dt
            p[4] -= dt
            if p[4] > 0:
                alive.append(p)
        self.parts = alive

    def count(self) -> int:
        return len(self.parts)


# ------------------------------------------------------------------ 主逻辑
class Game:
    def __init__(self, bpm: float = BPM, start_time: float = 0.0,
                 seed: int = 20261104, difficulty: str = "standard",
                 spawn_boss: bool = True) -> None:
        self.seed = int(seed)
        self.rng = random.Random(seed)
        self.clock = BeatClock(bpm, start_time)
        self.now = 0.0
        self.difficulty = difficulty if difficulty in DIFFICULTIES else "standard"
        self.diff = DIFFICULTIES[self.difficulty]

        self.groups: dict[int, Group] = {}
        self.active_cycle = 0

        # 长关卡表：全部波次一次性生成，远波 dormant，推进到 wake_units 内唤醒。
        self.cam_x = 0.0
        self.level = LEVEL
        self.map_len = float(LEVEL.get("length_units", 148.0))
        self.map_u0 = float(LEVEL.get("u_min", -12.0))
        self.segments = LEVEL["segments"]
        self.mile_every = float(LEVEL.get("props", {}).get("mile_every", 10.0))
        self.wake_units = float(LEVEL.get("wake_units", 12.0))
        self.segment_index = 0
        self.segment_entry = (0, 2.2)
        self.wave_cursor = 0
        if self.segments:
            first = self.segments[0]
            p3d.set_slope_deg(float(first.get("slope_deg",
                                             TERRAIN["slope_deg"])))
            # 时钟仍按 BeatClock(bpm) 构造；目标 BPM 以第一段配置为准
            self.clock.base_bpm = float(first.get("bpm", self.clock.base_bpm))
        else:
            p3d.set_slope_deg(float(TERRAIN["slope_deg"]))

        self.squad = Squad()
        self.formation = "changshe"
        self.enemies: list[Enemy] = []
        for wi, wave in enumerate(
                [w for seg in self.segments for w in seg.get("waves", [])]):
            self._spawn_wave(wave, wi)
        self.boss = Enemy("boss", float(LEVEL["boss"]["u"]), 0, v=0.0) \
            if spawn_boss else None
        if self.boss is not None:
            self.boss.hp = self.boss.max_hp = self.diff["boss_hp"]
            self.boss.active = False
            self._configure_boss_platform(self.boss)
        self.phase = "trash"

        self.combo = 0
        self.best_combo = 0
        self.combo_breaks = 0
        self.defend_until = -1.0
        self.penalty_until = -1.0
        self.stun_until = -1.0
        self.status = "playing"

        # 鼓劲槽 / Fever
        self.fever_gauge = 0
        self.fever_active = False
        self.fever_until = -1.0
        self.fever_cd_until = -1.0
        self.fever_count = 0
        self.fever_peak = False

        # Boss 破阵 / 意图谱
        self.score = BossScore(seed)
        self.boss_phase = 1
        self.boss_phase_reached = 1
        self.intent_key: str | None = None
        self.intent_cycle = -1
        self.intent_index = 0
        self.intent_variant = "normal"
        self.intent_windup = 0.0
        self.intent_reveal_beats = 4
        self.attempt: BossAttempt | None = None
        self._boss_resolved_cycle = -1
        self.stagger_until = -1.0
        self.cycle_command: tuple[int, str | None] = (-1, None)
        self.last_stagger_cycle = -1

        # 克制反馈 / 矩阵速查
        self.counter_pop = ("", 0.0)
        self.counter_hits = 0
        self.countered_hits = 0
        self.show_matrix = False

        # 自动行军
        self.auto_march_events = 0
        self._auto_checked_beat = None
        self.march_direction = 1.0       # +1 下坡（向敌），-1 上坡（回撤）
        self.hero_peak = ("", 0.0)       # (英雄, 剩余时间)：命中峰值放大特效
        self.hero_peak_events = 0
        self.peak_focus = (0.0, 0.0)     # 峰值特写裁切中心（渲染层写入）
        self._peak_pending = ""
        self._peak_target: Enemy | None = None
        self.show_lineup = False

        # 视觉倾斜 / 新手引导 / 石台高度
        self.visual_tilt = bool(TERRAIN["visual_tilt"])
        self.guidance = True             # 新手渐进引导（前 3 招免罚 + 一次性提示）
        self.makeup_enabled = True       # 二/三阶段补打（模拟手可关掉做改前对照）
        self.platform_enabled = True     # Boss 石台高度优势
        self.boss_attacks = 0            # 已结算的 Boss 出招数（含教学招）
        self.tutorial_seen: set[str] = set()
        self.tutorial_hint = ("", 0.0)   # (提示文本, 剩余秒)
        self.tutorial_shown = 0

        self.shake = Shake()
        self.sparks = SparkPool(self.rng)
        self.hitstop = 0.0
        self.shout_t = 0.0
        self.trail_t = 0.0
        self.banner = ("", 0.0)
        self.grade_pop = ("", 0.0, -1)
        self.result_pop = ("", 0.0)
        self.last_press: PressView | None = None
        self.last_tap: PressView | None = None
        # 事件驱动输入队列：(键, 事件时间戳)。同一帧多次按键按时间顺序消费。
        self.input_queue: list[tuple[str, float]] = []
        # 乐器按压反馈（渲染层读）：每键最近一次被接受的按键时间与判定
        self.press_times = {"J": -99.0, "K": -99.0, "L": -99.0}
        self.press_grades = {"J": "", "K": "", "L": ""}
        self.last_result: GroupResult | None = None
        self.results: list[GroupResult] = []
        self.events: list[tuple] = []
        # 判定偏移（遥测用）：[累计毫秒, 次数]
        self.judge_offsets = {g: [0.0, 0] for g in GRADES}
        self.stats = {"perfect": 0, "good": 0, "miss": 0,
                      "commands_ok": 0, "commands_fail": 0,
                      "attacks": 0, "marches": 0, "defends": 0,
                      "formations": 0, "damage_dealt": 0.0,
                      "intents_read": 0, "intents_hit": 0,
                      "intents_fail": 0, "boss_perfect_breaks": 0,
                      "missed_commands": 0, "fever_count": 0,
                      "auto_march": 0, "counter_hits": 0,
                      "countered_hits": 0, "hero_peaks": 0}

    # -------------------------------------------------------------- 便捷属性
    @property
    def beat_pos(self) -> float:
        return self.clock.beat_pos

    @property
    def beat_in_cycle(self) -> float:
        if self.beat_pos < 0:
            return -1.0
        return self.beat_pos % CYCLE_BEATS

    @property
    def beat_index(self) -> int:
        return int(math.floor(self.beat_pos))

    @property
    def cycle_index(self) -> int:
        return int(math.floor(self.beat_pos)) // CYCLE_BEATS

    @property
    def cycle_slot(self) -> int:
        return int(math.floor(self.beat_pos)) % CYCLE_BEATS

    @property
    def input_phase(self) -> bool:
        return 0 <= self.beat_in_cycle < INPUT_BEATS

    @property
    def action_phase(self) -> bool:
        return INPUT_BEATS <= self.beat_in_cycle < CYCLE_BEATS

    @property
    def strong_beat(self) -> bool:
        return self.beat_index % 2 == 0

    @property
    def face_tier(self) -> int:
        return face_tier(self.combo)

    @property
    def defending(self) -> bool:
        return self.now < self.defend_until

    @property
    def penalized(self) -> bool:
        return self.now < self.penalty_until

    @property
    def stunned(self) -> bool:
        return self.now < self.stun_until

    @property
    def boss_on_platform(self) -> bool:
        """Boss 是否仍站在石台上（破阵击落后为 False，高度加成消失）。"""
        return bool(self.platform_enabled and self.boss is not None
                    and self.boss.active and not self.boss.dead
                    and getattr(self.boss, "on_platform", False))

    @property
    def boss_telegraph_active(self) -> bool:
        """公示是否可见（含延长后的前哨拍），AOE 落点高亮跟随公示时长。"""
        return self.attempt is not None and not self.attempt.resolved

    @property
    def active_slots(self) -> list[Slot]:
        return self._group(self.active_cycle).slots

    @property
    def cycle_slots(self) -> list[Slot]:
        """当前循环的收令槽（行动拍仍显示刚打出的指令）。"""
        return self._group(self.cycle_index).slots

    @property
    def count_in(self) -> float:
        return max(0.0, self.clock.start_time - self.now)

    @property
    def window_scale(self) -> float:
        return float(self.diff["window_scale"])

    @property
    def fever_window_bonus(self) -> dict:
        return FEVER_WINDOW_ADD if self.fever_active else {}

    @property
    def perfect_ms(self) -> float:
        return (PERFECT_MS + self.fever_window_bonus.get("perfect", 0.0)) \
            * self.window_scale

    @property
    def good_ms(self) -> float:
        return (GOOD_MS + self.fever_window_bonus.get("good", 0.0)) \
            * self.window_scale

    @property
    def miss_ms(self) -> float:
        return MISS_MS * self.window_scale

    @property
    def formation_spec(self) -> dict:
        return FORMATIONS[self.formation]

    @property
    def formation_lag(self) -> int:
        return int(self.formation_spec.get("lag", 0))

    @property
    def fever_ratio(self) -> float:
        return min(1.0, self.fever_gauge / float(self.diff["fever_gauge"]))

    @property
    def fever_remain(self) -> float:
        return max(0.0, self.fever_until - self.now)

    @property
    def boss_active(self) -> bool:
        return self.boss is not None and self.boss.active and not self.boss.dead

    @property
    def boss_staggered(self) -> bool:
        return self.boss_active and self.now < self.stagger_until

    @property
    def intent(self) -> dict | None:
        return INTENTS.get(self.intent_key or "")

    @property
    def makeup_pending(self) -> bool:
        att = self.attempt
        return bool(att is not None and att.makeup_state == "pending"
                    and self.status == "playing")

    @property
    def makeup_pattern(self) -> str:
        """补打需要重新按下的正确四拍键位。"""
        att = self.attempt
        if att is None:
            return ""
        return COMMAND_KEYS.get(INTENTS[att.intent_key]["counter"], "")

    @property
    def makeup_remain(self) -> float:
        att = self.attempt
        if att is None or att.makeup_state != "pending":
            return 0.0
        return max(0.0, att.makeup_deadline - self.now)

    @property
    def boss_input_window(self) -> bool:
        """公示后 4 个拍位（循环第 5~8 拍）内可输入化解令。"""
        return (self.boss_active and self.attempt is not None
                and not self.attempt.resolved and 4 <= self.cycle_slot < 8)

    def intent_preview(self, count: int = 4) -> list[str]:
        if not self.boss_active or self.boss is None:
            return []
        hp_ratio = max(0.0, min(1.0, self.boss.hp / self.boss.max_hp))
        next_reveal = ((self.beat_index // CYCLE_BEATS) + 1) * CYCLE_BEATS + 4
        return self.score.preview(next_reveal, hp_ratio, count, CYCLE_BEATS)

    # -------------------------------------------------------------- 克制矩阵
    def counter_mult(self, formation: str | None = None,
                     intent_key: str | None = None) -> float:
        """阵法对当前 Boss 招式的伤害倍率；>1 克制，<1 被克。"""
        form = formation or self.formation
        key = intent_key if intent_key is not None else (self.intent_key or "")
        row = COUNTER_MATRIX.get(form) or {}
        try:
            return float(row.get(key, 1.0))
        except (TypeError, ValueError):
            return 1.0

    def counter_state(self, formation: str | None = None,
                      intent_key: str | None = None) -> str:
        m = self.counter_mult(formation, intent_key)
        if m > 1.0 + 1e-6:
            return "counter"
        if m < 1.0 - 1e-6:
            return "countered"
        return "neutral"

    @property
    def living_enemies(self) -> list[Enemy]:
        out = [e for e in self.enemies if not e.dead]
        if self.boss_active:
            out.append(self.boss)  # type: ignore[arg-type]
        return out

    # -------------------------------------------------------------- 组
    def _group(self, index: int) -> Group:
        g = self.groups.get(index)
        if g is None:
            g = Group(index=index, start_beat=index * CYCLE_BEATS)
            g.slots = [Slot(beat=g.start_beat + i) for i in range(INPUT_BEATS)]
            self.groups[index] = g
        return g

    def _advance_active(self) -> None:
        guard = 0
        while self._group(self.active_cycle).settled and guard < 64:
            self.active_cycle += 1
            guard += 1

    def _record_judgement(self, grade: str, dt_ms: float) -> None:
        rec = self.judge_offsets.get(grade)
        if rec is not None:
            rec[0] += float(dt_ms)
            rec[1] += 1

    # -------------------------------------------------------------- 拍位吸附
    def _mark_press(self, key: str, grade: str, now: float) -> None:
        """记录一次被接受的按键，供 HUD 乐器按压/火星动效使用。"""
        if key in self.press_times:
            self.press_times[key] = float(now)
            self.press_grades[key] = grade

    def beat_press(self, key: str, now: float, dt_ms: float):
        """按键 → 吸附最近整拍（输入缓冲）；动作拍拒收，超窗返回 None。

        返回 (view, beat, grade, will_settle, instant)。
        will_settle=True 表示第 4 个拍位落下后会在同一个 update 结算；
        instant 表示收令同时立刻结算（Boss 破阵用）。
        """
        if key not in ("J", "K", "L") or self.status != "playing":
            return None
        # 任何一次有效按键都让对应乐器下沉（判 OFF 也有反馈）；判定后覆盖 grade
        self._mark_press(key, "", now)
        b = self.clock.beat_at(now, self.fever_active)
        n = int(math.floor(b + 0.5))
        dt_ms = float(dt_ms)
        grade = judge_press(dt_ms, self.window_scale, self.fever_window_bonus)
        if grade is None:
            self.grade_pop = ("OFF", 0.35, -1)
            return None

        # 补打窗口优先：1 拍内重新收齐正确四拍（不占下一组的指令槽）
        if self.makeup_pending:
            att = self.attempt
            if now >= att.makeup_deadline:
                self._finish_makeup(False)
                return None
            if len(att.makeup_keys) < INPUT_BEATS:
                att.makeup_keys.append(key)
            view = PressView(key=key, grade="good", dt_ms=dt_ms,
                             slot=-2, beat=n)
            self.last_press = view
            self._mark_press(key, "good", now)
            self.grade_pop = ("补", 0.35, -1)
            if len(att.makeup_keys) >= INPUT_BEATS:
                self._finish_makeup()
            return view, n, "good", False, False

        slot_index = n % CYCLE_BEATS
        cycle = n // CYCLE_BEATS

        # Boss 破阵窗口优先：循环第 5~8 拍
        if (self.boss_active and 4 <= slot_index < 8
                and self.attempt is not None
                and self.attempt.cycle == cycle
                and not self.attempt.resolved):
            att = self.attempt
            pos = n - (cycle * CYCLE_BEATS + 4)
            if pos >= INPUT_BEATS or len(att.slots) != pos:
                return None
            slot = Slot(key=key, grade=grade, dt_ms=dt_ms, beat=n)
            att.slots.append(slot)
            self.stats[grade] += 1
            self._record_judgement(grade, dt_ms)
            view = PressView(key=key, grade=grade, dt_ms=dt_ms,
                             slot=pos, beat=n)
            self.last_press = view
            self._mark_press(key, grade, now)
            self.grade_pop = (grade.upper(), 0.45, pos)
            instant = pos == INPUT_BEATS - 1
            if instant:
                self._resolve_attempt(att, early=True)
            return view, n, grade, False, instant

        if slot_index >= INPUT_BEATS:
            # 动作拍的踏点：不组成指令，但可以驱动自动行军（行进鼓点）
            self.last_tap = PressView(key=key, grade=grade, dt_ms=dt_ms,
                                      slot=-1, beat=n)
            self._mark_press(key, grade, now)
            self._record_judgement(grade, dt_ms)
            if self.boss_active and self.boss_staggered:
                self._stagger_tap()
                self.grade_pop = ("击", 0.32, -1)
            else:
                self.grade_pop = ("踏", 0.32, -1)
            return self.last_tap, n, grade, False, False
        if cycle < self.active_cycle:
            return None
        g = self._group(cycle)
        if g.settled:
            return None
        slot = g.slots[slot_index]
        if slot.key is not None:
            return None
        slot.key = key
        slot.grade = grade
        slot.dt_ms = dt_ms
        self.stats[grade] += 1
        self._record_judgement(grade, dt_ms)
        view = PressView(key=key, grade=grade, dt_ms=dt_ms,
                         slot=slot_index, beat=n)
        self.last_press = view
        self._mark_press(key, grade, now)
        self.grade_pop = (grade.upper(), 0.45, slot_index)
        will_settle = (slot_index == INPUT_BEATS - 1)
        return view, n, grade, will_settle, False

    def push_input(self, key: str, t_event: float) -> None:
        """事件驱动入口：按键带事件时间戳入队，由 update() 按序判定。"""
        if key in ("J", "K", "L") and self.status == "playing":
            self.input_queue.append((key, float(t_event)))

    def _drain_input(self) -> None:
        """同一帧内多次按键按时间戳顺序入队判定，不丢拍、不并拍。"""
        if not self.input_queue:
            return
        queue = sorted(self.input_queue, key=lambda kv: kv[1])
        self.input_queue = []
        for key, t in queue:
            self.press(key, min(float(t), self.now))

    def press(self, key: str, now: float) -> PressView | None:
        """收令入口：只记录拍位，第 5 拍（行动重拍）统一起手结算。"""
        got = self.beat_press(key, now, 0.0)
        if got is None:
            return None
        return got[0]

    # -------------------------------------------------------------- 推进
    def update(self, now: float, dt: float) -> None:
        self.now = float(now)
        self._drain_input()
        # 段落切换：BPM 缓追（BeatClock 0.25s 平滑）、入场计时、坡度同步。
        # Boss 阶段不再按 squad.x 切段：直接进 Boss 的模拟手/自测不改变节奏。
        idx = segment_index_at(self.squad.x)
        seg = self.segments[idx] if self.segments else {}
        if self.phase == "trash" and idx != self.segment_index:
            self.segment_index = idx
            self.clock.base_bpm = float(seg.get("bpm", self.clock.base_bpm))
            self.segment_entry = (idx, 2.2)
            p3d.set_slope_deg(float(seg.get("slope_deg",
                                            TERRAIN["slope_deg"])))
        self.segment_entry = (self.segment_index,
                              max(0.0, self.segment_entry[1] - dt))
        # 唤醒波次：未醒波进入 wake_units 范围即转醒，并推进 wave_cursor
        for e in self.enemies:
            if e.dormant and e.x - self.squad.x <= self.wake_units:
                e.dormant = False
                self.wave_cursor = max(self.wave_cursor, e.wave)
        new_beats = self.clock.update(now, self.fever_active, dt)
        self._auto_march(new_beats, dt)
        self._update_fever(dt)
        self._settle_due(now)
        self._update_boss_window()
        self._update_makeup()

        self.shake.update(dt)
        self.sparks.update(dt)
        self.shout_t = max(0.0, self.shout_t - dt)
        self.trail_t = max(0.0, self.trail_t - dt)
        self.squad.attack_anim = max(0.0, self.squad.attack_anim - dt)
        self.squad.march_anim = max(0.0, self.squad.march_anim - dt)
        self.squad.march_pulse = max(0.0, self.squad.march_pulse - dt)
        self.squad.hurt_flash = max(0.0, self.squad.hurt_flash - dt)
        self.squad.brake_t = max(0.0, self.squad.brake_t - dt)
        self.hero_peak = (self.hero_peak[0], max(0.0, self.hero_peak[1] - dt))
        if self._peak_pending and self.squad.attack_anim <= \
                (1.0 - HERO_PEAK_PROGRESS) * 0.45:
            hero = self._peak_pending
            self._peak_pending = ""
            self.hero_peak = (hero, 0.55)
            self.hero_peak_events += 1
            self.stats["hero_peaks"] += 1
            self.events.append(("hero_peak", hero, self._peak_target))
        for u in self.squad.units:
            u.attack_anim = max(0.0, u.attack_anim - dt)
            u.hurt_flash = max(0.0, u.hurt_flash - dt)
            if u.down:
                u.down_t += dt
        self.tutorial_hint = (self.tutorial_hint[0],
                              max(0.0, self.tutorial_hint[1] - dt))
        self.banner = (self.banner[0], max(0.0, self.banner[1] - dt))
        self.grade_pop = (self.grade_pop[0], max(0.0, self.grade_pop[1] - dt),
                          self.grade_pop[2])
        self.counter_pop = (self.counter_pop[0],
                            max(0.0, self.counter_pop[1] - dt))
        self.result_pop = (self.result_pop[0], max(0.0, self.result_pop[1] - dt))
        for e in self.enemies + ([self.boss] if self.boss else []):
            e.flash = max(0.0, e.flash - dt * 6.0)
            e.attack_anim = max(0.0, e.attack_anim - dt)
            e.lunge = max(0.0, e.lunge - dt)
            if e.dead:
                e.down_t += dt

        if self.hitstop > 0.0:
            self.hitstop = max(0.0, self.hitstop - dt)
            return
        if self.clock.started and self.status == "playing":
            self._update_enemies(dt)

        if self.squad.wiped and self.status == "playing":
            self.status = "defeated"
            self.banner = ("全 军 覆 灭", 3.0)
            self.events.append(("defeated", None))

    def _settle_due(self, now: float) -> None:
        if self.status != "playing":
            return
        guard = 0
        while guard < 8:
            guard += 1
            g = self._group(self.active_cycle)
            if g.settled:
                self.active_cycle += 1
                continue
            complete = all(s.key is not None for s in g.slots)
            if complete:
                # 4 拍收满 → 卡在行动重拍（第 5 拍）起手，动作与鼓点同拍
                if self.beat_pos >= g.start_beat + INPUT_BEATS:
                    self._settle(g)
                    self.active_cycle += 1
                    continue
            elif self.beat_pos >= (g.start_beat + INPUT_BEATS - 1
                                   + self.miss_ms / BEAT_MS):
                self._settle(g)
                self.active_cycle += 1
                continue
            break

    def _settle(self, g: Group) -> None:
        if g.settled:
            return
        g.settled = True
        keys = "".join(s.key or "·" for s in g.slots)
        command = None
        grade = None
        success = False
        reason = ""
        if any(s.key is None for s in g.slots):
            reason = "漏拍"
        elif any(s.grade == "miss" for s in g.slots):
            reason = "脱拍"
        elif keys in COMMANDS:
            success = True
            command, _ = COMMANDS[keys]
            grade = "perfect" if all(s.grade == "perfect" for s in g.slots) \
                else "good"
        else:
            reason = "错令"
        result = GroupResult(group=g.index, keys=keys, command=command,
                             grade=grade, success=success, reason=reason)
        g.result = result
        self.last_result = result
        self.results.append(result)
        self.cycle_command = (g.index, command if success else None)
        self.events.append(("group", result))
        if success:
            self._on_success(result)
        else:
            self._on_fail(result)

    # -------------------------------------------------------------- 结算效果
    def _on_success(self, r: GroupResult) -> None:
        self.penalty_until = -1.0
        self.stats["commands_ok"] += 1
        gain = 2 if r.grade == "perfect" else 1
        self.combo += gain
        self.best_combo = max(self.best_combo, self.combo)
        self._add_gauge(gain)
        name = COMMAND_NAMES.get(r.command or "", r.command or "")
        self.banner = (f"{name} · {FORMATIONS[self.formation]['name']}", 1.25)
        self.result_pop = ("PERFECT!" if r.grade == "perfect" else "GOOD!", 0.75)
        self.events.append(("success", r))
        if r.command == "attack":
            self._do_attack(r)
        elif r.command == "march":
            self._do_march(r)
        elif r.command == "defend":
            self._do_defend(r)
        elif r.command in COMMAND_FORMATION:
            self._do_formation(r)

    def _on_fail(self, r: GroupResult) -> None:
        self.stats["commands_fail"] += 1
        if r.reason == "漏拍":
            self.stats["missed_commands"] += 1
        if self.combo > 0:
            self.combo_breaks += 1
        self.combo = 0
        if self.fever_active:
            self._end_fever("断档")
        else:
            self.fever_gauge = 0
            self.squad.walking = False
            self.squad.stance = "halt"
            self.squad.march_streak = 0
            self.squad.brake_t = 0.70
        self.penalty_until = self.now + 4.0 * self.clock.beat_sec
        self.hitstop = 0.0
        self.shout_t = 0.0
        self.trail_t = 0.0
        self.shake.add(0.45)
        self.sparks.burst(SCREEN_BASE_X + 20,
                          ground_screen_y(SCREEN_BASE_X + 20) - 70,
                          n=10, color=(255, 90, 70))
        self.banner = (f"乱 阵 ！· {r.reason}", 1.2)
        self.result_pop = (f"MISS · {r.reason}", 0.9)
        self.events.append(("fail", r))

    def _front_screen_x(self) -> float:
        return SCREEN_BASE_X + 50.0

    def enemy_screen_x(self, e: Enemy) -> float:
        return SCREEN_BASE_X + (e.x - self.squad.x) * PX_PER_UNIT

    def screen_anchor(self, u: float, v: float,
                      dy: float = 0.0) -> tuple[int, int]:
        """战斗特效的世界坐标 → 屏幕落点（单点透视，不带镜头下压）。"""
        sx, sy = p3d.world_to_screen(u, v, self.cam_x, 0)
        return (sx, int(round(sy + dy)))

    def _front_world(self) -> tuple[float, float]:
        """队伍前卫的世界坐标（渲染用同一套阵型槽位）。"""
        slots = FORMATION_SLOTS.get(self.formation) or \
            FORMATION_SLOTS["changshe"]
        du, dv = slots[0]
        return (self.squad.x + du, dv)

    # -------------------------------------------------------------- 鼓劲槽 / Fever
    def _add_gauge(self, n: int) -> None:
        if self.now < self.fever_cd_until:
            return
        if self.fever_active:
            self.fever_gauge = min(self.diff["fever_gauge"],
                                   self.fever_gauge + n)
            return
        self.fever_gauge += n
        if self.fever_gauge >= self.diff["fever_gauge"]:
            self._start_fever()

    def _end_fever(self, reason: str) -> None:
        if not self.fever_active:
            return
        self.fever_active = False
        self.fever_until = -1.0
        self.fever_gauge = 0
        self.fever_cd_until = self.now + self.diff["fever_cd_sec"]
        self.events.append(("fever_end", reason))

    def _update_fever(self, dt: float) -> None:
        if not self.fever_active:
            return
        if self.fever_remain <= 0.0:
            self._end_fever("超时")
            return
        if self.fever_remain <= 2.0 and not self.fever_peak:
            self.fever_peak = True
            self.events.append(("fever_peak", None))

    # -------------------------------------------------------------- 自动行军
    def _auto_march(self, new_beats: float, dt: float) -> None:
        """每拍判定一次：保持合拍就前压；脱拍则停步扬尘。"""
        if self.status != "playing" or not self.clock.started:
            return
        k = int(math.floor(new_beats))
        if self._auto_checked_beat is None:
            self._auto_checked_beat = k
            return
        guard = 0
        while self._auto_checked_beat < k and guard < 8:
            guard += 1
            self._auto_checked_beat += 1
            self._auto_march_tick(self._auto_checked_beat)

    def _auto_march_tick(self, beat: int) -> None:
        if self.status != "playing":
            return
        if self.boss_active and self.boss_staggered:
            self._stagger_tap()
        last = self.last_press
        tap = self.last_tap
        on_beat = ((last is not None and last.beat == beat
                    and abs(last.dt_ms) <= AUTO_MARCH["window_ms"]
                    and last.grade in ("perfect", "good"))
                   or (tap is not None and tap.beat == beat
                       and abs(tap.dt_ms) <= AUTO_MARCH["window_ms"]
                       and tap.grade in ("perfect", "good")))
        if on_beat:
            if not self.squad.walking:
                self.squad.walking = True
                self.squad.stance = "march"
            self.squad.march_streak += 1
            gain = min(AUTO_MARCH["max_step"],
                       AUTO_MARCH["step"]
                       + AUTO_MARCH["streak_step"]
                       * max(0, self.squad.march_streak - 1))
            gain *= self.formation_spec["march"]
            gain *= slope_march_factor(self.march_direction,
                                       self.squad.march_streak)
            if self.stunned:
                gain = 0.0
            self._march_forward(gain, self.march_direction)
            self.auto_march_events += 1
            self.stats["auto_march"] += 1
            self.squad.march_anim = 0.32
            self.squad.march_pulse = 0.22
            self.squad.march_step += 1
            fx = self._front_screen_x() - 30
            if self.squad.march_step % 2 == 1:
                self.sparks.burst(fx, ground_screen_y(fx) - 4, n=4,
                                  color=(210, 180, 130))
        else:
            if self.squad.walking:
                self.squad.brake_t = 0.62
            if self.penalized:
                self.squad.walking = False
                self.squad.stance = "halt"
                return
            self.squad.march_streak = 0
            self.squad.walking = False
            self.squad.stance = "halt"
            fx = self._front_screen_x() - 24
            self.sparks.burst(fx, ground_screen_y(fx) - 2, n=6,
                              color=(150, 120, 96))

    def _forward_limit(self) -> float:
        """行军前沿：不越过关卡末端、最近未死敌人（含 dormant）与 Boss。"""
        limit = float(self.map_len) - 2.0
        xs = [e.x for e in self.enemies if not e.dead]
        if xs:
            limit = min(limit, min(xs) - 3.6)
        if self.boss_active and self.boss is not None:
            limit = min(limit, self.boss.x - 3.6)
        return max(self.squad.x, limit)

    def _march_forward(self, step: float, direction: float = 1.0) -> None:
        """沿坡前进/回撤；下坡不额外修正（加速已计入 step），上坡仅用于回撤。"""
        if step <= 0.0:
            return
        if direction >= 0:
            step *= float(segment_at(self.squad.x).get("march_boost", 1.0))
            self.squad.x = min(self._forward_limit(), self.squad.x + step)
        else:
            self.squad.x = max(0.0, self.squad.x - step)
            self.squad.brake_t = max(self.squad.brake_t, 0.50)

    # -------------------------------------------------------------- 指令效果
    def _do_attack(self, r: GroupResult) -> None:
        self.squad.attack_anim = 0.45
        perfect = r.grade == "perfect"
        self.hitstop = 0.12 if perfect else 0.045
        self.trail_t = 0.40 if perfect else 0.22
        self.shake.add(0.68 if perfect else 0.32)
        if perfect:
            self.shout_t = 0.80
        elif self.fever_active:
            self.shout_t = 0.45
        self.stats["attacks"] += 1
        for u in self.squad.alive_units:
            u.attack_anim = 0.42
        front = self.squad.front
        self._peak_pending = HERO_FOR_KIND.get(front.kind, "") if front else ""
        self._peak_target = None
        if self.formation == "menghu":
            self.stun_until = self.now + self.formation_spec["stun_sec"]
            self.events.append(("stun_start", None))

        targets = self.living_enemies
        if not targets:
            fu, fv = self._front_world()
            ax, ay = self.screen_anchor(fu + 1.4, fv, dy=-70)
            self.sparks.burst(ax, ay, n=8, color=(240, 220, 160))
            return
        target = min(targets, key=lambda e: e.x)
        self._peak_target = target
        form_atk = self.formation_spec["atk"]
        mult = (1.25 if perfect else 1.0) * (FEVER_DAMAGE if self.fever_active else 1.0)
        total = 0.0
        for u in self.squad.alive_units:
            if (target.x - self.squad.x) > u.range + 1.1:
                continue
            dmg = u.atk * form_atk * mult
            if not (self.fever_active and u.kind == "spear"):
                dmg *= (1.0 - target.armor)
            if u.kind == "drummer" and self.fever_active:
                dmg *= 1.35
            total += dmg
        counter = 1.0
        if target.is_boss and self.intent_key:
            counter = self.counter_mult()
            total = max(1.0, round(total * counter, 1))
        if target.is_boss and self.boss_on_platform:
            # 台下仰攻：命中率 85%、伤害 ×0.85
            total = max(1.0, round(total * float(BOSS_PLATFORM["player_damage_mult"]), 1))
            self.events.append(("boss_low_hit", target, total))
        self._damage_enemy(target, total, perfect)
        self._emit_counter(target, counter)
        self.events.append(("attack_perfect" if perfect else "attack_good", target))

    def _do_march(self, r: GroupResult) -> None:
        step = 2.45 * self.formation_spec["march"] \
            * (1.15 if r.grade == "perfect" else 1.0) \
            * slope_march_factor(1.0, 0)
        step *= float(segment_at(self.squad.x).get("march_boost", 1.0))
        self.squad.x = min(self._forward_limit(), self.squad.x + step)
        self.squad.walking = True
        self.squad.stance = "march"
        self.squad.march_anim = 0.9
        self.squad.march_streak = 0
        self.stats["marches"] += 1
        if r.grade == "perfect":
            self.trail_t = max(self.trail_t, 0.35)
            self.shake.add(0.18)
        self.sparks.burst(SCREEN_BASE_X + 20,
                          ground_screen_y(SCREEN_BASE_X + 20) - 8,
                          n=10, color=(200, 170, 120))

    def _do_defend(self, r: GroupResult) -> None:
        self.defend_until = self.now + 4.0 * self.clock.beat_sec
        self.stats["defends"] += 1
        self.squad.walking = False
        self.squad.stance = "defend"
        self.squad.march_streak = 0
        self.shake.add(0.12)
        self.sparks.burst(SCREEN_BASE_X + 88,
                          ground_screen_y(SCREEN_BASE_X + 88) - 46,
                          n=10, color=(120, 200, 255))

    def _do_formation(self, r: GroupResult) -> None:
        cmd = r.command or "changshe"
        self.formation = COMMAND_FORMATION[cmd]
        self.stats["formations"] += 1
        self.squad.walking = True
        self.squad.stance = "march"
        self.squad.march_streak = 0
        spec = self.formation_spec
        self.shake.add(0.2)
        for u in self.squad.alive_units:
            self.sparks.burst(SCREEN_BASE_X + 40,
                              ground_screen_y(SCREEN_BASE_X + 40) - 50,
                              n=6, color=unit_color(u.kind))
        self.banner = (f"变阵 · {spec['name']}", 1.4)
        self.events.append(("formation", self.formation))

    def _emit_counter(self, target: Enemy, mult: float) -> None:
        """克制/被克命中：累加统计并触发「克」字印与事件。"""
        if not target.is_boss or abs(mult - 1.0) < 1e-6:
            return
        if mult > 1.0:
            self.counter_hits += 1
            self.stats["counter_hits"] += 1
            self.counter_pop = ("克", 0.60)
            self.result_pop = (f"克制 ×{mult:.2f}", 0.90)
            self.events.append(("counter_hit", target, mult))
            self.shake.add(0.22)
        else:
            self.countered_hits += 1
            self.stats["countered_hits"] += 1
            self.counter_pop = ("被克", 0.60)
            self.result_pop = (f"被克 ×{mult:.2f} · 伤害衰减", 0.90)
            self.events.append(("countered_hit", target, mult))

    def _damage_enemy(self, e: Enemy, dmg: float, perfect: bool) -> None:
        e.hp -= dmg
        e.flash = 0.22
        self.stats["damage_dealt"] += dmg
        ax, ay = self.screen_anchor(e.x, e.v, dy=-58)
        self.sparks.burst(ax, ay, n=30 if perfect else 12,
                          color=(255, 226, 120) if perfect else (255, 150, 80))
        if e.hp <= 0.0:
            e.hp = 0.0
            e.dead = True
            self.shake.add(0.35)
            self.events.append(("boss_dead" if e.is_boss else "enemy_dead", e))
            if e.is_boss:
                self.status = "cleared"
                self.banner = ("鼓 王 伏 诛", 3.0)
                self.events.append(("cleared", None))
            elif self.phase == "trash":
                if not [x for x in self.enemies if not x.dead and x.wave == e.wave]:
                    self._clear_wave(e.wave)
                if all(x.dead for x in self.enemies):
                    self._spawn_boss()

    def _clear_wave(self, wave: int) -> None:
        """整波清空：全队回血、倒地好汉扶起，长关卡中途唯一补给点。"""
        heal = float(LEVEL.get("wave_clear_heal", 0.35))
        revive = float(LEVEL.get("wave_clear_revive", 0.25))
        for u in self.squad.units:
            if u.down:
                u.down = False
                u.down_t = 0.0
                u.hp = max(u.hp, u.max_hp * revive)
            else:
                u.hp = min(u.max_hp, u.hp + u.max_hp * heal)
        self.banner = ("整 军 再 进", 1.2)
        self.events.append(("wave_clear", wave))


    def _spawn_wave(self, w: dict, wi: int) -> None:
        """按关卡表生成一波：grunt/brute 沿 lane_spacing 居中铺开。"""
        spacing = float(LEVEL.get("props", {}).get("lane_spacing", 5.0))
        grunts = max(0, int(w.get("grunt", 0)))
        brutes = max(0, int(w.get("brute", 0)))
        count = grunts + brutes
        if count <= 0:
            return
        kinds = ["grunt"] * count
        start = (count - brutes) // 2
        for k in range(brutes):
            kinds[min(count - 1, start + k)] = "brute"
        u = float(w.get("u", 0.0))
        dormant = wi != 0
        for i, kind in enumerate(kinds):
            v = spacing * (i - (count - 1) / 2.0)
            x = u + self.rng.uniform(0.0, 0.3)
            self.enemies.append(Enemy(kind, x, i, v=v, wave=wi,
                                      dormant=dormant))

    def _configure_boss_platform(self, boss: Enemy,
                                  x: float | None = None) -> None:
        """按关卡表的 boss 石台几何写回 Enemy（x 可指定击落后的落点）。"""
        bc = LEVEL.get("boss", {})
        base_u = float(bc.get("u", boss.x))
        anchor = float(boss.x if x is None else x)
        delta = anchor - base_u
        boss.platform_x = anchor
        boss.platform_u0 = float(bc.get("platform_u0",
                                        base_u - 1.55)) + delta
        boss.platform_u1 = float(bc.get("platform_u1",
                                        base_u + 1.55)) + delta
        boss.platform_v_half = float(bc.get("platform_v_half", 1.75))
        boss.platform_h = int(bc.get("thickness_px", 30))
        boss.platform_steps = int(bc.get("steps", 3))

    def _spawn_boss(self) -> None:
        self.phase = "boss"
        if self.boss is None:
            return
        self.boss.active = True
        self.boss.dead = False
        self.boss.hp = self.boss.max_hp
        self.boss.x = float(LEVEL["boss"]["u"])
        self._configure_boss_platform(self.boss)
        self.score = BossScore(self.seed)
        self.boss_phase = 1
        self.boss_phase_reached = 1
        self.intent_variant = "normal"
        self.intent_windup = 0.0
        self.intent_reveal_beats = 4
        self.intent_index = 0
        self.intent_key = None
        self.intent_cycle = -1
        self.attempt = None
        self._boss_resolved_cycle = -1
        self.stagger_until = -1.0
        self.shake.add(0.6)
        self.banner = ("鼓 王 登 场 · 抬 手 即 公 示", 3.0)
        self.events.append(("boss_spawn", self.boss))

    # -------------------------------------------------------------- 敌人 AI
    def _unit_damage_scale(self, u: Unit) -> float:
        scale = (1.0 - u.armor) * (1.0 - self.formation_spec["dr"])
        if self.defending:
            scale *= 0.40
        return max(0.05, scale)

    def _hit_unit(self, u: Unit, raw: float) -> float:
        if self.fever_active:
            raw *= 0.85  # Fever 护体
        dmg = max(1.0, raw * self._unit_damage_scale(u))
        u.hp = max(0.0, u.hp - dmg)
        u.hurt_flash = 0.35
        self.squad.hurt_flash = 0.35
        if u.hp <= 0.0 and not u.down:
            u.down = True
            self.events.append(("unit_down", u))
        return dmg

    def _update_enemies(self, dt: float) -> None:
        beat = self.beat_index
        for e in self.enemies:
            if e.dead or e.dormant:
                continue
            target_x = self.squad.x + e.standoff
            if e.x > target_x:
                e.x = max(target_x, e.x - e.speed * dt)
            if (e.x - self.squad.x) <= 3.4 and beat >= e.next_attack_beat:
                u = self.squad.front
                if u is not None:
                    e.attack_anim = 0.45
                    e.next_attack_beat = beat + e.atk_every
                    raw = e.atk * self.diff["enemy_dmg"]
                    dmg = self._hit_unit(u, raw)
                    self.shake.add(0.5)
                    ax, ay = self.screen_anchor(e.x, e.v, dy=-54)
                    self.sparks.burst(ax, ay, n=10, color=(255, 84, 66))
                    self.events.append(("squad_hit", e, dmg))

    # -------------------------------------------------------------- Boss 破阵
    def _update_boss_window(self) -> None:
        if not self.boss_active or self.status != "playing":
            return
        c = self.cycle_index
        slot = self.cycle_slot
        hp_ratio = max(0.0, min(1.0, self.boss.hp / self.boss.max_hp))
        # 第一阶段公示 6 拍：抬手提前 2 拍（第 2 拍位），输入窗口仍是第 4–7 拍
        lead = 0
        if self.guidance:
            lead = max(0, self.score.reveal_for_hp(hp_ratio) - 4)
        reveal_beat = c * CYCLE_BEATS + 4 - lead
        # 抬手与公示略早于重拍（0.08 拍 ≈ 36ms），保证重拍按下第一记化解也能收
        if self.beat_pos >= reveal_beat - 0.08 and self.intent_cycle != c:
            pick = self.score.pick(reveal_beat, hp_ratio)
            if pick is None:
                return
            prev_phase = self.boss_phase
            self.intent_cycle = c
            self.intent_key = pick.intent
            self.intent_index += 1
            self.intent_variant = pick.variant
            self.intent_windup = pick.windup
            self.intent_reveal_beats = pick.reveal_beats if self.guidance else 4
            self.boss_phase = pick.phase
            self.boss_phase_reached = max(self.boss_phase_reached, pick.phase)
            self.attempt = BossAttempt(
                cycle=c, intent_key=pick.intent, variant=pick.variant,
                phase=pick.phase, windup=pick.windup)
            self.shake.add(0.18)
            intent = INTENTS[pick.intent]
            self._maybe_tutorial_hint(pick.intent)
            if pick.phase != prev_phase or pick.variant == "phase_open":
                self.banner = (f"第 {pick.phase} 阶段 · {pick.phase_name}"
                               f" · 长公示 {pick.reveal_beats} 拍", 2.4)
                self.result_pop = (f"阶段 {pick.phase} · {pick.phase_name}", 1.4)
                self.events.append(("boss_phase", pick.phase))
            else:
                self.banner = (f"鼓王抬手 · {intent['name']}"
                               f" · {intent['tell']}", 1.6)
            self.events.append(("boss_read", pick.intent, pick))

        att = self.attempt
        if att is not None and not att.resolved and att.cycle == c:
            filled = len(att.slots)
            # 第 4+filled 拍位已过仍未收到该拍 → 整组化解失败
            if filled < INPUT_BEATS and slot >= 4 + filled + 1:
                self._resolve_attempt(att, early=False)
            elif filled >= INPUT_BEATS:
                self._resolve_attempt(att, early=False)

    def _maybe_tutorial_hint(self, key: str) -> None:
        """每种招式只在第一次出现时弹一次提示，不做常驻弹窗。"""
        if not self.guidance or key in self.tutorial_seen:
            return
        self.tutorial_seen.add(key)
        self.tutorial_hint = (tutorial_hint_text(key), float(TUTORIAL["hint_sec"]))
        self.tutorial_shown += 1
        self.events.append(("tutorial_hint", key))

    def _resolve_attempt(self, att: BossAttempt, early: bool,
                         at_beat: float | None = None) -> None:
        if att.resolved:
            return
        att.resolved = True
        self._boss_resolved_cycle = att.cycle
        intent = INTENTS[att.intent_key]
        expected = intent["counter"]
        keys = "".join(s.key or "·" for s in att.slots)
        grace = (self.guidance
                 and self.boss_attacks < int(TUTORIAL["grace_attacks"]))
        self.boss_attacks += 1

        if att.all_perfect and COMMANDS.get(keys, (None,))[0] == expected:
            att.perfect = True
            att.avoided = True
            self.stats["intents_read"] += 1
            self.stats["boss_perfect_breaks"] += 1
            self.last_stagger_cycle = att.cycle
            self.stagger_until = self.now + STAGGER_SEC
            self._start_fever(from_break=True)
            self.banner = ("极 限 破 阵 ！· 鼓王硬直", 2.2)
            self.result_pop = ("极限破阵！", 1.2)
            # 下坡击退：Boss 顺坡被推得更远
            if self.boss is not None:
                was_on_platform = bool(self.boss.on_platform
                                       and self.platform_enabled)
                kb = slope_knock_distance(0.9, 1.0)
                self.boss.x = min(self.map_len - 4.0, self.boss.x + kb)
                self.events.append(("boss_knock", round(kb, 2)))
                if was_on_platform:
                    # 破阵直接把 Boss 拽下石台：失去高度优势 + 更长硬直
                    self.boss.on_platform = False
                    self.stagger_until = self.now + float(
                        BOSS_PLATFORM["knockdown_stagger_sec"])
                    self.result_pop = ("击落台下！· 长硬直", 1.6)
                    self.events.append(("boss_knockdown", self.boss))
            self.events.append(("boss_perfect", att))
            return

        matched = False
        if COMMANDS.get(keys, (None,))[0] == expected:
            grades = [s.grade for s in att.slots]
            if any(g == "miss" for g in grades):
                matched = False
            else:
                weighted = 0.0
                for g in grades:
                    weighted += 1.0 if g == "perfect" else 0.5
                matched = (weighted / INPUT_BEATS) >= 0.5
        if matched:
            att.avoided = True
            self.stats["intents_read"] += 1
            self.banner = ("破 阵 成 功 · 化 解", 1.5)
            self.events.append(("boss_read_ok", att))
            return

        # 失败：吃伤害；教学期内只公示免罚，且不清连击/鼓劲槽
        self.stats["intents_hit"] += 1
        self.stats["intents_fail"] += 1
        self.events.append(("boss_fail", att))
        if grace:
            self.stats["tutorial_grace"] = self.stats.get("tutorial_grace", 0) + 1
            self.result_pop = ("教学招 · 只公示免罚", 1.4)
            self.events.append(("tutorial_grace", att))
            self._boss_damage(att, intent, grace)
            return
        # 二/三阶段：错令或窗口内漏拍 → 1 拍补打机会，伤害延后结算
        if (self.makeup_enabled and not grace
                and att.phase in MAKEUP["phases"] and not att.makeup_used):
            att.makeup_used = True
            att.makeup_state = "pending"
            att.makeup_deadline = self.now + float(
                MAKEUP["window_beats"]) * self.clock.beat_sec
            att.makeup_keys.clear()
            self.banner = ("补 打 机 会 · 1 拍 内 补 令", 1.1)
            self.result_pop = ("补打！" + self.makeup_pattern, 1.1)
            self.hitstop = 0.05
            self.events.append(("boss_makeup_open", att))
            return
        self._boss_damage(att, intent, grace)

    def _finish_makeup(self, success: bool | None = None) -> None:
        """结算补打：成功半伤且保留连击；失败/超时按原规则全额。"""
        att = self.attempt
        if att is None or att.makeup_state != "pending":
            return
        pattern = COMMAND_KEYS.get(INTENTS[att.intent_key]["counter"], "")
        ok = ("".join(att.makeup_keys) == pattern
              and len(att.makeup_keys) == INPUT_BEATS) if success is None \
            else bool(success)
        intent = INTENTS[att.intent_key]
        att.makeup_state = "ok" if ok else "failed"
        if ok:
            self.stats["makeup_ok"] = self.stats.get("makeup_ok", 0) + 1
            self.stats["good"] += 1          # 补打按 Good 计，不算 Perfect
            self.result_pop = ("补 打 成 功 · GOOD · 半 伤", 1.6)
            self.banner = ("补 打 成 功 · 半 伤", 1.6)
            self.events.append(("boss_makeup_ok", att))
            self._boss_damage(att, intent, grace=False,
                              mult=float(MAKEUP["damage_mult"]), makeup=True)
        else:
            self.stats["makeup_fail"] = self.stats.get("makeup_fail", 0) + 1
            self.result_pop = ("补 打 失 败 · 全 额", 1.5)
            self.banner = ("补 打 失 败 · 全 额 伤 害", 1.5)
            self.events.append(("boss_makeup_fail", att))
            self._boss_damage(att, intent, grace=False)

    def _update_makeup(self) -> None:
        att = self.attempt
        if att is None or att.makeup_state != "pending":
            return
        if self.now >= att.makeup_deadline:
            self._finish_makeup(False)

    def _boss_damage(self, att: BossAttempt, intent: dict,
                     grace: bool = False, mult: float = 1.0,
                     makeup: bool = False) -> None:
        if self.boss is None:
            return
        raw = intent["dmg"] * self.diff["enemy_dmg"] * max(0.0, float(mult))
        if grace:
            raw *= float(TUTORIAL["damage_mult"])
            if raw <= 0.0:
                # 教学招：只公示，不结算伤害/击退/硬直
                self.banner = ("教 学 招 · 只 公 示 · 免 罚", 1.4)
                self.hitstop = 0.0
                return
        # 石台高度优势：台上 Boss 的近战伤害 ×1.35（AOE 吼/扫不算近战）
        if self.boss_on_platform and intent.get("kind") != "aoe":
            raw *= float(BOSS_PLATFORM["boss_damage_mult"])
        if self.boss.hp <= self.boss.max_hp * 0.5:
            raw *= 1.25
        form_dr = max(0.0, self.formation_spec["dr"])
        raw *= max(0.0, 1.0 - form_dr)
        if self.formation_spec.get("stun_sec"):
            raw *= 0.8
        if intent["aoe"]:
            units = list(self.squad.alive_units)
            share = raw / max(1.0, float(len(units)))
            total = 0.0
            for u in units:
                total += self._hit_unit(u, share)
        else:
            u = self.squad.front
            total = self._hit_unit(u, raw) if u is not None else 0.0
        if not grace and not makeup:
            # 补打成功保留连击/鼓劲槽、不累积 Fever；只有彻底失败才清零
            self.combo = 0
            self.fever_gauge = 0
            if self.fever_active:
                self._end_fever("破阵失败")
        self.shake.add(0.9)
        self.hitstop = 0.09
        # 上坡击退：队伍被迫回撤，坡向让距离更短
        recoil = slope_knock_distance(0.55, -1.0)
        self.squad.x = max(0.0, self.squad.x - recoil)
        self.squad.walking = False
        self.squad.brake_t = 0.55
        self.events.append(("squad_knock", round(recoil, 2)))
        bx, by = self.screen_anchor(self.boss.x, self.boss.v, dy=-60)
        self.sparks.burst(bx, by, n=34, color=(255, 70, 54))
        self.events.append(("boss_hit", att, total))

    def _start_fever(self, from_break: bool = False) -> None:
        prev = self.fever_active
        if not prev:
            self.fever_active = True
            self.fever_peak = False
            self.fever_until = self.now + self.diff["fever_sec"]
            self.fever_gauge = self.diff["fever_gauge"]
            self.fever_count += 1
            self.stats["fever_count"] = self.fever_count
            self.shake.add(0.55)
            fu, fv = self._front_world()
            ax, ay = self.screen_anchor(fu, fv, dy=-80)
            self.sparks.burst(ax, ay, n=36, color=(255, 210, 100))
            self.events.append(("fever_start", None))
        else:
            # Fever 中再破阵：整罐续满的额外充能，最多延到 3 倍时长
            cap = self.now + self.diff["fever_sec"] * 3.0
            self.fever_until = min(cap, self.fever_until
                                   + self.diff["fever_sec"] * 0.8)
            self.fever_gauge = self.diff["fever_gauge"]
            self.result_pop = ("破阵充能！", 1.0)
            self.events.append(("fever_refill", None))
        if from_break:
            fu, fv = self._front_world()
            ax, ay = self.screen_anchor(fu, fv, dy=-80)
            self.sparks.burst(ax, ay, n=24, color=(255, 120, 60))

    def boss_stagger_remaining(self) -> float:
        if not self.boss_staggered:
            return 0.0
        return max(0.0, self.stagger_until - self.now)

    def _stagger_tap(self) -> None:
        """硬直期踏点击打：每拍一次小队追击，Fever 时翻倍。"""
        boss = self.boss
        if boss is None:
            return
        base = sum(u.atk for u in self.squad.alive_units) * 0.55
        counter = self.counter_mult() if self.intent_key else 1.0
        dmg = round(base * (FEVER_DAMAGE if self.fever_active else 1.0)
                    * counter, 1)
        if self.boss_on_platform:
            dmg *= float(BOSS_PLATFORM["player_damage_mult"])
        self._damage_enemy(boss, max(1.0, dmg), True)
        self.events.append(("stagger_hit", boss))

    # -------------------------------------------------------------- 收尾
    def drain_events(self) -> list[tuple]:
        ev = self.events
        self.events = []
        return ev

    def start_boss_fight(self, squad_x: float | None = None,
                         boss_x: float | None = None) -> None:
        """跳过杂兵，直接进入 Boss 战（模拟手/自测用，可复现）。"""
        if boss_x is None:
            boss_x = float(LEVEL["boss"]["u"])
        if squad_x is None:
            squad_x = boss_x - 6.4
        self.phase = "boss"
        for e in self.enemies:
            e.dead = True
        self.enemies.clear()
        if self.boss is not None:
            self.boss.active = True
            self.boss.dead = False
            self.boss.hp = self.diff["boss_hp"]
            self.boss.max_hp = self.diff["boss_hp"]
            self.boss.x = boss_x
            self.boss.on_platform = True
            self._configure_boss_platform(self.boss, boss_x)
        self.squad.x = squad_x
        self.squad.walking = True
        self.score = BossScore(self.seed)
        self.boss_phase = 1
        self.boss_phase_reached = 1
        self.boss_attacks = 0
        self.tutorial_seen.clear()
        self.tutorial_hint = ("", 0.0)
        self.intent_key = None
        self.intent_cycle = -1
        self.attempt = None
        self.stagger_until = -1.0
        self.banner = ("鼓 王 登 场 · 抬 手 即 公 示", 3.0)
        self.events.append(("boss_spawn", self.boss))

    def reset(self, now: float, seed: int | None = None) -> None:
        if seed is not None:
            self.rng = random.Random(seed)
            self.seed = seed
        difficulty = self.difficulty
        spawn_boss = self.boss is not None
        fresh = Game(bpm=self.clock.base_bpm, start_time=now + 1.1,
                     seed=int(seed if seed is not None
                              else self.rng.randint(0, 2 ** 31)),
                     difficulty=difficulty, spawn_boss=spawn_boss)
        self.__dict__.update(fresh.__dict__)
        self.banner = ("重 整 旗 鼓", 1.5)


def unit_color(kind: str) -> tuple[int, int, int]:
    return UNIT_TYPES[kind]["color"]

