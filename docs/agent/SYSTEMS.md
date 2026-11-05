# 《踏鼓》系统索引

> 只读分析；批次 1：核心运行时。结论标注：[确认] 有代码依据 / [推测] 基于命名或结构 / [未知] 未找到。
> 约束：每个系统最多读 1 个入口文件 + 3 个核心类/脚本；未覆盖部分见 `UNKNOWNS.md`。

### 运行时主循环与装配

- 职责：初始化 pygame 与全部子系统，驱动固定步长更新、渲染、暂停/重开与试玩日志导出。
- 入口：`drumbeat-m0/run.py:32` → `drumbeat-m0/drumbeat/app.py:468`（`Game.run` 在 app.py:160）
- 核心类与方法：`Game`（app.py:39；`__init__` L40、`run` L160、`_step` L323、`_render` L375、`_export_log` L437）；`FeelParam`（app.py:24）；`Data`（config.py:44）；`main`（app.py:468）
- 依赖：`audio`、`combat`、`config`、`energy`、`hud`、`inputs`、`judgement`、`level`、`motion`、`synth`、`tempo`；被 `run.py` 与 `build.ps1`/`踏鼓M0.spec` 依赖。[确认]
- 数据流：pygame 事件 → `InputManager.poll(audio_time)` → `_handle_input` → `PlayerBody`/`PlayerCombat`；`_step` 以 1/120s 固定步进 → `_render` → `display.flip`；退出时导出 `playtest_log.csv` 与 `playtest_summary.csv`。[确认]
- 扩展点：新增全局按键或面板项改 `_global_keys`（app.py:212）与 `_build_feel_params`（app.py:87）；新增子系统需在 `Game.__init__`（L40）装配并接入 `_step`（L323）。`judgement.py` 不在改动范围。[确认]
- 状态：[确认]

### 合拍判定

- 职责：以音频时钟为唯一时间源，在按键帧计算与最近判定点的 Δt，输出 perfect / good / off。
- 入口：`drumbeat-m0/drumbeat/inputs.py:77`（打时间戳）→ `drumbeat-m0/drumbeat/combat.py:121`（攻击按键）→ `drumbeat-m0/drumbeat/judgement.py:67`（`Judgement.judge`）
- 核心类与方法：`Judgement`（judgement.py:27；`judge` L67、`stats` L94、`set_anchor` L54、`set_offset_ms` L58）；`JudgeResult`（judgement.py:18）；`InputManager`（inputs.py:56；`poll` L77）；`InputFrame.first_press_time`（inputs.py:32）
- 依赖：`tempo.MusicDirector` 的 `beat_at` / `judge_delta_ms`（tempo.py:118/186）；`config.DATA.judgement`；被 `combat.py`、`app.py`、HUD 使用。[确认]
- 数据流：pygame 事件 → `InputManager.poll(t)` 记录按键音频时间 → `first_press_time("attack")` → `Judgement.judge(audio_time)` → `beat_at` → `judge_delta_ms` → grade → 战斗倍率与音效反馈。[确认]
- 扩展点：窗口数值改 `data/feel_params.json` 的 `judgement.perfect_ms` / `good_ms`；新锚点需加 `anchor_options` 并补 `combat.py` 的 `active_frame` 分支；设备校准改 `user_offset_ms`。[确认]
- 状态：[确认]

### 节奏与音频

- 职责：提供音频时钟、四档板式分层离散换板、鼓点前瞻调度与程序化锣鼓合成。
- 入口：`Game.__init__` 创建 `AudioEngine` / `Bank` / `MusicDirector`（app.py:46-58）；`MusicDirector.update` 由 `Game._step` 每步调用（app.py:366）。
- 核心类与方法：`AudioEngine`（audio.py:24；`audio_time` L108、`schedule` L121）；`NullAudioEngine`（audio.py:134）；`MusicDirector`（tempo.py:18；`update` L52、`_maybe_switch` L84、`force_layer` L97、`judge_delta_ms` L186、`_schedule` L143）；`Bank`（synth.py:114）
- 依赖：numpy、sounddevice（缺失时降级）；`config.DATA` 的 `tempo_layers` 与 `beat_tables`；`tempo` 依赖 `audio` 与 `synth`；被 `app` / `judgement` / `combat` 使用。[确认]
- 数据流：`tempo_layers.json` + `beat_tables.json` → `DATA` → `MusicDirector._schedule` → `Bank` 样本 → `AudioEngine.schedule` → 音频回调混音；`audio_time()` 作为输入与判定的统一时间源。[确认]
- 扩展点：新增板式改 `data/tempo_layers.json` + `data/beat_tables.json`（各板式事件偏移/数量必须一致，config.py:58-65 会校验）；换真实录音需改 `Bank`/`AudioEngine`（当前无 wav 读取逻辑，见 UNKNOWNS）。[确认]
- 状态：[确认]

### 运动与碰撞

- 职责：固定步长 1/120s 的横版移动、AABB 碰撞、跳跃/二段跳、抢步、矮子步与坑洞死亡。
- 入口：`drumbeat-m0/drumbeat/motion.py:134`（`PlayerBody.step`），由 `Game._step`（app.py:333）调用。
- 核心类与方法：`Rect`（motion.py:16；`overlaps` L38）；`PlayerBody`（motion.py:43；`step` L134、`aabb` L79、`request_jump` L95、`request_dash` L98、`take_damage` L110、`respawn` L120、`_move_and_collide` L216）
- 依赖：`config.DATA.motion/assist/combat`；`level.solid_rects` / `platform_rects` / `world`；被 `combat`（hitbox）与渲染层使用。[确认]
- 数据流：`InputFrame.held` → `Game._step` 计算 `dir_x` → `PlayerBody.step` → 查询关卡碰撞矩形 → 更新 `x/y/vx/vy` → 渲染；`speed` 同时驱动换板与鼓劲积累。[确认]
- 扩展点：手感数值改 `data/feel_params.json` 的 `motion` / `assist`；新增地形类型需改 `level.py` 与 `level_segment.json`；矮子步 0.9 / 站立 1.8 的碰撞规则不得随意改。[确认]
- 状态：[确认]

### 战斗与鼓劲

- 职责：帧数据驱动的挥槌三段、凌空挥槌、劈山、命中结算、对击弹反、鼓劲槽与满堂彩。
- 入口：`Game._handle_input` → `PlayerCombat.press_attack`（combat.py:121）/ `release_finisher`（L244）；`Game._step` → `PlayerCombat.update`（L172）。
- 核心类与方法：`PlayerCombat`（combat.py:24；`press_attack` L121、`update` L172、`_resolve_hits` L213、`_resolve_aoe` L231、`release_finisher` L244、`_find_parry_target` L104）；`DrumEnergy`（energy.py:13；`add_run` L32、`add_hit` L38、`add_parry` L47、`can_finish` L70、`finisher_damage` L77）
- 依赖：`config.DATA.attacks`（frame_data.json）与 `DATA.combat/energy`；`Judgement`；`DrumEnergy`；`level.enemies`；`motion.Rect`；被 `app` 与 HUD 使用。[确认]
- 数据流：`frame_data.json` → `DATA.attacks` → `_durs` 切 startup/active/recovery；按键 → `Judgement` 评级 → `GRADE_MULT` 伤害倍率 → 命中敌人；命中/弹反 → 鼓劲；满堂彩 → 范围伤害 + 加速 + 无敌。[确认]
- 扩展点：新增招式改 `data/frame_data.json` 的 `attacks` 并在 `combat._start`/`next` 链中登记；数值改 `feel_params.json` 的 `combat` / `drum_energy`；新敌人交互需改 `level.py`（本批未读）。[确认]
- 状态：[确认]

> 批次 2：玩家/角色控制、敌人/AI、战斗/技能/数值、关卡/场景加载（只读）。

### 玩家/角色控制

- 职责：把键盘/手柄事件映射为动作语义，驱动 `PlayerBody` 的移动、跳跃、抢步、矮子步与死亡/重生。
- 入口：`drumbeat-m0/drumbeat/app.py:168`（`InputManager.poll(audio_time)`）→ `app.py:265`（`Game._handle_input`）→ `app.py:323`（`Game._step`，固定 1/120s）
- 核心类与方法：`InputManager`（inputs.py:56；`poll` L77、`_handle` L86、`set_frame_time` L142）；`InputFrame`（inputs.py:23；`just_pressed` L29、`first_press_time` L32）；`PlayerBody`（motion.py:43；`step` L134、`request_jump` L95、`request_dash` L98、`take_damage` L110、`respawn` L120）；`Game._handle_input`（app.py:265）
- 输入入口：`_KEYMAP`（inputs.py:42）映射 A/D、空格、J、L/Shift、S、F；手柄按钮映射 `_PAD_BUTTONS`（inputs.py:53）；攻击用 `first_press_time("attack")` 取按键发生瞬间的音频时间戳。[确认]
- IME 防护：Windows 下 `Game.__init__` 调用 `_disable_ime()`（app.py:471），对窗口 `ImmAssociateContext(hwnd, None)` 禁用输入法，避免中文 IME 吞掉字母键导致 WASD 无反应；调试面板（F1）末行显示当前 `held` 按键，用于区分「按键未到达」与「角色未动」。[确认]
- 状态变化：无独立玩家状态机，由字段隐式表达——`on_ground`/`sliding`（高 0.9，400ms）/`dash_t`+`invincible_t`（250ms，200ms 无敌）/`jumps_used`（二段跳）/`dead`+`hp`；死亡后 `Game.state="dead"`，1.5s 自动 `restart(full=True)`。[确认]
- 数据流：pygame 事件 → `InputManager.poll(t)` → `InputFrame.held/presses` → `_handle_input`（跳/抢步/攻击/矮子步/满堂彩）→ `PlayerBody.step` 与 `PlayerCombat` → 渲染。[确认]
- 扩展点：新增按键改 `_KEYMAP`；新增角色动作需同时改 `motion.py` 与 `hud.py`（表现层未读，见 U-06）；手感改 `data/feel_params.json` 的 `motion`/`assist`。[确认/推测]
- 状态：[确认]（控制链路）；动画表现映射 [未知]（U-06）

### 敌人/AI

- 职责：直线巡逻、朝向玩家、近战前摇/攻击/后摇、受击硬直、弹反眩晕与死亡。
- 入口：`Level.__init__`（level.py:137）读取 `DATA.level["enemies"]` → `Level.reset`（L157）创建 `Enemy`；`Game._step`（app.py:344）逐敌调用 `Enemy.update`。
- 核心类与方法：`Enemy`（level.py:11；`update` L61、`attack_hitbox` L45、`_in_range` L107、`_patrol` L110、`take_damage` L121、`stun` L130）；`Level`（level.py:136；`reset` L157、`total_enemies` L161、`killed_enemies` L165）
- 状态机：`patrol → startup → active → recovery → patrol`；被弹反进入 `stun`（1200ms）；hp≤0 进入 `dead`。[确认]
- 数值位置：`hp=40`、`damage=10`、`speed=1.6`、攻击帧 20/5/20、冷却 0.6s 均硬编码在 `Enemy.__init__`（level.py:22-39）；`level_segment.json` 只提供 `type/x/patrol_left/patrol_right`。[确认]
- 伤害出口：`active` 阶段 `attack_hitbox()` 与玩家 AABB 相交且玩家非无敌时返回 `{"hit_player":10}`（level.py:92-94），由 `Game._step` 调 `PlayerBody.take_damage`（app.py:347）。[确认]
- 依赖：`motion.Rect`、`config.DATA/FRAME_MS`、`level_segment.json`；被 `PlayerCombat._find_parry_target`（combat.py:104）与 `Game._step` 使用。[确认]
- 扩展点：新增敌人类型必须在 `Level.reset` 按 `spec["type"]` 分派（当前未读取 `type`，所有敌人均为 `Enemy`）；数值要可调需迁移到 JSON/新数据表。[确认]
- 状态：[确认] 仅一种巡逻兵；第二种敌人/Boss [未知]（未发现实现）

### 战斗/技能/数值

- 职责：帧数据切分招式阶段、命中与伤害倍率、对击弹反、鼓劲积累与满堂彩结算。
- 入口：`Game._handle_input`（app.py:265）→ `PlayerCombat.press_attack`（combat.py:121）；`Game._step`（app.py:335）→ `PlayerCombat.update`（combat.py:172）；`F` → `release_finisher`（combat.py:244）。
- 核心类与方法：`PlayerCombat`（combat.py:24；`press_attack` L121、`update` L172、`_resolve_hits` L213、`_resolve_aoe` L231、`release_finisher` L244、`can_cancel` L46）；`DrumEnergy`（energy.py:13；`add_run` L32、`add_hit` L38、`add_parry` L47、`can_finish` L70、`finisher_damage` L77）；`_durs`（combat.py:14）；`GRADE_MULT`（combat.py:21）
- 技能选择：地面按 J → `atk_g1`（`next` 连到 g2/g3）；空中 → `atk_a1`（→ a2 → dive）；空中按 S+J → `dive`；`parry` 条目仅作数据占位，实际对击走 `_find_parry_target`。[确认]
- 对击：扫描 `state=="startup"`、距离≤3.2、剩余前摇≤100ms 的敌人；成功 `stun(1.2s)` 并按 perfect/good 加鼓劲；过早按键进入 12 帧破绽（combat.py:104-150）。[确认]
- 伤害计算：`伤害 = frame_data.damage × GRADE_MULT`（perfect 1.5 / good 1.3 / off 1.0），在 `_resolve_hits` 命中时结算（combat.py:216-221）；劈山落地后 `_resolve_aoe` 以半径 2.5 再结算（combat.py:231-241）。[确认]
- 数值位置：招式帧/伤害/`next` 在 `data/frame_data.json`；玩家 hp 100、对击窗口 100ms、弹反眩晕 1200ms、鼓劲 100、命中 +3、疾行 6/s、脱战 3s 后 2/s 衰减、满堂彩 200 基础伤害在 `data/feel_params.json`。[确认]
- 实现差异：`frame_data.json` 的 `cancel_window_f` 与 `feel_params.json` 的 `cancel_window_pct` 未被代码读取；`can_cancel` 固定用 recovery 的 60%（combat.py:57）。[确认]
- 扩展点：新增招式改 `frame_data.json` 并登记 `next` 链；伤害公式改 `combat.py`；数值优先改 JSON。[确认]
- 状态：[确认]

### 关卡/场景加载

- 职责：从单一 JSON 构建世界边界、地面/平台/矮墙/陷阱矩形与敌人列表。
- 入口：`Game.__init__`（app.py:56）创建 `Level`；`Level.__init__`（level.py:137）读取 `DATA.level`；`Data._load` 在 config.py:39。
- 核心类与方法：`Level`（level.py:136；`__init__` L137、`reset` L157、`total_enemies` L161、`killed_enemies` L165）；`Data`（config.py:44；`_load` L39）；`Game.restart`（app.py:144）
- 加载方式：启动时一次性 `_load("level_segment.json")`（config.py:50），`Level` 取 `world/solids/hazards/low_walls/enemies`；没有按关卡 id 动态加载，也没有场景切换。[确认]
- 关卡切换：不存在；`restart(full=True)` 仅重置同一赛段的敌人/音乐/判定/鼓劲（app.py:144-150）；到达 `goal_x` 只把 `Game.state` 置为 `cleared`（app.py:371），不加载下一关。[确认]
- 数据流：`level_segment.json` → `DATA.level` → `Level` 构造 `Rect` → `PlayerBody._move_and_collide` 消费 `solid_rects/platform_rects`；`hazard_rects` 由 `Game._step` 判伤（app.py:353-359）；`goal_x` 触发结算。[确认]
- 数据差异：`level_segment.json` 的 `pixels_per_unit=40` 未被代码使用，实际为 `config.PIXELS_PER_UNIT=80`（config.py:8）；`view_width/height` 是否被 HUD 使用 [未知]（hud.py 未读）。[确认/未知]
- 扩展点：新增 L2/L3 需增加 JSON 并改造 `Data`/`Level` 支持按 id 加载；当前仅支持默认 `level_segment.json`。[确认]
- 状态：[确认] 单赛段 M0-1；多关卡/换板场景 [未知]（T2-6/T2-7 计划，未实现）

> 批次 3：物品/背包/任务、存档/设置/本地化、物理/碰撞/寻路、网络/多人（只读）。

### 物品/背包/任务

- 职责：本项目无此系统；M0 仅有单赛段动作闯关，没有物品、背包、任务的数据表或代码。[确认]
- 入口：无。
- 核心类与方法：无。
- 依赖：无。
- 数据流：无。
- 扩展点：若新增，至少需要 `data/` 物品表、`level.py` 拾取物、`app.py` 拾取与背包状态、`hud.py` 背包显示；当前这些文件均无相关实现。[推测]
- 状态：[确认] 不存在

### 存档/设置/本地化

- 职责：无正式存档与设置持久化；仅导出试玩 CSV；无本地化框架。
- 入口：`Game._export_log`（app.py:437）；F2 手感面板（`_feel_keys` app.py:252、`_build_feel_params` app.py:87）；配置读取 `config.Data`（config.py:44）。
- 核心类与方法：`Game._export_log`（app.py:437）、`FeelParam`（app.py:24）、`Game._set_offset`（app.py:132）、`Data._load`（config.py:39）
- 数据存放与格式：试玩日志为两份 CSV——`playtest_log.csv`（audio_time_s/dt_ms/grade）与 `playtest_summary.csv`（指标/值），由 `Game._export_log` 写入（app.py:437-457），代码中无读取方。[确认]
- 设置读写：`feel_params.json` 只在启动时由 `Data._load` 读入（config.py:49）；F2 面板改的是内存 `DATA`，未写回文件；无 settings/save 文件。[确认]
- 本地化：无 `locale`/`i18n`/`gettext`；中文文案硬编码在 `app.py`（如 L383-405），`hud.py` 未读，文案情况 [推测]。
- 数据流：启动读 5 张 JSON → 运行时改内存 → 退出写 CSV；没有读档、存档或设置保存。
- 扩展点：设置持久化需新增写回 `feel_params.json` 或独立设置文件；本地化需引入文案表并替换硬编码字符串；存档需新增序列化模块（当前无）。
- 状态：[确认] 无存档/无 i18n；HUD 文案 [未知]（U-07）

### 物理/碰撞/寻路

- 职责：自研固定步长运动 + AABB 碰撞；无独立物理引擎、无寻路。
- 入口：`PlayerBody.step`（motion.py:134）→ `PlayerBody._move_and_collide`（motion.py:216）；关卡碰撞矩形在 `Level.__init__`（level.py:137）。
- 核心类与方法：`Rect`（motion.py:16；`overlaps` L38）；`PlayerBody`（motion.py:43；`step` L134、`aabb` L79、`_move_and_collide` L216、`_blocked_when_standing` L209）；`Level`（level.py:136；`solid_rects` L150、`platform_rects` L148、`hazard_rects` L151）
- 碰撞层划分（按矩形列表分组，非位掩码）：`solid_rects` = 地面 + 矮墙，水平与垂直都阻挡（motion.py:221-244）；`platform_rects` 仅下落时单向落地（motion.py:247-254）；`hazard_rects` 不参与运动碰撞，只由 `Game._step` 判伤（app.py:353-359）。[确认]
- 实体碰撞：敌人不参与地形碰撞（`Enemy.y` 固定 0，仅巡逻）；玩家攻击用 `hitbox()` 与敌人 AABB 相交（combat.py:61-68、213-221）；敌人攻击用 `attack_hitbox()` 与玩家 AABB 相交（level.py:92-94）。[确认]
- 寻路方案：无；`Enemy._patrol` 在 `patrol_left/right` 间直线往返，靠近玩家只改朝向（level.py:110-119）。[确认]
- 数值：`FIXED_DT=1/120`、重力/初速由 `jump_height_units` 与 `air_time_ms` 反推（config.py:88-93）；站立 1.8 / 矮子步 0.9（motion.py:44-45）。
- 扩展点：新碰撞类型需在 `Level` 增加矩形列表并在 `_move_and_collide` 加分支；寻路需新增模块（当前无）。
- 状态：[确认] AABB + 单向平台；无寻路。

### 网络/多人

- 本项目无此系统（代码中无 socket/network/multiplayer/UDP/TCP 相关实现）。[确认]

> 批次 4：资源加载、配置表/数据表、构建打包、插件与第三方 SDK、编辑器工具（只读）。

### 资源加载

- 职责：启动时把 `assets/` 下的角色/敌人/环境/UI 贴图全部预加载到内存，提供按逻辑键查询与缩放/翻转/叠色缓存。
- 入口：`Renderer.__init__` 创建 `Assets`（hud.py:67）→ `Assets.__init__`（assets.py:50）→ `_preload`（assets.py:78）。
- 核心类与方法：`Assets`（assets.py:49；`_load` L60、`_preload` L78、`player` L91、`enemy` L97、`env` L103、`ui` L107、`scaled` L112、`flipped` L120、`tinted` L128）；`asset_dir()`（config.py:24）；`Renderer`（hud.py:67 持有）
- 加载方式：直接文件引用，无 Addressables / AssetBundle / 自定义包；`os.path.join(asset_dir(), rel)` + `pygame.image.load`，开发时读 `drumbeat-m0/assets`，打包后读 `_MEIPASS/assets`。[确认]
- 键映射：`PLAYER_FILES`（assets.py:17）、`ENEMY_FILES`（L23）、`ENV_FILES`（L31）、`UI_FILES`（L46）硬编码文件名；`manifest.json` 未被任何代码读取，仅是素材说明。[确认]
- 回退：文件缺失或加载异常时 `_raw[rel]=None` 且 `missing += 1`，由 `hud.py` 走程序化绘制；`assets.py` 本身不抛异常。[确认/推测：hud 回退细节未读]
- 数据流：`Assets.__init__` 预加载全部素材 → HUD 按 `player/enemy/env/ui` 查询 Surface；`far*` 层保留整幅画布的分支已实现；其余层裁剪后缩放 → `scaled/flipped/tinted` 缓存后 blit。[确认]
- 扩展点：新增素材需加文件到对应目录并改 `assets.py` 映射表（当前玩家仅有 run/jump/charge/death）；T4-2 视觉未通过，`far_4..far_1` 当前未启用，`cloud2` / `fore_2..4` 仍未使用；新增加载格式需改 `_load`。[确认]
- 状态：[确认] 直接加载 + 缺图回退；远景层未启用（T4-2 视觉未通过）；`hud.py` 回退绘制细节 [未知]（U-06）

### 配置表/数据表

- 职责：启动时加载 5 张 JSON（板式、节拍、帧数据、手感、关卡），作为全局 `DATA` 单例供各系统读取。
- 入口：`config.py:96` 的模块级 `DATA = Data()`；`Data.__init__`（config.py:44）→ `_load`（L39）→ `data_dir()`（L17）。
- 核心类与方法：`Data`（config.py:44；`_load` L39、`layer_index` L78、`events_for` L84、`jump_physics` L88）；`data_dir()`（config.py:17）
- 加载时机：模块导入时一次性读取，之后整局不再重载；开发时路径 `drumbeat/data`，打包后 `sys._MEIPASS/drumbeat/data`。[确认]
- 生效方式：F2 面板修改的是内存 `DATA`（如 `_set_offset` app.py:132），不会写回 JSON；要让文件改动生效必须重启进程；打包版需重新打包才能替换内置数据。[确认]
- 校验：`Data.__init__` 会校验各板式事件偏移与数量一致（config.py:58-65），不一致直接 `ValueError` 阻止启动。[确认]
- 数据差异：`tempo_layers.json` 的 `min_speed/max_speed` 与 `crossfade_ms` 未被 `tempo.py` 使用，换板阈值在 `_layer_for_speed` 硬编码 4.0/8.0（tempo.py:65-82）。[确认]
- 数据流：`drumbeat/data/*.json` → `Data` 字段（`tempo/beat/frame/feel/level`）→ `tempo/combat/level/motion` 等读取；无写回路径。[确认]
- 扩展点：数值调整直接改 JSON 重启；新增数据表需在 `Data.__init__` 加 `_load` 并暴露字段。[确认]
- 状态：[确认]

### 构建打包

- 职责：用 PyInstaller 把 `run.py`、`drumbeat/data` 与 `assets` 打成 Windows 单文件窗口程序。
- 入口：`drumbeat-m0/build.ps1:11-21`（`python -m PyInstaller ... run.py`）；另有 `drumbeat-m0/踏鼓M0.spec` 可复用配置。
- 核心步骤：`--onefile --windowed --name "踏鼓M0"`；`--add-data "drumbeat/data;drumbeat/data"`；`--add-data "assets;assets"`；`--collect-all sounddevice`；排除 tkinter/matplotlib/PIL/scipy/pandas。[确认]
- 产物：`drumbeat-m0/dist/踏鼓M0.exe`（build.ps1:24 提示）。[确认]
- 运行入口：`run.py` 捕获异常写 `crash.log` 并弹 Windows 消息框（run.py:19-38）。[确认]
- 文档工具链：`tools/package.json` 提供 `npm run docx`（md2docx.js）与 `npm run ppt`（build_ppt.js），仅生成 DOCX/PPT，不参与游戏打包。[确认]
- 扩展点：新增数据/素材目录需在 `build.ps1` 增加 `--add-data`；新增 Python 依赖需确认 PyInstaller 能收集（sounddevice 用 `--collect-all`）。[确认]
- 状态：[确认] 仅 Windows exe；网页版/其他平台 [未知]（未实现）

### 插件与第三方 SDK

- 职责：无自有插件体系；运行时依赖三个 pip 包，文档工具依赖两个 npm 包。
- 入口：`drumbeat/app.py:9`（pygame）、`synth.py:10`/`audio.py:16`（numpy）、`audio.py:18-21`（sounddevice，try/except 可选）。
- 强依赖：`pygame`（渲染/输入/事件，缺失无法启动）、`numpy`（音频合成/混音，缺失无法启动）。[确认]
- 弱依赖：`sounddevice`（仅音频输出；导入失败或设备不可用时降级 `NullAudioEngine`，判定仍可跑）。[确认]
- 构建依赖：`pyinstaller`（仅打包时）；文档依赖：`docx ^9.10.0`、`pptxgenjs ^4.0.1`（tools/package.json）。[确认]
- 插件目录：仓库内无 `plugin/`、`vendor/`、`third_party/`、`Packages/` 等第三方 SDK 目录；无 Unity/Unreal 插件。[确认]
- 数据流：无插件加载器/反射注册；依赖在 import 时静态绑定。[确认]
- 扩展点：新增 pip 依赖需更新 README 安装命令并在 `build.ps1` 处理收集；新增 npm 依赖改 `tools/package.json`。[确认]
- 状态：[确认]

### 编辑器工具

- 职责：项目无引擎内编辑器；提供无窗口冒烟测试、渲染预览与文档转换三类 CLI 工具。
- 入口：`drumbeat-m0/tools/smoke_test.py:50`（`main`）；`drumbeat-m0/tools/preview.py:48`（`main`）；`tools/package.json` 的 `docx` / `ppt` 脚本。
- 核心类与方法：`smoke_test.main`（smoke_test.py:50；`_ground_at` L29、`_hazard_ahead` L36、`_low_wall_ahead` L43）；`preview.main`（preview.py:48）；`md2docx.js` / `build_ppt.js`（根 `tools/`）
- 冒烟测试：强制 `SDL_VIDEODRIVER=dummy` / `SDL_AUDIODRIVER=dummy`，用 `NullAudioEngine` + 虚拟时钟跑 60s，机器人自动跳跃/矮子步/踩拍攻击，最后校验通关、完美率≥75%、|Δt|≤30ms、敌人全清、面板无异常（smoke_test.py:171-178）。[确认]
- 预览工具：同样无窗口，按 0/2/4/6/8/10/12s 输出普通、`_debug`、`_feel` 三版 PNG，结算时输出 `state_cleared.png`（preview.py:66-109）。[确认]
- 文档工具：`npm run docx -- <in.md> <out.docx>` 与 `npm run ppt`（README 第十一节）。[确认]
- 依赖：pygame、numpy（与游戏一致）；文档工具为 Node.js。[确认]
- 扩展点：新增验收场景改 `smoke_test.py` 的机器人策略与判定阈值；新增预览时间点改 `preview.py` 的 `shots` 列表。[确认]
- 状态：[确认]
