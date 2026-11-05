"""数据加载与全局常量。"""
from __future__ import annotations

import json
import os
import sys

PIXELS_PER_UNIT = 80            # M1-3：40 → 80，让像素素材（角色约 149px 高）不再被过度下采样
FIXED_DT = 1.0 / 120.0          # 固定步长，保证运动确定性
REFERENCE_FPS = 60              # 帧数据参考帧率
FRAME_MS = 1000.0 / REFERENCE_FPS

SCREEN_W = 1280
SCREEN_H = 720

# 玩法模式开关："PATAPON" 阵列指挥（J/K/L/S 四拍指令，默认）/ "CLASSIC" 单角色跑打（M0 原模式）。
# 回滚对比：设环境变量 DRUMBEAT_MODE=CLASSIC，或把此处默认值改回 "CLASSIC"。
MODE = os.environ.get("DRUMBEAT_MODE", "PATAPON").upper()


def data_dir() -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "drumbeat", "data")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def asset_dir() -> str:
    """像素素材目录：开发时为 drumbeat-m0/assets，打包后在 _MEIPASS/assets。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "assets")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def app_dir() -> str:
    """可写的运行目录：打包后为 exe 所在目录，开发时为工程根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str) -> dict:
    with open(os.path.join(data_dir(), name), "r", encoding="utf-8") as f:
        return json.load(f)


class Data:
    def __init__(self) -> None:
        self.tempo = _load("tempo_layers.json")
        self.beat = _load("beat_tables.json")
        self.frame = _load("frame_data.json")
        self.feel = _load("feel_params.json")
        self.level = _load("level_segment.json")

        self.layers = self.tempo["layers"]
        self.transition = self.tempo["transition"]
        self.bar_beats = int(self.tempo["bar_beats"])
        self.judge_offsets_in_bar = self._judge_offsets()

        # 每小节的事件偏移（所有板式的偏移一致，仅音色不同）
        events = self.beat["tables"]["slow"]["events"]
        self.event_offsets = [float(e["beat"] - 1) + float(e["sub"]) for e in events]
        for tid, table in self.beat["tables"].items():
            offs = [float(e["beat"] - 1) + float(e["sub"]) for e in table["events"]]
            if offs != self.event_offsets:
                raise ValueError(f"板式 {tid} 的事件偏移与其他板式不一致，前瞻调度假设被破坏")
            if len(table["events"]) != len(self.event_offsets):
                raise ValueError(f"板式 {tid} 的事件数量与其他板式不一致")

        self.attacks = {a["id"]: a for a in self.frame["attacks"]}
        self.motion = self.feel["motion"]
        self.assist = self.feel["assist"]
        self.combat = self.feel["combat"]
        self.judgement = self.feel["judgement"]
        self.energy = self.feel["drum_energy"]

    def _judge_offsets(self) -> list[int]:
        strong = [int(b) - 1 for b in self.tempo["strong_beats"]]
        return sorted(strong)

    def layer_index(self, layer_id: str) -> int:
        for i, l in enumerate(self.layers):
            if l["id"] == layer_id:
                return i
        raise KeyError(layer_id)

    def events_for(self, layer_id: str) -> list[dict]:
        return self.beat["tables"][layer_id]["events"]

    # 由跳跃高度与滞空时间反推重力与初速，使手感参数保持可调且自洽
    def jump_physics(self) -> tuple[float, float]:
        h = float(self.motion["jump_height_units"])
        air = float(self.motion["air_time_ms"]) / 1000.0
        gravity = 8.0 * h / (air * air)
        v0 = 4.0 * h / air
        return gravity, v0


DATA = Data()