"""战前场景状态机（第十八轮）：标题 → 选将 → 新手指南 → 战斗。

本模块不 import pygame，全部逻辑可在无显示器环境跑通：
- 9 宫格选将（3 位好汉 + 6 个锁定格）、悬停条件、领队选择与持久化；
- 6 步新手指南，每步有可交互目标，完成才允许进入下一步；
- 第 6 步个人节奏校准：8 拍自由敲，写入 input_offset_ms；
- 战斗暂停菜单：继续 / 新手指南（每局一次）/ 返回标题。

判定窗口一律调用 core.judge_press，不改窗口数值；教学场景只放宽 Miss 反馈
（不罚连击、失败给针对性提示）。
"""
from __future__ import annotations

import json
import math
import os

import core

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "config", "settings.json")
MODE_PATH = os.path.join(HERE, "config", "mode.json")

# 默认版本开关：第20-22轮新增的跑酷/三态必须能被这里整体关掉，
# 关闭后默认流程回到第18-19轮 Title → Roster → Guide → Boss。
DEFAULT_MODE = {
    "default_mode": "boss_1819",
    "runner_enabled": False,
    "culture_enabled": False,
    "hud_style": "ribbon",
    "guide_v2": True,
}


def load_mode(path: str = MODE_PATH) -> dict:
    data = dict(DEFAULT_MODE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data.update({k: loaded[k] for k in DEFAULT_MODE if k in loaded})
    except Exception:
        pass
    data["default_mode"] = str(data["default_mode"])
    data["runner_enabled"] = bool(data["runner_enabled"])
    data["culture_enabled"] = bool(data["culture_enabled"])
    data["hud_style"] = str(data["hud_style"])
    data["guide_v2"] = bool(data["guide_v2"])
    return data


# ------------------------------------------------------------------ 流程
SCENES = ("title", "roster", "guide", "runner", "battle")
GUIDE_STEPS = (
    {"key": "drum", "title": "这是鼓", "hint": "按一次 J，听触键音",
     "goal": "按 J 1 次"},
    {"key": "group", "title": "四拍成令", "hint": "J×4，踩准四拍落定",
     "goal": "一组 4 拍全中"},
    {"key": "three", "title": "三种乐器", "hint": "J 攻 · K 行 · L 守",
     "goal": "每种各成一组"},
    {"key": "forms", "title": "阵法", "hint": "JKJK 锋矢 · LKLK 龟甲",
     "goal": "两阵各成一次"},
    {"key": "boss", "title": "读谱与破阵", "hint": "照公示打化解键",
     "goal": "四拍化解"},
    {"key": "calib", "title": "个人节奏校准", "hint": "按 8 拍自由敲",
     "goal": "8 拍或跳过"},
)

# Boss 教学公示：固定招式，方便玩家按 K K K K。
GUIDE_INTENT = "slam"
GUIDE_KEYS = core.INTENTS[GUIDE_INTENT]["keys"]

# ------------------------------------------------------------------ 选将
HERO_CELLS = (
    {"kind": "hero", "hero": "wusong"},
    {"kind": "hero", "hero": "linchong"},
    {"kind": "hero", "hero": "likui"},
)
LOCK_CELLS = (
    {"kind": "lock", "id": "lock1", "cond": ("第 6 关", "坡上林地")},
    {"kind": "lock", "id": "lock2", "cond": ("击败", "Boss A 后")},
    {"kind": "lock", "id": "lock3", "cond": ("第 9 关", "坡中街市")},
    {"kind": "lock", "id": "lock4", "cond": ("达成", "20 连击")},
    {"kind": "lock", "id": "lock5", "cond": ("通关", "操练档")},
    {"kind": "lock", "id": "lock6", "cond": ("击败", "Boss B 后")},
)
ROSTER_CELLS = HERO_CELLS + LOCK_CELLS
ROSTER_GRID = (3, 3)

# 领队 → 初始阵型推荐、开场台词、脸谱/兵种/技能/站位说明
LEADER_LOADOUT = {
    "wusong": {
        "name": "武松", "face": "赤面", "kind": "drummer", "unit": "鼓手",
        "skill": "双抛槌", "effect": "连击不断，双击破甲",
        "formation": "shuanglong", "stand": "前排居中，领鼓先手",
        "line": "赤面金睛，领鼓开阵",
    },
    "linchong": {
        "name": "林冲", "face": "白面豹纹", "kind": "spear", "unit": "矛兵",
        "skill": "回马枪", "effect": "无视护甲，穿透后排",
        "formation": "fengshi", "stand": "两翼展开，箭簇突前",
        "line": "枪出如龙，锋矢先破",
    },
    "likui": {
        "name": "李逵", "face": "黑面环眼", "kind": "shield", "unit": "盾兵",
        "skill": "旋风劈", "effect": "横扫前排，全队减伤",
        "formation": "guijia", "stand": "阵前承伤，护住鼓手",
        "line": "黑塔承伤，龟甲压阵",
    },
}
HERO_ORDER = ("wusong", "linchong", "likui")

# 9 宫格布局（逻辑 960×540），渲染与鼠标命中都只读这里
ROSTER_ORIGIN = (96, 112)
ROSTER_CELL = 84
ROSTER_GAP = 12
ROSTER_PITCH = ROSTER_CELL + ROSTER_GAP
ROSTER_PREVIEW = (404, 96, 524, 352)

# 标题交互：两种模式各一条热区，热区与视觉边界一致
TITLE_ENTER_RECT = (330, 370, 300, 40)      # ENTER：急行
TITLE_BOSS_RECT = (330, 422, 300, 40)       # B：Boss 战
RUNNER_RESTART_RECT = (356, 508, 120, 28)
RUNNER_BOSS_RECT = (490, 508, 120, 28)
RUNNER_TITLE_RECT = (624, 508, 120, 28)

# 指南布局（逻辑坐标）：渲染与鼠标命中只读同一份常量。
# 右栏 324..904：大鼓居中，锣/镲为两侧配器（同时就是 K/L 键位牌）。
GUIDE_STEP_RECT = (68, 100, 224, 54)
GUIDE_STEP_PITCH = 62
GUIDE_DRUM_RECT = (492, 190, 236, 146)          # J：点鼓面 = 按 J
GUIDE_KEY_RECT = {
    "J": GUIDE_DRUM_RECT,
    "K": (416, 210, 58, 104),                    # 锣
    "L": (746, 210, 58, 104),                    # 镲
}
GUIDE_TICKS = tuple((GUIDE_DRUM_RECT[0] + 40 + i * 54,
                     GUIDE_DRUM_RECT[1] + 96) for i in range(4))
GUIDE_STRIP_RECT = (348, 340, 532, 38)
GUIDE_RIBBON_RECT = (348, 386, 532, 22)
GUIDE_NEXT_RECT = (348, 432, 180, 36)
GUIDE_SKIP_RECT = (700, 432, 150, 36)
GUIDE_SKIP_ALL_RECT = (812, 96, 88, 26)


def guide_step_rect(index: int) -> tuple[int, int, int, int]:
    return (GUIDE_STEP_RECT[0], GUIDE_STEP_RECT[1] + index * GUIDE_STEP_PITCH,
            GUIDE_STEP_RECT[2], GUIDE_STEP_RECT[3])


def guide_step_at(x: int, y: int) -> int:
    for i in range(len(GUIDE_STEPS)):
        gx, gy, gw, gh = guide_step_rect(i)
        if gx <= x < gx + gw and gy <= y < gy + gh:
            return i
    return -1


PAUSE_ITEM_RECT = (336, 198, 288, 36)


def pause_item_at(x: int, y: int) -> int:
    for i in range(len(PAUSE_ITEMS)):
        rx, ry, rw, rh = PAUSE_ITEM_RECT
        ry += i * 56
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return i
    return -1


def _in(rect: tuple[int, int, int, int], x: int, y: int) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def roster_cell_rect(index: int) -> tuple[int, int, int, int]:
    col = index % ROSTER_GRID[1]
    row = index // ROSTER_GRID[1]
    return (ROSTER_ORIGIN[0] + col * ROSTER_PITCH,
            ROSTER_ORIGIN[1] + row * ROSTER_PITCH,
            ROSTER_CELL, ROSTER_CELL)


def roster_cell_at(x: int, y: int) -> int:
    for i in range(len(ROSTER_CELLS)):
        cx, cy, cw, ch = roster_cell_rect(i)
        if cx <= x < cx + cw and cy <= y < cy + ch:
            return i
    return -1


def cell_spec(index: int) -> dict:
    return ROSTER_CELLS[index] if 0 <= index < len(ROSTER_CELLS) else {}


def cell_player(index: int) -> str | None:
    spec = cell_spec(index)
    return spec.get("hero") if spec.get("kind") == "hero" else None


# ------------------------------------------------------------------ 设置
SETTING_DEFAULTS = {"leader": "wusong", "input_offset_ms": 0, "guide_seen": False}


def load_settings(path: str = SETTINGS_PATH) -> dict:
    out = dict(SETTING_DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out.update({k: v for k, v in data.items() if k not in ("_note",)})
            if "_note" in data:
                out["_note"] = data["_note"]
    except Exception:
        pass
    if out.get("leader") not in LEADER_LOADOUT:
        out["leader"] = SETTING_DEFAULTS["leader"]
    try:
        out["input_offset_ms"] = int(round(float(out.get("input_offset_ms", 0))))
    except (TypeError, ValueError):
        out["input_offset_ms"] = 0
    out["input_offset_ms"] = max(-120, min(120, out["input_offset_ms"]))
    out["guide_seen"] = bool(out.get("guide_seen", False))
    return out


def save_settings(patch: dict, path: str = SETTINGS_PATH) -> dict:
    """合并写回设置；保留 `_note`，不影响未知字段。"""
    data = load_settings(path)
    data.update(patch)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return data


# ------------------------------------------------------------------ 选将逻辑
class Roster:
    """9 宫格光标 / 悬停 / 预览 / 领队确认。"""

    def __init__(self, leader: str = "wusong", path: str = SETTINGS_PATH) -> None:
        self.path = path
        self.leader = leader if leader in LEADER_LOADOUT else "wusong"
        self.cursor = HERO_ORDER.index(self.leader)
        self.hover = -1
        self.preview = self.cursor
        self.slide_px = 0
        self.toast = ("", 0.0)

    # -- 光标
    def move(self, dx: int, dy: int) -> None:
        col = (self.cursor % ROSTER_GRID[1] + dx) % ROSTER_GRID[1]
        row = (self.cursor // ROSTER_GRID[1] + dy) % ROSTER_GRID[0]
        self.cursor = row * ROSTER_GRID[1] + col
        self.hover = -1
        self._retarget(self.cursor)

    def set_hover(self, index: int) -> None:
        self.hover = index if 0 <= index < len(ROSTER_CELLS) else -1
        self._retarget(self.preview_index())

    def preview_index(self) -> int:
        return self.hover if self.hover >= 0 else self.cursor

    def _retarget(self, index: int) -> None:
        if index != self.preview:
            # ≤120ms 的整数像素滑入：±6px，每帧 2px
            self.slide_px = 6 if index > self.preview else -6
            self.preview = index

    def tick(self, dt: float) -> None:
        if self.slide_px > 0:
            self.slide_px = max(0, self.slide_px - 2)
        elif self.slide_px < 0:
            self.slide_px = min(0, self.slide_px + 2)

    # -- 确认
    def confirm(self) -> str | None:
        """可选中格返回 hero id；锁定格返回 None 并更新提示。"""
        spec = cell_spec(self.cursor)
        hero = cell_player(self.cursor)
        if hero is None:
            cond = "·".join(spec.get("cond", ("未解锁",)))
            self.toast = (f"锁定：{cond}", 2.4)
            return None
        self.leader = hero
        save_settings({"leader": hero}, self.path)
        return hero

    def click(self, x: int, y: int) -> str | None:
        index = roster_cell_at(x, y)
        if index < 0:
            return None
        self.cursor = index
        self.hover = -1
        self._retarget(index)
        return self.confirm()

    def preview_spec(self) -> dict:
        return cell_spec(self.preview_index())


# ------------------------------------------------------------------ 指南
class Guide:
    """6 步教学；每步目标完成才允许 next()。"""

    def __init__(self, bpm: float = core.BPM, start_time: float = 0.0,
                 leader: str = "wusong", path: str = SETTINGS_PATH) -> None:
        self.path = path
        self.leader = leader
        self.clock = core.BeatClock(bpm, start_time)
        self.step = 0
        self.done = [False] * len(GUIDE_STEPS)
        self.skipped = False
        self.finished = False
        self.calib_ms = 0
        self.retries = 0
        self.msg = ("", 0.0)
        self.last_grade = ""
        self.flash_key: str | None = None
        self.flash_until = 0.0
        self._base = 1
        self._tick = 0
        self.slots: list[core.Slot] = []
        self.three = {"J": [], "K": [], "L": []}
        self.form_index = 0
        self.taps: list[float] = []
        self._enter_step(0, 0.0)

    # -- 每步初始化
    def _enter_step(self, index: int, now: float) -> None:
        self.step = index
        self.msg = ("", 0.0)          # 换步不保留上一步的提示，避免旧文案残留
        self.slots = []
        self._tick = 0
        self._base = max(1, int(math.floor(self.clock.beat_at(now))) + 1)
        if index == 2:
            self.three = {"J": [], "K": [], "L": []}
        if index == 3:
            self.form_index = 0
        if index == 5:
            self.taps = []

    def update(self, now: float, dt: float) -> None:
        self.clock.update(now)
        if self.msg[0] and now >= self.msg[1]:
            self.msg = ("", 0.0)

    def next_press_time(self) -> float:
        """当前这一拍的目标时间（供 UI 节拍提示与自测对拍）。"""
        return self.clock.beat_time(self._base + self._tick)

    def expected_keys(self) -> tuple[str, ...]:
        if self.step == 2:
            used = [len(self.three[k]) for k in ("J", "K", "L")]
            idx = min(2, sum(1 for n in used if n >= 4))
            return (("J", "K", "L")[idx],) * 4
        if self.step == 3:
            seq = ("J", "K", "J", "K") if self.form_index == 0 \
                else ("L", "K", "L", "K")
            return seq
        if self.step == 4:
            return tuple(GUIDE_KEYS)
        if self.step == 5:
            return ("*",) * 8
        return ("J",) * 4

    def step_done(self) -> bool:
        return self.done[self.step]

    @property
    def next_enabled(self) -> bool:
        return self.done[self.step]

    # -- 按键
    def press(self, key: str, now: float) -> bool:
        """返回 True 表示这一下被计入目标。"""
        if self.finished or self.finished_skip:
            return False
        self.flash_key = key
        self.flash_until = now + 0.18
        if self.step == 0:
            if key == "J":
                self.done[0] = True
                self.msg = ("鼓声收到，按 Enter 继续", now + 2.0)
                return True
            self.msg = ("这是鼓：先按 J", now + 1.5)
            return False
        if self.step == 5:
            self.taps.append(self._dt(now))
            self._tick += 1
            if len(self.taps) >= 8:
                self._finish_calibration()
            return True

        expected = self.expected_keys()
        pos = len(self.slots) if self.step in (1, 3, 4) else self._tick
        want = expected[min(pos, len(expected) - 1)]
        if key != want:
            self.msg = (f"这一拍是 {want}", now + 1.6)
            self._reset_group(now)
            return False

        dt_ms = self._dt(now)
        grade = core.judge_press(dt_ms, 1.0)
        self.last_grade = grade or "off"
        if grade not in ("perfect", "good"):
            self.retries += 1
            self.msg = (self._correction(dt_ms), now + 1.8)
            self._reset_group(now)
            return False

        slot = core.Slot(key=key, grade=grade, dt_ms=dt_ms,
                         beat=self._base + self._tick)
        self._tick += 1
        if self.step in (1, 3, 4):
            self.slots.append(slot)
            if len(self.slots) >= 4:
                self.slots = []
                if self.step == 1:
                    self.done[1] = True
                    self.msg = ("四拍成令 · 过", now + 2.0)
                elif self.step == 3:
                    self.form_index += 1
                    if self.form_index >= 2:
                        self.done[3] = True
                        self.msg = ("阵法 · 过", now + 2.0)
                    else:
                        self.msg = ("锋矢 · 过，下一阵 L K L K", now + 2.0)
                elif self.step == 4:
                    self.done[4] = True
                    self.msg = ("化解 · 过", now + 2.0)
        elif self.step == 2:
            group_key = expected[0]
            self.three[group_key].append(grade)
            if len(self.three[group_key]) >= 4:
                self.msg = (f"{group_key} 组 · 过", now + 1.8)
                if all(len(self.three[k]) >= 4 for k in ("J", "K", "L")):
                    self.done[2] = True
                    self.msg = ("三种乐器 · 过", now + 2.0)
        return True

    def _dt(self, now: float) -> float:
        return (float(now) - self.next_press_time()) * 1000.0

    def _reset_group(self, now: float) -> None:
        self.slots = []
        self._tick = 0
        self._base = max(1, int(math.floor(self.clock.beat_at(now))) + 1)

    @staticmethod
    def _correction(dt_ms: float) -> str:
        ms = int(round(abs(dt_ms)))
        return f"{'晚' if dt_ms > 0 else '早'}了 {ms}ms，看判定线落手"

    # -- 第 6 步校准
    def _finish_calibration(self) -> None:
        mean = sum(self.taps) / len(self.taps) if self.taps else 0.0
        self.calib_ms = int(round(max(-120.0, min(120.0, mean))))
        self.done[5] = True
        self.msg = (f"平均偏移 {self.calib_ms:+d}ms，已写入配置", 0.0)

    def finish_calibration_early(self) -> None:
        """Enter / 鼠标「跳过校准」：不足 8 拍按 0 记录。"""
        if not self.done[5]:
            self.calib_ms = 0
            self.done[5] = True
            self.msg = ("已跳过校准，记为 0", 0.0)

    def restart_calibration(self, now: float = 0.0) -> None:
        """「开始校准」按钮：清空 8 拍，重新计时。"""
        self.taps = []
        self.done[5] = False
        self.calib_ms = 0
        self.msg = ("自由敲 8 拍，跟住鼓点", now + 2.2)

    def goto(self, index: int, now: float = 0.0) -> bool:
        """点击左侧步骤：只允许回到已完成（或已走过）的步骤。"""
        if not (0 <= index < len(GUIDE_STEPS)):
            return False
        if index == self.step:
            return True
        if not (index < self.step or self.done[index]):
            self.msg = ("先完成当前目标", now + 1.6)
            return False
        self._enter_step(index, now)
        self.msg = ("", 0.0)
        return True

    # -- 推进 / 跳过
    def next(self, now: float | None = None) -> bool:
        if not self.done[self.step]:
            return False
        if self.step >= len(GUIDE_STEPS) - 1:
            self.finished = True
            return True
        if now is None:
            now = self.clock.beat_time(self._base + self._tick)
        self._enter_step(self.step + 1, float(now))
        return True

    @property
    def finished_skip(self) -> bool:
        return self.skipped and self.finished

    def skip(self) -> None:
        self.skipped = True
        self.finished = True

    def report(self) -> dict:
        return {
            "skipped": bool(self.skipped),
            "steps_done": sum(1 for d in self.done if d),
            "calib_ms": int(self.calib_ms),
            "retries": int(self.retries),
        }


# ------------------------------------------------------------------ 暂停
PAUSE_ITEMS = ("继续", "新手指南", "返回标题")


class PauseMenu:
    def __init__(self, replay_available: bool = True) -> None:
        self.sel = 0
        self.replay_available = replay_available

    def move(self, d: int) -> None:
        self.sel = (self.sel + d) % len(PAUSE_ITEMS)

    def enabled(self, index: int) -> bool:
        return index != 1 or self.replay_available

    def confirm(self) -> str:
        if not self.enabled(self.sel):
            return "disabled"
        return ("resume", "replay_guide", "to_title")[self.sel]


# ------------------------------------------------------------------ 流程
class Flow:
    """场景状态机；main.py 只负责把 token 落到实际游戏/渲染。"""

    def __init__(self, settings_path: str = SETTINGS_PATH,
                 bpm: float = core.BPM, mode: str | None = None,
                 mode_path: str = MODE_PATH) -> None:
        self.settings_path = settings_path
        mode_cfg = load_mode(mode_path)
        self.mode_cfg = mode_cfg
        self.runner_enabled = bool(mode_cfg["runner_enabled"])
        self.culture_enabled = bool(mode_cfg["culture_enabled"])
        self.hud_style = str(mode_cfg["hud_style"])
        self.guide_v2 = bool(mode_cfg["guide_v2"])
        s = load_settings(settings_path)
        self.bpm = float(bpm)
        if mode is None:
            want_runner = (str(mode_cfg["default_mode"]).lower() != "boss_1819"
                           and self.runner_enabled)
            mode = "runner" if want_runner else "boss"
        self.mode = "boss" if str(mode) == "boss" else "runner"
        self.leader = s["leader"]
        self.offset_ms = int(s["input_offset_ms"])
        self.guide_seen = bool(s["guide_seen"])
        self.scene = "title"
        self.roster = Roster(self.leader, settings_path)
        self.guide: Guide | None = None
        self.guide_return = "roster"
        self.replay_used = False
        self.paused = False
        self.pause: PauseMenu | None = None
        self.toast = ("", 0.0)
        self.guide_report: dict | None = None
        self.last_token: str | None = None
        # 鼠标状态：四场景共用；渲染层只读这些字段做悬停高亮
        self.mouse = (-1, -1)
        self.hover_key: str | None = None
        self.hover_rect: str | None = None
        self.guide_hover = -1
        self.last_click_key: str | None = None

    # -- 输入：返回 token，None 表示场景内部已消化
    def key(self, key: str, now: float = 0.0) -> str | None:
        self.last_token = None
        if self.scene == "title":
            if key == "ENTER":
                # runner_enabled=false 时，Enter 与 B 都落到 Boss 主线；
                # 显式构造 mode="runner" 的测试路径保留原模式。
                if self.runner_enabled or self.mode == "runner":
                    self.mode = "runner"
                else:
                    self.mode = "boss"
                self.scene = "roster"
                return "to_roster"
            if key == "B":
                self.mode = "boss"
                self.scene = "roster"
                return "to_roster"
            if key == "ESC":
                return "quit"
            return None

        if self.scene == "roster":
            if key in ("UP", "DOWN", "LEFT", "RIGHT"):
                dx, dy = {"LEFT": (-1, 0), "RIGHT": (1, 0),
                          "UP": (0, -1), "DOWN": (0, 1)}[key]
                self.roster.move(dx, dy)
                return None
            if key == "ENTER":
                hero = self.roster.confirm()
                if hero is None:
                    return None
                self.leader = hero
                if self.mode == "boss":
                    self._start_guide(now)
                    return "to_guide"
                self.scene = "runner"
                return "to_runner"
            if key == "G":
                self.leader = self.roster.leader
                self.guide_report = {"skipped": True, "steps_done": 0,
                                     "calib_ms": 0, "retries": 0}
                save_settings({"leader": self.leader, "guide_seen": True},
                              self.settings_path)
                self.guide_return = "roster"
                if self.mode == "boss":
                    self.scene = "battle"
                    return "to_battle"
                self.scene = "runner"
                return "to_runner"
            if key == "ESC":
                self.scene = "title"
                return "to_title"
            return None

        if self.scene == "runner":
            if key == "TAB":
                return "display"
            if key == "R":
                return "restart"
            if key == "B":
                self.mode = "boss"
                self.scene = "battle"
                return "to_battle"
            if key == "ESC":
                self.scene = "title"
                return "to_title"
            if key == "ENTER":
                return "restart"
            return None

        if self.scene == "guide":
            return self._guide_key(key, now)

        if self.scene == "battle":
            if not self.paused:
                if key == "ESC":
                    self.paused = True
                    self.pause = PauseMenu(not self.replay_used)
                    return "open_pause"
                return None
            # 暂停菜单
            if key in ("UP", "DOWN"):
                self.pause.move(-1 if key == "UP" else 1)
                return None
            if key == "ESC":
                self.paused = False
                return "resume"
            if key == "ENTER":
                action = self.pause.confirm()
                if action == "resume":
                    self.paused = False
                    return "resume"
                if action == "replay_guide":
                    self.replay_used = True
                    self.paused = False
                    self._start_guide(now, return_scene="battle")
                    return "to_guide"
                if action == "to_title":
                    self.paused = False
                    self.scene = "title"
                    self._persist_guide()
                    return "to_title"
                self.toast = ("本局已重进过一次指南", now + 1.6)
                return None
            return None
        return None

    # -- 指南
    def _start_guide(self, now: float, return_scene: str = "roster") -> None:
        self.guide_return = return_scene
        self.guide = Guide(self.bpm, start_time=float(now) + 0.8,
                           leader=self.leader, path=self.settings_path)
        self.scene = "guide"

    def _guide_key(self, key: str, now: float) -> str | None:
        guide = self.guide
        if guide is None:
            return None
        if key in ("J", "K", "L"):
            guide.press(key, now)
            return None
        if key == "ENTER":
            if guide.finished:
                return self._leave_guide(now, via="enter")
            if guide.step == 5 and not guide.done[5]:
                guide.finish_calibration_early()
                return None
            if guide.next(now):
                return None
            self.toast = ("先完成当前目标", now + 1.6)
            return None
        if key == "G":
            guide.skip()
            return self._leave_guide(now, via="skip")
        if key == "ESC":
            return self._leave_guide(now, via="back")
        if key in ("UP", "DOWN", "LEFT", "RIGHT"):
            return None
        return None

    def _leave_guide(self, now: float, via: str) -> str:
        guide = self.guide
        if guide is None:
            self.scene = "battle" if self.guide_return == "battle" else "roster"
            return "resume" if self.guide_return == "battle" else "to_roster"
        self.guide_report = guide.report()
        self.offset_ms = int(guide.calib_ms) if guide.done[5] else self.offset_ms
        self.guide_seen = True
        self.guide = None
        self._persist_guide()
        if via == "back":
            if self.guide_return == "battle":
                self.scene = "battle"
                return "resume"
            self.scene = "roster"
            return "to_roster"
        self.scene = "battle"
        return "to_battle" if self.guide_return == "roster" else "resume"

    def _persist_guide(self) -> None:
        patch = {"guide_seen": bool(self.guide_seen)}
        if self.guide is not None:
            patch["leader"] = self.leader
        else:
            patch["input_offset_ms"] = int(self.offset_ms)
        save_settings(patch, self.settings_path)

    def apply_report_offset(self) -> None:
        """指南结束后把校准值写进配置。"""
        if self.guide_report is None:
            return
        save_settings({"input_offset_ms": int(self.offset_ms),
                       "guide_seen": True}, self.settings_path)

    # -- 鼠标（四场景共用；键盘路径保持不变）
    def hover(self, x: int, y: int) -> None:
        self.mouse = (int(x), int(y))
        if self.scene == "roster":
            self.roster.set_hover(roster_cell_at(x, y))
        elif self.scene == "guide":
            self.guide_hover = guide_step_at(x, y)
        elif self.scene == "battle" and self.paused and self.pause:
            i = pause_item_at(x, y)
            if i >= 0:
                self.pause.sel = i
        self.hover_key = self.key_at(x, y)
        self.hover_rect = self.hit_target(x, y)

    def key_at(self, x: int, y: int) -> str | None:
        """指南里三个乐器键位牌（鼓面/锣/镲）。"""
        if self.scene != "guide" or self.guide is None:
            return None
        for key, rect in GUIDE_KEY_RECT.items():
            if _in(rect, x, y):
                return key
        return None

    def hit_target(self, x: int, y: int) -> str | None:
        """悬停目标名（用于高亮，保证「看着能点」）。"""
        if self.scene == "title":
            if _in(TITLE_ENTER_RECT, x, y):
                return "enter"
            if self.runner_enabled and _in(TITLE_BOSS_RECT, x, y):
                return "boss"
            return None
        if self.scene == "runner":
            for name, rect in (("restart", RUNNER_RESTART_RECT),
                               ("boss", RUNNER_BOSS_RECT),
                               ("title", RUNNER_TITLE_RECT)):
                if _in(rect, x, y):
                    return name
        if self.scene == "guide" and self.guide is not None:
            if _in(GUIDE_NEXT_RECT, x, y):
                return "next"
            if _in(GUIDE_SKIP_RECT, x, y):
                return "skip"
            if _in(GUIDE_SKIP_ALL_RECT, x, y):
                return "skip_all"
            i = guide_step_at(x, y)
            if i >= 0:
                return f"step{i}"
            key = self.key_at(x, y)
            if key:
                return f"key_{key}"
        if self.scene == "battle" and self.paused and self.pause:
            i = pause_item_at(x, y)
            if i >= 0:
                return f"pause{i}"
        return None

    def click(self, x: int, y: int, now: float = 0.0) -> str | None:
        self.mouse = (int(x), int(y))
        self.last_click_key = None
        if self.scene == "title":
            if _in(TITLE_ENTER_RECT, x, y):
                if self.runner_enabled or self.mode == "runner":
                    self.mode = "runner"
                else:
                    self.mode = "boss"
                self.scene = "roster"
                return "to_roster"
            if self.runner_enabled and _in(TITLE_BOSS_RECT, x, y):
                self.mode = "boss"
                self.scene = "roster"
                return "to_roster"
            return None
        if self.scene == "runner":
            if _in(RUNNER_RESTART_RECT, x, y):
                return "restart"
            if _in(RUNNER_BOSS_RECT, x, y):
                self.mode = "boss"
                self.scene = "battle"
                return "to_battle"
            if _in(RUNNER_TITLE_RECT, x, y):
                self.scene = "title"
                return "to_title"
            return None
        if self.scene == "roster":
            hero = self.roster.click(x, y)
            if hero:
                self.leader = hero
                if self.mode == "boss":
                    self._start_guide(now)
                    return "to_guide"
                self.scene = "runner"
                return "to_runner"
            return None
        if self.scene == "guide":
            return self._guide_click(x, y, now)
        if self.scene == "battle":
            return self._pause_click(x, y, now) if self.paused else None
        return None

    def _guide_click(self, x: int, y: int, now: float) -> str | None:
        guide = self.guide
        if guide is None:
            return None
        if guide.finished:
            return self._leave_guide(now, via="enter")
        # 1) 乐器键位：鼠标点鼓面/锣/镲 = 按 J/K/L
        key = self.key_at(x, y)
        if key:
            self.last_click_key = key
            if guide.step < 5:
                # 教学场景：鼠标点击按「当前这一拍」的拍点计入，
                # 判定窗口本身仍走 core.judge_press，不改任何数值。
                guide.press(key, guide.next_press_time())
                guide.flash_until = now + 0.18   # 下沉反馈用真实点击时刻
            else:
                guide.press(key, now)
            return None
        # 2) 左侧步骤：仅已完成 / 已走过的步骤可切
        i = guide_step_at(x, y)
        if i >= 0:
            guide.goto(i, now)
            return None
        # 3) 跳过整段指南
        if _in(GUIDE_SKIP_ALL_RECT, x, y):
            guide.skip()
            return self._leave_guide(now, via="skip")
        if _in(GUIDE_SKIP_RECT, x, y):
            if guide.step == 5 and not guide.done[5]:
                guide.finish_calibration_early()
                return None
            guide.skip()
            return self._leave_guide(now, via="skip")
        # 4) 主按钮：下一步 / 开始校准 / 完成校准
        if _in(GUIDE_NEXT_RECT, x, y):
            if guide.step == 5:
                if not guide.done[5]:
                    guide.restart_calibration(now)
                    return None
                return self._leave_guide(now, via="enter")
            if guide.next_enabled:
                guide.next(now)
                return None
            self.toast = ("先完成当前目标", now + 1.6)
            self.guide.msg = ("先完成当前目标", now + 1.6)
            return None
        return None

    def _pause_click(self, x: int, y: int, now: float) -> str | None:
        menu = self.pause
        if menu is None:
            return None
        i = pause_item_at(x, y)
        if i < 0:
            return None
        menu.sel = i
        action = menu.confirm()
        if action == "disabled":
            self.toast = ("本局已重进过一次指南", now + 1.6)
            return None
        if action == "resume":
            self.paused = False
            return "resume"
        if action == "replay_guide":
            self.replay_used = True
            self.paused = False
            self._start_guide(now, return_scene="battle")
            return "to_guide"
        self.paused = False
        self.scene = "title"
        self._persist_guide()
        return "to_title"

    def hotzones(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        """当前场景所有可点热区（F2 覆盖与自测共用）。"""
        out: list[tuple[str, tuple[int, int, int, int]]] = []
        if self.scene == "title":
            out.append(("enter", TITLE_ENTER_RECT))
            if self.runner_enabled:
                out.append(("boss", TITLE_BOSS_RECT))
        elif self.scene == "runner":
            out.append(("restart", RUNNER_RESTART_RECT))
            out.append(("boss", RUNNER_BOSS_RECT))
            out.append(("title", RUNNER_TITLE_RECT))
        elif self.scene == "roster":
            for i in range(len(ROSTER_CELLS)):
                out.append((f"cell{i}", roster_cell_rect(i)))
        elif self.scene == "guide" and self.guide is not None:
            for i in range(len(GUIDE_STEPS)):
                out.append((f"step{i}", guide_step_rect(i)))
            for key, rect in GUIDE_KEY_RECT.items():
                out.append((f"key_{key}", rect))
            out.append(("next", GUIDE_NEXT_RECT))
            out.append(("skip", GUIDE_SKIP_RECT))
            out.append(("skip_all", GUIDE_SKIP_ALL_RECT))
        elif self.scene == "battle" and self.paused:
            for i, item in enumerate(PAUSE_ITEMS):
                rx, ry, rw, rh = PAUSE_ITEM_RECT
                out.append((item, (rx, ry + i * 56, rw, rh)))
        return out

    # -- 便捷
    def skip_to_battle(self) -> None:
        self.scene = "battle"
        self.guide_return = "roster"

    def update(self, now: float, dt: float) -> None:
        if self.scene == "guide" and self.guide is not None:
            self.guide.update(now, dt)
        if self.scene == "roster":
            self.roster.tick(dt)
        for src in ("toast",):
            text, until = getattr(self, src)
            if text and now >= until:
                setattr(self, src, ("", 0.0))
        if self.roster.toast[0] and now >= self.roster.toast[1]:
            self.roster.toast = ("", 0.0)


def new_battle(leader: str, bpm: float = core.BPM, difficulty: str = "standard",
               start_time: float = 1.1, seed: int = 20261104) -> core.Game:
    """按领队开局：写 leader、初始阵型推荐、开场台词。"""
    game = core.Game(bpm=bpm, start_time=start_time, seed=seed,
                     difficulty=difficulty)
    apply_leader(game, leader)
    return game


def apply_leader(game: core.Game, leader: str) -> None:
    load = LEADER_LOADOUT.get(leader, LEADER_LOADOUT["wusong"])
    game.leader = leader
    game.formation = load["formation"]
    game.banner = (load["line"], 3.0)
