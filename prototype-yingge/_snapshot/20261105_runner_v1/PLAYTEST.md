# 真人可玩性验证手册

本手册只针对 `prototype-yingge/` 的 Boss 战原型。目标是在没有真人的情况下，把「怎么跑、看什么、什么算手感不对」固定下来，下一轮真人测试可直接照做。

## 1. 启动

```powershell
# 标准档，自动演示；按任意鼓键接管
py -3 prototype-yingge/main.py

# 操练档（判定窗口 ×1.35，Boss 血量 420）
py -3 prototype-yingge/main.py --difficulty drill

# 无头回归（固定 45 秒，出截图和遥测）
py -3 prototype-yingge/main.py --headless --auto-exit 45

# 跑三档模拟手（不需要显示器）
py -3 prototype-yingge/tools/playtest_sim.py
```

遥测文件：`prototype-yingge/playtest/telemetry.csv`（真人/演示每局追加一行，退出或重开时写盘）。
模拟手数据：`playtest/sim_runs.csv`、`difficulty_table.csv`、`difficulty_table.md`。

## 2. 键位

| 键 | 作用 |
|---|---|
| `J` | 鼓：攻击 / 抓取类突击 |
| `K` | 锣：行军队列 / 单体重击侧闪 |
| `L` | 镲：架挡 / AOE 化解 |
| `R` | 重开一局 |
| `1` / `2` | 操练 / 标准难度 |
| `M` | 开关 5 阵 × 5 招克制矩阵速查 |
| `Space` | 暂停/恢复自动演示 |
| `ESC` | 退出（退出前写遥测） |

自动演示状态下按任意鼓键立即接管；演示会自己完成破阵、极限破阵和 Fever，可当“完美手”参考。

## 3. 每局看什么

`telemetry.csv` 每行字段：

- `perfect` / `good` / `miss` 与 `perfect_rate`：判定分布；`avg_offset_ms` / `avg_abs_offset_ms` 是平均偏差（正=偏晚）。
- `combo_breaks`：断连（漏拍/错令）次数；表里再折算成 `断连/分钟`。
- `fever_count`：本局进入 Fever 次数。
- `break_success` / `break_fail` / `break_rate`：破阵成功、失败与成功率。
- `boss_hp_left` / `squad_hp_left` / `status` / `duration_sec`：胜败与用时。
- `phase_reached` / `phase1_survived`：是否活过第一阶段（Boss 血量 100%→66%）。
- `counter_hits` / `countered_hits`：克制/被克命中次数。

截图：
- `shots/02_boss_telegraph.png` 公示与 4 拍输入条
- `shots/05_phase_telegraph.png` 新阶段首招长公示
- `shots/06_counter_stamp.png` 「克」字印与克制状态
- `shots/07_playtest_table.png` 三档模拟手难度曲线

## 4. 什么算「手感不对」

先看两条硬阈值（满足任意一条即判定当前窗口过严，需要回调）：

1. **Perfect 率 < 40%**（`perfect_rate`）。
2. **断连 > 6 次/分钟**（`combo_breaks / duration_sec × 60`）。

补充观察：

- 平均偏差 `avg_offset_ms` 绝对值 > 35ms：说明玩家整体抢拍/拖拍，先查设备延迟，再考虑窗口。
- 破阵成功率 < 50%：先看是「读不懂」还是「按不中」；读不懂改公示节奏型，按不中才改窗口。
- 第一阶段存活率 < 60%：新手门槛过高，建议先让玩家用操练档，或下调第一阶段单次伤害。
- Fever 次数 > 3/局：破阵收益过高，Boss 压力不足，考虑缩短硬直或降低硬直期伤害。

## 5. 本轮模拟手结论（2026-11-04）

同一 seed 组 5 局，Boss 600 HP，标准档：

| 模拟手 | 胜率 | 平均用时 | Perfect 率 | 破阵成功率 | 第一阶段存活 | 断连/分 |
|---|---|---|---|---|---|---|
| 完美（0ms / 0 漏拍） | 100% | 8.5s | 100% | 100% | 100% | 0.0 |
| 熟练（±28ms / 2% 漏拍） | 100% | 9.4s | 95.9% | 100% | 100% | 0.0 |
| 新手（±90–140ms / 10% 漏拍） | 0% | 34.1s | 0% | 0% | 0% | 6.0 |

**新手能不能活过第一阶段：不能（0/5）。** 新手几乎无法在 4 拍内完成一次有效破阵，每轮吃满 Boss 伤害，约 34 秒全灭；Perfect 率 0% 与断连 6.0 次/分钟同时触线。

结论：标准档的判定窗口对完全新手过严，但对熟练玩家可达 100% 破阵。真人测试应先让新手跑操练档（窗口 ×1.35），并重点观察其破阵成功率是否随着对三类节奏型的熟悉而上升；若操练档仍 <50%，再考虑放宽 Good 窗口或降低第一阶段伤害，而不是直接改 Perfect 窗口。

## 6. 已知边界

- 模拟手只校验节拍与指令正确性，不会“读图标后改变策略”；真人会利用克制矩阵换阵，模拟手固定用长蛇/演示龟甲。
- 遥测是本地 CSV，无上传；时间戳为本地时区。
- 真人测试仍缺：真实输入设备延迟、玩家对三类招式节奏型的辨识时间、换阵决策负担、连续多局疲劳曲线。
