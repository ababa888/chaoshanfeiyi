# 《踏鼓 / Project Drumbeat》项目画像

- 分析对象：`E:\chaoshanfeiyi\YingGeGame-main\YingGeGame-main`（GitHub ZIP 解压快照，无 `.git`）
- 分析方式：只读；未运行构建、未安装依赖、未执行工程脚本、未修改代码
- 分析日期：2026-10-22

## 一、一句话描述

《踏鼓》是一款以潮汕英歌舞为主题、跟着锣鼓鼓点出招的像素风 2D 横版动作闯关游戏；当前为 M0 完成、M1 素材接入完成的可玩原型，M2 因玩家动作素材缺失而阻塞。

## 二、游戏类型与玩法关键词

- 类型：2D 横版动作闯关 / 节奏动作 / 跑酷与战斗无缝衔接
- 关键词：鼓点驱动、合拍判定（完美 ±40ms / 合拍 ±80ms）、按键帧锚点、四档板式（慢板 90 / 中板 110 / 快板 140 / 极板 150 BPM）、分层离散换板（仅小节边界）、帧数据战斗、三段挥槌、凌空挥槌、对击弹反、二段跳 / 抢步 / 矮子步、鼓劲槽、满堂彩、像素风、潮汕英歌舞非遗

## 三、技术栈清单

| 类别 | 内容 |
| --- | --- |
| 引擎 | 自研 2D 游戏框架，无 Unity / Unreal / Godot |
| 主语言 | Python 3.10+（README 要求；打包环境为 3.10，开发机实测 3.12.6） |
| 图形与输入 | pygame（开发机实测 2.6.1，未锁定版本） |
| 音频 | numpy 程序化锣鼓合成 + sounddevice 输出；设备不可用时降级为 NullAudioEngine（无声但判定可跑） |
| 数据 | 5 张 JSON 数据表（手感、板式、节拍、招式帧、关卡） |
| 构建 | PyInstaller（onefile / windowed），产物 `dist/踏鼓M0.exe` |
| 目标平台 | Windows 桌面（唯一验证过的平台）；源码理论上跨平台，但 `run.bat` 仅适用于 Windows |
| 文档工具 | Node.js + `docx ^9.10.0` + `pptxgenjs ^4.0.1`（仅生成 DOCX/PPT，不参与游戏运行） |
| 测试 | 自研无窗口冒烟测试 `tools/smoke_test.py`；无 pytest、无 CI 配置 |

## 四、如何本地运行

以下为文档中的原始命令，本次分析未执行：

```bash
# 1. 安装依赖（一次）
python -m pip install pygame numpy sounddevice pyinstaller

# 2. 启动游戏（二选一）
cd drumbeat-m0
python run.py
# 或双击 drumbeat-m0/run.bat（自动挑选能 import pygame 的解释器）

# 3. 冒烟测试（验收标准：打印 SMOKE: PASS）
python tools/smoke_test.py

# 4. 无窗口渲染预览（输出到 preview_out/）
python tools/preview.py preview_out 14

# 5. 打包 Windows exe（可选）
powershell -ExecutionPolicy Bypass -File build.ps1
```

环境提示：`run.bat` 优先使用 `C:\Pychram\Python云烟\python.exe`，失败后回退 `python`。打包必须使用已安装 sounddevice 的 Python 环境，否则 exe 无声。

## 五、目录树（深度 ≤ 3，已忽略构建产物、缓存与第三方包）

```text
YingGeGame-main/
├─ drumbeat-m0/                 # 游戏工程
│  ├─ drumbeat/                 # 游戏代码包
│  │  ├─ data/                  # 5 张 JSON 数据表
│  │  ├─ app.py                 # 主循环与运行时装配
│  │  ├─ judgement.py           # 合拍判定核心
│  │  ├─ audio.py / synth.py    # 音频时钟与程序化锣鼓
│  │  └─ ...                    # tempo/combat/level/motion/hud 等
│  ├─ assets/                   # characters / environment / ui + manifest.json
│  ├─ tools/                    # smoke_test.py / preview.py
│  ├─ run.py / run.bat          # 启动入口
│  └─ build.ps1 / 踏鼓M0.spec   # PyInstaller 打包
├─ docs/                        # agent / screenshots / 汇报 / 策划案 / 设计文档 / 进度与验收
├─ art-source/picture/          # 原始素材包（约 52.7 MB，品红底）
├─ archive/                     # 历史归档（早期跑酷策划案等）
└─ tools/                       # Node 文档工具（md2docx.js / build_ppt.js）
```

## 六、目录职责表

| 路径 | 职责 | 是否核心 |
| --- | --- | --- |
| `drumbeat-m0/` | 游戏工程根目录，运行与打包的最小工作区 | 是 |
| `drumbeat-m0/drumbeat/` | 游戏逻辑包（主循环、判定、战斗、关卡、渲染、音频） | 是 |
| `drumbeat-m0/drumbeat/data/` | 数值与关卡数据表：`feel_params` / `tempo_layers` / `beat_tables` / `frame_data` / `level_segment` | 是（调参优先改这里） |
| `drumbeat-m0/assets/` | 成品像素素材：角色、敌人、环境、UI、`manifest.json` | 是（表现层） |
| `drumbeat-m0/tools/smoke_test.py` | 无窗口冒烟测试，核心验收标准 | 是（验收） |
| `drumbeat-m0/tools/preview.py` | 无窗口渲染预览，用于美术与镜头验收 | 是（验收） |
| `drumbeat-m0/run.py`、`run.bat` | 开发运行入口与解释器自动选择 | 是（运行） |
| `drumbeat-m0/build.ps1`、`踏鼓M0.spec` | PyInstaller 打包配置 | 否（发布） |
| `docs/` | 策划案、设计文档、进度与验收、汇报材料 | 否（文档） |
| `docs/agent/` | Agent 产出物落点（本文件所在目录） | 否 |
| `art-source/picture/` | AI 生成的原始素材，供重新抠图/分帧 | 否（素材源） |
| `archive/` | 历史归档与早期版本 | 否 |
| `tools/` | Node 文档工具，Markdown 转 DOCX、汇报 PPT 生成 | 否（文档工具） |

## 七、提交历史（GitHub API）

仓库共有 10 条提交（不足 30 条），均为 `shuda_li` 于 2026-10-13 至 2026-10-20 提交：

| 日期 | 提交内容 |
| --- | --- |
| 2026-10-20 | 新增《待完成清单》，指导团队指挥 AI 完成游戏开发 |
| 2026-10-14 | 新增项目汇报 PPT 与启动器，补充环境排查记录 |
| 2026-10-14 | 第 8 小组策划案移入 `docs/策划案/` |
| 2026-10-14 | 整理项目文件结构，根目录文档归类到 `docs/` |
| 2026-10-14 | 忽略 Office 临时文件 |
| 2026-10-14 | 策划案按评分表对齐，新增项目进度文档 |
| 2026-10-13 | 背景层改为镜像拼接，消除平铺接缝 |
| 2026-10-13 | README 加入画面预览截图 |
| 2026-10-13 | 纳入原始素材包 `picture/`（52.7 MB） |
| 2026-10-13 | 首次提交：M0 可玩原型 |

## 八、不确定项

1. **无本地 Git 元数据**：当前目录为 ZIP 快照，`.git` 不存在，无法在本地执行 `git log` / 查看分支；提交历史改用 GitHub API 获取，且仓库实际只有 10 条提交而非 30 条。
2. **无 CI/CD**：不存在 `.github/` 与任何流水线配置，验收完全依赖本地 `smoke_test.py`。
3. **依赖未锁定**：无 `requirements.txt` / `pyproject.toml`，仅有 README 中的安装命令；pygame、numpy、sounddevice 版本不确定，存在环境漂移风险。
4. **解释器路径强绑定**：`run.bat` 优先硬编码 `C:\Pychram\Python云烟\python.exe`，其他机器行为取决于 PATH 中的 `python`。
5. **平台覆盖有限**：仅验证 Windows exe，macOS / Linux / 网页版均未见实现。
6. **音频设备依赖**：缺少 sounddevice 或音频设备时自动静音降级，实际试玩环境是否出声未确认。
7. **文化参数待确认**：极板 150 BPM 上限仍待非遗传承人试听确认（OQ-2）。
8. **素材缺口**：玩家 `idle` 与全部招式帧、敌人 `hurt`、障碍物与 HUD 素材缺失；M2 因此阻塞，当前战斗表现存在程序化色块回退。
9. **大体积二进制未展开**：`docs/汇报/` 约 98 MB（单个 PPT 约 99.6 MB）、`art-source/` 约 52.7 MB，仅确认存在，未逐项审阅内容。
10. **文档状态早于最新提交**：《项目进度.md》更新时间为 2026-10-14，而仓库最新提交为 2026-10-20，个别进度描述可能滞后。
