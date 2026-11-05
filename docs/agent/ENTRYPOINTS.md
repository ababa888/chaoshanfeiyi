# 《踏鼓》启动流程、主循环与生命周期

- 只读分析；未运行游戏或脚本。所有行号基于当前快照。

## 一、入口矩阵

| 入口 | 文件 | 用途 |
| --- | --- | --- |
| 用户启动（开发） | `drumbeat-m0/run.bat` | 自动挑选能 `import pygame` 的解释器并执行 `run.py` |
| 直接启动 | `drumbeat-m0/run.py` | 调用 `drumbeat.app.main()`，捕获异常写 `crash.log` |
| 打包产物 | `dist/踏鼓M0.exe` | PyInstaller 以 `run.py` 为入口生成的单文件程序 |
| 冒烟测试 | `drumbeat-m0/tools/smoke_test.py` | 无窗口创建 `Game`，用虚拟时钟和机器人跑完赛段 |
| 渲染预览 | `drumbeat-m0/tools/preview.py` | 无窗口创建 `Game`，按时间点输出 PNG |
| 构建 | `drumbeat-m0/build.ps1` | 调用 PyInstaller，不参与运行时逻辑 |

## 二、启动流程

```text
run.bat / 双击 exe
  → run.py:main()                         run.py:32
      → drumbeat.app.main()               app.py:468
          → Game()                        app.py:40
              → Game.run()                app.py:160
```

`Game.__init__`（app.py:40-84）的装配顺序：

1. `pygame.init()`、窗口标题、`set_mode(1280×720)`、`Clock`（app.py:41-44）。
2. `synth.Bank()`：启动时一次性合成锣鼓与反馈音（app.py:46、synth.py:114）。
3. `AudioEngine.start()`；失败则 `stop()` 并替换为 `NullAudioEngine`，判定仍可跑（app.py:47-52）。
4. `Renderer()`：内部创建 `Assets()` 并预加载全部贴图（app.py:54、hud.py:67、assets.py:78）。
5. `InputManager()`：初始化键盘与手柄（app.py:55）。
6. `Level()`：读取 `DATA.level`，构造地形/陷阱/敌人（app.py:56、level.py:137）。
7. `MusicDirector(audio, bank)`：初始化板式、BPM、拍相位（app.py:57）。
8. `Judgement(music)`：判定窗口、锚点、偏移（app.py:58）。
9. `DrumEnergy()`：鼓劲槽（app.py:59）。
10. `PlayerBody(level)`：玩家物理状态与出生点（app.py:60）。
11. `PlayerCombat(judgement, energy)`：战斗状态机（app.py:61）。
12. 初始化 `elapsed / hitstop / acc / state / paused / 面板开关`（app.py:64-81）。
13. `_build_feel_params()`：F2 面板参数表（app.py:83、87-130）。
14. 计算 `playtest_log.csv` 输出路径（app.py:84）。

启动完成后由 `run()` 进入主循环；`run.py` 的 `_report()` 在未捕获异常时向 exe/工程目录写 `crash.log` 并弹 Windows 消息框（run.py:19-28）。[确认]

## 三、主循环

`Game.run()`（app.py:160-209）每帧顺序：

1. `clock.tick(240)` 得到 `real_dt`，同时记录 FPS（app.py:166-167）。
2. 取 `t = audio.audio_time()`，作为本帧输入时间戳与判定时间源（app.py:168）。
3. `inputs.set_frame_time(t)` → `inputs.poll(t)`，读取 pygame 事件并记录按键时刻（app.py:170-171、inputs.py:77）。
4. 统计输入轮询频率（每 0.5s 刷新 `poll_hz`，app.py:173-177）。
5. `_global_keys(frame)`：ESC 退出；F1/F2/F3 面板；P 暂停；R 重开；1/2/3/4 强制板式；F2 时处理 ↑↓←→（app.py:212-263）。
6. 未暂停时：
   - `_handle_input(frame, t)`：跳跃、抢步、攻击/矮子步、满堂彩（app.py:265-288）。
   - `state == "playing"` 时累加 `acc`，按 `FIXED_DT = 1/120` 执行 `_step`，单帧最多 8 步，超过则丢弃余量（app.py:186-193）。
   - `state == "dead"` 时累加死亡计时，满 1.5s 自动 `restart(full=True)`（app.py:194-197）。
7. `_update_flash(real_dt)` 衰减判定闪光与提示文字（app.py:315-320）。
8. `_render(t)`：相机跟随 → `draw_world` → `draw_hud` → 状态文字/帮助/面板（app.py:375-413）。
9. `pygame.display.flip()`（app.py:201）。
10. 若设置 `DRUMBEAT_SMOKE_FRAMES`，达到帧数后退出（app.py:204-205）。

每个固定步 `_step(dt, t)` 的顺序（app.py:323-372）：命中停顿 → 玩家物理 → 战斗状态机 → 敌人更新/伤害 → 陷阱 → 鼓劲 → 音乐推进 → 判死亡/到达终点。

## 四、生命周期与状态

| 状态 / 动作 | 触发 | 行为 |
| --- | --- | --- |
| `playing` | 初始 / `restart` | 正常输入、固定步进、渲染 |
| `paused` | F1/F2 面板之外按 P | 跳过输入处理与 `_step`，仍渲染 |
| `dead` | `player.dead`（hp≤0 或坠坑） | 显示“落阵”，1.5s 后 `restart(full=True)` |
| `cleared` | `player.x >= level.goal_x` | 显示“收阵”与统计，按 R 重开；不加载下一关 |
| `restart(full=True)` | R / 死亡自动 | 重置 `Level`、`MusicDirector`、`Judgement`、`DrumEnergy`，玩家回到 `start_x` |
| `restart(full=False)` | 预留检查点重开 | 玩家回到 `checkpoint_x`，不重置关卡/节奏/判定 |
| 退出 | ESC / 冒烟帧数到达 | `_export_log()` → `audio.stop()` → `pygame.quit()` |

关键数值：`start_x=0`、`checkpoint_x=19`、`goal_x=50`、`fall_death_y=-12`（level_segment.json:9-14）；玩家死亡后 `death_t>=1.5` 自动重开（app.py:196）；通关只置 `state="cleared"`（app.py:371-372）。[确认]

## 五、工具入口的生命周期差异

- `tools/smoke_test.py` 不调用 `Game.run()`：直接 `Game()` 后替换为 `NullAudioEngine`，用 `clock["t"]` 逐步 `set_frame_time` / `_handle_input` / `_step` / `_render`，最后自检并打印 `SMOKE: PASS`（smoke_test.py:50-179）。[确认]
- `tools/preview.py` 同样不进入真实主循环：固定每 1/120s 推进一步，按 0/2/4/6/8/10/12s 输出普通、`_debug`、`_feel` 三版 PNG，结算时输出 `state_cleared.png`（preview.py:48-112）。[确认]
- `build.ps1` 只调用 PyInstaller，不执行游戏逻辑；产物启动后仍走 `run.py → app.main → Game` 同一链路（build.ps1:11-21、run.py:32-38）。[确认]
