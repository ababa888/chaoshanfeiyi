"""生成斜俯视伪 3D 验收图（33–42）。

运行：py -3 prototype-yingge/tools/perspective_shots.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame

import core
import pseudo3d as p3d
import render as r
import selftest as st

SHOTS = os.path.join(ROOT, "shots")
OUT_W, OUT_H = 1920, 1080


def view(ren: r.Renderer, game: core.Game, cam: float | None = None,
         dt: float = 1 / 60) -> pygame.Surface:
    if cam is not None:
        ren.cam_x = cam
    raw = pygame.Surface((r.VIEW_W, r.VIEW_H))
    ren.draw(raw, game, game.now, dt)
    return pygame.transform.scale(raw, (OUT_W, OUT_H))


def scene(formation: str, cam: float = 2.2,
          boss_platform: bool = True) -> core.Game:
    g = st.boss_game()
    g.formation = formation
    g.squad.x = cam + 1.0
    g.status = "playing"
    lanes = (1.6, -1.2, 2.6)
    g.enemies = []
    for i, lane in enumerate(lanes):
        e = core.Enemy("grunt" if i < 2 else "brute",
                       g.squad.x + 3.2 + i * 1.15, i, v=lane)
        e.hp = e.max_hp
        g.enemies.append(e)
    if g.boss is not None:
        g.boss.active = True
        g.boss.hp = g.boss.max_hp
        g.boss.x = g.boss.platform_x
        g.boss.v = 0.0
        g.boss.dead = False
        g.boss.on_platform = boss_platform
    g.fever_active = False
    g.combo = 12
    g.tutorial_hint = ("", 0.0)
    return g


def render_scene(g: core.Game, cam: float) -> pygame.Surface:
    ren = r.Renderer()
    ren.cam_x = cam
    ren.slot_pos = [list(p) for p in core.FORMATION_SLOTS[g.formation]]
    return view(ren, g, cam)


def label(surf: pygame.Surface, text: str, x: int, y: int,
          color=(255, 236, 200), size: int = 18) -> None:
    f = r.FontBook()
    f.text(surf, text, size, color, (x, y), center=True, bold=True,
           outline=(24, 12, 10))


def save_compare(name: str, left: pygame.Surface, right: pygame.Surface,
                 left_txt: str, right_txt: str) -> None:
    panel = pygame.Surface((OUT_W, 620))
    panel.fill((18, 12, 14))
    small = pygame.transform.scale(left, (960, 540))
    panel.blit(small, (0, 46))
    panel.blit(pygame.transform.scale(right, (960, 540)), (960, 46))
    pygame.draw.rect(panel, (70, 48, 36), (0, 46, 960, 540), 2)
    pygame.draw.rect(panel, (70, 48, 36), (960, 46, 960, 540), 2)
    label(panel, left_txt, 480, 20, size=22)
    label(panel, right_txt, 1440, 20, size=22)
    pygame.image.save(panel, os.path.join(SHOTS, name))


_MEASURE_FONT: r.FontBook | None = None


def _measure_font() -> r.FontBook:
    global _MEASURE_FONT
    if _MEASURE_FONT is None:
        _MEASURE_FONT = r.FontBook()
    return _MEASURE_FONT


def vertical_text(surf: pygame.Surface, text: str, x: int, y: int,
                  size: int = 32, color=(255, 236, 200)) -> None:
    """日式竖排：逐字向下堆叠。"""
    gap = int(round(size * 1.16))
    for i, ch in enumerate(text):
        label(surf, ch, x, y + i * gap, color=color, size=size)


def tag_block(surf: pygame.Surface, lines: list[str], cx: int, cy: int,
              color=(255, 236, 200), size: int = 22):
    """带半透明底板的标注块；返回底板矩形，供引线连接。"""
    f = _measure_font()
    tw = max(f.measure(t, size)[0] for t in lines) + 8
    line_h = size + 7
    pad = 10
    w = tw + pad * 2
    h = line_h * len(lines) + pad * 2
    rect = pygame.Rect(int(cx - w // 2), int(cy - h // 2), w, h)
    plate = pygame.Surface((w, h), pygame.SRCALPHA)
    plate.fill((18, 12, 14, 228))
    pygame.draw.rect(plate, (104, 74, 50), plate.get_rect(), 2)
    surf.blit(plate, rect.topleft)
    for i, line in enumerate(lines):
        label(surf, line, rect.centerx, rect.y + pad + line_h * i + line_h // 2,
              color=color, size=size)
    return rect


def callout(surf: pygame.Surface, head: tuple[int, int],
            lines: list[str], cx: int, cy: int,
            color=(255, 236, 200), size: int = 22) -> None:
    rect = tag_block(surf, lines, cx, cy, color=color, size=size)
    ax = rect.left if cx >= head[0] else rect.right
    pygame.draw.line(surf, (250, 214, 150), head, (ax, cy), 2)
    pygame.draw.circle(surf, (255, 244, 206), head, 5)
    pygame.draw.circle(surf, (96, 48, 30), head, 5, 1)


def _scene_game(cam: float, formation: str = "changshe",
                lead: float = 4.0) -> core.Game:
    """无 Boss、无杂兵的空场，用于全景/纵深示意。"""
    g = core.Game(spawn_boss=False)
    g.formation = formation
    g.squad.x = cam + lead
    g.squad.walking = False
    g.squad.stance = "halt"
    g.enemies = []
    g.segment_entry = (core.segment_index_at(g.squad.x), 0.0)
    g.status = "playing"
    g.banner = ("", 0.0)
    g.tutorial_hint = ("", 0.0)
    g.fever_active = False
    g.combo = 0
    return g


def _frame(g: core.Game, cam: float, slots=None, dt: float = 0.0,
           zoom: float = 1.0, focal: float | None = None):
    ren = r.Renderer()
    ren.zoom = zoom
    if focal is not None:
        ren.focal = ren.focal_target = float(focal)
        ren.zoom_from = ren.focal
        p3d.set_focal(ren.focal)
    ren.cam_x = cam
    ren.slot_pos = [list(p) for p in (
        core.FORMATION_SLOTS[g.formation] if slots is None else slots)]
    return ren, view(ren, g, cam, dt)


# ================================================================ 38 长图全景
def shot_long_panorama() -> None:
    canvas = pygame.Surface((OUT_W, OUT_H))
    canvas.fill((14, 10, 12))
    pw, ph, x0 = 640, 340, 700
    ys = (30, 375, 720)
    cams = (22.0, 71.0, 123.0)
    name_colors = ((166, 198, 130), (230, 178, 116), (214, 212, 202))

    for i, cam in enumerate(cams):
        seg = core.segment_at(cam + 4.0)
        p3d.set_slope_deg(float(seg.get("slope_deg", 10.0)))
        g = _scene_game(cam)
        g.clock.base_bpm = g.clock.bpm = float(seg.get("bpm", 132.0))
        _ren, frame = _frame(g, cam, dt=0.0)
        small = pygame.transform.scale(frame, (pw, ph))
        canvas.blit(small, (x0, ys[i]))
        pygame.draw.rect(canvas, (82, 58, 42),
                         (x0, ys[i], pw, ph), 2)
        pygame.draw.rect(canvas, name_colors[i],
                         (x0, ys[i], 5, ph))
        label(canvas, f"cam {int(cam)}", x0 + pw - 70, ys[i] + 18,
              color=(232, 214, 180), size=16)

        # 左侧日式竖排
        vertical_text(canvas, str(seg.get("name", "")), 566,
                      ys[i] + 26, size=34, color=name_colors[i])
        pygame.draw.line(canvas, name_colors[i],
                         (520, ys[i] + 34), (520, ys[i] + 176), 3)
        label(canvas, f"{int(seg.get('u0', 0))}–{int(seg.get('u1', 0))}",
              566, ys[i] + 210, color=name_colors[i], size=24)
        label(canvas, f"{float(seg.get('slope_deg', 0)):.0f}° · "
                      f"{float(seg.get('bpm', 0)):.0f} BPM",
              566, ys[i] + 244, color=(218, 204, 182), size=20)

    # 右侧 0–148 总长刻度尺
    rx, top, bot = 1420, 30, 1060
    total = float(core.LEVEL.get("length_units", 148.0))
    ruler_cols = ((112, 146, 88), (186, 132, 82), (196, 194, 186))
    pygame.draw.line(canvas, (64, 52, 46), (rx, top), (rx, bot), 2)
    for si, seg in enumerate(core.LEVEL["segments"]):
        u0 = float(seg.get("u0", 0))
        u1 = float(seg.get("u1", 0))
        ya = top + int(round((bot - top) * u0 / total))
        yb = top + int(round((bot - top) * u1 / total))
        pygame.draw.line(canvas, ruler_cols[si % len(ruler_cols)],
                         (rx - 8, ya), (rx - 8, yb), 7)
        for uu, yy in ((u0, ya), (u1, yb)):
            if si == 0 or uu == u1:
                pygame.draw.line(canvas, (228, 206, 166),
                                 (rx - 12, yy), (rx + 12, yy), 2)
                label(canvas, f"{int(uu)}", rx + 42, yy,
                      color=(240, 224, 192), size=22)
    label(canvas, "总长 148 单位", 1700, 150,
          color=(255, 226, 166), size=30)
    label(canvas, "0 → 148 · 下坡方向", 1700, 192,
          color=(206, 190, 168), size=18)
    label(canvas, "坡上林地 → 坡中街市 → 坡底广场", 1700, 232,
          color=(196, 180, 158), size=17)

    # 左上标题与分隔线
    label(canvas, "长图全景 · 148 单位", 350, 24,
          color=(255, 232, 190), size=24)
    pygame.draw.line(canvas, (74, 58, 46), (30, 1064), (1890, 1064), 1)

    pygame.image.save(canvas, os.path.join(SHOTS, "38_long_panorama.png"))


# ================================================================ 39 三档纵深
def shot_depth_three_heroes() -> None:
    p3d.set_slope_deg(10.0)
    cam, squad_u = 20.0, 20.0
    lanes = (-4.2, 0.0, 4.2)
    tags = ("近", "中", "远")
    colors = ((255, 190, 120), (255, 226, 150), (132, 202, 240))

    g = _scene_game(cam, lead=squad_u - cam)
    g.squad.x = squad_u
    for i, u in enumerate(g.squad.units):
        u.v = lanes[i]          # 供标注读取；渲染走 slot_pos
    # u 基准同为 20；横向仅做 0 / +2.8 / +6.6 的微错位，避免同 u 时
    # 三人完全重叠（远近大小仍完全由 v 档位决定）。
    du = (0.0, 2.8, 6.6)
    _ren, surf = _frame(g, cam, slots=[(du[0], lanes[0]), (du[1], lanes[1]),
                                       (du[2], lanes[2])], dt=0.0)

    label(surf, "纵深三档：v=(-4.2 / 0 / +4.2) · u 基准 20",
          960, 34, color=(255, 232, 190), size=28)

    callout_x = (1120, 1500, 1690)
    callout_y = (640, 380, 232)
    for i, u in enumerate(g.squad.units):
        dv = float(lanes[i])
        b = p3d.band_index(dv)
        bs = p3d.band_scale(b)
        hero = _ren.bank.hero_for_kind[u.kind]
        img = _ren.hero_band_img(hero, dv, "idle_0")
        sx, sy = p3d.world_to_screen(squad_u + du[i], dv, _ren.cam_x)
        head = (sx * 2, (sy + 4 + _ren._squad_bob - img.get_height()) * 2)
        lines = [f"{tags[i]} v={dv:+.1f} · 档 b{b} · ×{bs:.2f}",
                 f"{core.HERO_NAMES.get(hero, hero)} · 贴图 "
                 f"{img.get_width()}×{img.get_height()}"]
        callout(surf, head, lines, callout_x[i], callout_y[i],
                color=colors[i], size=21)
        pygame.draw.circle(surf, colors[i], head, 9, 2)

    label(surf, "档号与贴图尺寸为实际渲染值；横向微错位仅用于展开三人",
          960, 1046, color=(226, 210, 186), size=18)

    pygame.image.save(surf, os.path.join(SHOTS, "39_depth_three_heroes.png"))


# ================================================================ 40 地面收敛
def shot_ground_convergence() -> None:
    p3d.set_slope_deg(10.0)
    cam = 70.0
    u0, step, cols = cam - 3.5, 0.7, 12
    row_cols = ((100, 120, 88), (96, 112, 80), (108, 96, 72),
                (116, 100, 76), (126, 116, 98), (136, 128, 112),
                (146, 144, 132), (152, 150, 138), (158, 156, 144),
                (164, 162, 150))
    base = pygame.Surface((r.VIEW_W, r.VIEW_H))
    base.fill((14, 14, 20))
    hy = p3d.horizon_y()
    base.fill((24, 26, 38), (0, 0, r.VIEW_W, hy))

    for i in range(p3d.BAND_COUNT):
        v0, v1 = p3d.band_v_bounds(i)
        for c in range(cols):
            ua = u0 + c * step
            ub = ua + step
            pts = p3d.cell_quad(ua, ub, v0, v1, cam, 0.0)
            col = row_cols[i]
            if c % 2:
                col = tuple(max(0, v - 7) for v in col)
            pygame.draw.polygon(base, col, pts)
            pygame.draw.polygon(base, (34, 30, 32), pts, 1)

    pygame.draw.line(base, (244, 92, 206), (0, hy), (r.VIEW_W, hy), 1)
    vx, vy = p3d.vp_point()
    pygame.draw.line(base, (0, 236, 255), (vx - 14, vy), (vx + 14, vy), 2)
    pygame.draw.line(base, (0, 236, 255), (vx, vy - 14), (vx, vy + 14), 2)
    pygame.draw.circle(base, (0, 236, 255), (vx, vy), 6, 2)

    surf = pygame.transform.scale(base, (OUT_W, OUT_H))
    label(surf, "地面梯形收敛 · cam=70 · 10 档 × 12 列",
          960, 36, color=(255, 232, 190), size=30)
    label(surf, f"消失点 VP {p3d.vp_point()}",
          720, 198, color=(114, 236, 255), size=20)
    label(surf, f"地平线 y={hy}", 1280, 218,
          color=(255, 128, 214), size=20)

    for i in range(p3d.BAND_COUNT):
        lx, ly = p3d.world_to_screen(u0, p3d.band_v_center(i), cam, 0.0)
        ty = ly * 2
        pygame.draw.line(surf, (226, 212, 186), (170, ty), (lx * 2, ty), 2)
        pygame.draw.circle(surf, row_cols[i], (lx * 2, ty), 5)
        label(surf, f"b{i} ×{p3d.band_scale(i):.2f}", 116, ty,
              color=(255, 238, 204), size=20)

    tag_block(surf, ["纵向边线逐档收窄，全部指向同一消失点；"
                     f"近档 b0 ×{p3d.band_scale(0):.2f} / "
                     f"远档 b9 ×{p3d.band_scale(9):.2f}"],
              960, 1038, color=(240, 222, 192), size=19)
    pygame.image.save(surf, os.path.join(SHOTS, "40_ground_convergence.png"))


# ================================================================ 41 坡中街市
def shot_market_scene() -> None:
    p3d.set_slope_deg(10.0)
    cam = 72.0
    g = st.boss_game()
    g.formation = "fengshi"
    g.squad.x = cam + 1.0
    g.squad.walking = False
    g.squad.stance = "halt"
    g.segment_entry = (1, 1.8)
    g.clock.base_bpm = g.clock.bpm = 132.0
    g.status = "playing"
    g.enemies = []
    lanes = ((-4.4, "grunt"), (-1.2, "grunt"),
             (1.8, "brute"), (4.2, "grunt"))
    for i, (v, kind) in enumerate(lanes):
        e = core.Enemy(kind, cam + 4.0 + i * 1.15, i, v=v)
        e.hp = e.max_hp
        g.enemies.append(e)

    _ren, surf = _frame(g, cam, dt=0.0)
    tag_block(surf, ["坡中街市 44–98 · 10° · 132 BPM · 灯笼 1.0"],
              1470, 1038, color=(255, 226, 164), size=22)
    tag_block(surf, ["灯笼最密 · 4 名敌兵"], 1680, 226,
              color=(236, 210, 174), size=18)
    label(surf, "坡中街市 · 灯笼密度 1.0", 960, 34,
          color=(255, 232, 190), size=28)
    pygame.image.save(surf, os.path.join(SHOTS, "41_market_scene.png"))


# ================================================================ 42 Boss 广场
def shot_boss_plaza() -> None:
    p3d.set_slope_deg(12.0)
    cam = 128.0
    g = st.boss_game()
    g.start_boss_fight(squad_x=136.0, boss_x=142.5)
    g.formation = "menghu"
    g.squad.walking = False
    g.squad.stance = "halt"
    g.segment_entry = (2, 1.8)
    g.clock.base_bpm = g.clock.bpm = 138.0
    g.status = "playing"
    g.banner = ("", 0.0)
    g.tutorial_hint = ("", 0.0)

    # cam=128 是进入广场的起始机位；直接出图时 142.5 的 Boss 会落在
    # 960 视口右侧之外，跟随到 139.4 又会让读招面板挡住 Boss / 把阵列
    # 压进左侧 HUD。取 134.0 的构图机位，台基、三级台阶、猛虎阵与
    # Boss 同时可见且互不遮挡。
    shot_cam = 134.0
    _ren, surf = _frame(g, shot_cam, dt=0.0)

    tag_block(surf, ["坡底广场 98–148 · 12° · 138 BPM · Boss 142.5"],
              1430, 1038, color=(255, 228, 176), size=22)
    label(surf, "坡底广场 · 石台 / 三级台阶 / 猛虎阵", 960, 34,
          color=(255, 232, 190), size=28)

    bx, by = p3d.world_to_screen(142.5, 0.0, _ren.cam_x, _ren.cam_dip)
    callout(surf, (bx * 2, (by - 176) * 2),
            ["鼓王 · u=142.5", "台基厚 30px · 3 级台阶"],
            430, 760, color=(255, 206, 146), size=19)
    pygame.image.save(surf, os.path.join(SHOTS, "42_boss_plaza.png"))


# ================================================================ 43 三档焦距
def _market_fight() -> tuple[core.Game, float]:
    p3d.set_slope_deg(10.0)
    cam = 74.0
    g = st.boss_game()
    g.formation = "fengshi"
    g.squad.x = cam + 1.2
    g.squad.walking = False
    g.squad.stance = "halt"
    g.segment_entry = (1, 1.5)
    g.clock.base_bpm = g.clock.bpm = 132.0
    g.status = "playing"
    g.enemies = []
    for i, lane in enumerate((-4.4, -1.4, 1.6, 4.2)):
        e = core.Enemy("grunt" if i < 3 else "brute",
                       cam + 3.6 + i * 1.05, i, v=lane)
        e.hp = e.max_hp
        g.enemies.append(e)
    return g, cam


def shot_zoom_compare() -> None:
    canvas = pygame.Surface((OUT_W, OUT_H))
    canvas.fill((14, 10, 12))
    label(canvas, "同场景三档真实焦距：投影整体重算，贴图只换档不 resize",
          960, 26, color=(255, 232, 190), size=28)
    panels = (("standard", 4.0, (255, 226, 150)),
              ("near", 3.2, (255, 178, 112)),
              ("far", 5.0, (128, 198, 240)))
    for i, (name, focal, col) in enumerate(panels):
        g, cam = _market_fight()
        _ren, surf = _frame(g, cam, focal=focal, dt=0.0)
        small = pygame.transform.scale(surf, (620, 349))
        x = 15 + i * 635
        canvas.blit(small, (x, 64))
        pygame.draw.rect(canvas, (70, 48, 36), (x, 64, 620, 349), 2)
        zg = p3d.FOCAL_REF / focal
        label(canvas, f"{name}  f={focal:.1f}  ·  v=0 增益 ×{zg:.2f}",
              x + 310, 430, color=col, size=24)
        label(canvas, f"视宽 {r.VIEW_W / p3d.KX:.1f} 单位 · "
                      f"scale_total {p3d.BAND_MIN:.2f}–{p3d.BAND_MAX:.2f}",
              x + 310, 460, color=(220, 204, 182), size=17)
        label(canvas, f"近档 b0 ×{p3d.band_scale(0):.2f} → "
                      f"远档 b9 ×{p3d.band_scale(9):.2f}",
              x + 310, 484, color=(196, 180, 158), size=16)

    lines = ["档位表（按 scale_total = scale(v) × zoom_gain 等比切分）"]
    for i in range(p3d.BAND_COUNT):
        lo, hi = p3d.band_scale_bounds(i)
        lines.append(f"b{i}  {lo:.3f}–{hi:.3f}  ×{p3d.band_scale(i):.3f}")
    tag_block(canvas, lines[:6], 480, 780, color=(236, 218, 190), size=17)
    tag_block(canvas, lines[6:], 960, 780, color=(236, 218, 190), size=17)
    tag_block(canvas, ["三焦距落档覆盖 b0–b9，无空档；",
                       "变焦过渡 180ms，逐帧整档切换",
                       "HUD 固定，不随焦距缩放"],
              1480, 780, color=(255, 220, 168), size=18)
    pygame.image.save(canvas, os.path.join(SHOTS, "43_zoom_compare.png"))


# ================================================================ 44 道具档位条
def shot_prop_bands() -> None:
    rows = (("tree_0", "树（林地）"), ("flag_0", "旗（街市/广场）"),
            ("gate_forest", "门·林地牌坊"), ("gate_market", "门·街市牌坊"),
            ("gate_plaza", "门·广场石阶"), ("mile_0", "里程桩"))
    canvas = pygame.Surface((OUT_W, OUT_H))
    canvas.fill((16, 12, 14))
    label(canvas, "道具预烘档位条：同一素材 × b0–b9（尺寸取整、只换档不缩放）",
          960, 24, color=(255, 232, 190), size=26)
    left, top = 150, 56
    cw = (OUT_W - left - 16) // p3d.BAND_COUNT
    rh = 148
    for ri, (name, title) in enumerate(rows):
        y = top + ri * rh
        label(canvas, title, 82, y + rh // 2 - 8,
              color=(255, 224, 168), size=15)
        imgs = [pygame.image.load(os.path.join(
            r.ROOT, "assets_gen", "bands", f"b{b}", "props", name + ".png"))
            for b in range(p3d.BAND_COUNT)]
        maxh = max(im.get_height() for im in imgs)
        k = min(1.0, (rh - 38) / maxh)      # 同行统一倍率，保留档位尺寸差
        for b, img in enumerate(imgs):
            nw, nh = max(1, int(img.get_width() * k)), \
                max(1, int(img.get_height() * k))
            cell = pygame.transform.scale(img, (nw, nh))
            x = left + b * cw + (cw - nw) // 2
            yy = y + rh - 24 - nh
            canvas.blit(cell, (x, yy))
            if b:
                pygame.draw.line(canvas, (52, 40, 34),
                                 (left + b * cw, y), (left + b * cw,
                                                       y + rh - 6), 1)
            label(canvas, f"b{b} ×{p3d.band_scale(b):.2f}", left + b * cw + cw // 2,
                  y + rh - 12, color=(214, 198, 172), size=13)
    tag_block(canvas, ["7 类道具 × 10 档 = 70 张（其中门 3 型）；"
                       "每档 79 张 × 10 档（含 10 张阴影）= 790 文件",
                       "统一左上光源，阴影方向一致；同行等比显示"],
              960, 1022, color=(236, 216, 188), size=16)
    pygame.image.save(canvas, os.path.join(SHOTS, "44_prop_bands.png"))


# ================================================================ 45 道具遮挡
def shot_prop_occlusion() -> None:
    p3d.set_slope_deg(8.0)
    probe = r.Renderer()
    probe.cam_x = 20.0
    trees = sorted((p for p in probe._visible_props(_scene_game(20.0, lead=1.0))
                    if p[2] == "tree_0" and p[1] > 0),
                   key=lambda p: abs(p[0] - 21.5))[:2]
    tree_a, tree_b = sorted(trees, key=lambda p: p[0])
    ta, tv = tree_a[0], tree_a[1]
    tb = tree_b[0]
    cam = ta - 1.6          # 让树 A 落在 HUD 右侧，避免被左侧面板挡住

    g = _scene_game(cam, "changshe", lead=1.0)
    # 角色世界 u 略小（更近），但屏幕 x 与树 B 对齐 → 真正挡住树干
    g.squad.x = cam + (tb - cam) * 0.73
    g.squad.walking = False
    g.squad.stance = "halt"
    g.enemies = []
    e = core.Enemy("grunt", ta + 0.35, 0, v=tv + 0.3)   # 树 A 后：树冠压角色
    e.hp = e.max_hp
    g.enemies.append(e)
    g.status = "playing"
    _ren, surf = _frame(g, cam, dt=0.0)

    tsx, tsy = p3d.world_to_screen(ta, tv, _ren.cam_x, _ren.cam_dip)
    ex, ey = p3d.world_to_screen(ta + 0.35, tv + 0.3, _ren.cam_x, _ren.cam_dip)
    ux, uy = p3d.world_to_screen(g.squad.x, 0.0, _ren.cam_x, _ren.cam_dip)
    callout(surf, (ex * 2, int((ey - 46) * 2)),
            ["树后敌人 纵深 +5.3", "角色更远：树冠后画、压住角色"],
            900, 210, color=(132, 202, 240), size=19)
    callout(surf, (ux * 2, int((uy - 50) * 2)),
            ["树前角色 纵深 0", "角色更近：角色后画，树干被挡、树冠仍露出"],
            1310, 800, color=(255, 206, 146), size=18)

    # 敌人包围盒虚线框：直观显示“人被树冠盖住”的范围
    ew, eh = _ren.bank.enemy_bands["grunt"][_ren.band_for(tv + 0.3)][
        "idle_0"].get_size()
    bx0, bx1 = ex * 2 - ew, ex * 2 + ew
    by0, by1 = (ey - eh) * 2, ey * 2
    for k in range(int(bx0), int(bx1), 16):
        pygame.draw.line(surf, (240, 210, 130), (k, by0), (min(k + 8, bx1), by0), 1)
        pygame.draw.line(surf, (240, 210, 130), (k, by1), (min(k + 8, bx1), by1), 1)
    for k in range(int(by0), int(by1), 16):
        pygame.draw.line(surf, (240, 210, 130), (bx0, k), (bx0, min(k + 8, by1)), 1)
        pygame.draw.line(surf, (240, 210, 130), (bx1, k), (bx1, min(k + 8, by1)), 1)

    # 细节裁切：框住树冠 + 树后敌人（不含前排角色）
    crop = pygame.Rect(ex * 2 - 110, ey * 2 - 230, 220, 250)
    crop = crop.clip(surf.get_rect())
    inset = surf.subsurface(crop).copy()
    ix, iy = 1500, 74
    pygame.draw.rect(surf, (40, 28, 22),
                     (ix - 6, iy - 28, inset.get_width() + 12,
                      inset.get_height() + 34))
    surf.blit(inset, (ix, iy))
    pygame.draw.rect(surf, (250, 214, 150),
                     (ix, iy, *inset.get_size()), 2)
    label(surf, "细节（屏幕 2×）：黄框=敌人包围盒，被树冠遮住",
          ix + inset.get_width() // 2, iy - 14,
          color=(255, 226, 166), size=15)
    label(surf, "道具纵深排序 · 树冠遮角色 / 角色遮树干",
          960, 32, color=(255, 232, 190), size=28)
    pygame.image.save(surf, os.path.join(SHOTS, "45_prop_occlusion.png"))


# ================================================================ 46 街市旗阵
def shot_market_flags() -> None:
    p3d.set_slope_deg(10.0)
    cam = 80.0
    g = _scene_game(cam, "fengshi", lead=1.2)
    g.squad.x = cam + 1.2
    g.segment_entry = (1, 1.5)
    g.clock.base_bpm = g.clock.bpm = 132.0
    g.enemies = []
    for i, lane in enumerate((-4.2, -1.0, 1.8, 4.0)):
        e = core.Enemy("grunt" if i < 3 else "brute",
                       cam + 3.4 + i * 1.05, i, v=lane)
        e.hp = e.max_hp
        g.enemies.append(e)
    _ren, surf = _frame(g, cam, dt=0.0)
    label(surf, "坡中街市 · 旗阵（远排 v=+5.0 / 近排 v=-4.6）+ 灯笼",
          960, 32, color=(255, 232, 190), size=28)
    tag_block(surf, ["旗阵随鼓点整像素上下振动（2px / 灯笼 1px）",
                     "旗、门、桩、树全部参与 (v,u) 深度排序",
                     "灯谜密度 1.0 · 132 BPM"],
              1450, 1020, color=(255, 226, 164), size=19)
    bu = cam + 3.0
    bx, by = p3d.world_to_screen(bu, 5.0, _ren.cam_x, _ren.cam_dip)
    callout(surf, (bx * 2, int((by - 50) * 2)),
            ["远排旗 v=+5.0", "预烘档位图 + 整像素振动"],
            470, 280, color=(236, 168, 118), size=19)
    pygame.image.save(surf, os.path.join(SHOTS, "46_market_flags.png"))


def main() -> None:
    pygame.init()
    pygame.display.set_mode((r.VIEW_W, r.VIEW_H))
    os.makedirs(SHOTS, exist_ok=True)

    # 33 斜俯视全阵：锋矢，前后排 + Boss 台基
    g = scene("fengshi", cam=4.2)
    full = render_scene(g, 4.2)
    pygame.image.save(full, os.path.join(SHOTS, "33_persp_full_formation.png"))

    # 34 长蛇纵深 vs 龟甲方阵
    gl = scene("changshe", cam=2.0)
    left = render_scene(gl, 2.0)
    gr = scene("guijia", cam=2.0)
    right = render_scene(gr, 2.0)
    save_compare("34_persp_changshe_vs_guijia.png", left, right,
                 "长蛇：单列纵深（同 v）", "龟甲：3×3 方阵足迹")

    # 35 三棱柱侧厚与坡底截面：相机 0 / 4 对比
    gc = scene("fengshi", cam=0.6)
    a = render_scene(gc, 0.6)
    b = render_scene(gc, 4.2)
    save_compare("35_persp_prism_side.png", a, b,
                 "相机 u=0.6：坡底截面移出屏右", "相机 u=4.2：坡底截面进入画面")

    # 36 俯视 3/4 角色特写
    close = pygame.Surface((OUT_W, 620))
    close.fill((20, 14, 16))
    pygame.draw.rect(close, (44, 30, 26), (24, 48, OUT_W - 48, 520), 2)
    heroes = (("wusong", "武松"), ("linchong", "林冲"), ("likui", "李逵"))
    for i, (hid, name) in enumerate(heroes):
        img = pygame.image.load(os.path.join(
            r.ASSET_ROOT, "sprites", hid, "top_idle_0.png")).convert_alpha()
        big = pygame.transform.scale(img, (img.get_width() * 3,
                                           img.get_height() * 3))
        close.blit(big, (110 + i * 610, 300 - big.get_height() // 2))
        label(close, name, 110 + i * 610 + big.get_width() // 2, 516,
              size=26)
        label(close, "头顶 / 肩线 / 武器投影", 110 + i * 610
              + big.get_width() // 2, 550, size=14, color=(196, 176, 152))
    pygame.image.save(close, os.path.join(SHOTS, "36_persp_topdown_closeup.png"))

    # 37 Boss 台基上下对比
    gp = scene("menghu", cam=5.2, boss_platform=True)
    gp.boss.x = gp.boss.platform_x
    up = render_scene(gp, 5.2)
    gd = scene("menghu", cam=5.2, boss_platform=False)
    gd.boss.x = gd.boss.platform_x + 2.3
    gd.boss.v = -2.4
    down = render_scene(gd, 5.2)
    save_compare("37_boss_platform_updown.png", up, down,
                 "Boss 在台基上（台厚 34px）", "Boss 被击落台下（低 34px）")

    print("[shots]", os.path.join(SHOTS, "33_persp_full_formation.png"))
    print("[shots]", os.path.join(SHOTS, "34_persp_changshe_vs_guijia.png"))
    print("[shots]", os.path.join(SHOTS, "35_persp_prism_side.png"))
    print("[shots]", os.path.join(SHOTS, "36_persp_topdown_closeup.png"))
    print("[shots]", os.path.join(SHOTS, "37_boss_platform_updown.png"))

    # 38–42 第 13 轮验收图（全景 / 纵深 / 地面收敛 / 街市 / Boss 广场）
    shot_long_panorama()
    shot_depth_three_heroes()
    shot_ground_convergence()
    shot_market_scene()
    shot_boss_plaza()

    print("[shots]", os.path.join(SHOTS, "38_long_panorama.png"))
    print("[shots]", os.path.join(SHOTS, "39_depth_three_heroes.png"))
    print("[shots]", os.path.join(SHOTS, "40_ground_convergence.png"))
    print("[shots]", os.path.join(SHOTS, "41_market_scene.png"))
    print("[shots]", os.path.join(SHOTS, "42_boss_plaza.png"))

    # 43–46 第 14 轮：三档焦距 / 道具档位条 / 道具遮挡 / 街市旗阵
    shot_zoom_compare()
    shot_prop_bands()
    shot_prop_occlusion()
    shot_market_flags()
    for name in ("43_zoom_compare.png", "44_prop_bands.png",
                 "45_prop_occlusion.png", "46_market_flags.png"):
        print("[shots]", os.path.join(SHOTS, name))
    print("SHOTS: OK 43..46")


if __name__ == "__main__":
    main()
