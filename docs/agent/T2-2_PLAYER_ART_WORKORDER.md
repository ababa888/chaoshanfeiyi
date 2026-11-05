# T2-2 玩家动作素材出图工单

- 依据：`drumbeat/data/frame_data.json`、`hud._player_state`、`assets.PLAYER_FILES`、`assets/characters/player/` 现状
- 基准（U-10 已确认）：`PIXELS_PER_UNIT = 80`；角色屏幕高约 **149px**；玩家素材统一 **1/6 缩放**
- 交付边界：李玉赫负责素材、命名、`assets.py` 映射与验收意见；逐招式播放由陈圣源在 T2-1/T2-3 接入
- 图片规格：PNG-32 透明底、只做朝右、脚底中心对齐、无抗锯齿、24–32 色英歌调色板

## 一、现有资产盘点

目录：`drumbeat-m0/assets/characters/player/`

| 文件名 | 尺寸 | 现有用途（`assets.py` 逻辑键） |
| --- | --- | --- |
| `run_0.png` | 112×148 | `run` 第 1 帧 |
| `run_1.png` | 123×149 | `run` 第 2 帧 |
| `run_2.png` | 118×148 | `run` 第 3 帧 |
| `run_3.png` | 117×140 | `run` 第 4 帧 |
| `jump.png` | 93×140 | `air`（上升/下落共用） |
| `charge.png` | 87×131 | `attack`（所有攻击共用占位） |
| `death.png` | 91×115 | `death` |

**共 7 张。** 状态实际数量：

| 状态 | 张数 | 文件 |
| --- | --- | --- |
| run | 4 | `run_0` ~ `run_3` |
| jump / air | 1 | `jump.png` |
| charge / attack 占位 | 1 | `charge.png` |
| death | 1 | `death.png` |
| idle | 0 | 无，HUD 复用 `run_0` |
| fall | 0 | 无，HUD 复用 `jump.png` |
| atk_g1 / g2 / g3 | 0 | 无，HUD 统一显示 `charge.png` |
| atk_a1 / a2 | 0 | 无，同上 |
| dive / parry | 0 | 无，同上 |
| slide / dash / hurt | 0 | 无，HUD 用 `run_0` 或叠色 |
| finisher | 0 | 无，当前没有对应播放状态 |

现有素材高度 115–149px 不一致；`charge/jump/death` 是历史 1/3 缩放，需在 T4-3 统一到 1/6。

## 二、`frame_data.json` 帧数基线

参考帧率 60fps；帧序号从 `00` 开始。active 帧必须落在视觉挥槌最亮的一帧。

| 招式 | startup | active | recovery | 固定总帧数 | active 帧区间 | 建议文件名 |
| --- | --- | --- | --- | --- | --- | --- |
| `atk_g1` | 8 | 4 | 14 | 26 | 08–11 | `atk_g1_00..25.png` |
| `atk_g2` | 7 | 4 | 14 | 25 | 07–10 | `atk_g2_00..24.png` |
| `atk_g3` | 12 | 5 | 24 | 41 | 12–16 | `atk_g3_00..40.png` |
| `atk_a1` | 6 | 4 | 10 | 20 | 06–09 | `atk_a1_00..19.png` |
| `atk_a2` | 8 | 4 | 16 | 28 | 08–11 | `atk_a2_00..27.png` |
| `dive` | 10 | `until_land` | 18 | 28 + active | 建议 10–13 循环 | 待确认，见 U-12 |
| `parry` | 2 | 8 | 12 | 22 | 02–09 | `parry_00..21.png`（当前不会播放） |

无 `frame_data` 的状态（按《待完成清单》口径）：`idle` 4、`dash` 4、`slide` 4、`hurt` 3、`finisher` 8；`fall`、死亡过渡帧未定义。

## 三、`hud.py` 当前播放逻辑

`Renderer._player_state`（hud.py:231-244）当前只返回四种状态：

- `player.dead` → `death`，第 0 帧
- `combat.attack_id` → `attack`，第 0 帧，实际永远显示 `charge.png`
- `not player.on_ground` → `air`，第 0 帧，实际永远显示 `jump.png`（上升/下落不分）
- `player.sliding` → `run` 第 0 帧，并用 `yscale=0.55` 压扁
- 移动中 → `run` 4 帧，按移动距离每 0.45 单位换帧
- 静止 → `run` 第 0 帧（缺 idle）
- `dash` 没有独立状态；`hurt` 只叠色闪红；`finisher` 没有对应状态；`parry` 走 `charge.png`

**结论：即使新素材放进目录，只有先更新 `assets.py` 映射并由 T2-3 改 `_player_state`/接入 `anim.py`，才会真正播放。** 本轮李玉赫只交付素材、命名、映射表和验收意见，不擅自改播放逻辑。

## 四、出图工单（按优先级）

| 优先级 | 状态 | 张数 | 文件名 | 时序 / 动作要点 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| P0 | `idle` | 4 | `idle_00..03.png` | 4 帧循环，建议 8–10fps；呼吸、重心微动；脚底不动 | 无 |
| P0 | `fall` | 2 | `fall_00..01.png` | 跳跃顶点后下落；衣摆上扬、槌自然下垂；与 `jump` 区分 | T2-3 需拆 `air/fall` |
| P1 | `atk_g1` | 26 | `atk_g1_00..25.png` | 0–7 前摇，8–11 active（最亮挥槌），12–25 后摇 | T2-1/T2-3 |
| P1 | `atk_g2` | 25 | `atk_g2_00..24.png` | 0–6 前摇，7–10 active，11–24 后摇；起手承接 g1 后摇 | T2-1/T2-3 |
| P1 | `atk_g3` | 41 | `atk_g3_00..40.png` | 0–11 前摇，12–16 active，17–40 后摇；第三段幅度最大 | T2-1/T2-3 |
| P1 | `atk_a1` | 20 | `atk_a1_00..19.png` | 0–5 前摇，6–9 active，10–19 后摇；空中挥槌 | T2-1/T2-3 |
| P1 | `atk_a2` | 28 | `atk_a2_00..27.png` | 0–7 前摇，8–11 active，12–27 后摇；a2 末段可接 dive | T2-1/T2-3 |
| P2 | `dash` | 4 | `dash_00..03.png` | 250ms 抢步，4 个关键姿势；身体前倾、槌后收 | T2-3 |
| P2 | `slide` | 4 | `slide_00..03.png` | 400ms 矮子步，低姿；脚底仍贴地，不用 `yscale` 压扁 | T2-3 |
| P2 | `hurt` | 3 | `hurt_00..02.png` | 受击后仰/踉跄；800ms 无敌期可复用 | T2-3 |
| P2 | `dive` | 32（待确认） | `dive_00..31.png` | 0–9 前摇，10–13 active 循环，14–31 后摇；落地前保持下劈 | 需确认 active 循环 |
| P2 | `finisher` | 8（待确认） | `finisher_00..07.png` | 2 秒演出，8 帧需慢放/停留；建议 2 前摇 + 4 判定 + 2 后摇 | 需确认演出节奏 |
| P3 | `parry` | 22（暂缓） | `parry_00..21.png` | 0–1 前摇，2–9 active，10–21 后摇；当前 combat 不启动该攻击 | 需 T2-3 接对击表现 |
| P3 | `death` 过渡 | 2（可选） | `death_1.png`、`death_2.png` | 现有 `death.png` 仅 1 帧；补倒地过渡，非 frame_data 定义 | 待确认 |

合计（不含可选 death 过渡、含 parry 与 dive 建议值）：**219 张**。其中 P0+P1（idle/fall/地面三段/凌空两段）共 **146 张**，是解决“战斗像色块”的最小闭环。

## 五、统一规格

- **画布建议**：最终 **192×160 px**（源图 1152×960，按 1/6 整数下采样）；角色高 149px，脚底中心在画布底边中点。若 T4-3 另定画布，以 T4-3 为准，重导出即可。
- **缩放**：同一角色所有帧统一 1/6，禁止不同状态用不同倍率；不要用非整数缩放。
- **朝向**：只做朝右，`facing<0` 由程序翻转。
- **像素**：硬边、无抗锯齿、无模糊；调色板锁定英歌红 `#D11430`、粉白 `#FBEFF3`、金 `#D4A017`、夜蓝 `#12203A`、青绿 `#2E7D6B`。
- **一致性**：先出定妆图；每个状态用「定妆图 + 妆造照片」两张参考，只改动作段，避免长相漂移。
- **active 帧**：必须落在视觉挥槌最亮、槌头最靠前的一帧；否则判定提示与画面错位。
- **命名**：`{state}_{两位序号}.png`，序号从 `00` 开始；不得用占位图冒充正式素材。

## 六、过渡帧专项

| 过渡 | 由哪些帧承担 |
| --- | --- |
| run → idle | `idle_00..03`（循环首帧要能接 run 末帧） |
| jump 上升 → fall 下落 | `fall_00..01`；HUD 需区分 `vy` 正负 |
| idle/run → 攻击 | 各招式 startup 帧（0 起） |
| 攻击 → idle/run | 各招式 recovery 末段 |
| g1 → g2 → g3 | g1/g2 的 recovery 后段要与下一段 startup 兼容；代码在 recovery 60% 处可取消 |
| a1 → a2 → dive | a2 recovery 末段要与 dive startup 兼容 |
| run → dash / slide | `dash_00..03` / `slide_00..03` |
| 受击 → 恢复 | `hurt_00..02`，末帧回到站立姿态 |
| 死亡 | 现有 `death.png`；如需倒地过程，补 `death_1/death_2` |

## 七、`assets.py` 映射更新清单（素材到位后由李玉赫改）

当前 `PLAYER_FILES` 只有 `run / air / attack / death`。建议新增或改为：

| 逻辑键 | 文件列表 |
| --- | --- |
| `idle` | `idle_00..03.png` |
| `run` | 现有 `run_0..3.png` |
| `jump` | `jump.png` |
| `fall` | `fall_00..01.png` |
| `atk_g1` / `atk_g2` / `atk_g3` | 对应 26 / 25 / 41 张 |
| `atk_a1` / `atk_a2` | 对应 20 / 28 张 |
| `dive` | 待确认的 32 张 |
| `parry` | 22 张（暂缓接入） |
| `slide` / `dash` / `hurt` | 4 / 4 / 3 张 |
| `finisher` | 8 张 |
| `death` | 现有 `death.png`（可选加过渡帧） |

`hud._player_state` 必须由 T2-3 改为按招式 id / 物理状态返回上述键；本轮不改。

## 八、验收清单

1. 文件名、张数、帧区间与本工单一致；无缺帧、无多余占位图。
2. 所有帧画布尺寸一致（建议 192×160），脚底在同一水平线；叠加参考线检查。
3. 所有帧统一 1/6 缩放、朝右、PNG-32 透明底、无抗锯齿。
4. active 帧位于约定区间，且是挥槌最亮帧。
5. `assets.py` 映射能解析所有新键；缺图仍静默回退。
6. `python tools/smoke_test.py` 必须 `SMOKE: PASS`，完美率不低于 86%。
7. 游戏内视觉验收需等 T2-3 接入后再做 `preview.py`；在此之前不得宣称“已接入”。

## 九、待确认 / 风险

- `dive` active 循环帧数与规则（U-12）。
- `finisher` 8 帧 vs 2000ms 演出（U-12）。
- `parry` 22 帧生成后当前不会播放（U-12）。
- `death` 是否需要倒地过渡帧。
- 最终画布 192×160 是否与 T4-3 统一方案一致。
- 现有 `charge/jump/death` 为 1/3 缩放，T4-3 需统一到 1/6。
