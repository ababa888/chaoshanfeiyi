"""入口：python prototype-yingge/main.py

操作：J=鼓 / K=锣 / L=镲，四拍成令；R 重开，1/2 切难度，ESC 退出。
键位在 config/controls.json 配置；手柄按钮 0/1/2 同三令，扳机轴接口已预留。
默认自动演示，按任意鼓键立即接管；--headless 用固定步长模拟时钟出真实截图。

自动演示编排：垃圾兵阶段轮换展示长蛇/双龙/猛虎；Boss 阶段按公示谱面逐拍化解，
全 Perfect → 极限破阵；硬直期继续踏点击打，随后进入 Fever 供截图。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

HEADLESS = ("--headless" in sys.argv) or os.environ.get("PROTOTYPE_HEADLESS") == "1"
if HEADLESS:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

import core
import runner
import scenes
from audio import Audio
from input_map import InputMap
from render import (Renderer, VIEW_W, VIEW_H, PRESENT_SCALE,
                    ZOOM_ORDER, W, H)
from scene_ui import SceneUI
from telemetry import GuideRecorder, RunRecorder

ROOT = os.path.dirname(os.path.abspath(__file__))
SHOTS_DIR = os.path.join(ROOT, "shots")
SETTINGS_PATH = os.path.join(ROOT, "config", "settings.json")
KEY_FOR_ACTION = {"attack": "J", "march": "K", "defend": "L"}
KEY_FOR_COMMAND = {
    "attack": "J", "march": "K", "defend": "L",
    "fengshi": "J", "guijia": "L", "shuanglong": "J", "menghu": "K",
}
PATTERN_KEYS = {
    "attack": "JJJJ",
    "march": "KKKK",
    "defend": "LLLL",
    "fengshi": "JKJK",
    "guijia": "LKLK",
    "shuanglong": "JJKK",
    "menghu": "KLKL",
}
# 自动演示的阵法轮换（先让队伍走起来，再展示展开阵型）
DEMO_PLAN = ("march", "attack", "shuanglong", "attack", "menghu",
             "attack", "fengshi", "attack", "guijia", "attack")

# 场景按键 → 状态机 token（鼠标只作可选补充）
SCENE_KEYMAP = {
    pygame.K_UP: "UP", pygame.K_DOWN: "DOWN",
    pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT",
    pygame.K_RETURN: "ENTER", pygame.K_KP_ENTER: "ENTER",
    pygame.K_ESCAPE: "ESC", pygame.K_g: "G", pygame.K_b: "B",
    pygame.K_j: "J", pygame.K_k: "K", pygame.K_l: "L",
    pygame.K_TAB: "TAB",
}


def load_settings() -> dict:
    data = {"bpm": core.BPM, "difficulty": "standard"}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data.update(json.load(f))
    except Exception:
        pass
    if data.get("difficulty") not in core.DIFFICULTIES:
        data["difficulty"] = "standard"
    return data


class DemoDriver:
    """按节拍驱动的自动演示；被玩家按键会关闭。"""

    def __init__(self) -> None:
        self.active = True
        self.beat = 0
        self._cmd = "march"
        self._boss_setup = 0

    def reset(self, game: core.Game) -> None:
        self.active = True
        self.beat = 0
        self._cmd = "march"
        self._boss_setup = 0

    def _plan_trash(self, game: core.Game, cycle: int) -> str:
        if game.squad.hp < 52.0 and cycle % 4 == 2:
            return "defend"
        return DEMO_PLAN[cycle % len(DEMO_PLAN)]

    def _counter_formation(self, game: core.Game) -> str | None:
        for form in ("guijia", "shuanglong", "menghu", "changshe", "fengshi"):
            if game.counter_mult(form, game.intent_key or "") > 1.0:
                return form
        return None

    def _plan_boss(self, game: core.Game, cycle: int) -> str:
        # 演示开场两拍：先立阵、再反打，保证画面里出现「克」字印
        if self._boss_setup == 0:
            self._boss_setup = 1
            return "guijia"
        if self._boss_setup == 1:
            self._boss_setup = 2
            if game.counter_state() == "counter":
                return "attack"
            form = self._counter_formation(game)
            return form or "attack"
        if game.counter_state() != "counter":
            form = self._counter_formation(game)
            if form and form != game.formation:
                return form
        return "attack"

    def update(self, now: float, game: core.Game) -> list[str]:
        if not self.active or game.status != "playing":
            return []
        pressed: list[str] = []
        predicted = game.clock.beat_at(now, game.fever_active)
        guard = 0
        while predicted >= self.beat and guard < 4:
            guard += 1
            n = self.beat
            slot = n % core.CYCLE_BEATS
            if slot == 0:
                if game.boss_active:
                    self._cmd = self._plan_boss(game, n // core.CYCLE_BEATS)
                else:
                    self._cmd = self._plan_trash(game, n // core.CYCLE_BEATS)
            if slot < core.INPUT_BEATS:
                key = PATTERN_KEYS[self._cmd][slot]
            elif game.boss_active and game.attempt and game.intent:
                key = game.intent["keys"][slot - core.INPUT_BEATS]
            else:
                # 动作拍踏点：驱动自动行军 / 硬直期输出
                key = PATTERN_KEYS[self._cmd][0]
            game.push_input(key, now)
            pressed.append(key)
            self.beat += 1
        return pressed


class ShotDirector:
    """保存真实运行帧：行军 / 公示 / 硬直 / Fever / 新阶段 / 克制特效。"""

    NAMES = ("01_march_array", "02_boss_telegraph",
             "03_break_stagger", "04_fever_glow",
             "05_phase_telegraph", "06_counter_stamp",
             "07_slope_charge", "08_slope_formation",
             "09_hero_peak", "10_hero_lineup",
             "11_slope_tilt_charge", "12_boss_platform_compare",
             "13_phase1_reveal6", "14_tutorial_hint",
             "15_wide_parallax", "16_near_occlusion",
             "17_parallax_layers", "18_hud_1080p")

    def __init__(self, out_dir: str, enabled: bool = True,
                 renderer: Renderer | None = None) -> None:
        self.out_dir = out_dir
        self.enabled = enabled
        self.renderer = renderer
        self.done: set[str] = set()
        self.pending: list[tuple[str, float]] = []
        self._fever_at = -1.0
        self._fever_armed = False
        self._platform_on_crop: pygame.Surface | None = None
        if enabled:
            os.makedirs(out_dir, exist_ok=True)

    def reset(self) -> None:
        self.done.clear()
        self.pending.clear()
        self._fever_at = -1.0
        self._fever_armed = False
        self._platform_on_crop = None
        self._last_now = 0.0

    def after_render(self, screen: pygame.Surface, game: core.Game,
                     now: float, events: list[tuple]) -> None:
        if not self.enabled:
            return
        self._last_now = now
        # Boss 还在台上时先留一张对比用裁切帧
        if game.boss_on_platform and self._platform_on_crop is None:
            for ev in events:
                if ev[0] == "boss_read":
                    self._platform_on_crop = self._crop_platform(screen, game)
        self._collect(game, now, events)
        remain = []
        for name, at in self.pending:
            if now >= at:
                self._save(screen, name, game)
            else:
                remain.append((name, at))
        self.pending = remain

    def _crop(self, screen: pygame.Surface, cx: float, cy: float,
              w: int = 640, h: int = 360) -> pygame.Surface:
        sw, sh = screen.get_size()
        x = int(max(0, min(sw - w, cx - w / 2)))
        y = int(max(0, min(sh - h, cy - h / 2)))
        return screen.subsurface((x, y, w, h)).copy()

    def _crop_platform(self, screen: pygame.Surface,
                       game: core.Game) -> pygame.Surface:
        boss = game.boss
        zoom = self.renderer.zoom if self.renderer else 1.0
        px = (core.SCREEN_BASE_X
              + (boss.platform_x - game.cam_x) * core.PX_PER_UNIT * zoom)
        px *= PRESENT_SCALE
        py = core.ground_screen_y(px / PRESENT_SCALE) * PRESENT_SCALE
        return self._crop(screen, px - 40, py - 110)

    def _save(self, screen: pygame.Surface, name: str,
              game: core.Game | None = None) -> None:
        path = os.path.join(self.out_dir, name + ".png")
        img = screen
        if name == "09_hero_peak" and game is not None:
            # 峰值特写：从真实运行帧裁 640×360 再整数 2× 放大到 1280×720
            fx, fy = game.peak_focus
            img = pygame.transform.scale(
                self._crop(screen, fx * PRESENT_SCALE, fy * PRESENT_SCALE),
                (1280, 720))
        elif name == "11_slope_tilt_charge" and game is not None:
            # 冲锋倾斜特写：围绕队伍裁 640×360 后 2× 放大
            fx, fy = game.squad_focus
            img = pygame.transform.scale(
                self._crop(screen, fx * PRESENT_SCALE,
                           (fy - 70) * PRESENT_SCALE), (1280, 720))
        elif name == "12_boss_platform_compare" and game is not None:
            off = self._crop_platform(screen, game)
            on = self._platform_on_crop or off
            img = pygame.Surface((640, 748))
            img.fill((16, 10, 12))
            img.blit(on, (0, 34))
            img.blit(off, (0, 406))
            font = pygame.font.Font(None, 24)
            img.blit(font.render("Boss 台上：近战 ×1.35 / 仰攻 ×0.85",
                                 True, (255, 214, 140)), (12, 8))
            img.blit(font.render("破阵击落台下：同层 · 长硬直 3.4s",
                                 True, (255, 176, 104)), (12, 380))
            pygame.draw.line(img, (190, 140, 88), (0, 371), (640, 371), 2)
        elif name == "17_parallax_layers" and game is not None \
                and self.renderer is not None:
            snaps = self.renderer.layer_breakdown(game, self._last_now)
            # 2×2 拼图：每格 960×540 逻辑像素，画布即 1920×1080 输出尺寸
            img = pygame.Surface((VIEW_W * PRESENT_SCALE,
                                  VIEW_H * PRESENT_SCALE))
            img.fill((10, 8, 12))
            labels = ("FAR  0.24x", "MID  0.70x",
                      "NEAR  1.45x / above units", "COMPOSITE")
            font = pygame.font.Font(None, 26)
            for i, (key, snap) in enumerate(snaps[:4]):
                col, row = i % 2, i // 2
                x, y = col * VIEW_W, row * VIEW_H
                panel = pygame.Surface((VIEW_W, VIEW_H))
                panel.fill((92, 90, 104))
                panel.blit(snap, (0, 0))
                img.blit(panel, (x, y))
                img.blit(font.render(labels[i], True, (255, 214, 150),
                                     (12, 8, 12)), (x + 14, y + 10))
                pygame.draw.rect(img, (90, 66, 52),
                                 (x, y, VIEW_W, VIEW_H), 2)
        pygame.image.save(img, path)
        self.done.add(name)
        print(f"[shot] {path}")
        if game is not None and name == "10_hero_lineup":
            game.show_lineup = False

    def _collect(self, game: core.Game, now: float,
                 events: list[tuple]) -> None:
        # 01 自动行军阵列：已进入双龙/猛虎阵并走起来
        if ("01_march_array" not in self.done
                and game.formation in ("shuanglong", "menghu")
                and game.squad.walking
                and game.squad.march_streak >= 2
                and game.beat_in_cycle >= 1.0):
            self._schedule("01_march_array", now)
        # 07 下坡冲锋全景：垃圾兵阶段高速行军，前方有敌阵可冲锋
        if ("07_slope_charge" not in self.done
                and game.phase == "trash"
                and game.formation in ("shuanglong", "menghu")
                and game.squad.walking
                and game.squad.march_streak >= 3
                and game.squad.x >= 2.0
                and any(not e.dead for e in game.enemies)):
            self._schedule("07_slope_charge", now + 0.02)
        # 11 沿坡前倾特写：同一次冲锋的 2× 裁切，能看清身体压着坡
        if ("11_slope_tilt_charge" not in self.done
                and game.phase == "trash"
                and game.formation == "menghu"
                and game.squad.walking
                and game.squad.march_streak >= 3
                and game.squad.x >= 2.2
                and any(not e.dead for e in game.enemies)):
            self._schedule("11_slope_tilt_charge", now + 0.05)
        # 08 坡面阵型展开：猛虎一字横排最宽，等插值展开后再拍
        if ("08_slope_formation" not in self.done
                and game.formation == "menghu"
                and game.squad.walking
                and game.squad.x >= 2.6
                and game.beat_in_cycle >= 1.0):
            self._schedule("08_slope_formation", now + 0.42)
        # 10 三好汉定妆照 lineup（叠加层真实渲染帧）
        if ("10_hero_lineup" not in self.done
                and not any(p[0] == "10_hero_lineup" for p in self.pending)
                and now >= 2.0):
            game.show_lineup = True
            self._schedule("10_hero_lineup", now + 0.12)
        # 15/17 拉远全景 + 三层拆解：猛虎横排、有敌人、三层都可见
        wide_ready = (game.phase == "trash"
                      and game.formation == "menghu"
                      and game.squad.walking
                      and game.squad.march_streak >= 2
                      and game.squad.x >= 1.5
                      and any(not e.dead for e in game.enemies))
        if wide_ready and "15_wide_parallax" not in self.done:
            self._schedule("15_wide_parallax", now + 0.02)
        if wide_ready and "17_parallax_layers" not in self.done \
                and not any(p[0] == "17_parallax_layers" for p in self.pending):
            self._schedule("17_parallax_layers", now + 0.55)
        # 16 近景遮挡：等渲染器判定前景真的压住我方
        if ("16_near_occlusion" not in self.done
                and self.renderer is not None
                and self.renderer.near_occludes
                and game.squad.walking):
            self._schedule("16_near_occlusion", now + 0.02)
        for ev in events:
            # 18 1080p HUD 可读性：Boss 公示时的读招面板 + 四拍条
            if (ev[0] == "boss_read"
                    and "18_hud_1080p" not in self.done):
                self._schedule("18_hud_1080p", now + 0.04)
            # 公示帧尽量在非 Fever 状态拍，画面更干净；若一直 Fever 则等下一轮公示
            if (ev[0] == "boss_read" and not game.fever_active
                    and "02_boss_telegraph" not in self.done):
                self._schedule("02_boss_telegraph", now + 0.02)
            if ev[0] == "boss_perfect" and "03_break_stagger" not in self.done:
                self._schedule("03_break_stagger", now + 0.10)
            if ev[0] == "boss_perfect":
                self._fever_at = now
                self._fever_armed = True
            if ev[0] == "boss_phase" and ev[1] >= 2 \
                    and "05_phase_telegraph" not in self.done:
                self._schedule("05_phase_telegraph", now + 0.12)
            if ev[0] == "counter_hit" and "06_counter_stamp" not in self.done:
                self._schedule("06_counter_stamp", now + 0.04)
            if (ev[0] == "hero_peak" and "09_hero_peak" not in self.done
                    and game.formation == "menghu"):
                # 猛虎一字横排间距最大，峰值特写不会被队友糊住
                self._schedule("09_hero_peak", now + 0.06)
            # 13 第一阶段 6 拍公示：落点高亮与读招面板同时拉长
            if (ev[0] == "boss_read" and "13_phase1_reveal6" not in self.done
                    and ev[1] and game.boss_phase == 1
                    and game.intent_reveal_beats >= 6):
                self._schedule("13_phase1_reveal6", now + 0.28)
            # 14 新手一次性教学提示
            if (ev[0] == "tutorial_hint"
                    and "14_tutorial_hint" not in self.done):
                self._schedule("14_tutorial_hint", now + 0.10)
            # 12 破阵击落台下的对比帧（台上裁切已在 after_render 存好）
            if (ev[0] == "boss_knockdown"
                    and "12_boss_platform_compare" not in self.done):
                self._schedule("12_boss_platform_compare", now + 0.55)
        # 等硬直面板退场后再拍 Fever，避免 03/04 两张看起来一样
        if (self._fever_armed and "04_fever_glow" not in self.done
                and game.fever_active
                and now - self._fever_at >= core.STAGGER_SEC + 0.4):
            self._schedule("04_fever_glow", now)

    def _schedule(self, name: str, at: float) -> None:
        if name in self.done or any(p[0] == name for p in self.pending):
            return
        self.pending.append((name, at))


def parse_args():
    p = argparse.ArgumentParser(description="英歌 × Patapon 八拍原型（第三轮）")
    p.add_argument("--headless", action="store_true", help="无窗口渲染（仍保存截图）")
    p.add_argument("--no-shots", action="store_true", help="不自动保存截图")
    p.add_argument("--auto-exit", type=float, default=0.0,
                   help="运行 N 秒后自动退出（0 = 一直运行）")
    p.add_argument("--shots-dir", default=SHOTS_DIR)
    p.add_argument("--difficulty", choices=("drill", "standard"), default=None)
    p.add_argument("--bpm", type=float, default=None)
    p.add_argument("--no-telemetry", action="store_true",
                   help="不写 playtest/telemetry.csv")
    p.add_argument("--skip-menu", action="store_true",
                   help="跳过标题/选将/指南，直接进战斗（调试与旧脚本）")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    difficulty = args.difficulty or settings["difficulty"]
    bpm = args.bpm or float(settings["bpm"])

    pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()
    pygame.display.set_caption("踏鼓 · 英歌八拍原型 ｜ 960×540 → 1920×1080")
    screen = pygame.display.set_mode(
        (VIEW_W * PRESENT_SCALE, VIEW_H * PRESENT_SCALE))
    # 输出帧 = 1920×1080：世界层在这里按整数 2× 合成，HUD 直接按输出像素排版。
    view = pygame.Surface((VIEW_W * PRESENT_SCALE, VIEW_H * PRESENT_SCALE))
    audio = Audio()
    audio.init()
    input_map = InputMap()
    renderer = Renderer(input_map)
    renderer.parallax_debug = int(settings.get("parallax_debug", 0))
    renderer.layer_variant_seed = int(settings.get(
        "layer_variant_seed", renderer.layer_variant_seed))
    game = scenes.new_battle(
        scenes.load_settings(SETTINGS_PATH)["leader"], bpm, difficulty,
        start_time=1.1, seed=20261104)
    visual_tilt = bool(settings.get("visual_tilt", True))
    game.visual_tilt = visual_tilt
    flow = scenes.Flow(SETTINGS_PATH, bpm)
    flow.leader = getattr(game, "leader", flow.leader)
    scene_ui = SceneUI(renderer, screen)
    demo = DemoDriver()
    shots = ShotDirector(args.shots_dir, enabled=not args.no_shots,
                         renderer=renderer)
    recorder = RunRecorder(enabled=not args.no_telemetry,
                           hand="demo" if demo.active else "human",
                           seed=game.seed, difficulty=difficulty)
    guide_rec = GuideRecorder(enabled=not args.no_telemetry)
    sim_now = [0.0]
    battle_live = [False]
    frozen_screen: pygame.Surface | None = None
    runner_sess = [None]
    runner_start = [0.0]
    runner_pending: list[tuple[float, str]] = []

    def start_runner() -> None:
        cfg = runner.load_config()
        disp = str(scenes.load_settings(SETTINGS_PATH).get("runner_display", ""))
        if disp in cfg.display_levels:
            cfg.display_level = disp
        runner_sess[0] = runner.RunnerSession(
            cfg, leader=flow.leader, seed=20261105,
            culture=cfg.culture.enabled)
        runner_pending.clear()
        runner_start[0] = now_ref[0] + 0.35

    def advance_runner(now: float) -> None:
        sess = runner_sess[0]
        if sess is None or sess.finished:
            return
        guard = 0
        while not sess.finished and guard < 8:
            target = runner_start[0] + sess.beat * sess.beat_s
            if now < target:
                break
            key = None
            dt = 0.0
            if runner_pending:
                best = min(runner_pending, key=lambda p: abs(p[0] - target))
                if abs(best[0] - target) <= 0.20:
                    key, dt = best[1], (best[0] - target) * 1000.0
                runner_pending.remove(best)
            sess.step(key, dt)
            guard += 1

    def flush_guide() -> None:
        report = flow.guide_report
        if report is None:
            return
        flow.guide_report = None
        guide_rec.write(flow.leader, report)

    def start_battle(opening: bool = True) -> None:
        nonlocal game, recorder, frozen_screen
        sim_now[0] = 0.0
        game = scenes.new_battle(
            flow.leader, bpm, difficulty, start_time=1.1, seed=20261104)
        game.visual_tilt = visual_tilt
        demo.reset(game)
        recorder = RunRecorder(enabled=not args.no_telemetry,
                               hand="demo", seed=game.seed,
                               difficulty=game.difficulty)
        renderer.trail.clear()
        renderer.dust.clear()
        renderer.hit_effect_reset()
        shots.reset()
        battle_live[0] = True
        frozen_screen = None
        prev_beat_ref[0] = None
        prev_fever_ref[0] = False

    def restart() -> None:
        nonlocal recorder
        if not battle_live[0]:
            return
        recorder.hand = "demo" if demo.active else "human"
        recorder.finish(game, "restart")
        game.reset(sim_now[0])
        game.visual_tilt = visual_tilt
        scenes.apply_leader(game, flow.leader)
        demo.reset(game)
        recorder = RunRecorder(enabled=not args.no_telemetry,
                               hand="demo", seed=game.seed,
                               difficulty=game.difficulty)
        renderer.trail.clear()
        renderer.dust.clear()
        renderer.hit_effect_reset()
        shots.reset()
        prev_beat_ref[0] = None
        prev_fever_ref[0] = False

    now_ref = [0.0]
    prev_beat_ref = [None]
    prev_fever_ref = [False]
    epoch = time.perf_counter()
    clock = pygame.time.Clock()
    frame = 0
    running = True

    if args.skip_menu:
        flow.skip_to_battle()
        start_battle()

    while running:
        events = pygame.event.get()
        if args.headless:
            frame += 1
            dt = 1.0 / 60.0
            now = frame / 60.0
        else:
            raw = clock.tick(60)
            dt = min(raw / 1000.0, 0.05)
            now = time.perf_counter() - epoch
        now_ref[0] = now

        # ------------------------------------------------------ 战前场景
        if flow.scene != "battle" or flow.paused:
            for ev in events:
                token = None
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_F2:
                        scene_ui.show_hotzones = not scene_ui.show_hotzones
                        continue
                    if ev.key == pygame.K_F3:
                        scene_ui.debug_overlay = not scene_ui.debug_overlay
                        continue
                    key_name = {pygame.K_j: "J", pygame.K_k: "K",
                                pygame.K_l: "L"}.get(ev.key)
                    if flow.scene == "runner" and key_name:
                        runner_pending.append((now, key_name))
                        audio.key(key_name)
                        continue
                    token = flow.key(SCENE_KEYMAP.get(ev.key, ""), now)
                    if (flow.scene == "guide" and key_name):
                        audio.key(key_name)
                elif ev.type == pygame.MOUSEMOTION:
                    lx, ly = scene_ui.logical_pos(ev.pos)
                    flow.hover(lx, ly)
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    lx, ly = scene_ui.logical_pos(ev.pos)
                    token = flow.click(lx, ly, now)
                    if flow.last_click_key:
                        audio.key(flow.last_click_key)
                if token == "quit":
                    running = False
                elif token == "to_battle":
                    flush_guide()
                    if flow.guide_return != "battle" or not battle_live[0]:
                        start_battle()
                elif token == "to_title":
                    flush_guide()
                    if battle_live[0]:
                        recorder.hand = "demo" if demo.active else "human"
                        recorder.finish(game, "to_title")
                        battle_live[0] = False
                    runner_sess[0] = None
                elif token == "to_runner":
                    start_runner()
                elif token == "restart":
                    if runner_sess[0] is not None:
                        runner_sess[0].restart()
                        runner_pending.clear()
                        runner_start[0] = now + 0.35
                elif token == "display":
                    if runner_sess[0] is not None:
                        level = runner_sess[0].cycle_display()
                        scenes.save_settings({"runner_display": level},
                                             SETTINGS_PATH)
                elif token == "open_pause":
                    frozen_screen = screen.copy()
            flow.update(now, dt)
            if flow.scene == "title":
                scene_ui.draw_title(screen, flow, now)
            elif flow.scene == "roster":
                scene_ui.draw_roster(screen, flow, now)
            elif flow.scene == "guide":
                scene_ui.draw_guide(screen, flow, now)
            elif flow.scene == "runner":
                if runner_sess[0] is None:
                    start_runner()
                advance_runner(now)
                scene_ui.draw_runner(screen, flow, runner_sess[0], now)
            elif flow.paused:
                if frozen_screen is not None:
                    screen.blit(frozen_screen, (0, 0))
                scene_ui.draw_pause(screen, flow, now)
            scene_ui.overlay(screen, flow)
            pygame.display.flip()
            if args.auto_exit > 0 and now >= args.auto_exit:
                running = False
            continue

        # ------------------------------------------------------ 战斗
        sim_now[0] += dt
        bn = sim_now[0]
        offset_sec = float(flow.offset_ms) / 1000.0

        def push_key(key: str) -> None:
            t = max(game.clock.start_time, bn - offset_sec)
            game.push_input(key, t)

        pressed_now = []
        for ev in events:
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    token = flow.key("ESC", bn)
                    if token == "open_pause":
                        frozen_screen = screen.copy()
                elif ev.key == pygame.K_b:
                    # B 键切回急行：不推翻 Boss 战，只做模式切换
                    flow.mode = "runner"
                    flow.scene = "runner"
                    if battle_live[0]:
                        recorder.hand = "demo" if demo.active else "human"
                        recorder.finish(game, "to_runner")
                        battle_live[0] = False
                    start_runner()
                elif ev.key == pygame.K_r:
                    restart()
                elif ev.key == pygame.K_1:
                    game.difficulty = "drill"
                    restart()
                elif ev.key == pygame.K_2:
                    game.difficulty = "standard"
                    restart()
                elif ev.key == pygame.K_SPACE:
                    demo.active = not demo.active
                    if demo.active:
                        demo.beat = int(math.floor(game.beat_pos)) + 1
                elif ev.key == pygame.K_m:
                    game.show_matrix = not game.show_matrix
                elif ev.key == pygame.K_p:
                    if ev.mod & pygame.KMOD_SHIFT:
                        renderer.debug_persp = not renderer.debug_persp
                        game.banner = (
                            "透视调试：" + ("开" if renderer.debug_persp
                                          else "关"), 1.8)
                    else:
                        game.show_lineup = not game.show_lineup
                elif ev.key == pygame.K_z:
                    name = renderer.cycle_zoom()
                    game.banner = (
                        f"焦距 {name} f={renderer.focal_target:.1f}"
                        f" ｜ 可视 {renderer.visible_units():.1f} 单位", 1.8)
                elif ev.key == pygame.K_v:
                    renderer.parallax_debug = (renderer.parallax_debug + 1) % 4
                    label = {0: "三层全开", 1: "关闭远景", 2: "关闭中景",
                             3: "关闭近景"}[renderer.parallax_debug]
                    game.banner = (f"景深调试：{label}", 1.8)
                else:
                    action = input_map.action_from_key(ev.key)
                    if action is not None:
                        demo.active = False
                        key = KEY_FOR_ACTION[action]
                        # 事件时间戳入队；本帧内多键按事件顺序消费
                        push_key(key)
                        pressed_now.append(key)
            elif ev.type == pygame.JOYBUTTONDOWN:
                action = input_map.action_from_button(ev.button)
                if action in KEY_FOR_ACTION:
                    demo.active = False
                    key = KEY_FOR_ACTION[action]
                    push_key(key)
                    pressed_now.append(key)
                elif action == "restart":
                    restart()

        for action in input_map.poll_axes():
            key = KEY_FOR_ACTION.get(action)
            if key:
                demo.active = False
                push_key(key)
                pressed_now.append(key)

        for key in demo.update(bn, game):
            pressed_now.append(key)

        game.update(bn, dt)

        for key in pressed_now:
            audio.key(key)

        bi = game.beat_index
        if game.clock.started and bi != prev_beat_ref[0] and bi >= 0:
            audio.beat(game.strong_beat)
        prev_beat_ref[0] = bi
        if game.fever_active and not prev_fever_ref[0]:
            audio.play("fever")
        elif not game.fever_active and prev_fever_ref[0]:
            audio.play("fail")
        prev_fever_ref[0] = game.fever_active

        evs = game.drain_events()
        for ev in evs:
            kind = ev[0]
            if kind == "success":
                result = ev[1]
                audio.grade(result.grade)
                audio.play("role" if result.command == "attack" else "success")
            elif kind == "fail":
                audio.fail()
            elif kind == "squad_hit" or kind == "boss_hit":
                audio.play("hit")
            elif kind in ("enemy_dead", "boss_dead"):
                audio.play("fever")
            elif kind == "fever_start":
                audio.play("fever")
            elif kind == "boss_read":
                variant = ""
                if len(ev) > 2:
                    variant = getattr(ev[2], "variant", "")
                audio.play("read_long" if variant == "long" else "read")
            elif kind in ("boss_read_ok", "boss_perfect"):
                audio.play("read")
            elif kind == "counter_hit":
                audio.play("counter")
            elif kind == "hero_peak":
                audio.play("counter")
            elif kind == "countered_hit":
                audio.play("fail")
            elif kind == "formation":
                audio.play("success")
            elif kind in ("defeated", "cleared"):
                audio.play("fever")

        renderer.draw(view, game, bn, dt)
        screen.blit(view, (0, 0))
        shots.after_render(screen, game, bn, evs)
        pygame.display.flip()

        if args.auto_exit > 0 and now >= args.auto_exit:
            running = False

    if battle_live[0]:
        recorder.hand = "demo" if demo.active else "human"
        recorder.finish(game, "exit")
    if args.headless:
        print(f"[state] status={game.status} phase={game.phase} "
              f"beat={game.beat_pos:.1f} squad_hp={game.squad.hp:.0f}/"
              f"{game.squad.max_hp:.0f} boss_hp="
              f"{(game.boss.hp if game.boss else 0):.0f} combo={game.combo} "
              f"focal={renderer.focal:.2f}({renderer.zoom_name()}) "
              f"visible={renderer.visible_units():.1f}")
        print(f"[stats] {game.stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
