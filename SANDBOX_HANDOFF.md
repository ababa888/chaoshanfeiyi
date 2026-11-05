# 沙盒代码交接文档（2026-10-30）

> 项目：《踏鼓 / Project Drumbeat》→ Patapon 阵列模式。代码根目录：
> `e:\chaoshanfeiyi\YingGeGame-main\YingGeGame-main\drumbeat-m0\`
> 纪律红线：**`judgement.py` 判定数学逻辑绝对禁止修改**（只能改调用方）。
> 2026-10-30 起用户已授权改造主项目：原单角色跑打逻辑由开关 `MODE` 封装保留
> （`config.py`，`DRUMBEAT_MODE` 环境变量，`PATAPON` 阵列指挥 = 默认 / `CLASSIC` = M0 原模式），
> 未物理删除，可随时回滚对比。

---

## 0. 沙盒资产清单（3 个文件，全部未跟踪、可独立运行）

| 文件 | 状态 | 说明 |
|---|---|---|
| `sandbox_patapon.py` | S1–S4 全过（`SANDBOX: PASS`） | 无头逻辑沙盒：拍量化行军/逐拍判定/四相循环/阵型数值/Boss破阵/成长扩编 |
| `sandbox_formations.json` | 稳定 | 三阵型槽位+数值+成长表（生成器与规范槽位加载时互校验） |
| `advanced_squad_renderer.py` | 语法通过，未实机运行 | 可视化渲染层（本机 Python 3.11 缺 pygame，需 `py -m pip install pygame`） |

---

## 1. `advanced_squad_renderer.py` 已实现的类

| 类 | 核心功能 |
|---|---|
| `SpriteBank` | 贴图库。真实 PNG 优先（`assets/characters/player/{chui,luo,dun}_{run_0,run_1,attack}.png`），失败自动生成程序化英歌武士后备帧。**base/ghost(30%α)/glow(金色加法) 三变体启动期一次烘焙**，渲染循环零 transform。`get(utype, frame, variant)` |
| `FormationLerp` | 变阵插值。`morph_to(new_slots)` 触发；交错窗口（0.07s/人）+ `ease_out_cubic`，波浪式逐人就位。`positions()` 返回当前帧槽位 |
| `ScreenShake` | 震屏。trauma² 衰减模型，`add(amount)` / `offset()`；0.2s 衰减完，只偏移最终 blit 不动实体 |
| `AfterimageTrail` | 残影。0.055s 间隔快照全队位置，TTL 0.3s，用预烘焙 ghost 变体回放 |
| `SparkPool` | 打击火花。`burst(x,y,n,color)`；速度衰减×0.90 + 微重力 + 透明度渐隐，硬上限 220 粒 |
| `FeverFX` | 满堂彩滤镜。预烘焙径向红晕 vignette + `draw_ring()` 脚下逐拍扩散冲击波 |
| `AdvancedSquadRenderer` | 主渲染器。`render(screen, positions, utypes, anchor, beat, bpm, fever, dashing, attack_beat, dt)`；绘制序：残影→光环→单位→火花→滤镜→震屏上屏。`on_attack(x,y,perfect)` 外部事件钩子（火花+震屏） |
| 模块级函数 | `ease_out_cubic(p)` / `leap_y(p)` 跃起抛物线（落地卡拍）/ `march_bob(beat)` 整数像素三角摆动 / `FORMATION_SLOTS` 三阵型槽位生成器 |

**依赖注入设计**：renderer 不 import 项目任何模块，`beat` 拍相位由外部喂入；对接时接 `MusicDirector.beat_pos` 即可。踩点动画：`run_0/run_1` 由 `int(beat)%2` 切换，attack 帧仅在 `[attack_beat, +1拍)` 窗口。

## 2. 已完成的视觉特效

- **震屏**：Perfect/攻击触发，0.1–0.2s，trauma² 衰减，整屏偏移
- **残影拖尾**：长蛇阵（dashing）或 Fever 时常驻，预烘焙 ghost 变体
- **打击火花**：纯色圆点粒子，速度衰减+透明度降低+微重力
- **满堂彩滤镜**：红色径向渐晕（屏幕边缘）+ 脚下冲击波光环 + 全队 `BLEND_ADD` 金色发光
- **拍相位动画**：行军 bob（整数拍归零）、run 帧踩点切换、跃起劈山抛物线落地卡拍
- **变阵缓动**：ease-out-cubic + 交错窗口的"发力感"变形

**性能纪律**（报告 §7.4，必须继续遵守）：渲染循环内零 transform / 零 set_alpha / 零新 Surface；SRCALPHA 覆盖层 ≤2 层（现用 1 层）；bob 偏移整数像素。

## 3. ~~严重 Bug~~ 已修复（2026-10-30）：输入逻辑已切换为 4 拍指令管线

- 旧测试入口的 1/2/3 直切阵型、Space 出招、F/↑↓ 调试键已全部删除。
- 现状：`main()` 为真实四相循环（输入 → 应答唱和 → 执行 → 输入），J/K/L/S 击鼓进
  `RhythmCommander` 缓冲池（上限 4 次/小节、拒绝同拍连点），小节末 `evaluate()` 匹配
  `COMMANDS`；成功 → 下一执行小节触发特效，失败 → 乱阵一小节（急停+散射+闪烁+破音）。
- 拍源：真实 `AudioEngine` 优先（鼓点/唱和/反馈音可闻），失败自动降级 `NullAudioEngine`
  虚拟时钟；判定与渲染共用同一 `SandboxMusic.beat_pos`。
- 满堂彩：连续 2 小节全 PERFECT 触发 `fever=True`（视效沿用 FeverFX）。
- 回归：`py_compile` OK；`py sandbox_patapon.py` 全绿（S1–S4 PASS）；`git status` 仍只有
  3 个未跟踪沙盒文件。本机无 pygame，实机联调待有 pygame 的环境执行。

## 4. 本次落地的 4 拍指令输入层（对应原待办 1–5，已全部完成）

1. **接拍缓冲池**：KEYDOWN(J/K/L/S) 记录 `(key, 音频时刻)`，每小节最多 4 次，
   同拍连点（round(beat_at) 不递增）直接拒绝；击键即时出鼓声（J=咚/K=台/L=才/S=号角）。
2. **踩点判定**：`RhythmCommander.on_press` 内部走 `grade_beat_press` 平行判定
   （perfect ±40ms / good ±80ms，DATA.judgement）；脱拍额外播闷音 `feedback["off"]`。
3. **指令匹配 → 特效绑定**：JJJJ→执行小节 4 拍 `on_attack` 火花+震屏+hit 音；
   KKKK→`MarchAnchor.set_mult(1.5)` 突进（地面刻度滚屏加速 + 残影）；LLLL→整小节
   马步防守姿态 + 盾墙矢量椭圆 + 预烘焙 guard 蓝光变体；KLKL→`FormationLerp.morph_to`
   循环变阵。失败 → 乱阵（`anchor.freeze` + 散射衰减 + 抽帧闪烁 + 预烘焙红闪 + 破音）。
4. **拍源切换**：`SandboxMusic(audio, bank, phase_fn=...)`（输入小节背景鼓静音），
   每帧 `music.update(0.0)`，卡顿由 tempo.py dt>0.25 守卫兜底。
5. **满堂彩条件**：`perfect_streak >= 2`（连续全 PERFECT 小节）→ fever，失误即清零。
6. **回归纪律**：已执行（见 §3 末）。

## 5. 快速恢复上下文提示词（新窗口首条消息可粘贴）

> 继续《踏鼓》Patapon 开发。请先读 `e:\chaoshanfeiyi\SANDBOX_HANDOFF.md`。主项目集成已完成（§6）：
> `DRUMBEAT_MODE=PATAPON`（默认）阵列指挥 / `CLASSIC` 单角色跑打，四路验证全绿。
> 下一步：实机联调手感与判定延迟，或推进 S5（敌人/Level 接入 PATAPON 模式，当前行军到
> GOAL_UNITS=90 即收阵结算）。红线：`judgement.py` 判定数学逻辑一字不动。

---

## 6. 主项目集成（2026-10-30 完成，四路验证全绿）

**改造方案：复用而非搬运** —— 主项目通过 sys.path 自愈 import 沙盒两件套
（`sandbox_patapon.py` / `advanced_squad_renderer.py`），单一事实源，沙盒仍独立可跑。

### 6.1 改动清单

| 文件 | 改动 | 说明 |
|---|---|---|
| `drumbeat/config.py` | +`MODE` | `os.environ.get("DRUMBEAT_MODE", "PATAPON").upper()`，含回滚注释 |
| `drumbeat/squad.py` | **新建** | `PataponGame` 编排器：`SandboxMusic` 拍源 + `RhythmCommander` 缓冲池 + `MarchAnchor` 拍量化行军 + 四相循环（input→echo 唱和→execute→input）+ 乱阵/满堂彩/收阵结算（`GOAL_UNITS=90.0`）。JKLS 击键即时出声，`ab=round(music.beat_at(t))` 拒绝同拍连点 |
| `drumbeat/hud.py` | 末尾追加 | `SquadView` 阵列渲染系统（原 `Renderer` 逐行未动）：惰性 import `AdvancedSquadRenderer((1280,720))`，管变阵/乱阵散射红闪/攻击钩子 + HUD（信息行/指令提示/收阵进度条/4 拍输入槽带评级色/判定闪字/横幅/帮助 F3） |
| `drumbeat/app.py` | MODE 分支 | `if MODE=="PATAPON"` 走 `_patapon_frame()`：**自行 `pygame.event.get()` 泵事件**（`InputManager.poll()` 会吞掉全部事件，必须绕开），`patapon.update(dt)` + `squad_view.draw(...)`；`else` 原 CLASSIC 装配与循环逐行保留（仅缩进） |
| `advanced_squad_renderer.py` | 尺寸参数化 | `FeverFX`/`AdvancedSquadRenderer` 的 `ground_y` 与地面/刻度/盾墙改用实例 `w/h`；默认 960×540 独立入口行为不变 |
| `tools/smoke_test.py` | +1 行 env | `DRUMBEAT_MODE=CLASSIC` 固定，保持单角色链路绿色 |
| `tools/smoke_patapon.py` | **新建** | PATAPON 无头冒烟：假时钟 120fps 推 10 小节，脚本化输入 `JJJJ/KKKK/JLJL(失误)`，断言攻击×4、指令成/败、echo/execute/luan 相位全覆盖、fever 曾触发、12 键全 perfect |

### 6.2 验证结果（2026-10-30 全绿）

```
py_compile 六文件                EXIT 0
py tools\smoke_test.py           SMOKE: PASS        （CLASSIC 回归）
py tools\smoke_patapon.py        SMOKE-PATAPON: PASS（新管线：相位/指令/fever/判定全覆盖）
py sandbox_patapon.py            SANDBOX: PASS      （S1–S4 沙盒回归）
DRUMBEAT_SMOKE_FRAMES=300 + SDL_VIDEODRIVER=dummy  py -m drumbeat.app   EXIT 0（实循环无异常）
```

### 6.3 已知边界 / 后续候选

- ~~PATAPON 模式暂未接入敌人与 Level~~ → **S5 已完成（见 §7）**。
- 实机手感/音频输出延迟（~93ms 已自动扣除）与满屏特效压力测试待真机联调。
- 判定锚点 = 按键时刻 `audio_time()`；`InputManager`/`Judgement` 在 PATAPON 路径完全不经过，`judgement.py` 零改动。

---

## 7. S5 关卡与战斗接入（2026-10-30 完成，六路验证全绿）

**玩法闭环**：行军 → 遭遇站桩敌群（JJJJ 击杀，阵型数值门控）→ 击杀解锁阵型
（5 杀铁壁 / 12 杀猛虎）→ 渠魁拦路（预警 + 停军 + 破阵窗口：铁壁阵且完整度 ≥0.9）
→ 两次破阵击破 → 放行收阵。队伍 HP 归零 → 全军覆灭。

### 7.1 改动清单

| 文件 | 改动 | 说明 |
|---|---|---|
| `drumbeat/data/patapon_stage.json` | **新建** | 赛道排期：goal 90、12 站桩敌人（hp25，链式覆盖排期）、Boss（x82，hp120，breakable_by=[tiebi]，approach 6） |
| `drumbeat/squad.py` | S5 重写 | 加载 stage；`StageEnemy/StageBoss`（沙盒类 + max_hp/flash/dead）；`fstats` 属性（完整度门控，乱阵/变阵中回落缺省）；行军 = 指令倍率 × 阵型速度；`_resolve_attack`（长蛇穿透/猛虎 AOE/单体最近，范围 -0.5~+2.5）；`_check_unlock`（growth.unlock_kills）；`_update_boss`（预警 freeze 停军 → 激活拍结算 → 击破 resume 放行 / 失败扣血击退再预警）；`squad_hit`（铁壁减伤 0.4 免击退）；`status` 增 defeated；变阵只在已解锁阵型间循环；完整度 = 乱阵 0 / 变阵逐人就位比例 / 否则 1 |
| `advanced_squad_renderer.py` | +`EnemyBank` | 敌人/Boss 程序化精灵（base + 白热 flash 变体，启动期预烘焙）；`render()` 增 `enemies/boss` 依赖注入参数（世界坐标→滚屏变换、头顶血条、Boss 预警红环随拍收缩）；沙盒 main() 不传参行为不变 |
| `drumbeat/hud.py` | SquadView 扩展 | 变阵参数从 squad 模块取（单一事实源）；新钩子 `on_enemy_hit/on_squad_hit/on_boss_break`；HUD 增队伍 HP 条、击杀/解锁行、Boss 血条；受击红闪；defeated 结算屏；帮助更新 |
| `drumbeat/app.py` | 摘要行 | PATAPON 退出摘要加 击杀/破阵 |
| `tools/smoke_s5.py` | **新建** | 全流程无头验收：完美玩家剧本（JJJJ 决策带 [a+12, a+18.5] / Boss 段 KLKL→LLLL） |

### 7.2 关键设计教训（相位网格）

行军所有周期位移都是 1.5 整数倍拍 ⇒ 敌人与攻击拍点（间距 1.5 单位）的相位对齐**设计期锁死**，
freeze/stride/击退都不改变 mod 1.5 相位。因此：敌 hp 定 25（一击必杀，窗宽 3 > 拍距 1.5 扫过必中），
排期按「execute 起点 A = 输入小节锚点 +12、命中拍点 ∈ [A, A+4.5] ⇒ 敌人 ∈ [A, A+6.5]」链式推导，
组间距 = 前组 max +13~19.5。首版 hp30 + 宽决策带已实证失败（击杀 0 → 连锁团灭），勿回退。

### 7.3 验证结果

```
py tools\smoke_s5.py        SMOKE-S5: PASS  —— 28 小节收阵：12/12 杀、三阵型全解锁、
                                                Boss 破阵 2/0、队伍无伤、40 键全 perfect
py tools\smoke_test.py      SMOKE: PASS         （CLASSIC 回归）
py tools\smoke_patapon.py   SMOKE-PATAPON: PASS（基础管线回归）
py sandbox_patapon.py       SANDBOX: PASS       （S1–S4 沙盒回归）
headless 600 帧实循环        EXIT 0
```

### 7.4 已知边界 / 后续候选

- 扩编（S4 的 8→12→16 人）未接入主项目（视图 FormationLerp 人数绑定，改造留 S6）。
- 敌人纯站桩无反击（沙盒语义）；压力全部来自 Boss 破阵窗口。
- 实机联调：JJJJ 提前量手感（决策带 [a+12, a+18.5] 约提前 2 小节）、Boss 预警可读性。
