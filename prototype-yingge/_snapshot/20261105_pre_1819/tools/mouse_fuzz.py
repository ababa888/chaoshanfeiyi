"""鼠标闪退复现 / 全量点击 / 随机模糊测试（第十九轮）。

用法：
    py -3 prototype-yingge/tools/mouse_fuzz.py --repro
    py -3 prototype-yingge/tools/mouse_fuzz.py --all --fuzz 500
    py -3 prototype-yingge/tools/mouse_fuzz.py --scale

脚本完全无头（不建窗口，直接画在 Surface 上），事件分发与 main.py 的战前
场景分支保持一致：MOUSEMOTION → hover，MOUSEBUTTONDOWN(1) → click。
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import traceback

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pygame

import core
import render as r
import scenes
import scene_ui as sui


def make_ui() -> tuple[sui.SceneUI, pygame.Surface]:
    pygame.init()
    # dummy 驱动也要有一个 video mode，否则 convert_alpha 全失败 → 素材退化成 24×32
    pygame.display.set_mode((r.VIEW_W, r.VIEW_H))
    ren = r.Renderer()
    screen = pygame.Surface((r.VIEW_W * r.PRESENT_SCALE,
                             r.VIEW_H * r.PRESENT_SCALE))
    ui = sui.SceneUI(ren, screen)
    return ui, screen


def draw(ui: sui.SceneUI, screen: pygame.Surface, flow: scenes.Flow,
         now: float = 0.0) -> None:
    if flow.scene == "title":
        ui.draw_title(screen, flow, now)
    elif flow.scene == "roster":
        ui.draw_roster(screen, flow, now)
    elif flow.scene == "guide":
        ui.draw_guide(screen, flow, now)
    elif flow.paused:
        ui.draw_pause(screen, flow, now)


def dispatch(ui: sui.SceneUI, flow: scenes.Flow,
             ev: pygame.event.Event, now: float = 0.0) -> str | None:
    """与 main.py 战前分支同构的事件分发。"""
    if ev.type == pygame.MOUSEMOTION:
        lx, ly = ui.logical_pos(ev.pos)
        flow.hover(lx, ly)
    elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
        lx, ly = ui.logical_pos(ev.pos)
        return flow.click(lx, ly, now)
    return None


def click_once(ui, screen, flow, x: int, y: int, now: float = 0.0) -> None:
    for kind in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN,
                 pygame.MOUSEBUTTONUP):
        ev = pygame.event.Event(kind, {"pos": (x, y), "button": 1,
                                       "buttons": (1, 0, 0),
                                       "rel": (0, 0)})
        dispatch(ui, flow, ev, now)
    draw(ui, screen, flow, now)


def points_for(flow: scenes.Flow) -> list[tuple[str, int, int]]:
    """枚举每个场景的重点热区（逻辑坐标，之后 × scale 成物理坐标）。"""
    pts: list[tuple[str, int, int]] = []
    for name, (x, y, w, h) in flow.hotzones():
        pts.append((name, x + w // 2, y + h // 2))
        # 四角内缩 1px：验证热区边界与视觉一致，且角落不越界
        pts.append((name + "/tl", x + 1, y + 1))
        pts.append((name + "/br", x + w - 1, y + h - 1))
        pts.append((name + "/out", x - 1, y - 1))
    if flow.scene == "title":
        pts += [("title_portrait", 400, 282), ("title_blank", 200, 500)]
    elif flow.scene == "roster":
        pts += [("roster_blank", 40, 40), ("roster_gap", 180, 96),
                ("preview_panel", 660, 200), ("preview_text", 590, 130),
                ("preview_lock", 590, 240), ("footer", 300, 480)]
    elif flow.scene == "guide":
        pts += [("right_panel", 700, 160), ("guide_blank", 40, 520),
                ("drum_center", 610, 250), ("above_panel", 400, 80)]
    elif flow.paused:
        pts += [("pause_outside", 100, 100), ("pause_panel", 480, 360)]
    return pts


def run_case(name: str, make_flow, ui, screen, scale: int = 1,
             verbose: bool = True) -> list[dict]:
    flow = make_flow()
    draw(ui, screen, flow)
    bad: list[dict] = []
    for label, lx, ly in points_for(flow):
        x, y = lx * scale, ly * scale
        scene_before = flow.scene
        try:
            click_once(ui, screen, flow, x, y, now=0.0)
        except Exception:
            bad.append({"scene": scene_before, "point": label,
                        "pos": (x, y), "trace": traceback.format_exc()})
        # 点击可能切场景，切了就把新场景的绘制跑一遍再继续
        try:
            draw(ui, screen, flow)
        except Exception:
            bad.append({"scene": flow.scene, "point": label + "/draw",
                        "pos": (x, y), "trace": traceback.format_exc()})
    if verbose:
        for b in bad:
            print(f"\n[异常] 场景={b['scene']} 元素={b['point']} "
                  f"物理坐标={b['pos']}\n{b['trace']}")
    print(f"[{name}] 元素点击 {len(points_for(make_flow()))} 个，"
          f"异常 {len(bad)} 次")
    return bad


def run_fuzz(make_flow, ui, screen, n: int = 500, scale: int = 1,
             seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    flow = make_flow()
    draw(ui, screen, flow)
    bad: list[dict] = []
    buttons = (1, 2, 3, 4, 5)
    target = pygame.Surface(screen.get_size())
    for i in range(n):
        # 每次 12 次后重开，避免无限切场景后 state 不合法
        scene_before = flow.scene
        x = rng.randrange(0, r.VIEW_W) * scale
        y = rng.randrange(0, r.VIEW_H) * scale
        button = rng.choice(buttons)
        try:
            ev = pygame.event.Event(pygame.MOUSEMOTION,
                                    {"pos": (x, y), "button": button,
                                     "buttons": (1, 0, 0), "rel": (0, 0)})
            dispatch(ui, flow, ev)
            ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                    {"pos": (x, y), "button": button,
                                     "buttons": (1, 0, 0), "rel": (0, 0)})
            dispatch(ui, flow, ev)
            ev = pygame.event.Event(pygame.MOUSEBUTTONUP,
                                    {"pos": (x, y), "button": button,
                                     "buttons": (0, 0, 0), "rel": (0, 0)})
            dispatch(ui, flow, ev)
            draw(ui, target, flow)
            pygame.Surface.blit(screen, target, (0, 0))
        except Exception:
            bad.append({"scene": scene_before, "pos": (x, y),
                        "button": button, "trace": traceback.format_exc()})
        if flow.scene == "battle" and not flow.paused:
            # 点击可进战斗：重开一次继续测，保证三场景都被覆盖
            flow = make_flow()
        elif not flow.paused and flow.scene == "guide" and flow.guide is None:
            flow = make_flow()
    if bad:
        for b in bad[:5]:
            print(f"\n[模糊异常] 场景={b['scene']} 坐标={b['pos']} "
                  f"按钮={b['button']}\n{b['trace']}")
    print(f"[fuzz] {n} 次随机点击，异常 {len(bad)} 次")
    return bad


def make_flows(tmp: str):
    def title():
        return scenes.Flow(os.path.join(tmp, "s1.json"), core.BPM)

    def roster():
        f = scenes.Flow(os.path.join(tmp, "s2.json"), core.BPM)
        f.key("ENTER", 0.0)
        return f

    def guide():
        f = scenes.Flow(os.path.join(tmp, "s3.json"), core.BPM)
        f.key("ENTER", 0.0)
        f.key("ENTER", 0.0)
        return f

    def pause():
        f = scenes.Flow(os.path.join(tmp, "s4.json"), core.BPM)
        f.skip_to_battle()
        f.key("ESC", 0.0)
        return f

    return {"title": title, "roster": roster, "guide": guide, "pause": pause}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repro", action="store_true", help="只复现闪退")
    ap.add_argument("--all", action="store_true", help="全量元素点击")
    ap.add_argument("--fuzz", type=int, default=0, help="随机点击次数")
    ap.add_argument("--scale", action="store_true",
                    help="额外测 1× / 1.5× / 2× 坐标映射")
    args = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="yingge_mouse_")
    ui, screen = make_ui()
    makers = make_flows(tmp)

    total = []
    if args.repro or not (args.all or args.fuzz or args.scale):
        for name, mk in makers.items():
            total += run_case(name, mk, ui, screen)
    if args.all:
        for name, mk in makers.items():
            total += run_case(name, mk, ui, screen)
    if args.fuzz:
        for name, mk in makers.items():
            total += run_fuzz(mk, ui, screen, args.fuzz)
    if args.scale:
        # 物理窗口尺寸 → 逻辑坐标映射：四个角 + 中心
        for w, h in ((960, 540), (1440, 810), (1920, 1080)):
            scr = pygame.Surface((w, h))
            ui2 = sui.SceneUI(ui.r, scr)
            ui2._canvas_for(scr)
            probes = ((0, 0), (w - 1, h - 1), (w // 2, h // 2),
                      (w - 1, 0), (0, h - 1))
            mapped = [ui2.logical_pos(p) for p in probes]
            print(f"[scale] {w}×{h} → {mapped}")
    print(f"\n合计异常 {len(total)} 次")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
