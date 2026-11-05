# 《踏鼓》分层架构

- 只读分析；未运行构建或脚本。结论标注：[确认] 代码依据 / [推测] 命名或结构 / [未知] 未找到。
- 工程：Python + pygame 自研 2D 框架，无引擎场景系统。

## 一、分层视图

| 层 | 模块 | 职责 |
| --- | --- | --- |
| 启动层 | `run.py`、`run.bat`、`build.ps1`、`踏鼓M0.spec` | 解释器选择、异常兜底、打包入口 |
| 编排层 | `drumbeat/app.py` 的 `Game` | 装配所有子系统，驱动主循环、固定步长、状态与日志 |
| 玩法域 | `inputs`、`motion`、`combat`、`energy`、`judgement`、`tempo`、`level` | 输入语义、运动碰撞、战斗结算、鼓劲、判定、节奏、关卡与敌人 |
| 表现层 | `hud.Renderer`、`assets.Assets` | 相机、视差背景、角色/敌人绘制、HUD 与调试面板、贴图加载 |
| 平台层 | `audio.AudioEngine` / `NullAudioEngine`、`synth.Bank` | 音频时钟/混音、程序化锣鼓合成、无设备降级 |
| 数据层 | `config.Data` + `drumbeat/data/*.json` | 启动时加载 5 张 JSON，作为全局单例 `DATA` |
| 工具层 | `tools/smoke_test.py`、`tools/preview.py`、根 `tools/*.js` | 无窗口验收、渲染出图、文档转换 |

## 二、模块依赖

`app.Game` 是唯一的装配点（app.py:40-84），其余模块之间以构造注入或直接 import 建立依赖：

```text
run.py
  └─ app.Game（装配）
       ├─ config.DATA ─────────────── 5 张 JSON（启动时加载一次）
       ├─ inputs.InputManager ─────── pygame 事件/手柄
       ├─ level.Level ─────────────── config.DATA + motion.Rect
       │    └─ Enemy
       ├─ motion.PlayerBody ───────── config.DATA + level（solid/platform/hazard）
       ├─ judgement.Judgement ─────── config.DATA + tempo.MusicDirector
       ├─ tempo.MusicDirector ─────── audio.AudioEngine + synth.Bank + config.DATA
       ├─ combat.PlayerCombat ─────── config.DATA + motion.Rect（注入 judgement/energy）
       ├─ energy.DrumEnergy ───────── config.DATA
       ├─ audio.AudioEngine ───────── numpy + sounddevice（可选）
       ├─ synth.Bank ──────────────── numpy
       ├─ hud.Renderer ────────────── assets.Assets + config
       └─ assets.Assets ───────────── config.asset_dir + pygame.image
```

直接 import 关系（静态）：

| 模块 | 直接依赖 |
| --- | --- |
| `app.py` | `audio`、`combat`、`config`、`energy`、`hud`、`inputs`、`judgement`、`level`、`motion`、`synth`、`tempo` |
| `combat.py` | `config`、`motion` |
| `level.py` | `config`、`motion` |
| `motion.py` | `config` |
| `judgement.py` | `config`、`tempo` |
| `tempo.py` | `audio`、`config`、`synth` |
| `hud.py` | `assets`、`config` |
| `assets.py` | `config`、`pygame` |
| `audio.py` | `numpy`、`sounddevice`（try/except） |
| `synth.py` | `numpy` |
| `energy.py` / `inputs.py` / `config.py` | `config` / `pygame` / 标准库 |

## 三、核心数据流

```text
键盘/手柄
  → InputManager.poll(audio_time)        inputs.py:77
  → InputFrame.held / presses            inputs.py:23
  → Game._handle_input / Game._step      app.py:265 / 323
      ├─ PlayerBody.step                 motion.py:134（移动/跳跃/抢步/矮子步/AABB）
      │    └─ speed → MusicDirector.update  tempo.py:52（换板 + 鼓点调度）
      └─ PlayerCombat.press_attack       combat.py:121
           ├─ Judgement.judge(t)         judgement.py:67
           │    └─ MusicDirector.beat_at / judge_delta_ms → grade + Δt
           ├─ startup → active → recovery
           └─ _resolve_hits: damage × GRADE_MULT → Enemy.take_damage
  → Enemy.update                         level.py:61（命中 → PlayerBody.take_damage）
  → Game._step 判 goal_x / hp / hazard    app.py:323
  → Game.state: playing / dead / cleared  app.py:367-372
  → Renderer.draw_world / draw_hud        app.py:375-380
  → 画面 + HUD；退出导出 playtest CSV     app.py:437
```

时间基准：`AudioEngine.audio_time()` 是输入时间戳与判定的唯一时间源；运动使用固定步长 `FIXED_DT = 1/120`，与渲染帧率解耦（config.py:9、app.py:166-201）。[确认]

## 四、架构约束

1. `judgement.py` 与 ADR-001 的四条约定是判定核心，不允许在表现层或数据调整中改动（待完成清单第一节）。[确认]
2. 判定锚点默认 `keydown`，`active_frame` 仅作为可选分支（judgement.py:35、combat.py:99-102、190-194）。[确认]
3. 板式只在小节边界切换，换板逻辑集中在 `MusicDirector._maybe_switch`（tempo.py:84-95）。[确认]
4. `DATA` 是模块级全局单例，所有系统共享同一份内存数据；运行期没有重载入口（config.py:96）。[确认]
5. 战斗层通过返回 `dict` 事件与 `Game` 通信（`judge/parry/hits/hitstop_ms` 等），没有事件总线（combat.py、app.py:290-310）。[确认]

## 五、耦合与风险

- `Game` 同时负责装配、输入分发、固定步长、敌人/陷阱伤害、鼓劲、音乐推进、渲染、日志导出，是典型的 God Object；新增子系统需改 `__init__` 与 `_step`（app.py:40、323）。[确认]
- 渲染层直接读取玩法对象字段（`player.dead/on_ground/sliding`、`enemy.state/hp`），没有视图模型或场景抽象（hud.py:226-297）。[确认]
- 关卡只有单文件 `level_segment.json`，`Data` 与 `Level` 都没有按 id 加载的入口；敌人 `spec["type"]` 未被读取（config.py:50、level.py:153-158）。[确认]
- 表现层状态映射硬编码在 `hud.py`：玩家攻击一律用 `charge.png`、站立复用 `run_0`、敌人 `stun` 用 `block`（hud.py:226-239、278-279）。[确认]
- `Assets` 同步预加载全部素材，当前规模（31 项）可接受；没有异步/分包机制（assets.py:78-88）。[确认]
- 无存档、设置持久化、网络、热更新或 Mod 机制（见 SYSTEMS.md 批次 3/4）。[确认]
