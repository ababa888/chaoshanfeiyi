# 项目速览

《踏鼓 / Project Drumbeat》——潮汕英歌舞主题、跟随锣鼓鼓点出招的 2D 横版像素动作闯关游戏。引擎：Python 3.10+ + pygame 自研 2D 框架；平台：Windows 桌面（PyInstaller 单文件 exe），无 Unity / Unreal / Godot。

# 先读这些

1. `docs/agent/PROJECT_OVERVIEW.md` — 项目画像、技术栈、运行方式
2. `docs/agent/ARCHITECTURE.md` — 分层架构、模块依赖、核心数据流
3. `docs/agent/ENTRYPOINTS.md` — 启动流程、主循环、生命周期
4. `docs/agent/SYSTEMS.md` — 各系统索引与扩展点
5. `docs/agent/UNKNOWNS.md` — 未确认点、风险清单
6. `docs/agent/ASSET_PIPELINE.md` — 资源、配置表、构建打包（涉及素材或发布时必读）
7. `docs/agent/GLOSSARY.md` — 术语、类名、缩写（遇到不熟悉的词先查这里）

# 工作约定

- 改代码前先说明影响哪些系统（引用 `SYSTEMS.md` 的系统名与入口）。
- 不确定的先查 `UNKNOWNS.md`，不要猜；查不到就记录为新的未知项。
- 大资源 / 二进制文件只记录路径与引用关系，不读取内容。
- 不执行未知脚本；不运行构建、安装依赖或打包，除非任务明确要求。
- 改完更新对应 `docs/agent/` 文档，并至少跑一次 `python tools/smoke_test.py` 确认 `SMOKE: PASS`。

# 高风险区

1. **判定核心不可乱动**：`drumbeat-m0/drumbeat/judgement.py` 与 ADR-001 的四条约定（按键帧锚点、极板上限 150 BPM、板式仅在小节边界分层离散切换、判定点固定第 1/3 拍）。改动必须全组同意，并在提示词中写明“不得改动判定数学”。
2. **表现层状态映射写死在 `hud.py`**：玩家攻击一律显示 `charge.png`、站立复用 `run_0`、敌人 `stun` 用 `block`；新增素材不会自动生效，必须同步修改 `hud.py` 的状态选择与 `assets.py` 映射。
3. **JSON 字段漂移**：`cancel_window_f`、`cancel_window_pct`、`crossfade_ms`、`min_speed/max_speed`、`break_wall` 等字段存在于数据表但未被代码读取；调参前先确认代码是否真的消费该字段。
4. **单关卡与敌人类型硬编码**：`config.Data` 固定加载 `level_segment.json`，`Level.reset` 不读取 `spec["type"]`；新增 L2/L3 或第二种敌人必须改代码，不能只加 JSON。
5. **素材与发布债**：`assets/manifest.json` 未被运行时代码读取，玩家素材缩放不一致（`run_0..3` 为 1/6，`charge/jump/death` 为 1/3）；无 CI，版本 `0.1.0` 未嵌入 exe，发布前只能靠本地 `smoke_test` 验收。
