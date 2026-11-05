# 《踏鼓》资源与构建流水线（ASSET_PIPELINE）

- 分析对象：`E:\chaoshanfeiyi\YingGeGame-main\YingGeGame-main`
- 方式：只读；未执行打包、构建或工程脚本；二进制资源仅记录路径、类型与引用关系，未读取内容。
- 项目技术栈：Python + pygame 自研 2D 框架，无 Unity / Unreal / Godot 工程文件。

## 一、资源目录组织

本项目没有引擎场景、Prefab、蓝图或模型文件；关卡由 JSON 描述，动画由逐帧 PNG + 帧数据表驱动。

| 资源类型 | 位置 | 形式 / 数量 | 说明 |
| --- | --- | --- | --- |
| 场景 | 无场景文件 | 0 | `drumbeat/data/level_segment.json` 描述单赛段世界、地形与敌人 |
| Prefab / 蓝图 | 无 | 0 | 对象由 `level.py` 的 `Level` / `Enemy` 在运行时构造 |
| 角色贴图 | `drumbeat-m0/assets/characters/player/` | PNG × 7 | `run_0..3`、`jump`、`charge`、`death` |
| 敌人贴图 | `drumbeat-m0/assets/characters/enemy/` | PNG × 8 | `idle`、`walk`、`attack1`、`attack2`、`block`、`defeat_0..2` |
| 环境贴图 | `drumbeat-m0/assets/environment/` | PNG × 13 | 天空、云朵、远景层、中景、前景层、地面砖 |
| UI 贴图 | `drumbeat-m0/assets/ui/` | PNG × 3 | `win`、`win_alt`、`lose` |
| 模型 | 无 | 0 | 2D 像素游戏，不使用模型文件 |
| 音频 | 无音频文件 | 0 | `synth.py` 运行时程序化合成锣鼓与反馈音 |
| 动画 | 无动画文件 | 0 | 逐帧 PNG + `frame_data.json` 的 startup/active/recovery 时序 |
| 资源清单 | `drumbeat-m0/assets/manifest.json` | JSON，31 条 | 素材处理元数据；运行时代码不读取 |
| 原始素材 | `art-source/picture/` | 19 PNG + 7 JPEG，约 52.7 MB | 品红底原图，仅供离线重新抠图/分帧，不进运行时 |
| 预览图 | `drumbeat-m0/assets/_preview_*.png` | PNG × 3 | 素材合成预览，不被代码引用 |
| 文档物料 | `docs/screenshots/`、`docs/汇报/` | PNG、PPTX（约 99.6 MB） | 仅文档展示，不参与游戏运行 |

### 命名规范

- 玩家：`characters/player/<state>[_帧序号].png`；`assets.py` 的逻辑键为 `run / air / attack / death`，其中 `air → jump.png`、`attack → charge.png`。[确认]
- 敌人：`characters/enemy/<state>[_帧序号].png`；逻辑键为 `idle / walk / attack1 / attack2 / block / defeat`。[确认]
- 环境：`environment/<层名>.png`，实际文件名为中文（`天空.png`、`云朵_2/3.png`、`远景层_1..4.png`、`level_map.png`、`前景层_1..4.png`、`ground_tile.png`），`assets.py` 用英文键映射。[确认]
- UI：`ui/win.png`、`ui/win_alt.png`、`ui/lose.png`。[确认]
- 规格：28–48px 网格、PNG-32 透明底、只做朝右；同族素材同一整数倍缩放（玩家 1/6、敌人 1/10，见 `manifest.json` 的 `scale_1/` 字段）。[确认]
- 渲染尺度：运行时 `PIXELS_PER_UNIT = 80`（config.py:8），`manifest.json` 的 `recommended_pixels_per_unit` 也是 80；策划提示词套件中的“1 单位 = 40px”与运行时不一致，属历史规格。[确认/未知]

## 二、配置与数据表

| 文件 | 格式 | 关键字段 | 加载入口 | 消费方 |
| --- | --- | --- | --- | --- |
| `drumbeat/data/tempo_layers.json` | JSON | `time_signature`、`bar_beats`、`strong_beats`、`judge_points_per_bar`、`layers[id/name/bpm/drum_hits_per_bar/min_speed/max_speed/manual_only]`、`transition[mode/micro_adjust_pct/crossfade_ms/hysteresis_speed]` | `Data.__init__`（config.py:46） | `tempo.MusicDirector` |
| `drumbeat/data/beat_tables.json` | JSON | `tables.{slow,mid,fast,extreme}.events[beat/sub/inst/judge]`、`notation_legend` | `Data.beat`（config.py:47） | `tempo._schedule` / `Data.events_for` |
| `drumbeat/data/frame_data.json` | JSON | `reference_fps`、`attacks[id/name/startup_f/active_f/recovery_f/damage/cancel_window_f/next]`；`dive` 另有 `aoe_radius_units` / `break_wall` | `Data.attacks`（config.py:67） | `combat.PlayerCombat` |
| `drumbeat/data/feel_params.json` | JSON | `motion`、`assist`、`combat`、`judgement`、`drum_energy` 五组数值 | `Data` 字段（config.py:68-72） | `motion` / `combat` / `judgement` / `energy` / F2 面板 |
| `drumbeat/data/level_segment.json` | JSON | `id/name/tempo_span`、`world`、`solids[kind=ground/platform]`、`hazards`、`low_walls`、`enemies[type/x/patrol_left/patrol_right]` | `Data.level`（config.py:50） | `level.Level` |
| `drumbeat-m0/assets/manifest.json` | JSON | `target_char_height=149`、`recommended_pixels_per_unit=80`、`tolerance=80`、`palette`、`palette_dark`、`assets[source/output/category/native_size/final_size/state/frame/scale_1/]` | 无代码读取 | 仅供人工/素材流程查阅 |
| `playtest_log.csv` / `playtest_summary.csv` | CSV | 判定记录与汇总指标 | `Game._export_log` 写出（app.py:437） | 人工/外部分析；代码不读回 |

加载入口：`config.py:96` 的模块级 `DATA = Data()` 在所有模块 import 时执行一次，之后整局不重载。开发路径为 `drumbeat/data/`，打包后为 `sys._MEIPASS/drumbeat/data/`。[确认]

## 三、资源加载方式

- **直接文件引用 + 自定义加载器**，没有 Addressables、AssetBundle、资源包或异步流式加载。[确认]
- `Assets.__init__`（assets.py:50）在启动时一次性 `_preload()` 全部角色/敌人/环境/UI 贴图，存入内存字典；按逻辑键查询。[确认]
- 路径由 `asset_dir()`（config.py:24）决定：开发时 `drumbeat-m0/assets`，PyInstaller 打包后 `_MEIPASS/assets`。[确认]
- 缺图回退：文件不存在或 `pygame.image.load` 失败时记录 `None` 并累加 `missing`，不抛异常；由 `hud.py` 改用程序化绘制（具体回退分支未读，标 [推测]）。[确认/推测]
- 远景层（`far_1..4`）在 `_prep_layer` 中保留整幅画布的分支已实现（hud.py:142-145），但当前 `PARALLAX_LAYERS` 未启用远景层；T4-2 视觉验收未通过，保留中景。[确认]
- L2 环境素材（2026-10-28 接入）：`far_L2.png`（黄昏整幅天空，走 `far*` 不裁剪分支）与 `level_map_L2.png`（骑楼街景，天空已从顶部泛洪抠除）登记为 `ENV_FILES["far_L2"/"mid_L2"]`；hud.py 新增 `PARALLAX_LAYERS_L2`，当关卡 JSON 含 `"env": "L2"` 时切换（`draw_world` 读取 `level.raw`，默认仍为 L1）。L2 关卡 JSON 与选关入口属 T2-6/7，未实现。[确认]
- `manifest.json` 与 `_preview_*.png` 不参与运行时加载。[确认]

## 四、构建与打包

- 构建入口：`drumbeat-m0/build.ps1`，核心命令为 `python -m PyInstaller --onefile --windowed --name "踏鼓M0" ... run.py`（build.ps1:11-21）。[确认]
- 资源打包：`--add-data "drumbeat/data;drumbeat/data"`、`--add-data "assets;assets"`；`--collect-all sounddevice`；排除 `tkinter/matplotlib/PIL/scipy/pandas`。[确认]
- 规格文件：`drumbeat-m0/踏鼓M0.spec` 提供等价的 PyInstaller 配置，但 `build.ps1` 未调用它。[确认]
- 目标平台：仅 Windows 单文件窗口程序，产物 `drumbeat-m0/dist/踏鼓M0.exe`；未做安装包、代码签名或商店渠道配置（spec 中 `codesign_identity=None`）。[确认]
- CI：无。仓库无 `.github/`、`.gitlab-ci.yml`、Jenkinsfile 等流水线配置。[确认]
- 版本号：`drumbeat/__init__.py:3` 定义 `__version__ = "0.1.0"`，但未传入 PyInstaller，exe 文件名不含版本号。[确认]
- 渠道 / SDK：无广告、统计、账号、支付或平台 SDK；唯一可选的运行时第三方为 `sounddevice`。[确认]
- 文档工具链（不参与游戏打包）：`tools/package.json` 的 `npm run docx`（`md2docx.js`）与 `npm run ppt`（`build_ppt.js`）。[确认]

## 五、热更新 / Mod / DLC / 扩展机制

- 无热更新、无 Mod 加载器、无 DLC、无网络更新代码。[确认]
- 扩展方式只有数据驱动：改 `drumbeat/data/*.json`、在 `assets.py` 增加素材键、在 `frame_data.json` 增加招式；没有插件注册或反射扫描。[确认]
- 由于 PyInstaller 使用 `--onefile` 并把 `data`/`assets` 一并嵌入，发布后替换资源或改表必须重新打包；开发环境改文件后重启进程即可生效，无运行时热重载。[确认]

## 六、二进制资源清单（只记录，不读内容）

| 路径 | 类型 / 数量 | 被谁引用 |
| --- | --- | --- |
| `drumbeat-m0/assets/characters/player/*.png` | PNG × 7 | `assets.py:17` `PLAYER_FILES` → `Assets.player()` → HUD |
| `drumbeat-m0/assets/characters/enemy/*.png` | PNG × 8 | `assets.py:23` `ENEMY_FILES` → `Assets.enemy()` → HUD |
| `drumbeat-m0/assets/environment/*.png` | PNG × 13 | `assets.py:31` `ENV_FILES` → `Assets.env()` → HUD 视差层；`远景层_1..4` 当前未启用（T4-2 视觉验收未通过，保留中景，见 U-11） |
| `drumbeat-m0/assets/ui/*.png` | PNG × 3 | `assets.py:46` `UI_FILES`；结算界面尚未接入（见《项目进度》） |
| `drumbeat-m0/assets/_preview_*.png` | PNG × 3 | 无代码引用，素材预览图 |
| `drumbeat-m0/assets/manifest.json` | JSON，约 12 KB | 无代码引用，素材元数据 |
| `art-source/picture/*` | 19 PNG + 7 JPEG，约 52.7 MB | 离线素材源，不进运行时；仓库内无 `build_assets.py` |
| `docs/screenshots/*.png` | PNG × 3 | README 展示 |
| `docs/汇报/*.pptx` | PPTX × 1，约 99.6 MB | 项目汇报，不参与构建 |
| 音频 / 模型 / 场景 / Prefab / 蓝图 | 0 | 无 |

## 七、关键缺口与风险

1. 玩家动作素材仅覆盖 run/jump/charge/death；`idle`、挥槌三段、凌空挥槌、劈山、对击、矮子步、抢步、受击、满堂彩均缺（见 README 与《待完成清单》）。[确认]
2. 敌人缺 `hurt` / `stun` 帧；`hurt` 目前用叠色闪红代替。[确认]
3. 障碍物与 HUD 素材缺失，当前由 `hud.py` 程序化绘制。[确认]
4. 无音频素材，四档锣鼓全部由 `synth.py` 合成。[确认]
5. 资源处理流程不可复现：`art-source/picture → assets` 的脚本未入库，只有 `manifest.json` 记录参数（`build_assets.py` 尚未实现）。[确认]
6. `manifest.json` 未被代码读取，修改它不会影响游戏。[确认]
7. 版本号 0.1.0 未写入 exe 元数据，发布物无法从文件名区分版本。[确认]
8. 无 CI，合并/发布前只能依赖本地 `python tools/smoke_test.py` 验收。[确认]

## 八、新增 / 替换一项资源的完整步骤

1. 按命名规范把 PNG 放入 `assets/characters/...`、`assets/environment/` 或 `assets/ui/`。
2. 在 `drumbeat/asssets.py` 对应映射表（`PLAYER_FILES` / `ENEMY_FILES` / `ENV_FILES` / `UI_FILES`）登记文件名。
3. 若涉及新状态，还需在 `hud.py` 的状态选择逻辑中消费该键（当前未读，见 U-06）。
4. 运行 `python tools/smoke_test.py` 确认 `SMOKE: PASS`，再用 `python tools/preview.py preview_out 14` 出图验收。
5. 发布前重新执行 `build.ps1`，确认 `dist/踏鼓M0.exe` 内含新资源。
