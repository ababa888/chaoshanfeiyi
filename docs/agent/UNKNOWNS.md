# 未确认项与风险（UNKNOWNS）

> 只读整理；标注 [确认] 有代码依据 / [推测] 基于命名或结构 / [未知] 未找到。
> 已解决项保留结论，仍开放的问题置顶。

## 一、仍未确认 / 待验证

### U-05 真实音频素材接入路线未确认

- 已确认 `audio.py` / `synth.py` 只做程序化合成与内存样本调度，仓库内没有 `assets/audio/`，也没有读取 wav 的代码。[确认]
- 未知：T3-1 的四档锣鼓录音是否已有外部素材、后续由谁接入及如何与音频时钟对齐。
- 下一步：确认素材归属后，再决定改 `Bank` 还是新增音频文件加载层（不读音频内容）。

### U-08 发布规则与版本标识未确认

- `drumbeat/__init__.py:3` 有 `__version__ = "0.1.0"`，但 `build.ps1` 未把它传入 PyInstaller，exe 文件名/属性不含版本。[确认]
- 未知：团队是否有版本号递增规则、渠道包命名规则或发布检查清单。
- 下一步：向组长/发布负责人确认；当前只能以文件名 `踏鼓M0.exe` 区分。

### U-09 文化参数与判定窗口待外部确认

- 极板 150 BPM 上限待非遗传承人试听确认（OQ-2）；±40 / ±80ms 判定窗口待 ≥6 名真人试玩数据确认（OQ-1）。[确认]
- 这两项不在代码层可解决，当前数值只是默认值。

### U-10 出图单位与角色缩放基准（已确认，2026-10-23）

- 确认基准：运行时 `PIXELS_PER_UNIT = 80`；角色屏幕高约 149px；玩家素材统一按 1/6 缩放。
- 说明：`40px/单位` 作为历史出图规格不再作为运行时基准；现有 `charge/jump/death` 的 1/3 缩放属于历史遗留，需在 T4-3 统一到 1/6。
- 结论：T4-3 的“缩放基准”阻塞解除；画布像素尺寸仍由 T4-3 按 149px 角色高确定。

### U-11 T4-2 远景层（已关闭，2026-10-28）

- 尝试：启用 `far_1..4` 并移除镜像中景 `mid` 后，场景从祠堂街景变成水乡村落/海滩，用户明确否决“场景切换”。[确认]
- 回退：`PARALLAX_LAYERS` 已恢复 `cloud1 + mid`；回退后 `t000/t002/t004/t006` 与 `t4_2_before` 基线 SHA256 完全一致。[确认]
- 技术保留：`_prep_layer` 对 `far*` 保留整幅画布、不做 `get_bounding_rect` 裁剪的分支保留，等待另案复用。[确认]
- 现有素材限制：保留中景时，far 层内容位于中景不透明区域，几乎不可见；把 far 层抬到天空区域又会出现浮空硬边。[确认]
- 可选另案：A. 重做一套与祠堂风格一致、内容只占天空/屋顶后方的远景素材；B. 保留中景，暂不启用现有远景，等新素材；C. 降低中景透明度或高度（改动大，需美术与玩法共同确认）。
- 路线已定：用户确认走 A 案——保留中景，重做同风格远景素材。[确认 2026-10-28]
- 进度：出图工单已建（`T4-2_FAR_LAYER_WORKORDER.md`），试产样张 `art-out/far_layer_draft1.jpg`（仅天空/云/飞鸟/远山，无建筑），待视觉确认。[确认 2026-10-28]
- 待确认：已接入并实机运行验证（2026-10-28，`far_new` 视差 0.30 / 缩放 0.5 / top -0.50）；遗留：横向平铺时镜像接缝处的云形是否自然，需实机滚动观察。

### U-12 玩家动作帧数与现有数据/播放逻辑的冲突

- `dive` 的 `active_f="until_land"` 没有固定帧数；《待完成清单》写“28 帧”，但 startup 10 + recovery 18 已经等于 28，active 没有帧位。需要确认 active 循环帧数与播放规则。
- `parry` 在 `frame_data.json` 有 22 帧，但 `PlayerCombat.press_attack` 的对击分支不启动 `parry` 攻击，当前 HUD 也不会播放；生成后可能闲置，需 T2-3 先接表现。
- `finisher` 在《待完成清单》写 8 帧，但 `feel_params.finisher_duration_ms = 2000`；8 帧不足以覆盖 2 秒演出，需要确认慢放/停留/循环策略。

## 二、已确认并关闭

| 编号 | 结论 |
| --- | --- |
| U-00 | `ENTRYPOINTS.md` 已创建，入口链为 `run.py → app.main → Game.run`。[确认] |
| U-01 | `level.py` 与 `level_segment.json` 已读；只有一种 `Enemy` 巡逻兵，`spec["type"]` 未被分派，第二种敌人/Boss 当前不存在。[确认] |
| U-02 | `hud.py` 已读；`Renderer` 负责相机、视差、角色/敌人、HUD 与面板；`Assets` 在 `Renderer.__init__` 创建并预加载。[确认] |
| U-03 | 5 张 JSON 均已读；`tempo_layers.json` 的 `min_speed/max_speed` 与 `crossfade_ms` 未被 `tempo.py` 使用，换板阈值硬编码 4.0/8.0。[确认] |
| U-04 | `assist_enabled` / `mobile` 只存在于 `judgement.py:36-37`，全仓无赋值入口，当前恒为 `False`；属未启用的预留分支，不是缺陷。[确认] |
| U-06 | `hud._player_state` 确认：攻击一律用 `charge.png`、站立复用 `run_0`、滑行用 `run_0` + 0.55 纵向缩放；敌人 `stun` 用 `block`、死亡用 `defeat_0..2`；没有逐招式帧动画。[确认] |
| U-07 | T4-2 后 `PARALLAX_LAYERS` 启用 `far_4..far_1` + `cloud1`，不再使用镜像中景 `mid`；`FOREGROUND_LAYER` 仍仅 `fore`；`cloud2`、`fore_2..4` 仍未使用；`win/win_alt/lose` 未被 HUD 使用；`pixels_per_unit`、`break_wall`、`frame_data.parry` 未被逻辑/表现层消费。[确认] |

## 三、风险清单

1. **无 CI**：仓库无 `.github/` 或任何流水线；合并/发布前只能本地跑 `python tools/smoke_test.py`。[确认]
2. **素材流程不可复现**：`art-source/picture → assets` 的脚本未入库，只有 `manifest.json` 记录参数；`build_assets.py` 尚未实现。[确认]
3. **素材缩放不一致**：`manifest.json` 中玩家 `run_0..3` 为 1/6，`charge/jump/death` 为 1/3，导致角色高度不一致（run 149px、charge 131px）。[确认]
4. **配置字段漂移**：`crossfade_ms`、`min_speed/max_speed`、`cancel_window_f`、`cancel_window_pct`、`break_wall` 等字段存在于 JSON 但未被代码读取，调参可能“改了没效果”。[确认]
5. **单关卡硬编码**：`config.Data` 固定加载 `level_segment.json`，`Level` 不支持按 id 加载；新增 L2/L3 必须改代码。[确认]
6. **表现层状态映射硬编码**：攻击动作都显示 `charge.png`，玩家 idle 复用 `run_0`，敌人受击仅叠色闪红；新增素材不会自动生效，需要改 `hud.py`。[确认]
7. **版本与发布**：`0.1.0` 未嵌入 exe；无签名、安装包、渠道包或热更新机制。[确认]
8. **无存档/设置持久化/本地化/网络/Mod/DLC**：F2 改动只在内存，中文文案硬编码在 `app.py` / `hud.py`。[确认]
9. **文档重复维护**：`AGENTS.md` 的“高风险区”摘录自本文件；新增或变更风险时需同步两处，否则新 Agent 会读到过期条目。[确认]
