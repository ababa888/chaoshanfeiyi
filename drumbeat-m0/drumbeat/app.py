"""主循环与运行时装配。"""
from __future__ import annotations

import csv
import os
import sys
import time

import pygame

from .audio import AudioEngine, NullAudioEngine
from .combat import PlayerCombat
from .config import DATA, FIXED_DT, MODE, SCREEN_H, SCREEN_W, app_dir
from .energy import DrumEnergy
from .hud import GOLD, GREY, RED, WHITE, Renderer, SquadView
from .inputs import InputManager
from .judgement import Judgement
from .level import Level
from .motion import PlayerBody
from .synth import Bank
from .tempo import MusicDirector


class FeelParam:
    def __init__(self, label: str, getter, setter, step: float, fmt: str = "{:.2f}"):
        self.label = label
        self.getter = getter
        self.setter = setter
        self.step = step
        self.fmt = fmt

    def value_str(self) -> str:
        v = self.getter()
        if isinstance(v, str):
            return v
        return self.fmt.format(v)


class Game:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption(
            f"踏鼓 · Project Drumbeat — {'Patapon 阵列指挥' if MODE == 'PATAPON' else 'M0 原型'}")
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        _disable_ime()
        self.clock = pygame.time.Clock()

        self.bank = Bank()
        self.audio = AudioEngine()
        if not self.audio.start():
            print("[warn] 音频设备不可用，降级为 NullAudioEngine（判定仍可跑通，但无声音）")
            self.audio.stop()
            self.audio = NullAudioEngine()
            self.audio.start()

        self.fps = 0.0
        if MODE == "PATAPON":
            # 阵列指挥模式：J/K/L/S 四拍指令（squad.PataponGame 编排 + hud.SquadView 渲染）
            from .squad import PataponGame
            self.squad_view = SquadView()
            self.patapon = PataponGame(self.audio, self.bank, self.squad_view)
        else:
            # ---------------- CLASSIC 单角色跑打（M0 原模式，完整保留供回滚对比） ----------------
            self.renderer = Renderer()
            self.inputs = InputManager()
            self.level = Level()
            self.music = MusicDirector(self.audio, self.bank)
            self.judgement = Judgement(self.music)
            self.energy = DrumEnergy()
            self.player = PlayerBody(self.level)
            self.combat = PlayerCombat(self.judgement, self.energy)
            self.judgement._flash = (0.0, "perfect")

            self.elapsed = 0.0
            self.hitstop_t = 0.0
            self.acc = 0.0
            self.state = "playing"      # playing / dead / cleared
            self.death_t = 0.0
            self.paused = False
            self.show_debug = False
            self.show_feel = False
            self.feel_sel = 0
            self.show_help = True
            self.poll_hz = 0.0
            self._poll_count = 0
            self._poll_window_t = time.perf_counter()
            self.message = ""
            self.message_t = 0.0
            self.runs = 0
            self.finisher_count = 0

            self.feel_params = self._build_feel_params()
            self.log_path = os.path.join(app_dir(), "playtest_log.csv")

    # ------------------------------------------------------------------ 手感参数
    def _build_feel_params(self) -> list[FeelParam]:
        m = DATA.motion
        a = DATA.assist
        j = DATA.judgement
        c = DATA.combat

        def rejump() -> None:
            self.player.gravity, self.player.jump_v = DATA.jump_physics()

        def sync_judge() -> None:
            self.judgement.perfect_ms = float(j["perfect_ms"])
            self.judgement.good_ms = float(j["good_ms"])

        def num(d: dict, key: str, step: float, after=None, floor: float = 0.0):
            def f(delta: float) -> None:
                d[key] = max(floor, d[key] + delta * step)
                if after is not None:
                    after()
            return f

        def set_anchor(delta: float) -> None:
            opts = j["anchor_options"]
            i = opts.index(j["anchor"]) if j["anchor"] in opts else 0
            i = (i + (1 if delta > 0 else -1)) % len(opts)
            j["anchor"] = opts[i]
            self.judgement.set_anchor(opts[i])

        return [
            FeelParam("最大移速 (单位/秒)", lambda: m["max_speed"], num(m, "max_speed", 0.5, rejump), 1),
            FeelParam("加速度 (单位/秒²)", lambda: m["acceleration_per_s2"], num(m, "acceleration_per_s2", 2.0), 1),
            FeelParam("摩擦力 (单位/秒²)", lambda: m["friction_per_s2"], num(m, "friction_per_s2", 2.0), 1),
            FeelParam("跳跃高度 (单位)", lambda: m["jump_height_units"], num(m, "jump_height_units", 0.2, rejump, floor=0.5), 1),
            FeelParam("滞空时间 (ms)", lambda: m["air_time_ms"], num(m, "air_time_ms", 20.0, rejump, floor=100.0), 1, "{:.0f}"),
            FeelParam("抢步速度 (单位/秒)", lambda: m["dash_speed"], num(m, "dash_speed", 1.0), 1),
            FeelParam("抢步无敌 (ms)", lambda: m["dash_invincible_ms"], num(m, "dash_invincible_ms", 20.0), 1, "{:.0f}"),
            FeelParam("起跳缓冲 (ms)", lambda: a["jump_buffer_ms"], num(a, "jump_buffer_ms", 20.0), 1, "{:.0f}"),
            FeelParam("土狼时间 (ms)", lambda: a["coyote_ms"], num(a, "coyote_ms", 20.0), 1, "{:.0f}"),
            FeelParam("命中停顿上限 (ms)", lambda: a["hitstop_max_ms"], num(a, "hitstop_max_ms", 10.0), 1, "{:.0f}"),
            FeelParam("对击窗口 (ms)", lambda: c["parry_window_ms"], num(c, "parry_window_ms", 10.0), 1, "{:.0f}"),
            FeelParam("完美合拍窗口 (ms)", lambda: j["perfect_ms"], num(j, "perfect_ms", 5.0, sync_judge), 1, "{:.0f}"),
            FeelParam("合拍窗口 (ms)", lambda: j["good_ms"], num(j, "good_ms", 5.0, sync_judge), 1, "{:.0f}"),
            FeelParam("判定锚点", lambda: j["anchor"], set_anchor, 1),
            FeelParam("用户校准偏移 (ms)", lambda: j["user_offset_ms"], self._set_offset, 5, "{:.0f}"),
        ]

    def _set_offset(self, delta: float) -> None:
        v = max(-150.0, min(150.0, float(DATA.judgement["user_offset_ms"]) + delta * 5))
        DATA.judgement["user_offset_ms"] = v
        self.judgement.set_offset_ms(v)

    def _sync_params_from_data(self) -> None:
        self.judgement.perfect_ms = float(DATA.judgement["perfect_ms"])
        self.judgement.good_ms = float(DATA.judgement["good_ms"])
        self.judgement.anchor = DATA.judgement["anchor"]
        self.player.gravity, self.player.jump_v = DATA.jump_physics()

    # ------------------------------------------------------------------ 重置
    def restart(self, full: bool = False) -> None:
        if full:
            self.level.reset()
            self.music.reset()
            self.judgement.reset_run()
            self.energy.reset()
            self.runs += 1
        self.player.respawn(self.level.checkpoint_x if full is False else self.level.start_x)
        self.combat.attack_id = None
        self.elapsed = 0.0
        self.state = "playing"
        self.death_t = 0.0
        self.message = "重新出发" if full else "从检查点重开"
        self.message_t = 1.2

    # ------------------------------------------------------------------ 主循环
    def run(self) -> None:
        # 打包后自动化验证用：设置 DRUMBEAT_SMOKE_FRAMES 可跑固定帧数后自动退出并导出日志
        smoke_frames = int(os.environ.get("DRUMBEAT_SMOKE_FRAMES", "0") or "0")
        frame_i = 0
        running = True
        while running:
            real_dt = self.clock.tick(240) / 1000.0
            self.fps = self.clock.get_fps()

            if MODE == "PATAPON":
                running = self._patapon_frame(real_dt)
            else:
                # ---------------- CLASSIC 单角色跑打（原循环逐行保留） ----------------
                t = self.audio.audio_time()

                self.inputs.set_frame_time(t)
                frame = self.inputs.poll(t)
                self._poll_count += 1
                now_perf = time.perf_counter()
                if now_perf - self._poll_window_t >= 0.5:
                    self.poll_hz = self._poll_count / (now_perf - self._poll_window_t)
                    self._poll_count = 0
                    self._poll_window_t = now_perf

                if self._global_keys(frame):
                    running = False
                    break

                if not self.paused:
                    self._handle_input(frame, t)
                    if self.state == "playing":
                        self.acc += real_dt
                        steps = 0
                        while self.acc >= FIXED_DT and steps < 8:
                            self._step(FIXED_DT, t)
                            self.acc -= FIXED_DT
                            steps += 1
                        if steps >= 8:
                            self.acc = 0.0
                    elif self.state == "dead":
                        self.death_t += real_dt
                        if self.death_t >= 1.5:
                            self.restart(full=True)

                self._update_flash(real_dt)
                self._render(t)

            pygame.display.flip()

            frame_i += 1
            if smoke_frames and frame_i >= smoke_frames:
                running = False

        if MODE == "PATAPON":
            st = self.patapon.stats
            total = max(1, st["perfect"] + st["good"] + st["off"])
            print(f"[patapon] 指令成功 {st['cmd_ok']}  失误 {st['cmd_fail']}  攻击 {st['attacks']}  "
                  f"击杀 {self.patapon.kills}  破阵 {st['break_ok']}/{st['break_fail']}  "
                  f"完美 {st['perfect'] / total * 100:.0f}%  合拍 {st['good'] / total * 100:.0f}%  "
                  f"未合拍 {st['off'] / total * 100:.0f}%  状态 {self.patapon.status}")
        else:
            self._export_log()
        self.audio.stop()
        pygame.quit()

    def _patapon_frame(self, real_dt: float) -> bool:
        """PATAPON 阵列模式单帧：事件 → 编排推进 → 阵列渲染。返回 False 表示退出。

        注意：本路径不经过 InputManager/Judgement——鼓键事件在此直接进
        squad.PataponGame 的 4 拍缓冲池，判定走 sandbox_patapon 的平行路径。
        """
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return False
            self.patapon.handle_event(ev)
        self.patapon.update(real_dt)
        self.squad_view.draw(self.screen, self.patapon, real_dt, self.fps)
        return True

    # ------------------------------------------------------------------ 输入
    def _global_keys(self, frame) -> bool:
        if frame.quit_requested:        # 窗口右上角 ×
            return True
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:
            return True
        for e in pygame.event.get(pygame.KEYDOWN):
            pass
        if frame.just_pressed("finisher") and keys[pygame.K_f]:
            pass
        # 面板与调试按键走轮询，避免事件队列被消费两次
        if self._key_edge(pygame.K_F1):
            self.show_debug = not self.show_debug
        if self._key_edge(pygame.K_F2):
            self.show_feel = not self.show_feel
        if self._key_edge(pygame.K_F3):
            self.show_help = not self.show_help
        if self._key_edge(pygame.K_p):
            self.paused = not self.paused
        if self._key_edge(pygame.K_r):
            self.restart(full=True)
        if self._key_edge(pygame.K_1):
            self.music.force_layer("slow")
        if self._key_edge(pygame.K_2):
            self.music.force_layer("mid")
        if self._key_edge(pygame.K_3):
            self.music.force_layer("fast")
        if self._key_edge(pygame.K_4):
            self.music.force_layer("extreme")
        if self.show_feel:
            self._feel_keys()
        return False

    def _key_edge(self, keycode: int) -> bool:
        pressed = pygame.key.get_pressed()[keycode]
        prev = getattr(self, "_prev_keys", {})
        was = prev.get(keycode, False)
        if not hasattr(self, "_prev_keys"):
            self._prev_keys = {}
        self._prev_keys[keycode] = pressed
        return pressed and not was

    def _feel_keys(self) -> None:
        keys = pygame.key.get_pressed()
        if self._key_edge(pygame.K_UP):
            self.feel_sel = (self.feel_sel - 1) % len(self.feel_params)
        if self._key_edge(pygame.K_DOWN):
            self.feel_sel = (self.feel_sel + 1) % len(self.feel_params)
        if self._key_edge(pygame.K_LEFT):
            self.feel_params[self.feel_sel].setter(-1)
        if self._key_edge(pygame.K_RIGHT):
            self.feel_params[self.feel_sel].setter(1)
        if self._key_edge(pygame.K_o):
            self._sync_params_from_data()

    def _handle_input(self, frame, t: float) -> None:
        if self.state != "playing":
            return
        p = self.player
        if frame.just_pressed("jump"):
            p.request_jump()
        if frame.just_pressed("dash"):
            p.request_dash()

        # 攻击 / 对击 / 矮子步 / 劈山
        atk_t = frame.first_press_time("attack")
        if atk_t is not None:
            if frame.held.get("down") and p.on_ground:
                p.sliding = True
                p.slide_t = float(DATA.motion["slide_duration_ms"]) / 1000.0
            else:
                ev = self.combat.press_attack(atk_t, p, bool(frame.held.get("down")), self.level)
                self._consume_events(ev)

        if frame.just_pressed("finisher"):
            ev = self.combat.release_finisher(p, self.level)
            if ev.get("finisher"):
                self.finisher_count += 1
                self._consume_events(ev)

    def _consume_events(self, ev: dict) -> None:
        if not ev:
            return
        if ev.get("judge") is not None:
            self._flash(ev["judge"].grade)
            self.audio.schedule(self.audio.audio_time(), self.bank.feedback[ev["judge"].grade], 0.9)
        if ev.get("parry"):
            self.message = "合拍弹反！" if ev.get("parry_perfect") else "对击！"
            self.message_t = 0.9
            self.audio.schedule(self.audio.audio_time(), self.bank.feedback["parry"], 0.9)
        if ev.get("parry_fail"):
            self.message = "对击过早"
            self.message_t = 0.7
            self.audio.schedule(self.audio.audio_time(), self.bank.feedback["off"], 0.7)
        if ev.get("sfx") == "hit" and not ev.get("parry"):
            self.audio.schedule(self.audio.audio_time(), self.bank.feedback["hit"], 0.8)
        if ev.get("finisher"):
            self.message = "满堂彩！"
            self.message_t = 1.5
        if ev.get("hitstop_ms"):
            self.hitstop_t = max(self.hitstop_t, float(ev["hitstop_ms"]) / 1000.0)

    def _flash(self, grade: str) -> None:
        self.judgement._flash = (0.28, grade)

    def _update_flash(self, dt: float) -> None:
        f, g = self.judgement._flash
        if f > 0:
            self.judgement._flash = (max(0.0, f - dt), g)
        if self.message_t > 0:
            self.message_t = max(0.0, self.message_t - dt)

    # ------------------------------------------------------------------ 步进
    def _step(self, dt: float, t: float) -> None:
        if self.hitstop_t > 0.0:
            self.hitstop_t = max(0.0, self.hitstop_t - dt)
            self.music.update(self.player.speed)
            return

        self.elapsed += dt
        p = self.player
        held = self.inputs.frame.held
        dir_x = (1.0 if held.get("right") else 0.0) - (1.0 if held.get("left") else 0.0)
        p.step(dt, dir_x, bool(held.get("jump")), bool(held.get("down")), self.combat.busy)

        ev = self.combat.update(dt, p, self.level, t)
        if ev.get("judge") is not None:
            self._flash(ev["judge"].grade)
            self.audio.schedule(t, self.bank.feedback[ev["judge"].grade], 0.9)
        if ev.get("hits"):
            self.audio.schedule(t, self.bank.feedback["hit"], 0.8)
        if ev.get("hitstop_ms"):
            self.hitstop_t = max(self.hitstop_t, float(ev["hitstop_ms"]) / 1000.0)

        for e in self.level.enemies:
            e_ev = e.update(dt, p, t)
            if e_ev.get("hit_player"):
                if p.take_damage(e_ev["hit_player"]):
                    self.audio.schedule(t, self.bank.feedback["hurt"], 0.8)
                    self.message = "受击"
                    self.message_t = 0.5

        # 陷阱
        box = p.aabb()
        for hz in self.level.hazard_rects:
            if box.overlaps(hz):
                if p.take_damage(15.0):
                    self.audio.schedule(t, self.bank.feedback["hurt"], 0.8)
                    self.message = "尖刺"
                    self.message_t = 0.5

        # 鼓劲
        self.energy.add_run(dt, p.speed)
        self.energy.update(dt)

        # 音乐推进（板式由移速驱动）
        self.music.update(p.speed)

        if p.dead:
            self.state = "dead"
            self.death_t = 0.0
        elif p.x >= self.level.goal_x:
            self.state = "cleared"

    # ------------------------------------------------------------------ 渲染
    def _render(self, t: float) -> None:
        s = self.screen
        self.renderer.cam.update(self.player, float(DATA.assist["camera_lookahead_ratio"]))
        self.renderer.draw_world(s, self.level, self.player, self.combat)
        self.renderer.draw_hud(s, self.player, self.energy, self.judgement, self.combat,
                               self.music, self.elapsed, self.level)

        if self.state == "dead":
            self.renderer.draw_center_text(s, "落阵", "1.5 秒后自动重开（按 R 立即重开）", RED)
        elif self.state == "cleared":
            st = self.judgement.stats()
            self.renderer.draw_center_text(s, "收阵", "", GOLD)
            lines = [
                f"用时 {self.elapsed:.1f}s（目标 {self.level.target_time_s:.0f}s）",
                f"合拍率 {st['perfect_rate'] * 100:.0f}% 完美 / {st['good_rate'] * 100:.0f}% 合拍 / {st['off_rate'] * 100:.0f}% 未合拍",
                f"最高合拍连段 {st['best_streak']}   最高槌花 {self.combat.hit_count}   满堂彩 {self.finisher_count} 次",
                "按 R 重开",
            ]
            self.renderer.draw_help(s, lines)
        elif self.paused:
            self.renderer.draw_center_text(s, "暂停", "按 P 继续", GREY)

        if self.message_t > 0:
            msg = self.renderer.font_l.render(self.message, True, GOLD)
            s.blit(msg, (SCREEN_W // 2 - msg.get_width() // 2, int(SCREEN_H * 0.28)))

        if self.show_help:
            self.renderer.draw_help(s, [
                "A/D 移动  空格 跳跃   J 攻击（合拍）   L 抢步   S+J 矮子步   F 满堂彩",
                "F1 判定调试面板   F2 手感参数面板   F3 关闭帮助   P 暂停   R 重开",
                "1/2/3/4 强制板式：慢板 / 中板 / 快板 / 极板",
            ])

        if self.show_feel:
            rows = [(p.label, p.value_str()) for p in self.feel_params]
            self.renderer.draw_feel_panel(s, rows, self.feel_sel)

        if self.show_debug:
            self.renderer.draw_debug_panel(s, self._debug_lines(t))

    def _debug_lines(self, t: float) -> list[str]:
        st = self.judgement.stats()
        last = self.judgement.last
        b = self.music.beat_pos
        nxt, dt_next = self.music.judge_delta_ms(b)
        anchor = "按键帧" if DATA.judgement["anchor"] == "keydown" else "命中生效帧"
        lines = [
            f"音频时钟 {t:8.3f}s   设备输出延迟 {self.audio.output_latency * 1000:.0f}ms",
            f"FPS {self.fps:5.0f}   输入轮询 {self.poll_hz:5.0f}Hz   帧率无关判定: 是",
            f"板式 {self.music.layer_name} {self.music.bpm:.0f}BPM   拍相位 {self.music.beat_in_bar(b):.2f}/4",
            f"最近判定点 #{nxt}   Δt {dt_next:+.1f}ms",
        ]
        if last is not None:
            lines.append(f"上次判定 {last.grade:7s} Δt {last.dt_ms:+7.1f}ms   连段 {st['streak']}")
        lines.append(f"完美 {st['perfect_rate'] * 100:4.0f}%  合拍 {st['good_rate'] * 100:4.0f}%  未合拍 {st['off_rate'] * 100:4.0f}%  (样本 {st['total']})")
        lines.append(f"Δt 均值 {st['mean_dt_ms']:+6.1f}ms   标准差 {st['std_dt_ms']:5.1f}ms   （OQ-1：均值应接近 0）")
        lines.append(f"判定锚点 {anchor}   用户偏移 {DATA.judgement['user_offset_ms']:+.0f}ms   完美/合拍窗口 {DATA.judgement['perfect_ms']:.0f}/{DATA.judgement['good_ms']:.0f}ms")
        lines.append(f"移速 {self.player.speed:4.1f}   鼓劲 {self.energy.value:5.1f}/100   槌花 {self.combat.hit_count}   满堂彩 {self.finisher_count}")
        lines.append(f"赛段进度 x={self.player.x:5.1f}/{self.level.goal_x:.0f}   敌人 {self.level.killed_enemies}/{self.level.total_enemies}")
        held_now = sorted(a for a, v in self.inputs.frame.held.items() if v)
        lines.append(f"当前按住: {'+'.join(held_now) if held_now else '（无）'}   （按键无反应时先看这里是否变化）")
        return lines

    # ------------------------------------------------------------------ 导出
    def _export_log(self) -> None:
        st = self.judgement.stats()
        try:
            with open(self.log_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["audio_time_s", "dt_ms", "grade"])
                for row in self.judgement.history:
                    w.writerow([f"{row[0]:.4f}", f"{row[1]:.2f}", row[2]])
            with open(os.path.join(app_dir(), "playtest_summary.csv"), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["metric", "value"])
                for k, v in st.items():
                    w.writerow([k, f"{v:.4f}" if isinstance(v, float) else v])
                w.writerow(["elapsed_s", f"{self.elapsed:.2f}"])
                w.writerow(["finisher_count", self.finisher_count])
                w.writerow(["runs", self.runs])
                w.writerow(["audio_engine", type(self.audio).__name__])
                w.writerow(["audio_started", int(self.audio.started)])
                w.writerow(["audio_available", int(self.audio.available)])
                w.writerow(["output_latency_ms", f"{self.audio.output_latency * 1000:.1f}"])
                w.writerow(["poll_hz", f"{self.poll_hz:.1f}"])
            print(f"[playtest] 判定日志已导出：{self.log_path}")
            print(f"[playtest] 音频引擎 {type(self.audio).__name__}  输出延迟 {self.audio.output_latency * 1000:.0f}ms  "
                  f"输入轮询 {self.poll_hz:.0f}Hz")
            print(f"[playtest] 样本 {st['total']}  perfect {st['perfect_rate'] * 100:.0f}%  "
                  f"good {st['good_rate'] * 100:.0f}%  off {st['off_rate'] * 100:.0f}%  "
                  f"Δt均值 {st['mean_dt_ms']:+.1f}ms  标准差 {st['std_dt_ms']:.1f}ms")
        except Exception as exc:  # pragma: no cover
            print(f"[warn] 导出失败：{exc}")


def _disable_ime() -> None:
    """Windows 下对游戏窗口禁用输入法（IME）。

    中文输入法激活时会拦截 A/D/W/S 等字母键（进入候选流程），pygame 收不到
    KEYDOWN，表现为「窗口已聚焦但按键无反应」。将窗口 IME 上下文置空后按键直达。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = pygame.display.get_wm_info()["window"]
        ctypes.windll.imm32.ImmAssociateContext(hwnd, None)
    except Exception:
        pass


def main() -> int:
    Game().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())