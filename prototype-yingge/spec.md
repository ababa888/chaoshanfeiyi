# 第 13 轮规格：单点透视收敛 + 长图三段落

> 仅动 `prototype-yingge/`；`drumbeat-m0/` 只读；不装依赖；不改判定数学。
> 运行时**禁止任意缩放**：角色/敌人/Boss/道具/阴影全部在 `gen_assets.py` 按 7 档 nearest 预烘，运行时只按档挑图。

## 1. 投影模型（最终参数）

世界平面 `(u, v)`：`u` 沿下坡（屏幕右下），`v` 横跨坡宽（正值=远侧）。深度按到近沿的距离计。

`pseudo3d.py` 常量：

```
VIEW_W, VIEW_H = 960, 540
VPX, VPY       = 360, 120      # 消失点（地平线）
KX             = 46.0          # 中性行 px/u
Y_SPAN         = 190.0         # 中性行 y 偏移（px）
FOCAL          = 4.0           # 针孔焦距（世界单位）
DEPTH0         = 6.0           # 近沿附加深度
DEPTH_GAIN     = 1.35          # v 每单位增加的深度
V_NEAR, V_FAR  = -6.0, 6.0
BAND_COUNT     = 7
```

```
depth(v) = DEPTH0 + (v - V_NEAR) * DEPTH_GAIN          # 6.0 .. 22.2
depth0   = depth(0) = 14.1
scale(v) = (FOCAL + depth0) / (FOCAL + depth(v))      # 近 1.81 / 中 1.00 / 远 0.69
sx = round(VPX + (u - cam_x) * KX * scale(v))
sy = round(VPY + Y_SPAN * scale(v) + (u - cam_x) * tilt_px() * scale(v) + dip)
tilt_px() = tan(SLOPE_DEG) * KX        # 8°/10°/12° → 6.46 / 8.11 / 9.78 px/u
```

- 仅一个消失点：常数 `u` 的边线（沿 v）必过 `(VPX, VPY)`；`v` 方向不设横向偏斜，保证单点透视。
- `SLOPE_DEG` 为模块级状态（`set_slope_deg()`），渲染每帧按当前段落写入；自测显式设置。
- 反算 `screen_to_world`：对 `s ∈ [0.55, 1.95]` 做 60 次二分求 `s`，再解析求 `u,v`；`roundtrip_px` 必须为 0。
- 删掉旧的 `U_BASE/V_BASE/PX_PER_UNIT/ORIGIN/DEPTH_SCALE 恒 1×`。
- 保留 `depth_key/depth_sorted/shadow_points/footprint_rect/rect_overlap`，新增 `visible_u_range(v, cam, pad)`、`band_index(v)`、`band_scale(i)`、`band_bounds(i)`、`vp_point()`、`cell_quad(u0,u1,v0,v1)`、`clip_screen()`。

### 档位表（近 → 远，按档中心 v 计算）

| 档 | v 区间 | 预烘倍率 |
|---|---|---|
| b0 | -6.00 .. -4.29 | 1.62 |
| b1 | -4.29 .. -2.57 | 1.34 |
| b2 | -2.57 .. -0.86 | 1.15 |
| b3 | -0.86 .. 0.86 | 1.00 |
| b4 | 0.86 .. 2.57 | 0.89 |
| b5 | 2.57 .. 4.29 | 0.80 |
| b6 | 4.29 .. 6.00 | 0.72 |

近沿极限 1.81、远沿极限 0.69。档宽 12/7≈1.714；四舍五入后的贴图尺寸写入 manifest，自测按 manifest 校验。

## 2. 预烘（`tools/gen_assets.py`）

新增 `gen_bands()`，在 `main()` 末尾调用：

- `sprites/<hero>/top_<state>_<i>.png` → `bands/b<i>/sprites/<hero>/top_<state>_<i>.png`
  尺寸 `round(w * 0.625 * band_scale)` × `round(h * 0.625 * band_scale)`（当前 144×192 → 90×120@b3）。
- `enemies/<kind>/<state>_<i>.png` → `bands/b<i>/enemies/...`，基乘 0.75。
- `boss/<state>_<i>.png` → `bands/b<i>/boss/...`，基乘 0.75。
- `props/*.png` → `bands/b<i>/props/...`，基乘 0.75。
- 阴影：直接生成 `bands/b<i>/fx/shadow.png`，宽 `round(34*band)`、高 `round(12*band)`；方向固定左下；manifest 记 `dx=-round(20*band)`、`dy=round(13*band)`。
- 缩放一律 `pygame.transform.scale`（nearest），不 smoothscale。
- `MANIFEST["bands"] = {"count":7,"scales":[...],"images":{...},"shadows":{...}}`；每张图记 `size/base_size/scale/band`。
- 生成后清理旧 `bands/`；失败/缺图时 `AssetBank` 退回基图并在启动期 nearest 缩一次。

## 3. 渲染接入（`render.py`）

- `AssetBank`：
  - `self.hero_bands[hero][b][state]`、`enemy_bands[kind][b][state]`、`boss_bands[b][state]`、`prop_bands[b][name]`、`shadow_bands[b]`。
  - `HERO_BAND_FACTOR=0.625`、`WORLD_BAND_FACTOR=0.75`。
- `Renderer._camera`：`target = squad.x + lead`；`lead = 3.4 + 1.2*clamp(streak/6)`（前视 3.4–4.6 单位）；`cam_x` 限 `[0, map_len - CAM_END_MARGIN(6)]`；`cam_dip` 固定 0（旧下压逻辑移除）。
- `Renderer._draw_ground` 改为逐格四边形：
  - v 每 `BAND_W` 一行（7 行）、u 每 `CELL_U=2.0` 一格；逐行用 `visible_u_range` 只取屏幕内 u，并裁剪到 `[0, map_len]`。
  - 每格四角 `p3d.world_to_screen`，填段落底色 + 棋格明暗（纯色，不贴纹理），1px 边线；不画整张拉伸地面。
  - 近侧厚度、远侧薄唇、坡底截面（u=map_len）沿用 `slab_*` 思路但改为透视折线；Boss 台基改为 `u 142.5..149.0、v±3.2、厚 30px、3 级台阶` 的棱柱。
- `_draw_actors`：深度按 `(-v,-u)`；角色用 `band_index(v)` 挑图，**1× blit**；`world_to_screen(u,v,cam,0)` 整数落点；屏幕外（含 pad 32px）直接跳过（可视剔除）。
- `_draw_shadow`：按档取预烘阴影，`blit` 到 `(sx+dx, sy+dy)`，不做 resize；近档影子长、远档短。
- 新增 `_draw_props`：从 `level_long.json` 的段落参数**程序化循环生成**灯笼/树/旗/牌坊/石阶/里程桩，按 `hash(tile_index)` 选变体；只生成可视 u 范围；插入 actor 排序。
- `_draw_far/_draw_mid/_build_sky`：地平线改到 `VPY=120`；远景三层视差保留，`BG_TILT` 与新坡度同向；图块循环 + 变体不一次性铺满 150 单位。
- 段落入口：`Renderer` 读 `game.segment_entry`（序号, 剩余秒），前 2.2s 在 HUD 上画「段落卡」：段名/坡度/推荐阵法/迷你路线（走标示意图，不做真缩放）。
- `perspective_debug`：`Renderer.debug_persp`（`P` 键或 `DRUMBEAT_PERSPECTIVE_DEBUG=1`）；画消失点十字、地平线、每行档位号与每个单位头顶档位号。
- `zoom`（Z 键）：不再重采样精灵；`zoom=0.75` 时 band 索引向远侧移 1 档（`band_index(v)+1` 封顶），仅作调试。
- `world_px/visible_units` 保留给背景/README，改基于 `KX*scale(0)`。

## 4. 长图数据与逻辑（`config/level_long.json` + `core.py`）

新增 `config/level_long.json`：

```
length_units: 148.0
segments:
  1 坡上林地 u0=0   u1=44  slope_deg=8  bpm=126 lantern=0.55 recommend=changshe
    gate=石阶 march_boost=1.45  waves: u=16(2), 30(3), 40(2+1 brute)
  2 坡中街市 u0=44  u1=98  slope_deg=10 bpm=132 lantern=1.00 recommend=fengshi
    gate=牌坊 march_boost=1.45  waves: u=52(3), 64(3), 76(4), 86(3+1 brute)
  3 坡底广场 u0=98  u1=148 slope_deg=12 bpm=138 lantern=0.35 recommend=menghu
    gate=石阶 march_boost=1.45  waves: u=106(3), 118(4), 128(3+1 brute), 136(3)
boss: u=142.5 platform u0=139.5 u1=147.5 v_half=3.2 thick=30 steps=3
props: mile_every=10.0 lane_spacing=5.0
```

`core.py`：

- `LEVEL = _load_json_config("level_long.json", LEVEL_DEFAULT)`；`segment_at(u)`、`segment_index_at(u)`。
- `Game.__init__`：`self.level/self.map_len/self.segment_index/self.segment_entry/self.wave_cursor`；不再硬编码 3 个敌人；按 `waves` 生成当前波（`wake_units=12` 内才唤醒），最多同时两波。
- `Enemy`：加 `dormant`（远波不更新、不参与索敌）。
- `_march_forward` 上限 = `min(map_len, 下一活敌 u - 3.6, boss.x - 3.6)`；段落 `march_boost` 乘前压步长。
- 全波清空 → 下一波；最后一波清空 → `spawn_boss`（`boss.x = boss.u`，台基）。
- 段落切换：更新 `clock.base_bpm = seg["bpm"]`（`BeatClock` 已有 0.25s 平滑）；`self.segment_entry=(i, 2.2)`。
- 击退上限、Boss 击退、`start_boss_fight` 的 14.4 硬编码改为 `map_len - 4.0`。
- 战斗判定 `squad.x` 1D 逻辑、窗口、破阵/补打数学**不动**。
- 火花/伤害数字位置改用 `p3d.world_to_screen(e.x, e.v, self.cam_x, self.cam_dip)`（`core` 可 import `pseudo3d`）。

## 5. 验收与实测

`selftest.py` 新增：

- `test_perspective_convergence()`：
  1. `scale(v)` 在 `[-6,6]` 严格递减、`scale(0)=1.0`。
  2. 7 档覆盖无空档（每档区间连续、相邻共享边界、每档可达）。
  3. 每档预烘尺寸 == `manifest.bands` 记录（hero/enemy/boss/prop/shadow 各抽 1）。
  4. `(u,v)→屏幕→(u,v)` 往返，整数像素误差 0（网格 ≥ 200 点）。
  5. 地面格四角：两组常数-u 边延长线交点 == 消失点（≤1px）。
  6. 可视剔除：屏幕外 `u=cam+40` 不可见、`u=cam+2` 可见。
  7. 相机：`cam_x ∈ [0, map_len-6]`，前视 3.4–4.6。
  8. 像素：预烘档位 PNG 的 alpha 只有 0/255（无中间 alpha）；沿用既有锐度断言。
- `test_level_long()`：长度 148 ∈ [140,160]；3 段连续；每段坡度/BPM/灯笼密度/推荐阵法存在；波次 u 单调不重叠；Boss 在第三段。
- `SELFTEST: PASS` + `tools/smoke_test.py` 回归 `SMOKE: PASS`。

新增 `tools/longrun_bench.py`：脚本手从 u=0 跑到 Boss，逐帧 `renderer.draw` 960×540；输出总时长、平均/中位/p95/峰值帧时间、胜负、破阵与补打次数。重跑 `tools/playtest_sim.py` 对比上一轮（新手改后胜率 40%、破阵 60.1%、补打 12/11）。

出图（`tools/perspective_shots.py` 扩到 38–42）：

- 38 长图全景：三段各渲一张、拼成远景缩略（标注段名/里程/坡度）。
- 39 近/中/远三人对照（同 u、v=-5/0/+5，尺寸 1.62/1.00/0.72）。
- 40 地面收敛网格（只画地面 + VP + 格线，能看出梯形收向消失点）。
- 41 坡中街市一段实景（灯笼最密、牌坊）。
- 42 Boss 广场段（台基、阵列、第三段配色）。

## 6. 交付

中文、简短：透视公式与最终系数、7 档表、预烘做法、长图结构/段落差异、性能数字、`SELFTEST/SMOKE` 输出、截图路径、已知边界（单点透视只在 v 向收敛；档位是离散尺寸；远景仍是视差贴图；Z 档仅换档不缩放）。

## 7. 已知风险

- 近沿 1.62× 精灵可能比旧版大；若与 HUD 冲突，优先调 `Y_SPAN/VPY`，不调档位。
- 透视后 v 仅影响 y，五阵的 v 展开会压成 3 行；若可读性不足，优先加 `TILT` 与段落色差，不做二次缩放。
- 长图节奏靠 `march_boost` 与波次数；实测超出 4 分钟则先降波次，不改判定窗口。
