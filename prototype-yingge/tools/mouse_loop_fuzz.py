"""真实事件循环鼠标测试（P0）。

与 `mouse_fuzz.py` 的区别：不再直接调用 `Flow.click()`，而是
`pygame.event.post` → 真实 `pygame.event.get()` → 与 `main.py` 同构的分派，
并真实绘制每个场景（含 Boss 战斗与跑酷）。旧脚本保留不动。

用法：
    py -3 prototype-yingge/tools/mouse_loop_fuzz.py
    py -3 prototype-yingge/tools/mouse_loop_fuzz.py --fuzz 500
    py -3 prototype-yingge/tools/mouse_loop_fuzz.py --scale
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
import runner
import scenes
import scene_ui as sui

SCENE_KEYMAP = {
    pygame.K_UP: "UP", pygame.K_DOWN: "DOWN",
    pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT",
    pygame.K_RETURN: "ENTER", pygame.K_KP_ENTER: "ENTER",
    pygame.K_ESCAPE: "ESC", pygame.K_g: "G", pygame.K_b: "B",
    pygame.K_j: "J", pygame.K_k: "K", pygame.K_l: "L",
    pygame.K_TAB: "TAB",
}

BATTLE_HUD_POINTS = (
    ("hud_panel", 60, 60), ("hud_panel_bottom", 60, 400),
    ("hud_segment", 880, 60), ("hud_beat_bar", 300, 470),
    ("hud_beat_bar_mid", 620, 470), ("hud_instrument", 36, 434),
    ("hud_instrument2", 72, 434), ("hud_instrument3", 108, 434),
    ("hud_hint", 480, 520), ("hud_blank", 700, 300),
)


def make_env():
    pygame.init()
    screen = pygame.display.set_mode((r.VIEW_W * r.PRESENT_SCALE,
                                      r.VIEW_H * r.PRESENT_SCALE))
    view = pygame.Surface(screen.get_size())
    ren = r.Renderer()
    ui = sui.SceneUI(ren, screen)
    return ren, ui, screen, view


def post_click(x: int, y: int, button: int = 1) -> None:
    """把一次完整点击投进 pygame 事件队列。"""
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEMOTION, {"pos": (x, y), "rel": (0, 0),
                             "buttons": (1, 0, 0)}))
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"pos": (x, y), "button": button,
                                 "buttons": (1, 0, 0), "rel": (0, 0)}))
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONUP, {"pos": (x, y), "button": button,
                               "buttons": (0, 0, 0), "rel": (0, 0)}))


def post_key(key_code: int) -> None:
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {"key": key_code,
                                                           "mod": 0}))


def dispatch(flow, ui, events, now: float) -> list[str]:
    """与 main.py 战前分支 + 战斗分支同构的事件分派。"""
    tokens: list[str] = []
    for ev in events:
        token = None
        if ev.type == pygame.QUIT:
            continue
        elif ev.type == pygame.KEYDOWN:
            key_name = {pygame.K_j: "J", pygame.K_k: "K",
                        pygame.K_l: "L"}.get(ev.key)
            if flow.scene == "runner" and key_name:
                # 与 main 一致：跑酷按键先入 pending，不转成 flow.key
                continue
            token = flow.key(SCENE_KEYMAP.get(ev.key, ""), now)
        elif ev.type == pygame.MOUSEMOTION:
            lx, ly = ui.logical_pos(ev.pos)
            flow.hover(lx, ly)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            lx, ly = ui.logical_pos(ev.pos)
            token = flow.click(lx, ly, now)
        if token:
            tokens.append(token)
    return tokens


def draw(ui, screen, view, ren, flow, game, sess, now: float, dt: float) -> None:
    if flow.scene == "title":
        ui.draw_title(screen, flow, now)
    elif flow.scene == "roster":
        ui.draw_roster(screen, flow, now)
    elif flow.scene == "guide":
        ui.draw_guide(screen, flow, now)
    elif flow.scene == "runner" and sess is not None:
        ui.draw_runner(screen, flow, sess, now)
    elif flow.scene == "battle":
        if flow.paused:
            ui.draw_pause(screen, flow, now)
        elif game is not None:
            ren.draw(view, game, now, dt)
            pygame.Surface.blit(screen, view, (0, 0))
    ui.overlay(screen, flow)


class Case:
    """一个场景的可重建状态。"""

    def __init__(self, name, flow, game=None, sess=None):
        self.name = name
        self.flow = flow
        self.game = game
        self.sess = sess
        self.now = 0.0
        self.dt = 1.0 / 60.0


def build_cases(tmp: str) -> dict[str, "callable"]:
    def title():
        f = scenes.Flow(os.path.join(tmp, "t1.json"), core.BPM, mode="runner")
        return Case("title", f)

    def roster():
        f = scenes.Flow(os.path.join(tmp, "t2.json"), core.BPM, mode="runner")
        f.key("ENTER", 0.0)                    # title → roster
        return Case("roster", f)

    def guide():
        f = scenes.Flow(os.path.join(tmp, "t3.json"), core.BPM, mode="boss")
        f.key("ENTER", 0.0)                    # title → roster
        f.key("ENTER", 0.0)                    # roster → guide（boss 模式）
        assert f.scene == "guide", f.scene
        return Case("guide", f)

    def pause():
        f = scenes.Flow(os.path.join(tmp, "t4.json"), core.BPM, mode="boss")
        f.skip_to_battle()
        f.key("ESC", 0.0)                      # 开暂停
        return Case("pause", f, game=None)

    def battle():
        f = scenes.Flow(os.path.join(tmp, "t5.json"), core.BPM, mode="boss")
        f.skip_to_battle()
        g = scenes.new_battle(f.leader, core.BPM, "standard",
                              start_time=1.1, seed=20261104)
        return Case("battle", f, game=g)

    def runner_case():
        f = scenes.Flow(os.path.join(tmp, "t6.json"), core.BPM, mode="runner")
        f.key("ENTER", 0.0)
        f.key("ENTER", 0.0)                    # roster → runner
        assert f.scene == "runner", f.scene
        s = runner.RunnerSession(runner.load_config(), leader=f.leader,
                                 seed=20261105, culture=True)
        return Case("runner", f, sess=s)

    return {"title": title, "roster": roster, "guide": guide,
            "pause": pause, "battle": battle, "runner": runner_case}


def points_for(case: Case) -> list[tuple[str, int, int]]:
    f = case.flow
    pts: list[tuple[str, int, int]] = []
    for name, (x, y, w, h) in f.hotzones():
        pts += [(name + "/c", x + w // 2, y + h // 2),
                (name + "/tl", x + 1, y + 1),
                (name + "/br", x + w - 1, y + h - 1),
                (name + "/out", x - 1, y - 1)]
    if f.scene == "battle":
        pts += BATTLE_HUD_POINTS
        pts += [("battle_blank", 480, 200), ("battle_sky", 860, 460)]
    elif f.scene == "title":
        pts += [("portrait", 400, 282), ("blank", 200, 500)]
    elif f.scene == "roster":
        pts += [("blank", 40, 40), ("gap", 180, 96), ("footer", 300, 480)]
    elif f.scene == "guide":
        pts += [("right_panel", 700, 160), ("blank", 40, 520),
                ("drum_center", 610, 250)]
    elif f.scene == "runner":
        pts += [("track", 480, 470), ("blank", 480, 200)]
    return pts


def run_case(builder, ui, screen, view, ren, scale: int = 2,
             now: float = 0.0) -> list[dict]:
    case = builder()
    bad: list[dict] = []
    for label, lx, ly in points_for(case):
        case = builder()                    # 每个点都从干净状态开始
        x, y = lx * scale, ly * scale
        try:
            post_click(x, y)
            events = pygame.event.get()
            dispatch(case.flow, ui, events, now)
            draw(ui, screen, view, ren, case.flow, case.game, case.sess,
                 now, case.dt)
        except Exception:
            bad.append({"scene": case.name, "point": label,
                        "pos": (x, y), "trace": traceback.format_exc()})
    print(f"[{case.name}] 真实路径元素点击 {len(points_for(builder()))} 个，"
          f"异常 {len(bad)} 次")
    return bad


def run_fuzz(builder, ui, screen, view, ren, n: int = 500, scale: int = 2,
             seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    case = builder()
    bad: list[dict] = []
    for i in range(n):
        if i % 14 == 0:
            case = builder()                # 定期重建，避免状态漂移
        w, h = screen.get_size()
        px = rng.randrange(0, w)
        py = rng.randrange(0, h)
        try:
            post_click(px, py, button=rng.choice((1, 1, 1, 2, 3)))
            events = pygame.event.get()
            dispatch(case.flow, ui, events, case.now)
            draw(ui, screen, view, ren, case.flow, case.game, case.sess,
                 case.now, case.dt)
        except Exception:
            bad.append({"scene": case.name, "pos": (px, py),
                        "trace": traceback.format_exc()})
    print(f"[{case.name}] 真实路径随机点击 {n} 次，异常 {len(bad)} 次")
    return bad


def _center(rect) -> tuple[int, int]:
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


def run_replay(ui, screen, view, ren, tmp: str) -> tuple[list[dict], list[str]]:
    """真实事件循环脚本：Title→Roster(武松)→Guide 6 步→Boss 20s→暂停→返回。"""
    bad: list[dict] = []
    marks: list[str] = []
    f = scenes.Flow(os.path.join(tmp, "replay.json"), core.BPM)
    game_box = [None]
    now = [0.0]
    sim = [1.1]

    def frame(post=None, dt: float = 1.0 / 60.0) -> None:
        now[0] += dt
        if post is not None:
            post()
        events = pygame.event.get()
        try:
            dispatch(f, ui, events, now[0])
            f.update(now[0], dt)
            if f.scene == "battle" and not f.paused and game_box[0] is not None:
                sim[0] += dt
                game_box[0].update(sim[0], dt)
            draw(ui, screen, view, ren, f, game_box[0], None, now[0], dt)
        except Exception:
            bad.append({"scene": f.scene, "point": "replay",
                        "pos": (0, 0), "trace": traceback.format_exc()})

    def click(lx: int, ly: int, dt: float = 1.0 / 60.0) -> None:
        frame(lambda: post_click(lx * 2, ly * 2), dt)

    click(*_center(scenes.TITLE_ENTER_RECT))
    marks.append(f"title→{f.scene}")
    click(*_center(scenes.roster_cell_rect(0)))
    marks.append(f"roster→{f.scene}")

    # 指南 6 步（与 selftest 同一套鼠标序列，0.02s 步进）
    drum = _center(scenes.GUIDE_KEY_RECT["J"])
    gong = _center(scenes.GUIDE_KEY_RECT["K"])
    cym = _center(scenes.GUIDE_KEY_RECT["L"])
    nxt = _center(scenes.GUIDE_NEXT_RECT)
    click(*drum, dt=0.02)
    click(*nxt, dt=0.02)
    for _ in range(4):
        click(*drum, dt=0.02)
    click(*nxt, dt=0.02)
    for _ in range(4):
        click(*drum, dt=0.02)
    for _ in range(4):
        click(*gong, dt=0.02)
    for _ in range(4):
        click(*cym, dt=0.02)
    click(*nxt, dt=0.02)
    for keypos in (drum, gong, drum, gong, cym, gong, cym, gong):
        click(*keypos, dt=0.02)
    click(*nxt, dt=0.02)
    for _ in range(4):
        click(*gong, dt=0.02)
    click(*nxt, dt=0.02)
    for _ in range(8):
        click(*drum, dt=0.02)
    click(*nxt, dt=0.02)
    marks.append(f"guide→{f.scene}")

    game_box[0] = scenes.new_battle(f.leader, core.BPM, "standard",
                                    start_time=1.1, seed=20261104)
    # 战斗 20 秒（1200 帧），期间投递 4 次 J 键事件
    for i in range(1200):
        if i % 300 == 150:
            frame(lambda: post_key(pygame.K_j))
        else:
            frame()
    marks.append(f"battle20s→{f.scene}")

    frame(lambda: post_key(pygame.K_ESCAPE))
    marks.append(f"pause→{f.scene}/paused={f.paused}")
    pause_title = [rect for name, rect in f.hotzones() if name == "返回标题"]
    if pause_title:
        click(*_center(pause_title[0]))
    marks.append(f"back→{f.scene}")
    print("[replay] " + " | ".join(marks) + f" | 异常 {len(bad)} 次")
    return bad, marks


def check_mapping(ui, scale: float) -> list[str]:
    """逻辑坐标 → 物理 → 逻辑，必须回到原点 ±1。"""
    fails = []
    for lx, ly in ((10, 10), (480, 270), (959, 539), (300, 470), (880, 60)):
        phys = (int(lx * scale), int(ly * scale))
        back = ui.logical_pos(phys)
        if abs(back[0] - lx) > 1 or abs(back[1] - ly) > 1:
            fails.append(f"{scale}x: {phys} -> {back}")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuzz", type=int, default=500)
    ap.add_argument("--scale", action="store_true")
    args = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="yingge_loop_")
    ren, ui, screen, view = make_env()
    builders = build_cases(tmp)
    bad: list[dict] = []
    for name, mk in builders.items():
        bad += run_case(mk, ui, screen, view, ren, scale=2)
        bad += run_fuzz(mk, ui, screen, view, ren, n=args.fuzz, scale=2,
                        seed=7 + len(name))
    for b in bad[:8]:
        print(f"\n[异常] 场景={b['scene']} 元素={b['point']} "
              f"坐标={b['pos']}\n{b['trace']}")
    if args.scale:
        for w, h in ((960, 540), (1440, 810), (1920, 1080)):
            scr = pygame.Surface((w, h))
            ui2 = sui.SceneUI(ui.r, scr)
            ui2._canvas_for(scr)
            probes = ((0, 0), (w - 1, h - 1), (w // 2, h // 2))
            mapped = [ui2.logical_pos(p) for p in probes]
            print(f"[scale] {w}×{h} → {mapped}")
            f = check_mapping(ui2, w / r.VIEW_W)
            if f:
                bad.append({"scene": "scale", "point": f"{w}x{h}",
                            "pos": (w, h), "trace": "\n".join(f)})
    replay_bad, _ = run_replay(ui, screen, view, ren, tmp)
    bad += replay_bad
    for b in bad[:8]:
        print(f"\n[异常] 场景={b['scene']} 元素={b['point']} "
              f"坐标={b['pos']}\n{b['trace']}")
    print(f"\n合计异常 {len(bad)} 次")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
