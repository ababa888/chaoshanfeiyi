# 快照：20261105_pre_1819（恢复 18-19 之前的完整状态）

- 用途：冻结“跑酷 + 三态全开、默认入口为急行”的版本，作为恢复 18-19 默认流程前的对照存档。禁止覆盖。
- 采集时间：2026-11-05
- 范围：`prototype-yingge/` 根目录 py、`config/*.json`、`docs/`、`tools/*.py`、三个 md。
- 未复制：`assets_gen/`（二进制素材），见 `assets_gen_manifest.json`；复原时运行 `tools/gen_assets.py`。
- `shots/`：只保留清单 `shots_manifest.txt`，不复制图片。
- 注意：本快照**不含**恢复后新增的 `config/mode.json`，也不含 `tools/mouse_loop_fuzz.py`、`tools/restore_1819_shots.py`。

## Git 状态（采集时）

- 最新 commit：`dd65029 chore: 扁平化目录结构...`（3 个历史 commit）。
- `prototype-yingge/` 不是完全未跟踪：217 个文件已在索引（staged），未提交。
  - `A` 183 个；`AM` 34 个；`??` 147 个。
- 结论：这一版依赖“索引 + 工作区”两层状态，单纯 `git checkout` 不能完整复原，必须保留本快照。

## 文件

```
*.py                 运行时模块（含 runner.py / runner_model.py / scene_ui.py / main.py ...）
config/*.json         运行配置（runner.json、settings.json、level_long.json 等；无 mode.json）
docs/*.md             设计与参考文档（含 runner_loop_v1.md 的 §7/§8）
tools/*.py            跑酷出图、无头跑分、旧 mouse_fuzz.py 等
shots_manifest.txt    历史截图清单
assets_gen_manifest.json  素材库版本说明
git_status.txt        采集时 git 状态原文
```

## 复原方式

1. 源码：本目录整体覆盖回 `prototype-yingge/`。
2. 素材：`py -3 prototype-yingge/tools/gen_assets.py`。
3. 截图：按 `shots_manifest.txt` 运行对应 `tools/*_shots.py`。

## 已知边界

- 不含 `.venv/`、`.wheel_cache/`、`archive/`、`__pycache__/`。
- 快照只增不删，不随主线更新。
