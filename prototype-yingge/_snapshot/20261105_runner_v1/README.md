# 快照：20261105_runner_v1（跑酷 + 三态存档）

- 用途：冻结“跑酷独立模式 + 三层文化状态”这一版源码，后续任何回退/对比都以它为准，禁止覆盖。
- 采集时间：2026-11-05
- 范围：`prototype-yingge/` 根目录 py、`config/*.json`、`docs/`、`tools/*.py`、三个 md。
- 未复制：`assets_gen/`（二进制素材约 1.87MB），见 `assets_gen_manifest.json`；需要复原时运行 `tools/gen_assets.py` 或从 Git 索引取回。
- `shots/`：只保留清单 `shots_manifest.txt`（文件名 + 字节数），不复制图片，避免旧产物被覆盖。
- `git_status.txt`：采集时的 `git status --porcelain -- prototype-yingge` 原文。

## Git 状态（采集时）

- 当前分支有 3 个历史 commit，最新为 `dd65029 chore: 扁平化目录结构...`。
- `prototype-yingge/` **不是完全未跟踪**：它已有 217 个文件进入 Git 索引（staged），但**尚未提交**。
  - `A`（新增已暂存）183 个
  - `AM`（新增已暂存 + 工作区又改过）34 个
  - `??`（未跟踪）147 个
- 结论：这一版依赖“索引 + 工作区”两层状态；单纯 `git checkout` 不能完整复原，因此本快照必须保留。

## 快照内文件

```
*.py                 13 个运行时模块（main / scenes / render / scene_ui / core / runner ...）
config/*.json        运行配置（含 runner.json、settings.json、level_long.json 等）
docs/*.md            设计与参考文档
tools/*.py           出图/无头/分析脚本
README.md / PLAYTEST.md / NOTES-patapon.md
shots_manifest.txt   历史截图清单
assets_gen_manifest.json  素材库版本说明（不含量化二进制）
git_status.txt       采集时 git 状态原文
```

## 复原方式

1. 源码：本目录整体覆盖回 `prototype-yingge/`（仅限本快照采集时间点）。
2. 素材：运行 `py -3 prototype-yingge/tools/gen_assets.py`。
3. 截图：按 `shots_manifest.txt` 重新运行对应 `tools/*_shots.py`。

## 已知边界

- 本快照不包含 `.venv/`、`.wheel_cache/`、`archive/`。
- 不包含 `__pycache__/`。
- 快照是“只增不删”的存档，不随主线代码更新。
