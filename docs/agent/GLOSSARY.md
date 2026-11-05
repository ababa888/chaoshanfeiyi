# 《踏鼓》术语表（GLOSSARY）

> 只读整理；术语顺序按「文化 → 节奏判定 → 战斗 → 类与模块 → 工程缩写 → 数据字段」。

## 一、项目与文化概念

| 术语 | 含义 | 出处 |
| --- | --- | --- |
| 踏鼓 / Project Drumbeat | 本项目名称：英歌舞主题横版动作闯关游戏 | README |
| 英歌舞 | 潮汕非遗民间舞蹈，本项目将其动作与锣鼓节奏转译为玩法 | README、docs/策划案 |
| 槌手 | 玩家扮演的英歌队角色，以木槌为武器 | README、`combat.py` |
| 锣鼓经 | 锣鼓演奏的口诀/谱式；游戏中体现为 `beat_tables.json` 的乐器事件表 | `beat_tables.json` |
| 脸谱配色 | 红/黑/白/金；HUD 常量 `RED/DARK/WHITE/GOLD` | `hud.py:15-25` |
| 满堂彩 | 英歌表演中的高潮喝彩；游戏里是鼓劲满槽后的终结技 | `energy.py`、`combat.release_finisher` |
| 收阵 / 落阵 | 通关 / 死亡的界面文案 | `app.py:383-386` |

## 二、节奏与判定

| 术语 | 含义 | 出处 |
| --- | --- | --- |
| 板式 | 四档节奏层：慢板 90、中板 110、快板 140、极板 150 BPM | `tempo_layers.json` |
| BPM | 每分钟拍数；极板上限 150 | `tempo_layers.json`、ADR-001 |
| 小节 / bar | 4/4 拍，`bar_beats=4` | `tempo_layers.json` |
| 拍相位 / `beat_pos` | 当前绝对拍位置（可跨小节累计） | `tempo.py:34` |
| 判定点 | 每小节第 1、3 拍；`strong_beats=[1,3]` | `tempo_layers.json` |
| 分层离散换板 | 只在小节边界切换板式，不做连续插值 | `tempo._maybe_switch` |
| 迟滞 / hysteresis | 换板速度阈值附近的回差，避免频繁切换（0.5 单位/秒） | `tempo_layers.json`、`tempo.py:28` |
| 前瞻调度 / lookahead | 鼓点事件提前约 200ms 排入音频队列 | `tempo.py:19,143` |
| Δt / `dt_ms` | 按键音频时间与最近判定点的差值（毫秒） | `judgement.py:70` |
| perfect / good / off | 判定等级：完美 ±40ms、合拍 ±80ms、其余未合拍 | `judgement.py:72-77` |
| 辅助窗口 | `assist_window_ms=120`，辅助模式下的合拍窗口 | `feel_params.json`、`judgement.py:50` |
| 按键帧锚点 / `keydown` | 按键发生的音频时刻即为判定时刻（默认） | `judgement.py:5`、ADR-001 |
| 命中帧锚点 / `active_frame` | 以攻击 active 阶段为判定时刻（可选 A/B） | `combat.py:99-102,190-194` |
| `user_offset_ms` | 设备延迟校准偏移，判定前统一扣除 | `judgement.py:68`、`app.py:132` |

## 三、动作与战斗

| 术语 | 含义 | 出处 |
| --- | --- | --- |
| startup / active / recovery | 招式前摇 / 判定 / 后摇三个阶段 | `frame_data.json`、`combat._phase_of` |
| `until_land` | 劈山的 active 持续到落地 | `frame_data.json`、`combat.py:77-82` |
| 取消窗口 | recovery 后 40% 可取消并接下一段；代码实际固定为 60% 起点 | `combat.can_cancel`、`feel_params.json` |
| atk_g1 / g2 / g3 | 地面挥槌三段，`next` 串联 | `frame_data.json` |
| atk_a1 / a2 | 凌空挥槌两段，a2 后接 dive | `frame_data.json` |
| 劈山 / dive | 空中下劈，落地后 AoE 半径 2.5 | `combat._resolve_aoe` |
| 对击 / parry | 敌人前摇 100ms 内按攻击触发弹反，成功眩晕 1.2s | `combat._find_parry_target` |
| 对击失败破绽 | 过早按键进入 12 帧锁定 | `combat.py:147-150` |
| 抢步 / dash | 250ms 冲刺，200ms 无敌，冷却 0.25s | `feel_params.json`、`motion.request_dash` |
| 矮子步 / slide | 400ms 低姿（高 0.9），可过悬空横梁 | `motion.py:44-45,167-175` |
| 二段跳 | 空中再次跳跃，第二段初速为 0.8 倍 | `feel_params.json`、`motion.py:191-194` |
| 土狼时间 / coyote | 离开平台后仍可起跳的 100ms 宽限 | `feel_params.json`、`motion.py:257` |
| 跳跃缓冲 / jump buffer | 落地前 120ms 按跳，落地即起跳 | `feel_params.json`、`motion.request_jump` |
| 命中停顿 / hitstop | 命中瞬间冻结 40–80ms | `feel_params.json`、`app.py:324-327` |
| 槌花 / `hit_count` | 短时间内的命中计数，2s 无命中清零 | `combat.py:37`、`feel_params.json` |
| 合拍连段 / `streak` | 连续 perfect/good 次数；off 清零 | `judgement.py:79-83` |
| 鼓劲 / `DrumEnergy` | 疾行、命中、弹反积累的能量槽，满 100 | `energy.py`、`feel_params.json` |
| 满堂彩 / finisher | 鼓劲满且连段 ≥4 的范围终结技 | `energy.can_finish`、`combat.release_finisher` |

## 四、类与模块

| 名称 | 职责 | 位置 |
| --- | --- | --- |
| `Game` | 运行时装配、主循环、状态与日志 | `app.py:39` |
| `FeelParam` | F2 面板的单行可调参数 | `app.py:24` |
| `Data` | 5 张 JSON 的加载与派生数据 | `config.py:44` |
| `InputManager` / `InputFrame` / `Press` | 输入映射与按键音频时间戳 | `inputs.py:56/23/17` |
| `PlayerBody` | 固定步长运动、AABB 碰撞、生命 | `motion.py:43` |
| `Rect` | AABB 矩形与相交测试 | `motion.py:16` |
| `PlayerCombat` | 帧数据战斗、命中、对击、满堂彩 | `combat.py:24` |
| `DrumEnergy` | 鼓劲槽与终结技条件 | `energy.py:13` |
| `Judgement` / `JudgeResult` | 合拍判定与单次结果 | `judgement.py:27/18` |
| `MusicDirector` | 板式、BPM、拍相位、鼓点调度 | `tempo.py:18` |
| `AudioEngine` / `NullAudioEngine` | 音频时钟/混音；无设备降级 | `audio.py:24/134` |
| `Bank` | 程序化锣鼓样本与反馈音库 | `synth.py:114` |
| `Level` / `Enemy` | 关卡几何/敌人列表；巡逻兵状态机 | `level.py:136/11` |
| `Renderer` / `Camera` | 世界与 HUD 绘制；相机跟随 | `hud.py:60/48` |
| `Assets` | 贴图预加载、缩放/翻转/叠色缓存 | `assets.py:49` |

## 五、工程缩写

| 缩写 | 全称 / 含义 |
| --- | --- |
| ADR-001 | 判定锚点与 BPM 的架构决策记录；四条约定不可随意改 |
| M0 / M1 / M2 / M3 | 里程碑：可玩原型 / 素材接入 / 玩法扩展 / 打磨发布 |
| OQ-1 ~ OQ-4 | 待真人或文化方确认的开放问题（判定窗口、150 BPM、音频成本、移动端操作） |
| PPU / `PIXELS_PER_UNIT` | 每世界单位对应的像素数，运行时为 80 |
| `_MEIPASS` | PyInstaller 单文件程序运行时的临时解包目录 |
| SDL | pygame 底层多媒体库；`SDL_VIDEODRIVER/ SDL_AUDIODRIVER=dummy` 用于无窗口测试 |
| AABB | 轴对齐包围盒，本项目所有实体碰撞均用矩形 |
| HUD | 屏幕上的生命、鼓劲、板式、连段、判定圈等信息层 |
| CSV | 试玩日志格式（`playtest_log.csv` / `playtest_summary.csv`） |
| PyInstaller | 将 Python 工程打包为 Windows exe 的工具 |

## 六、关键数据字段

| 字段 | 含义 |
| --- | --- |
| `startup_f` / `active_f` / `recovery_f` | 招式三段帧数，按 60fps 换算为秒 |
| `damage` | 招式基础伤害，命中时乘以判定倍率 |
| `next` | 连段下一招 id；`null` 表示结束 |
| 判定倍率 / `GRADE_MULT` | perfect 1.5 / good 1.3 / off 1.0 |
| `judge` | 节拍事件是否为判定点 |
| `inst` | 该拍位触发的乐器列表（咚/匡/才/七/台/嘟/号角） |
| `perfect_rate` / `good_rate` / `off_rate` | 判定分布统计 |
| `mean_dt_ms` / `std_dt_ms` | Δt 均值/标准差，用于 OQ-1 手感评估 |
| `killed_enemies` / `total_enemies` | 已击杀/敌人总数，冒烟测试要求全清 |
