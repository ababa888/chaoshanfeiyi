# 任务清单（第 16 轮）

- [x] `core.py`：`input_queue` / `push_input` / `_drain_input`，`update()` 首行消费
- [x] `main.py`：四条输入路径改 `push_input` + 触键干声 `audio.key`
- [x] `render.py`：谱面带常量与 `_draw_beat_ribbon` / `_draw_ribbon_slot` / `_draw_key_symbol`
- [x] `render.py`：`_build_hud` 移除读招面板调用
- [x] `tools/input_latency.py`：链路实测（post→draw med 10.46 / max 15.51ms）
- [x] `render.py`：`instrument_pose` 当帧位移 ≥1px + 高亮语义；`AssetBank.instrument_lit`；`_draw_beat_ui` 用亮图
- [x] `render.py`：新增 `ribbon_cell_x()` 整数滚动助手并替换内联计算
- [x] `render.py`：Boss 公示文字移入带内顶部（教学条上移 y=356，避免重叠）
- [x] `selftest.py`：新增 `test_input_and_ribbon`（7 条断言）并注册到 `main()`
- [x] 跑 `selftest.py` → `SELFTEST: PASS`
- [x] 跑 `drumbeat-m0/tools/smoke_test.py` → `SMOKE: PASS`
- [x] `tools/longrun_bench.py --1080` 性能复测（avg 10.89 / p95 14.81 / peak 23.52）
- [x] 出图 6 张：52 按下三帧 / 53 常态 / 54 Perfect / 55 Miss / 56 Boss 预警 / 57 新旧对比
- [x] `README.md` 追加第 16 轮章节
- [x] 清理临时诊断脚本（Temp 目录已无残留）
