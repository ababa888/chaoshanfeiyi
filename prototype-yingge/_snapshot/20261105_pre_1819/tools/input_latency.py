"""输入链路实测：合成按键 → 判定 → HUD 首帧像素。

运行：py -3 prototype-yingge/tools/input_latency.py

分段口径（全部用 perf_counter，单位 ms）：
  post→get     : 事件投递到本帧 event.get() 取出（SDL 队列，不含键盘硬件延迟）
  get→judge    : 取出到 Game.press 被调用（入队 + 同帧消费）
  judge→draw   : 判定完成到 HUD 绘制结束（含谱面带/乐器架重绘）
  post→draw    : 游戏侧按键到首帧像素（应 ≤ 1 帧，16.7ms @60fps）

系统级键盘延迟（USB 扫描 + 驱动 + SDL）不在此工具口径内。
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame

import core
import render as r

DT = 1.0 / 60.0
TRIALS = 24


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((r.VIEW_W * 2, r.VIEW_H * 2))
    game = core.Game(start_time=0.0)
    ren = r.Renderer()

    post_get, get_judge, judge_draw = [], [], []
    press_t = {"t": 0.0}

    orig_press = core.Game.press

    def timed_press(self, key, now):
        press_t["t"] = time.perf_counter()
        return orig_press(self, key, now)

    core.Game.press = timed_press

    now = 0.0
    # 预热：走到稳定节拍段落
    for _ in range(90):
        now += DT
        game.update(now, DT)
        ren.draw(screen, game, now, DT)

    for trial in range(TRIALS):
        # 在帧间随机相位投递，覆盖 0–16.7ms 的系统送达抖动
        time.sleep(0.004 + (trial % 4) * 0.004)
        t_post = time.perf_counter()
        pygame.event.post(pygame.event.Event(
            pygame.KEYDOWN, key=(pygame.K_j, pygame.K_k, pygame.K_l)[trial % 3]))
        t_get = t_judge = None
        now += DT
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and t_get is None:
                t_get = time.perf_counter()
                key = {pygame.K_j: "J", pygame.K_k: "K",
                       pygame.K_l: "L"}[ev.key]
                game.push_input(key, now)
        press_t["t"] = 0.0
        game.update(now, DT)
        if press_t["t"]:
            t_judge = press_t["t"]
        ren.draw(screen, game, now, DT)
        t_draw = time.perf_counter()
        if t_get is not None:
            post_get.append((t_get - t_post) * 1000.0)
        if t_get and t_judge:
            get_judge.append((t_judge - t_get) * 1000.0)
        if t_judge:
            judge_draw.append((t_draw - t_judge) * 1000.0)

    def stat(name, vals):
        vals = sorted(vals)
        if not vals:
            print(f"{name}: -")
            return
        print("%-10s n=%d  min=%.2f  med=%.2f  max=%.2f ms"
              % (name, len(vals), vals[0], vals[len(vals) // 2], vals[-1]))

    print("INPUT-LATENCY: frames=1 (按键当帧判定并重绘)")
    stat("post->get", post_get)
    stat("get->judge", get_judge)
    stat("judge->draw", judge_draw)
    total = [a + b + c for a, b, c in zip(post_get, get_judge, judge_draw)]
    stat("post->draw", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
