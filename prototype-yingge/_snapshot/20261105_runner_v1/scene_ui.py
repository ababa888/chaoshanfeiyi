"""战前场景渲染（第十八轮）：标题 / 选将 / 新手指南 / 暂停。

全部画在 HudSurface（960×540 逻辑 → 1920×1080 物理）上：
- 只用整数坐标、整数像素边框（面板 2px、选中 4px）、纯色硬投影；
- 不做 alpha 渐变/缩放插值，悬停预览只做整数像素滑入（±6px / 每帧 2px）；
- 文本只走 pixel_font 的 16/20/24/30 输出字号阶梯。
"""
from __future__ import annotations

import pygame

import scenes
from render import HudSurface, VIEW_H, VIEW_W, hud_draw_scale

# 颜色（纯色，无半透明渐变）
INK = (12, 10, 16)
INK_A = (18, 14, 22)
INK_B = (24, 18, 26)
PANEL = (20, 16, 20, 235)
PANEL_DARK = (16, 12, 18, 240)
GOLD = (255, 204, 96)
GOLD_DIM = (146, 112, 52)
GOLD_SOFT = (212, 164, 84)
TEXT = (228, 216, 192)
MUTED = (138, 124, 106)
DIM = (88, 76, 64)
RED = (204, 56, 48)
RED_DIM = (120, 40, 36)
JADE = (104, 204, 168)
LOCK = (62, 52, 46)
LINE = (54, 44, 38)

GRADE_COLOR = {"perfect": GOLD, "good": JADE, "miss": RED, None: DIM}
GRADE_LABEL = {"perfect": "P", "good": "G", "miss": "M", None: "·"}


class SceneUI:
    # 调试开关：正式构建默认关闭；F2 热区、F3 性能浮层由 main.py 切换
    show_hotzones = False
    debug_overlay = False

    def __init__(self, renderer, screen: pygame.Surface | None = None) -> None:
        self.r = renderer
        self.fonts = renderer.fonts
        self.bank = renderer.bank
        self._cv: HudSurface | None = None
        self._cv_scale = 0
        self._bg: dict[str, HudSurface] = {}
        self._portrait: dict[tuple[str, int, int], pygame.Surface] = {}
        self._sprite: dict[tuple[str, int, int], pygame.Surface] = {}
        self._present_scale = 1.0
        self._present_off = (0, 0)
        self._present_size = (VIEW_W, VIEW_H)
        self._screen_size = (0, 0)
        self.debug_drawn = False
        if screen is not None:
            self.attach_screen(screen)

    # ------------------------------------------------------------ 基础
    def attach_screen(self, screen: pygame.Surface) -> None:
        """记录真实窗口尺寸：坐标换算只认窗口，不依赖上一帧缓存。"""
        self._screen_size = screen.get_size()
        self._layout(screen)

    def _layout(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        # 1× / 1.5× / 2× 都按实际比例换算；非 16:9 加黑边，点击同样落在黑边上不越界
        s = min(w / VIEW_W, h / VIEW_H)
        if s <= 0:
            s = 1.0
        dw, dh = int(round(VIEW_W * s)), int(round(VIEW_H * s))
        self._present_scale = s
        self._present_off = ((w - dw) // 2, (h - dh) // 2)
        self._present_size = (dw, dh)

    def _scale_for(self, screen: pygame.Surface) -> int:
        # 逻辑画布用整数倍渲染：≥2× 走 2×，1×~1.5× 走 1×，最后整体最近邻缩放到窗口
        return 2 if self._present_scale >= 1.75 else 1

    def logical_pos(self, pos: tuple[int, int]) -> tuple[int, int]:
        if self._screen_size != (0, 0):
            ox, oy = self._present_off
            dw, dh = self._present_size
            # 整数映射：物理像素 → 逻辑像素；1.5× 与黑边都不会被浮点误差带偏
            lx = (int(pos[0]) - ox) * VIEW_W // max(1, dw)
            ly = (int(pos[1]) - oy) * VIEW_H // max(1, dh)
            return (max(0, min(VIEW_W - 1, lx)),
                    max(0, min(VIEW_H - 1, ly)))
        return (int(pos[0]) // 2, int(pos[1]) // 2)

    def _canvas_for(self, screen: pygame.Surface) -> HudSurface:
        if self._screen_size != screen.get_size():
            self.attach_screen(screen)
        s = self._scale_for(screen)
        if self._cv is None or self._cv_scale != s:
            self._cv = HudSurface(VIEW_W, VIEW_H, scale=s)
            self._cv_scale = s
            self._bg.clear()
        return self._cv

    def _present(self, screen: pygame.Surface, canvas: HudSurface) -> None:
        screen.fill((0, 0, 0))
        dw, dh = self._present_size
        if (dw, dh) == pygame.Surface.get_size(canvas):
            screen.blit(canvas, self._present_off)
        else:
            screen.blit(pygame.transform.scale(canvas, (dw, dh)),
                        self._present_off)

    def _portrait_at(self, hero: str, logical: int, canvas: HudSurface):
        s = canvas._hud_scale
        key = (hero, logical, s)
        hit = self._portrait.get(key)
        if hit is None:
            src = self.bank.portraits[hero]
            size = logical * s
            hit = pygame.transform.scale(src, (size, size))
            self._portrait[key] = hit
        return hit

    def _face_at(self, hero: str, logical: int, canvas: HudSurface):
        """头像裁掉底部烘焙的两行小字，避免和我们自己的标签重复叠印。"""
        s = canvas._hud_scale
        key = (hero + ":face", logical, s)
        hit = self._portrait.get(key)
        if hit is None:
            src = self.bank.portraits[hero].subsurface((64, 24, 128, 128))
            size = logical * s
            hit = pygame.transform.scale(src, (size, size))
            self._portrait[key] = hit
        return hit

    def _sprite_at(self, img: pygame.Surface, w: int, h: int,
                   canvas: HudSurface, key: str) -> pygame.Surface:
        s = canvas._hud_scale
        cache_key = (key + f":{w}x{h}", s, 0)
        hit = self._sprite.get(cache_key)
        if hit is None:
            hit = pygame.transform.scale(img, (w * s, h * s))
            self._sprite[cache_key] = hit
        return hit

    def _blit_phys(self, canvas: HudSurface, img: pygame.Surface,
                   x: int, y: int) -> None:
        s = canvas._hud_scale
        pygame.Surface.blit(canvas, img, (x * s, y * s))

    # ------------------------------------------------------------ 调试覆盖层
    def overlay(self, screen: pygame.Surface, flow) -> None:
        """F2 热区（1px）/ F3 调试浮层；未开启时不画任何东西。"""
        self.debug_drawn = False
        if self.debug_overlay:
            self.debug_drawn = True
            w, h = screen.get_size()
            pygame.draw.rect(screen, (255, 0, 128), (0, 0, w, h), 2)
            pygame.draw.rect(screen, (255, 0, 128), (4, 4, 96, 12), 1)
        if not self.show_hotzones:
            return
        sc = self._present_scale
        ox, oy = self._present_off
        for name, (rx, ry, rw, rh) in flow.hotzones():
            r = pygame.Rect(int(ox + rx * sc), int(oy + ry * sc),
                            max(1, int(rw * sc)), max(1, int(rh * sc)))
            pygame.draw.rect(screen, (0, 255, 0), r, 1)
            pygame.draw.rect(screen, (0, 128, 0),
                             (r.x - 1, r.y - 1, r.w + 2, r.h + 2), 1)

    def _bg_for(self, kind: str, canvas: HudSurface) -> HudSurface:
        s = canvas._hud_scale
        hit = self._bg.get(kind)
        if hit is not None and hit.get_width() * s == canvas.get_width():
            return hit
        surf = HudSurface(VIEW_W, VIEW_H, scale=s)
        # 调用方已经处在 hud_draw_scale() 内，这里不能再嵌套（会二次放大坐标）
        surf.fill(INK)
        tops = {"title": (26, 20, 30), "roster": (22, 18, 26),
                "guide": (20, 17, 24), "runner": (18, 22, 30)}
        base = tops.get(kind, INK_A)
        for i, y in enumerate(range(0, VIEW_H, 24)):
            k = i / 22.0
            col = (int(base[0] * (0.55 + 0.45 * k)),
                   int(base[1] * (0.55 + 0.45 * k)),
                   int(base[2] * (0.55 + 0.60 * k)))
            pygame.draw.rect(surf, col, (0, y, VIEW_W, 24))
        seed = {"title": 7, "roster": 11, "guide": 13, "runner": 17}.get(kind, 7)
        import random
        rng = random.Random(seed)
        for _ in range(90):
            x = rng.randrange(0, VIEW_W, 4)
            y = rng.randrange(0, VIEW_H, 4)
            pygame.draw.rect(surf, (34, 28, 34), (x, y, 2, 2))
        # 上下暗边（纯色，不做半透明渐变）
        pygame.draw.rect(surf, (8, 6, 10), (0, 0, VIEW_W, 8))
        pygame.draw.rect(surf, (8, 6, 10), (0, VIEW_H - 8, VIEW_W, 8))
        if kind == "title":
            pygame.draw.circle(surf, (58, 22, 24), (480, 150), 64)
            pygame.draw.circle(surf, (86, 30, 30), (480, 150), 52)
            pygame.draw.circle(surf, (120, 40, 38), (480, 150), 40)
            pygame.draw.circle(surf, (158, 58, 48), (480, 150), 26)
        elif kind == "guide":
            pygame.draw.rect(surf, (34, 28, 34), (0, 190, VIEW_W, 2))
        elif kind == "runner":
            # 远处骑楼剪影 + 地平线；赛道滚动在 draw_runner 里按里程画
            pygame.draw.rect(surf, (26, 32, 40), (0, 300, VIEW_W, 60))
            for x in range(0, VIEW_W, 64):
                pygame.draw.rect(surf, (20, 24, 32), (x, 256, 44, 60))
                pygame.draw.rect(surf, (30, 36, 44), (x + 8, 266, 28, 50))
            pygame.draw.rect(surf, (44, 54, 52), (0, 360, VIEW_W, 180))
            pygame.draw.rect(surf, (34, 42, 42), (0, 392, VIEW_W, 2))
        self._bg[kind] = surf
        return surf

    def _t(self, canvas, text, size, color, pos, **kw):
        # 场景 UI 统一单层描边：小字叠加 2px 硬投影会在 10px 网格里并进笔画，
        # 视觉上就是「同一行字被画了两遍」。投影只留给标题的大字块。
        kw.setdefault("shadow", False)
        return self.fonts.text(canvas, text, size, color, pos, **kw)

    def _panel(self, canvas, rect, fill=PANEL, border=GOLD_DIM, width=2):
        pygame.draw.rect(canvas, fill, rect)
        if border:
            pygame.draw.rect(canvas, border, rect, width)

    def _block_text(self, canvas, text, color, center, mult=3):
        """原生 8px 字格按整数倍放大（标题专用，无重采样灰边）。"""
        s = canvas._hud_scale
        cells, w = [], 0
        for ch in text:
            cell, _adv = self.fonts.glyph(ch, 8, s)
            cells.append((cell, w))
            w += cell.get_width()
        img = pygame.Surface((w + 6, 22), pygame.SRCALPHA)
        for dx, dy, col in ((2, 2, (10, 6, 12)), (0, 0, tuple(color))):
            for cell, x in cells:
                numpy_free = cell.copy()
                numpy_free.fill((col[0], col[1], col[2], 255),
                               special_flags=pygame.BLEND_RGBA_MULT)
                img.blit(numpy_free, (x + dx, 2 + dy))
        img = pygame.transform.scale(img, (img.get_width() * mult,
                                           img.get_height() * mult))
        rect = img.get_rect(center=(center[0] * s, center[1] * s))
        pygame.Surface.blit(canvas, img, rect)

    # ------------------------------------------------------------ 标题
    def draw_title(self, screen, flow, now=0.0) -> None:
        canvas = self._canvas_for(screen)
        with hud_draw_scale():
            canvas.fill((0, 0, 0, 0))
            canvas.blit(self._bg_for("title", canvas), (0, 0))
            self._block_text(canvas, "踏鼓", GOLD, (480, 150), 3)
            self._t(canvas, "潮汕英歌 · 八拍鼓阵", 10, TEXT, (480, 214),
                    center=True)
            for i, hid in enumerate(scenes.HERO_ORDER):
                x = 480 - (64 * 3 + 24 * 2) // 2 + i * (64 + 24)
                self._blit_phys(canvas, self._portrait_at(hid, 64, canvas),
                                x, 250)
                pygame.draw.rect(canvas, GOLD_DIM, (x, 250, 64, 64), 2)
                self._t(canvas, scenes.LEADER_LOADOUT[hid]["name"], 10,
                        TEXT, (x + 32, 326), center=True)
            pygame.draw.rect(canvas, LINE, (330, 356, 300, 2))
            for token, rect, label, color in (
                    ("enter", scenes.TITLE_ENTER_RECT, "ENTER  急行 · 跑酷", GOLD),
                    ("boss", scenes.TITLE_BOSS_RECT, "B  Boss 战 · 鼓阵", RED)):
                hot = getattr(flow, "hover_rect", None) == token
                bx, by, bw, bh = rect
                pygame.draw.rect(canvas, (30, 22, 20) if hot else (18, 14, 18),
                                 (bx, by, bw, bh))
                pygame.draw.rect(canvas, color if hot else GOLD_DIM,
                                 (bx, by, bw, bh), 2)
                self._t(canvas, label, 14,
                        color if hot else GOLD_SOFT, (480, by + 20), center=True)
            self._t(canvas, "ESC  退出", 10, MUTED, (480, 478), center=True)
            self._t(canvas, "选人后进急行；B 可随时切 Boss 战 · 判定窗口不变",
                    10, DIM, (480, 512), center=True)
        self._present(screen, canvas)

    # ------------------------------------------------------------ 选将
    def draw_roster(self, screen, flow, now=0.0) -> None:
        canvas = self._canvas_for(screen)
        roster = flow.roster
        with hud_draw_scale():
            canvas.fill((0, 0, 0, 0))
            canvas.blit(self._bg_for("roster", canvas), (0, 0))
            self._t(canvas, "点将 · 选领队", 14, GOLD, (64, 52))
            self._t(canvas, f"已解锁 {len(scenes.HERO_CELLS)} / "
                            f"{len(scenes.ROSTER_CELLS)}", 10, MUTED, (64, 82))
            for i in range(len(scenes.ROSTER_CELLS)):
                self._draw_cell(canvas, i, roster)
            self._draw_preview(canvas, roster)
            leader = scenes.LEADER_LOADOUT[roster.leader]
            self._t(canvas, f"领队：{leader['name']} · 其余两人仍随队上场",
                    10, TEXT, (64, 476))
            self._t(canvas, "方向键 / 鼠标悬停预览 · ENTER 选定领队 · "
                            "ESC 返回 · G 跳过指南", 10, MUTED, (64, 500))
            if roster.toast[0]:
                self._t(canvas, roster.toast[0], 10, RED, (404, 456))
        self._present(screen, canvas)

    def _draw_cell(self, canvas, index: int, roster) -> None:
        x, y, w, h = scenes.roster_cell_rect(index)
        hover = index == roster.hover
        active = index == roster.cursor
        hero = scenes.cell_player(index)
        if hero:
            border = GOLD if active else (GOLD_DIM if hover else LINE)
            self._panel(canvas, (x, y, w, h), fill=PANEL, border=border)
            # 头像只裁脸部：原画底部烘焙的两行小字会和格子标签叠在一起
            self._blit_phys(canvas, self._face_at(hero, 56, canvas),
                            x + 14, y + 8)
            if roster.leader == hero:
                pygame.draw.rect(canvas, GOLD, (x, y, w, h), 4)
                pygame.draw.rect(canvas, GOLD, (x + w - 26, y + 4, 22, 14))
                self._t(canvas, "领", 10, INK, (x + w - 15, y + 11), center=True)
            self._t(canvas, scenes.LEADER_LOADOUT[hero]["name"], 10,
                    GOLD if active else TEXT, (x + w // 2, y + 74),
                    center=True)
        else:
            self._panel(canvas, (x, y, w, h), fill=(18, 15, 20),
                        border=GOLD_DIM if hover else LINE)
            self._t(canvas, "?", 14, DIM, (x + w // 2, y + 18), center=True)
            cond = scenes.cell_spec(index).get("cond", ("", ""))
            self._t(canvas, cond[0], 10, MUTED, (x + w // 2, y + 44),
                    center=True)
            self._t(canvas, cond[1], 10, MUTED, (x + w // 2, y + 60),
                    center=True)
        if hover and not active:
            pygame.draw.rect(canvas, GOLD_SOFT, (x, y, w, h), 2)

    def _draw_preview(self, canvas, roster) -> None:
        px, py, pw, ph = scenes.ROSTER_PREVIEW
        self._panel(canvas, (px, py, pw, ph), fill=PANEL_DARK, border=GOLD_DIM)
        index = roster.preview_index()
        hero = scenes.cell_player(index)
        slide = int(roster.slide_px)
        if hero:
            load = scenes.LEADER_LOADOUT[hero]
            self._blit_phys(canvas, self._face_at(hero, 128, canvas),
                            px + 12 + slide, py + 12)
            pygame.draw.rect(canvas, GOLD_DIM, (px + 12, py + 12, 128, 128), 2)
            tx = px + 164 + slide
            self._t(canvas, load["name"], 14, GOLD, (tx, py + 18))
            self._t(canvas, f"脸谱：{load['face']}", 10, TEXT, (tx, py + 52))
            self._t(canvas, f"兵种：{load['unit']}", 10, TEXT, (tx, py + 74))
            self._t(canvas, f"技能：{load['skill']}", 10, GOLD_SOFT,
                    (tx, py + 102))
            self._t(canvas, load["effect"], 10, MUTED, (tx, py + 124))
            form = scenes.core.FORMATIONS[load["formation"]]["name"]
            self._t(canvas, f"推荐阵法：{form}", 10, JADE, (tx, py + 156))
            self._t(canvas, "初始站位", 10, DIM, (tx, py + 186))
            self._t(canvas, load["stand"], 10, TEXT, (tx, py + 206))
            self._t(canvas, "开场", 10, DIM, (tx, py + 240))
            self._t(canvas, f"「{load['line']}」", 10, TEXT, (tx, py + 260))
            if roster.leader == hero:
                self._t(canvas, "★ 领队", 10, GOLD, (px + 16, py + 300))
        else:
            spec = scenes.cell_spec(index)
            self._t(canvas, "?", 14, DIM, (px + 76, py + 86), center=True)
            pygame.draw.rect(canvas, LINE, (px + 12, py + 12, 128, 128), 2)
            tx = px + 164
            self._t(canvas, "锁定位", 14, MUTED, (tx, py + 18))
            self._t(canvas, "解锁条件", 10, DIM, (tx, py + 60))
            cond = spec.get("cond", ("", ""))
            self._t(canvas, cond[0], 10, TEXT, (tx, py + 92))
            self._t(canvas, cond[1], 10, TEXT, (tx, py + 118))
            self._t(canvas, "锁定格不可确认", 10, RED_DIM, (tx, py + 170))
            self._t(canvas, "可悬停查看条件", 10, MUTED, (tx, py + 194))

    # ------------------------------------------------------------ 指南
    def _stamp_at(self, logical: int, canvas: HudSurface) -> pygame.Surface:
        s = canvas._hud_scale
        key = ("stamp", logical, s)
        hit = self._portrait.get(key)
        if hit is None:
            size = logical * s
            hit = pygame.transform.scale(self.bank.guide_stamp, (size, size))
            self._portrait[key] = hit
        return hit

    def _button(self, canvas, rect, label, enabled, hot=False) -> None:
        x, y, w, h = rect
        fill = (32, 24, 20) if (enabled and hot) else \
            ((26, 20, 18) if enabled else (16, 12, 14))
        border = (GOLD if (enabled and hot) else
                  (GOLD_SOFT if enabled else DIM))
        pygame.draw.rect(canvas, fill, (x, y, w, h))
        pygame.draw.rect(canvas, border, (x, y, w, h), 2)
        self._t(canvas, label, 10, GOLD if enabled else DIM,
                (x + w // 2, y + h // 2 - 6), center=True)

    def _mini_key(self, canvas, x, y, key, color, w=24, h=18) -> None:
        pygame.draw.rect(canvas, (14, 11, 16), (x, y, w, h))
        pygame.draw.rect(canvas, color, (x, y, w, h), 2)
        self._t(canvas, key, 10, color, (x + w // 2, y + 2), center=True)

    def _slot_row(self, canvas, x, y, slots, key) -> None:
        for n in range(4):
            sx = x + n * 58
            slot = slots[n] if n < len(slots) else None
            grade = getattr(slot, "grade", None) if slot else None
            col = GRADE_COLOR[grade]
            pygame.draw.rect(canvas, (14, 11, 16), (sx, y, 40, 30))
            pygame.draw.rect(canvas, col, (sx, y, 40, 30), 2)
            if slot is None:
                self._t(canvas, key, 10, DIM, (sx + 20, y + 7), center=True)
            else:
                self._t(canvas, GRADE_LABEL.get(grade, "·"), 10, col,
                        (sx + 20, y + 7), center=True)

    def draw_guide(self, screen, flow, now=0.0) -> None:
        canvas = self._canvas_for(screen)
        guide = flow.guide
        with hud_draw_scale():
            canvas.fill((0, 0, 0, 0))
            canvas.blit(self._bg_for("guide", canvas), (0, 0))
            if guide is None:
                self._present(screen, canvas)
                return
            self._t(canvas, "新手 · 鼓点入门", 14, GOLD, (64, 48))
            # 左栏步骤：悬停高亮 + 已完成印章（不再用缺字的 ✓/过）
            self._panel(canvas, (56, 86, 248, 396), fill=PANEL_DARK,
                        border=LINE)
            for i, step in enumerate(scenes.GUIDE_STEPS):
                x, y, w, h = scenes.guide_step_rect(i)
                cur = i == guide.step
                done = guide.done[i]
                hover = flow.guide_hover == i or flow.hover_rect == f"step{i}"
                pygame.draw.rect(canvas, (26, 20, 20) if hover
                                 else (14, 11, 16), (x, y, w, h))
                if cur:
                    pygame.draw.rect(canvas, GOLD, (x, y, w, h), 2)
                elif hover:
                    pygame.draw.rect(canvas, GOLD_SOFT, (x, y, w, h), 2)
                col = GOLD if cur else (JADE if done else MUTED)
                self._t(canvas, f"{i + 1}", 10, col, (x + 14, y + 16))
                self._t(canvas, step["title"], 10, col, (x + 42, y + 14))
                if done:
                    self._blit_phys(canvas, self._stamp_at(20, canvas),
                                    x + 174, y + 28)
                    self._t(canvas, "过", 10, GOLD, (x + 184, y + 38),
                            center=True)
                elif cur:
                    self._t(canvas, ">", 10, GOLD, (x + 192, y + 16))
            self._t(canvas, "J / K / L · ENTER · G 跳过", 10, DIM,
                    (68, 464))
            # 右侧内容：大鼓主视觉
            step = scenes.GUIDE_STEPS[guide.step]
            self._panel(canvas, (324, 86, 580, 396), fill=PANEL,
                        border=GOLD_DIM)
            self._t(canvas, step["title"], 14, GOLD, (348, 100))
            self._t(canvas, f"第 {guide.step + 1} / {len(scenes.GUIDE_STEPS)} 步",
                    10, MUTED, (348, 124))
            self._t(canvas, step["hint"], 10, TEXT, (348, 144))
            self._t(canvas, f"目标：{step['goal']}", 10, MUTED, (348, 164))
            pygame.draw.rect(canvas, LINE, (348, 182, 532, 2))
            # 跳过整段（始终可点，热区与视觉一致）
            hot_skip_all = flow.hover_rect == "skip_all"
            self._button(canvas, scenes.GUIDE_SKIP_ALL_RECT, "跳过",
                         True, hot_skip_all)

            # 触键反馈：对应乐器当帧下沉 4px（和战斗里的下沉一致）
            flash = {k: (guide.flash_key == k and now < guide.flash_until)
                     for k in ("J", "K", "L")}
            dy = 4 if flash["J"] else 0
            self._blit_phys(canvas, self.bank.guide_gong, 416,
                            210 + (4 if flash["K"] else 0))
            self._blit_phys(canvas, self.bank.guide_cymbal, 746,
                            210 + (4 if flash["L"] else 0))
            self._blit_phys(canvas, self.bank.guide_drum, 492, 190 + dy)
            for key, rect in scenes.GUIDE_KEY_RECT.items():
                off = 4 if flash[key] else 0
                if flow.hover_key == key:
                    pygame.draw.rect(canvas, GOLD_SOFT, rect, 2)
                if key == "J":
                    pygame.draw.rect(canvas, (16, 12, 16),
                                     (596, 312 + off, 28, 22))
                    pygame.draw.rect(canvas, GOLD, (596, 312 + off, 28, 22), 2)
                    self._t(canvas, "J", 14, GOLD, (610, 323 + off),
                            center=True)
                else:
                    x = rect[0]
                    self._t(canvas, key, 14, GOLD, (x + 29, 286 + off),
                            center=True)
                    self._t(canvas, "锣行" if key == "K" else "钹守",
                            10, GOLD_SOFT, (x + 29, 300 + off), center=True)
            # 鼓面 4 拍刻度：当前拍高亮
            beat = int(guide.clock.beat_pos) % 4
            for n, (tx, ty) in enumerate(scenes.GUIDE_TICKS):
                ty += dy
                if n == beat:
                    pygame.draw.rect(canvas, GOLD, (tx - 10, ty - 10, 20, 20))
                    pygame.draw.rect(canvas, RED, (tx - 7, ty - 7, 14, 14))
                    pygame.draw.rect(canvas, GOLD_SOFT, (tx - 3, ty - 3, 6, 6))
                else:
                    pygame.draw.rect(canvas, GOLD_DIM,
                                     (tx - 6, ty - 6, 12, 12))
                    pygame.draw.rect(canvas, GOLD_SOFT,
                                     (tx - 3, ty - 3, 6, 6))
            self._draw_guide_strip(canvas, guide)
            # 绸带进度：6 个节点
            self._blit_phys(canvas, self.bank.guide_ribbon, 348, 386)
            for i in range(len(scenes.GUIDE_STEPS)):
                nx = 348 + 30 + i * 94
                ny = 386 + 11
                if i < guide.step:
                    pygame.draw.polygon(canvas, JADE, [(nx, ny - 8),
                                                       (nx + 8, ny), (nx, ny + 8),
                                                       (nx - 8, ny)])
                elif i == guide.step:
                    pygame.draw.polygon(canvas, GOLD, [(nx, ny - 9),
                                                       (nx + 9, ny), (nx, ny + 9),
                                                       (nx - 9, ny)])
                    pygame.draw.polygon(canvas, INK, [(nx, ny - 5),
                                                      (nx + 5, ny), (nx, ny + 5),
                                                      (nx - 5, ny)])
                else:
                    pygame.draw.polygon(canvas, MUTED, [(nx, ny - 7),
                                                       (nx + 7, ny), (nx, ny + 7),
                                                       (nx - 7, ny)], 2)
            msg = guide.msg[0] or (flow.toast[0] if flow.toast[1] > now else "")
            if msg:
                col = RED if ("晚" in msg or "早" in msg or "Miss" in msg
                              or "先完成" in msg) else JADE
                self._t(canvas, msg, 10, col, (348, 412))
            # 完成印章
            if guide.done[guide.step]:
                self._blit_phys(canvas, self._stamp_at(64, canvas), 824, 190)
                self._t(canvas, "过", 20, GOLD, (856, 222), center=True)
            # 底栏按钮：文字与热区同一矩形
            if guide.step == 5:
                if guide.done[5]:
                    next_label, next_ok = "完成校准", True
                else:
                    next_label, next_ok = "开始校准", True
                skip_label = "跳过校准" if not guide.done[5] else "跳过指南"
            else:
                next_label, next_ok = "下一步", guide.next_enabled
                skip_label = "跳过指南"
            self._button(canvas, scenes.GUIDE_NEXT_RECT, next_label, next_ok,
                         flow.hover_rect == "next")
            self._button(canvas, scenes.GUIDE_SKIP_RECT, skip_label, True,
                         flow.hover_rect == "skip")
        self._present(screen, canvas)

    def _draw_guide_strip(self, canvas, guide) -> None:
        x, y, w, h = scenes.GUIDE_STRIP_RECT
        pygame.draw.rect(canvas, (14, 11, 16), (x, y, w, h))
        pygame.draw.rect(canvas, LINE, (x, y, w, h), 2)
        if guide.step == 0:
            self._t(canvas, "点鼓面（或按 J）· 触键音 + 乐器下沉",
                    10, TEXT, (x + 14, y + 12))
        elif guide.step == 1:
            slots = guide.slots
            if guide.done[1] and not slots:
                # 一组完成后保留 4 个落定位，避免「已落定 0/4」和完成印章自相矛盾
                slots = [scenes.core.Slot(key="J", grade="good", dt_ms=0,
                                          beat=0) for _ in range(4)]
            self._slot_row(canvas, x + 14, y + 4, slots, "J")
            self._t(canvas, f"已落定 {len(slots)} / 4", 10,
                    GOLD if guide.done[1] else MUTED, (x + 262, y + 11))
        elif guide.step == 2:
            self._t(canvas, "J 鼓攻 · K 锣行 · L 钹守", 10, TEXT,
                    (x + 14, y + 12))
            prog = "  ".join(f"{k} {len(guide.three[k])}/4"
                             for k in ("J", "K", "L"))
            self._t(canvas, prog, 10, GOLD if guide.done[2] else MUTED,
                    (x + 250, y + 12))
        elif guide.step == 3:
            forms = ((("J", "K", "J", "K"), "锋矢", 0),
                     (("L", "K", "L", "K"), "龟甲", 1))
            for n, (seq, name, idx) in enumerate(forms):
                ry = y + 2 + n * 18
                done = guide.form_index > idx or guide.done[3]
                self._t(canvas, name, 10, JADE if done else TEXT,
                        (x + 14, ry + 1))
                for k, key in enumerate(seq):
                    cur = (not done and guide.form_index == idx
                           and k == len(guide.slots))
                    self._mini_key(canvas, x + 124 + k * 30, ry, key,
                                   JADE if done else (GOLD if cur else DIM))
        elif guide.step == 4:
            intent = scenes.core.INTENTS[scenes.GUIDE_INTENT]
            self._blit_phys(canvas, self.bank.guide_boss, x, y)
            self._t(canvas, intent["name"], 10, RED, (x + 50, y + 12))
            for n in range(4):
                sx = x + 300 + n * 56
                slot = guide.slots[n] if n < len(guide.slots) else None
                grade = getattr(slot, "grade", None) if slot else None
                col = GRADE_COLOR[grade]
                self._mini_key(canvas, sx, y + 8, "K", col, 40, 22)
        elif guide.step == 5:
            if guide.done[5]:
                self._t(canvas, f"平均偏移 {guide.calib_ms:+d}ms", 10, GOLD,
                        (x + 14, y + 4))
                advice = ("建议输入提前 %dms" % guide.calib_ms
                          if guide.calib_ms > 0 else
                          "建议输入延后 %dms" % -guide.calib_ms
                          if guide.calib_ms < 0 else "节奏很稳，无需校准")
                self._t(canvas, advice + " · 已写入配置", 10, JADE,
                        (x + 14, y + 20))
            else:
                for n in range(8):
                    filled = n < len(guide.taps)
                    pygame.draw.circle(canvas, GOLD if filled else LINE,
                                       (x + 24 + n * 48, y + 19), 7,
                                       0 if filled else 2)
                self._t(canvas, f"已敲 {len(guide.taps)} / 8", 10, TEXT,
                        (x + 430, y + 11))

    # ------------------------------------------------------------ 急行
    def draw_runner(self, screen, flow, session, now=0.0) -> None:
        canvas = self._canvas_for(screen)
        cfg = session.cfg
        beat = session.beat
        with hud_draw_scale():
            canvas.fill((0, 0, 0, 0))
            canvas.blit(self._bg_for("runner", canvas), (0, 0))

            # 赛道：按里程滚动，纯整数像素
            scroll = int(session.distance * 12) % 64
            for x in range(-64, VIEW_W + 64, 64):
                xx = x - scroll
                pygame.draw.rect(canvas, (36, 46, 44), (xx, 396, 30, 3))
                pygame.draw.rect(canvas, (28, 36, 36), (xx + 8, 430, 16, 2))

            # 队伍：领队 + 两名好汉，按拍点上下 3px
            team = [flow.leader] + [h for h in scenes.HERO_ORDER if h != flow.leader]
            for i, hid in enumerate(team[:3]):
                frames = self.bank.heroes.get(hid, {})
                img = frames.get("march_0") or frames.get("idle_0")
                x = 196 + i * 44
                y = 330 + (0, -3, 2)[(beat + i) % 3]
                pygame.draw.ellipse(canvas, (18, 20, 18), (x - 2, y + 40, 34, 7))
                if img is not None:
                    self._blit_phys(canvas, self._sprite_at(
                        img, 30, 40, canvas, f"runner_{hid}"), x, y)

            # 头槌双敲：两下敲头顶的动作锚点
            if session.ui_flash.get("whack", -1) > beat:
                wob = 3 if (beat % 2 == 0) else -3
                for n in range(2):
                    sx = 196 + n * 8 + wob
                    self._t(canvas, "*", 20, GOLD, (sx, 306), center=True)
                self._t(canvas, "双槌", 10, GOLD, (218, 292), center=True)

            # 下一段敌阵：两列 + 明确缺口
            next_seg = session.seg + 1
            if 0 <= next_seg < len(cfg.route):
                seg = cfg.route[next_seg]
                # 当前段的终点才是下一次接触点
                end = sum(s.steps for s in cfg.route[:session.seg + 1])
                remain = end - session.distance
                if 0 < remain < 44 and not session.finished:
                    ex = 812 + int(remain * 3)
                    side = (session.warning or {}).get("gap_side", seg.gap_side)
                    gap_idx = 2
                    for col, cx in enumerate((ex, ex + 52)):
                        gap_here = (col == 0 and side == "left") or \
                                   (col == 1 and side == "right")
                        for row in range(4):
                            if gap_here and row == gap_idx:
                                pygame.draw.rect(canvas, (28, 54, 46),
                                                 (cx, 232 + row * 40, 34, 32))
                                pygame.draw.rect(canvas, JADE,
                                                 (cx, 232 + row * 40, 34, 32), 2)
                                self._t(canvas, "缝", 10, JADE,
                                        (cx + 17, 248 + row * 40), center=True)
                                continue
                            img = self.bank.enemies["grunt"]["march_0"]
                            self._blit_phys(canvas, self._sprite_at(
                                img, 34, 32, canvas, "runner_grunt"),
                                cx, 232 + row * 40)
                    self._t(canvas, f"缺口 · {'左' if side == 'left' else '右'}",
                            10, JADE, (ex + 26, 408), center=True)
                    if session.ui_flash.get("gap", -1) > beat:
                        self._t(canvas, "穿缝 +2.3 拍", 14, JADE,
                                (ex + 26, 200), center=True)
                    if session.ui_flash.get("hit", -1) > beat:
                        self._t(canvas, "撞阵 −4.2 拍", 14, RED,
                                (ex + 26, 200), center=True)
                        pygame.draw.rect(canvas, RED_DIM, (2, 2, VIEW_W - 4, VIEW_H - 4), 3)

            # 世俗民众：城镇段路边人群
            c_state = getattr(session, "culture_state", None) \
                if getattr(session, "culture_on", False) else None
            if c_state == "secular" and not session.finished:
                for i in range(8):
                    cx = 700 + i * 24 + (beat * 3 + i * 7) % 18
                    cy = 356 - ((i * 5 + beat) % 3) * 3
                    pygame.draw.circle(canvas, (116, 92, 68), (cx, cy), 5)
                    pygame.draw.rect(canvas, (74, 60, 48), (cx - 3, cy + 5, 6, 12))
                self._t(canvas, "民众", 10, GOLD, (812, 388), center=True)

            # 雨幕：求雨收集与雨 buff 期间的斜线
            rain_on = getattr(session, "rain_left", 0) > 0
            rain_collect = getattr(session, "rain_collect_left", 0) > 0
            if (rain_on or rain_collect) and not session.finished:
                col = (96, 148, 190) if rain_on else (78, 110, 138)
                for i in range(36):
                    rx = (i * 37 + beat * 9) % (VIEW_W + 40) - 20
                    ry = (i * 29 + beat * 17) % 300 + 60
                    pygame.draw.line(canvas, col, (rx, ry), (rx + 4, ry + 18), 1)

            # 顶部 HUD
            self._panel(canvas, (16, 10, 928, 46), fill=PANEL_DARK)
            self._t(canvas, "急行", 10, MUTED, (28, 20))
            self._t(canvas, self._fmt_time(session.time_s), 20, GOLD, (28, 32))
            self._t(canvas, f"阵 {cfg.form_name(session.formation)}", 14, TEXT,
                    (220, 20))
            f_now = cfg.form_f(session.formation)
            self._t(canvas, f"F {f_now:.2f} · C {self._runner_c(session):.2f}",
                    10, MUTED, (220, 40))
            gear = session.speed_gear
            mps = session.current_speed / max(1e-9, cfg.beat_s)
            self._t(canvas, f"{gear}  {mps:4.2f} m/s", 14,
                    RED if gear == "受阻" else JADE, (720, 20))
            pygame.draw.rect(canvas, LINE, (720, 40, 200, 8))
            fillw = max(4, min(200, int(200 * session.current_speed / 1.5)))
            pygame.draw.rect(canvas, JADE if gear != "受阻" else RED,
                             (720, 40, fillw, 8))

            # 当前文化态 + buff 行（不能靠玩家猜）
            if getattr(session, "culture_on", False):
                tag_col = {"holy": RED, "secular": GOLD,
                           "history": JADE}.get(c_state, TEXT)
                self._panel(canvas, (16, 58, 700, 22), fill=(18, 16, 20))
                self._t(canvas, f"环境 {session.state_label}", 12, tag_col,
                        (26, 62))
                chips = []
                if c_state == "secular":
                    chips.append("KKKK 巡游")
                    chips.append(f"人气 {session.popularity:.0f}/"
                                 f"{cfg.culture.popularity_max:.0f}")
                    chips.append(f"Fever 门槛 {session.fever_threshold}")
                    if session.guard_left > 0:
                        chips.append(f"护阵 {session.guard_left} 拍")
                if c_state == "holy":
                    chips.append("JJJJ 破邪 · LLLL 护阵")
                    chips.append(f"净化 {session.purifies} · 鼓劲 ×{session.drum_charge}")
                    if session.guard_left > 0:
                        chips.append(f"护阵 {session.guard_left} 拍")
                if c_state == "history":
                    chips.append("JJJJ 尚武 · 弱拍 J 求雨")
                    chips.append(f"武艺 {session.martial}/{cfg.culture.martial_per}"
                                 + (" 可用" if session.martial_ready else ""))
                    chips.append(f"雨 {session.rain_count}"
                                 + (f" 余{session.rain_left}" if session.rain_left > 0 else ""))
                    if session.rain_collect_left > 0:
                        chips.append(f"求雨 {session.rain_hits}/"
                                     f"{cfg.culture.rain_collect_hits}")
                if session.last_command:
                    chips.append("令 " + {"attack": "破邪", "guard": "护阵",
                                          "march": "巡游", "martial": "尚武"}.get(
                        session.last_command, session.last_command))
                self._t(canvas, "  ·  ".join(chips), 10, MUTED, (228, 63))

                # 破邪/护阵/尚武即时反馈
                if session.ui_flash.get("purify", -1.0) > session.beat:
                    self._t(canvas, "破邪 · 净化 +1", 14, GOLD, (360, 300))
                elif session.ui_flash.get("martial", -1.0) > session.beat:
                    self._t(canvas, "尚武 · 武艺 +1", 14, JADE, (360, 300))
                elif session.guard_left > 0:
                    self._t(canvas, f"护阵 · 撞阵 −{int(cfg.culture.guard_loss_cut * 100)}%",
                            14, JADE, (360, 300))

            # 分段 split：4 段 3 个切点
            for i, seg in enumerate(cfg.route):
                x = 936 - (len(cfg.route) - i) * 26
                done = i < len(session.splits)
                pygame.draw.circle(canvas, GOLD if done else LINE, (x, 72), 5,
                                   0 if done else 2)
                if done and i < len(session.splits) - 0 and i > 0:
                    pass
            for i, t in enumerate(session.splits):
                self._t(canvas, f"{i + 1} {t:4.1f}", 10, MUTED,
                        (936 - (len(cfg.route) - i) * 26 + 12, 68))

            # 遇敌预警条：提前 4 拍给出该换什么阵
            warn = session.warning
            if warn is not None and not session.finished:
                left = max(0, warn["contact_beat"] - beat)
                self._panel(canvas, (176, 88, 608, 48), fill=(42, 16, 16),
                            border=RED)
                self._t(canvas, f"遇敌 {warn['enemy_name']} · 换 "
                                f"{warn['name']} · 缺口"
                                f"{'左' if warn['gap_side'] == 'left' else '右'}",
                        12, GOLD, (190, 98))
                self._t(canvas, "3 拍内起手 · 2 拍完成变阵", 10, MUTED,
                        (190, 116))
                for n in range(4):
                    cx = 640 + n * 30
                    on = n < left
                    pygame.draw.rect(canvas, RED if on else LINE,
                                     (cx, 98, 24, 24), 0 if on else 2)
                    self._t(canvas, str(max(0, left - n)), 10,
                            TEXT if on else DIM, (cx + 12, 106), center=True)

            # 谱面带：整组提前 4 拍，单格提前 2 拍；三档显示层级
            if getattr(session, "culture_on", False) and session.beat <= 8 \
                    and not session.finished:
                self._t(canvas, "环境变了：同一个键，意思变了", 10, MUTED,
                        (480, 412), center=True)
            self._panel(canvas, (96, 424, 768, 72), fill=PANEL_DARK)
            group = session.display_group()
            if group is not None and not session.finished:
                self._t(canvas, group.label or cfg.form_name(group.formation),
                        12, GOLD, (110, 436))
                self._t(canvas, "提前 4 拍 · 单格 2 拍", 10, MUTED, (110, 456))
                self._t(canvas, f"显示：{self._runner_tier_label(cfg.display_level)}"
                                " · TAB", 10, MUTED, (110, 476))
                for i in range(len(group.keys)):
                    cell_beat = group.start_beat + i
                    visible = session.queue.cell_visible(beat, group, i)
                    cur = cell_beat == beat
                    done = cell_beat < beat
                    x = 320 + i * 96
                    y = 438
                    border = GOLD if cur else (JADE if done else LINE)
                    pygame.draw.rect(canvas, (30, 24, 28) if visible else (16, 14, 18),
                                     (x, y, 64, 48))
                    pygame.draw.rect(canvas, border, (x, y, 64, 48),
                                     4 if cur else 2)
                    if not visible:
                        continue
                    key = group.keys[i]
                    tier = cfg.display_level
                    if tier == "novice":
                        self._t(canvas, key, 20, GRADE_COLOR.get(
                            session.last_grade if cur else None) or TEXT,
                            (x + 12, y + 8))
                        self._blit_phys(canvas, self._sprite_at(
                            self.bank.instrument[key], 24, 24, canvas,
                            "pinst_" + key), x + 34, y + 16)
                    elif tier == "skilled":
                        self._blit_phys(canvas, self._sprite_at(
                            self.bank.instrument[key], 32, 32, canvas,
                            "pinst32_" + key), x + 16, y + 8)
                    else:
                        strong = (i % 2 == 0)
                        self._t(canvas, "强" if strong else "弱", 14,
                                GOLD if strong else DIM, (x + 32, y + 14),
                                center=True)


            # 底部按钮
            for token, rect, label in (
                    ("restart", scenes.RUNNER_RESTART_RECT, "R 重开"),
                    ("boss", scenes.RUNNER_BOSS_RECT, "B Boss 战"),
                    ("title", scenes.RUNNER_TITLE_RECT, "ESC 标题")):
                bx, by, bw, bh = rect
                hot = getattr(flow, "hover_rect", None) == token
                pygame.draw.rect(canvas, (34, 26, 24) if hot else (18, 14, 18),
                                 (bx, by, bw, bh))
                pygame.draw.rect(canvas, GOLD if hot else GOLD_DIM,
                                 (bx, by, bw, bh), 2)
                self._t(canvas, label, 10, GOLD if hot else GOLD_SOFT,
                        (bx + bw // 2, by + 9), center=True)

            if session.finished:
                pygame.draw.rect(canvas, (0, 0, 0, 150), (0, 0, VIEW_W, VIEW_H))
                res = session.result()
                self._panel(canvas, (240, 124, 480, 304), fill=PANEL_DARK,
                            border=GOLD, width=3)
                self._t(canvas, "急行结算", 20, GOLD, (480, 144), center=True)
                tlabel = (f"含 buff {self._fmt_time(res['time_s'])}"
                          if getattr(session, "culture_on", False)
                          else self._fmt_time(res["time_s"]))
                self._t(canvas, tlabel, 20, TEXT, (480, 174), center=True)
                if getattr(session, "culture_on", False):
                    self._t(canvas, f"不含 buff 可比 {self._fmt_time(res['time_no_buff'])}",
                            10, JADE, (480, 200), center=True)
                col = {"S": GOLD, "A": JADE, "B": TEXT}.get(res["rating"], RED)
                self._t(canvas, f"评级 {res['rating']}", 20, col, (480, 222),
                        center=True)
                self._t(canvas, f"Perfect {res['perfect_rate'] * 100:.1f}%  ·  "
                                f"撞阵 {res['hits']}  ·  变阵 {res['switches']}",
                        10, TEXT, (480, 244), center=True)
                if getattr(session, "culture_on", False):
                    self._t(canvas, f"净化 {res['purifies']}（鼓劲 ×{res['drum_charge']}）"
                                    f"  ·  求雨 {res['rain_count']}  ·  "
                                    f"尚武 {res['martial_count']}",
                            10, MUTED, (480, 260), center=True)
                splits = res["splits"]
                txt = "  ".join(f"S{i + 1} {t:.1f}s" for i, t in enumerate(splits))
                self._t(canvas, txt or "S1 —", 10, MUTED, (480, 278), center=True)
                self._t(canvas, f"平均 {res['avg_speed']:.2f} 步/拍  ·  "
                                f"缺口 {res['gaps']} 次", 10, MUTED,
                        (480, 296), center=True)
                self._t(canvas, "R 立即重开  ·  B 切 Boss 战  ·  ESC 回标题",
                        12, GOLD, (480, 336), center=True)
                self._t(canvas, "无 HP · 无失败，只比时间", 10, DIM,
                        (480, 366), center=True)
        self._present(screen, canvas)

    @staticmethod
    def _fmt_time(t: float) -> str:
        m = int(t // 60)
        return f"{m:02d}:{t - m * 60:04.1f}"

    @staticmethod
    def _runner_c(session) -> float:
        return float(getattr(session, "c_value", 1.0))

    @staticmethod
    def _runner_tier_label(level: str) -> str:
        return {"novice": "新手·完整键位", "skilled": "熟练·乐器图形",
                "master": "高手·阵法名与强弱"}.get(level, level)

    # ------------------------------------------------------------ 暂停
    def draw_pause(self, screen, flow, now=0.0) -> None:
        canvas = self._canvas_for(screen)
        with hud_draw_scale():
            canvas.fill((6, 4, 8, 196))
            self._panel(canvas, (300, 118, 360, 300), fill=PANEL_DARK,
                        border=GOLD)
            self._t(canvas, "暂 停", 14, GOLD, (480, 146), center=True)
            pygame.draw.rect(canvas, LINE, (336, 180, 288, 2))
            menu = flow.pause or scenes.PauseMenu()
            for i, item in enumerate(scenes.PAUSE_ITEMS):
                y = 210 + i * 56
                enabled = menu.enabled(i)
                hot = flow.hover_rect == f"pause{i}"
                rx, ry, rw, rh = scenes.PAUSE_ITEM_RECT
                if i == menu.sel or hot:
                    pygame.draw.rect(canvas, (26, 20, 22),
                                     (rx, ry + i * 56, rw, rh))
                col = GOLD if ((i == menu.sel or hot) and enabled) else (
                    DIM if not enabled else TEXT)
                if i == menu.sel:
                    self._t(canvas, ">", 10, col, (340, y + 2))
                self._t(canvas, item if enabled else "新手指南（已用过）",
                        10, col, (480, y), center=True)
            self._t(canvas, "方向键选择 · ENTER 确认 · ESC 继续", 10, MUTED,
                    (480, 392), center=True)
        self._present(screen, canvas)
