"""单点透视（针孔）投影：世界平面 (u, v) → 960×540 屏幕。

坐标约定：
- u 沿下坡方向（屏幕右下，随坡度角倾斜）；v 横跨坡宽（正 v = 远处、屏幕偏上）。
- 深度按到近沿的距离计：depth(v) = DEPTH0 + (v - V_NEAR) * DEPTH_GAIN。
- 三档真实焦距：standard=4.0、near=3.2、far=5.0；ZOOM_GAIN = FOCAL_REF/focal。
  scale(v) = ZOOM_GAIN * (FOCAL + depth(0)) / (FOCAL + depth(v))，
  v=0 时标准/推近/拉远分别 = 1.00 / 1.25 / 0.80。
- 档位改为按“最终屏幕缩放”分档：10 档边界在整个三焦距的 scale 极值之间
  等比切分，跨焦距共用同一张预烘表；贴图按档预烘。
- 只有一个消失点 (VPX, VPY)：常数 u 的边线沿 v 延长必过该点。
- 所有屏幕落点 round 到整数；运行时不缩放贴图（按档挑预烘图）。
- 本模块不 import pygame：渲染、自测、截图脚本共用同一套数学。
"""
from __future__ import annotations

import math

VIEW_W, VIEW_H = 960, 540

# 三档真实焦距；FOCAL_REF 是标准档，也是增益基准
ZOOM_NAMES = ("standard", "near", "far")
ZOOM_FOCALS = {"standard": 4.0, "near": 3.2, "far": 5.0}
FOCAL_REF = 4.0
GROUND_ANCHOR_Y = 310.0

# 消失点 / 地平线（VPX 固定；VPY 随焦距增益移动，地面锚点固定在 310）
VPX = 360.0
FOCAL = ZOOM_FOCALS["standard"]
ZOOM_GAIN = FOCAL_REF / FOCAL            # 标准 1.0、推近 1.25、拉远 0.8
KX = 46.0 * ZOOM_GAIN                    # px / u（中性行）
Y_SPAN = 190.0 * ZOOM_GAIN               # 中性行距地平线的像素偏移
VPY = GROUND_ANCHOR_Y - Y_SPAN

# 针孔深度（固定，不随焦距变）
DEPTH0 = 6.0
DEPTH_GAIN = 1.35
V_NEAR, V_FAR = -6.0, 6.0

DEPTH_CENTER = DEPTH0 + (0.0 - V_NEAR) * DEPTH_GAIN      # 14.1
SCALE_CENTER = (FOCAL + DEPTH_CENTER) / (FOCAL + DEPTH_CENTER)  # 恒 1.0

CELL_U = 2.0
CELL_V = 1.2                 # 固定 1.2 单位/行，10 行正好覆盖 [-6, 6]
BAND_W = CELL_V              # 兼容旧调用：渲染逐行扫地面时仍按单位步长走


def _scale_for(focal: float, v: float) -> float:
    """指定焦距下的屏幕缩放（与当前全局 FOCAL 无关，供跨档极值计算）。"""
    g = FOCAL_REF / float(focal)
    return g * (float(focal) + DEPTH_CENTER) / (float(focal) + depth_raw(v))


def depth_raw(v: float) -> float:
    return DEPTH0 + (float(v) - V_NEAR) * DEPTH_GAIN


# 10 档按最终屏幕缩放等比切分，覆盖三焦距全范围的 scale 极值
BAND_COUNT = 10
BAND_MIN = min(_scale_for(f, V_FAR) for f in ZOOM_FOCALS.values())
BAND_MAX = max(_scale_for(f, V_NEAR) for f in ZOOM_FOCALS.values())
BAND_RATIO = (BAND_MAX / BAND_MIN) ** (1.0 / BAND_COUNT)

# 阴影：方向固定左下（太阳右上）；尺寸随档位缩放（近长远短）
SHADOW = {"w": 34, "h": 12, "dx": -20, "dy": 13}

# 地形棱柱（用于近侧厚度 / 远侧薄唇 / 坡底截面）
SLAB = {"thickness_px": 30, "far_lip_px": 8}

# 当前段落坡度（由渲染每帧写入；自测显式设置）
SLOPE_DEG = 10.0

CAM_END_MARGIN = 6.0
CAM_LEAD_MIN = 3.4
CAM_LEAD_MAX = 4.6


def set_slope_deg(deg: float) -> None:
    global SLOPE_DEG
    SLOPE_DEG = float(deg)


def set_focal(focal: float) -> None:
    """设置任意焦距（180ms 平滑过渡逐帧调用；无需夹到三档）。"""
    global FOCAL, ZOOM_GAIN, KX, Y_SPAN, VPY
    FOCAL = float(focal)
    ZOOM_GAIN = FOCAL_REF / FOCAL
    KX = 46.0 * ZOOM_GAIN
    Y_SPAN = 190.0 * ZOOM_GAIN
    VPY = GROUND_ANCHOR_Y - Y_SPAN


def set_zoom(name: str) -> None:
    """切换三档真实焦距：standard / near / far。"""
    set_focal(ZOOM_FOCALS[name])


def tilt_px() -> float:
    """中性行 u 每单位的屏幕 y 增量（坡度角）。"""
    return math.tan(math.radians(SLOPE_DEG)) * KX


def vp_point() -> tuple[int, int]:
    return (int(round(VPX)), int(round(VPY)))


def horizon_y() -> int:
    return int(round(VPY))


def depth(v: float) -> float:
    return DEPTH0 + (float(v) - V_NEAR) * DEPTH_GAIN


def scale(v: float) -> float:
    """针孔缩放（含焦距增益）；v=0 → 标准 1.00 / 推近 1.25 / 拉远 0.80。"""
    return ZOOM_GAIN * (FOCAL + DEPTH_CENTER) / (FOCAL + depth(v))


def band_scale_bounds(i: int) -> tuple[float, float]:
    """第 i 档的最终屏幕缩放区间（跨三焦距的绝对 scale）。"""
    i = max(0, min(BAND_COUNT - 1, int(i)))
    lo = BAND_MIN * BAND_RATIO ** i
    hi = BAND_MIN * BAND_RATIO ** (i + 1)
    return (lo, hi)


def band_bounds(i: int) -> tuple[float, float]:
    """保留旧名，现返回 scale 边界（绝对屏幕缩放）。"""
    return band_scale_bounds(i)


def band_scale(i: int) -> float:
    """该档预烘倍率（边界等比中值，10 档中心）。"""
    lo, hi = band_scale_bounds(i)
    return math.sqrt(lo * hi)


def band_scales() -> list[float]:
    return [band_scale(i) for i in range(BAND_COUNT)]


def band_index_scale(s: float) -> int:
    """最终屏幕缩放 → 档号（对数落格，越界夹紧）。"""
    s = float(s)
    if s <= BAND_MIN:
        return 0
    if s >= BAND_MAX:
        return BAND_COUNT - 1
    i = int(math.floor(math.log(s / BAND_MIN) / math.log(BAND_RATIO)))
    return max(0, min(BAND_COUNT - 1, i))


def band_index(v: float) -> int:
    """纵深 v → 档号（按当前焦距的最终屏幕缩放落格）。"""
    return band_index_scale(scale(v))


def scale_to_v(s: float) -> float:
    """把任意屏幕缩放反算成 v（闭式，使用当前焦距）。"""
    depth_v = ZOOM_GAIN * (FOCAL + DEPTH_CENTER) / max(1e-9, float(s)) - FOCAL
    return V_NEAR + (depth_v - DEPTH0) / DEPTH_GAIN


def band_v_bounds(i: int) -> tuple[float, float]:
    """第 i 档的 scale 边界反算成当前焦距下的 v 边界（升序）。"""
    lo, hi = band_scale_bounds(i)
    a, b = scale_to_v(hi), scale_to_v(lo)     # scale 大 = 近 = v 小
    return (min(a, b), max(a, b))


def band_v_center(i: int) -> float:
    """第 i 档中心 scale 反算成当前焦距下的 v 中心。"""
    return scale_to_v(band_scale(i))


def band_center(i: int) -> float:
    """兼容旧调用：档中心的 v（地面行/阴影/调试定位用）。"""
    return band_v_center(i)


def project_f(u: float, v: float, cam_x: float = 0.0,
              dip: float = 0.0) -> tuple[float, float]:
    """世界 → 屏幕的浮点投影（供内部/测试；绘制必须用 world_to_screen）。"""
    s = scale(v)
    du = float(u) - float(cam_x)
    return (VPX + du * KX * s,
            VPY + Y_SPAN * s + du * tilt_px() * s + float(dip))


def world_to_screen(u: float, v: float, cam_x: float = 0.0,
                    dip: float = 0.0) -> tuple[int, int]:
    """整数落点：所有世界层对象都走这里，禁止亚像素。"""
    sx, sy = project_f(u, v, cam_x, dip)
    return (int(round(sx)), int(round(sy)))


def screen_to_world(sx: float, sy: float, cam_x: float = 0.0,
                    dip: float = 0.0) -> tuple[float, float]:
    """屏幕 → 世界反算（闭式解，与 world_to_screen 互逆）。

    由 dy = Y_SPAN*s + du*tilt*s 且 dx = du*KX*s 得：
      s  = (dy - dx*tilt/KX) / Y_SPAN
      du = dx / (KX*s)
    """
    dx = float(sx) - VPX
    dy = float(sy) - VPY - float(dip)
    s = (dy - dx * tilt_px() / KX) / Y_SPAN
    if s <= 1e-9:
        s = 1e-9
    # scale(v) = ZOOM_GAIN*(FOCAL+DEPTH_CENTER)/(FOCAL+depth(v)) 的反解
    depth_v = ZOOM_GAIN * (FOCAL + DEPTH_CENTER) / s - FOCAL
    v = V_NEAR + (depth_v - DEPTH0) / DEPTH_GAIN
    du = dx / (KX * s)
    return (du + float(cam_x), v)


def roundtrip_px(sx: int, sy: int, cam_x: float = 0.0,
                 dip: float = 0.0) -> int:
    """投影→反算→再投影的像素误差（期望 0）。"""
    u, v = screen_to_world(sx, sy, cam_x, dip)
    nx, ny = world_to_screen(u, v, cam_x, dip)
    return max(abs(nx - int(sx)), abs(ny - int(sy)))


def depth_key(v: float, u: float = 0.0) -> tuple[float, float]:
    """深度排序键：v 越大越远（先画）；同 v 时 u 越小越先画。"""
    return (-float(v), float(u))


def depth_sorted(items, v_of=lambda a: a[1], u_of=lambda a: a[0]):
    """按 v 从远到近排序（稳定）；同 v 按 u 从小到大。"""
    return sorted(items, key=lambda a: (-float(v_of(a)), float(u_of(a))))


def visible_u_range(v: float, cam_x: float = 0.0,
                    pad: float = 0.0) -> tuple[float, float]:
    """某一 v 行在屏幕 x∈[-pad, W+pad] 内可见的 u 范围。"""
    s = scale(v)
    u_left = float(cam_x) + (-pad - VPX) / (KX * s)
    u_right = float(cam_x) + (VIEW_W + pad - VPX) / (KX * s)
    return (min(u_left, u_right), max(u_left, u_right))


def u_to_screen_x(u: float, v: float, cam_x: float = 0.0) -> float:
    return VPX + (float(u) - float(cam_x)) * KX * scale(v)


def is_visible(u: float, v: float, cam_x: float = 0.0,
               pad: float = 32.0) -> bool:
    x = u_to_screen_x(u, v, cam_x)
    return -pad <= x <= VIEW_W + pad


def cell_quad(u0: float, u1: float, v0: float, v1: float,
              cam_x: float = 0.0, dip: float = 0.0) -> list[tuple[int, int]]:
    """地面一格的四角（整数）。近边 v0、远边 v1；返回 [近左, 近右, 远右, 远左]。"""
    return [world_to_screen(u0, v0, cam_x, dip),
            world_to_screen(u1, v0, cam_x, dip),
            world_to_screen(u1, v1, cam_x, dip),
            world_to_screen(u0, v1, cam_x, dip)]


def ground_row(u0: float, u1: float, v: float, cam_x: float = 0.0,
               dip: float = 0.0) -> tuple[tuple[int, int], tuple[int, int]]:
    return (world_to_screen(u0, v, cam_x, dip),
            world_to_screen(u1, v, cam_x, dip))


def project_uv(points, cam_x: float = 0.0, dip: float = 0.0
               ) -> list[tuple[int, int]]:
    return [world_to_screen(u, v, cam_x, dip) for u, v in points]


def slab_top(cam_x: float = 0.0, dip: float = 0.0,
             u0: float | None = None, u1: float | None = None
             ) -> list[tuple[int, int]]:
    """顶面（梯形/四边形）四角；默认取相机附近的可见段。"""
    if u0 is None:
        u0 = float(cam_x) - 6.0
    if u1 is None:
        u1 = float(cam_x) + 18.0
    return project_uv([(u0, V_FAR), (u1, V_FAR),
                       (u1, V_NEAR), (u0, V_NEAR)], cam_x, dip)


def slab_side(edge_v: float, cam_x: float = 0.0, dip: float = 0.0,
              u0: float | None = None, u1: float | None = None,
              thickness: int | None = None) -> list[tuple[int, int]]:
    """某一 v 边向下挤出厚度的侧面四边形（近侧 / 坡底截面共用）。"""
    if u0 is None:
        u0 = float(cam_x) - 6.0
    if u1 is None:
        u1 = float(cam_x) + 18.0
    th = int(SLAB["thickness_px"] if thickness is None else thickness)
    a, b = ground_row(u0, u1, edge_v, cam_x, dip)
    return [a, b, (b[0], b[1] + th), (a[0], a[1] + th)]


def slab_near_side(cam_x: float = 0.0, dip: float = 0.0,
                   u0: float | None = None, u1: float | None = None
                   ) -> list[tuple[int, int]]:
    return slab_side(V_NEAR, cam_x, dip, u0, u1)


def slab_far_lip(cam_x: float = 0.0, dip: float = 0.0,
                 u0: float | None = None, u1: float | None = None
                 ) -> list[tuple[int, int]]:
    """远侧薄唇：远边向上挤出 8px 的暗边。"""
    if u0 is None:
        u0 = float(cam_x) - 6.0
    if u1 is None:
        u1 = float(cam_x) + 18.0
    lip = int(SLAB["far_lip_px"])
    a, b = ground_row(u0, u1, V_FAR, cam_x, dip)
    return [a, b, (b[0], b[1] - lip), (a[0], a[1] - lip)]


def slab_end_side(u_end: float, cam_x: float = 0.0, dip: float = 0.0,
                  v0: float = V_NEAR, v1: float = V_FAR) -> list[tuple[int, int]]:
    """坡底横截面（u_end）：沿 v 的边向下挤出厚度。"""
    th = int(SLAB["thickness_px"])
    a = world_to_screen(u_end, v0, cam_x, dip)
    b = world_to_screen(u_end, v1, cam_x, dip)
    return [a, b, (b[0], b[1] + th), (a[0], a[1] + th)]


def _clip_len(p0: tuple[int, int], p1: tuple[int, int],
              width: int = VIEW_W) -> float:
    """线段在 [0,width] 内可见部分的长度（像素）。"""
    x0, y0 = p0
    x1, y1 = p1
    if x1 == x0:
        return 0.0
    t0 = (0 - x0) / (x1 - x0)
    t1 = (width - x0) / (x1 - x0)
    lo, hi = max(0.0, min(t0, t1)), min(1.0, max(t0, t1))
    if hi <= lo:
        return 0.0
    return math.hypot((x1 - x0) * (hi - lo), (y1 - y0) * (hi - lo))


def slab_end_visible_len(cam_x: float = 0.0, dip: float = 0.0) -> float:
    """坡底横截面在屏幕内的可见长度。"""
    th = int(SLAB["thickness_px"])
    a = world_to_screen(cam_x, V_NEAR, cam_x, dip)
    b = world_to_screen(cam_x, V_FAR, cam_x, dip)
    return (_clip_len(a, b) + _clip_len((a[0], a[1] + th),
                                        (b[0], b[1] + th)))


def slab_near_visible_len(cam_x: float = 0.0, dip: float = 0.0) -> float:
    """近侧面在屏幕内的可见长度（封顶整屏宽）。"""
    a, b = ground_row(cam_x - 6.0, cam_x + 18.0, V_NEAR, cam_x, dip)
    return min(float(VIEW_W), _clip_len(a, b))


def shadow_rect_band(i: int) -> tuple[int, int, int, int]:
    """按档中心最终屏幕缩放算预烘阴影 (dx, dy, w, h)；方向固定左下。"""
    s = band_scale(i)
    w = max(2, int(round(SHADOW["w"] * s)))
    h = max(2, int(round(SHADOW["h"] * s)))
    dx = -int(round(abs(SHADOW["dx"]) * s))
    dy = int(round(SHADOW["dy"] * s))
    return (dx, dy, w, h)


def shadow_rect(v: float) -> tuple[int, int, int, int]:
    """预烘阴影的 (dx, dy, w, h)；按 v 落档后取档中心尺寸。"""
    return shadow_rect_band(band_index(v))


def shadow_points(sx: int, sy: int, v: float = 0.0) -> list[tuple[int, int]]:
    """固定方向/长度的地面阴影块（指向左下，落在斜面上）。"""
    dx, dy, w, h = shadow_rect(v)
    return [(sx + dx, sy + dy), (sx + dx + w, sy + dy),
            (sx + dx + w, sy + dy + h), (sx + dx, sy + dy + h)]


def footprint_rect(sx: int, sy: int, w: int, h: int
                   ) -> tuple[int, int, int, int]:
    """角色脚底锚点 → 屏幕外接矩形（x, y, w, h）。"""
    return (int(sx) - w // 2, int(sy) - h, int(w), int(h))


def rect_overlap(a: tuple[int, int, int, int],
                 b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def on_screen(sx: int, sy: int, w: int = 0, h: int = 0,
              pad: int = 32) -> bool:
    """屏幕剔除：外接矩形完全在 [-pad, W+pad] × [-pad, H+pad] 之外才丢弃。"""
    return not (sx - w // 2 - pad > VIEW_W or sx + w // 2 + pad < 0
                or sy - h - pad > VIEW_H or sy + pad < 0)
