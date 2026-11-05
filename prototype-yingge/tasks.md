# 任务清单（第 13 轮）

1. [x] `pseudo3d.py` 重写：针孔 `scale(v)`、反算、7 档、VP/地平线、`visible_u_range`、`cell_quad`、`slab_*` 透视折线；删除旧线性投影常数。
2. [x] `tools/gen_assets.py` 加 `gen_bands()`：hero/enemy/boss/prop 7 档 nearest 预烘 + 7 档阴影；manifest 记尺寸/倍率/偏移。
3. [x] 运行 `gen_assets.py`，确认 `bands/b0..b6` 完整、b3 hero 为 90×120。
4. [x] `render.py` AssetBank 按档加载；角色/敌人/Boss/道具换档取图、1× blit。
5. [x] `render.py` 地面逐格四边形 + 段落配色 + 近侧/远唇/坡底截面 + Boss 台基。
6. [x] `render.py` 深度排序 + 可视剔除 + 阴影随档 + 程序化道具（灯笼/树/牌坊/石阶/里程桩）。
7. [x] `render.py` 相机前视 3.4–4.6、加速前压、边界夹紧；移除 `cam_dip` 下压。
8. [x] `render.py` 段落入口卡片、`perspective_debug`、Z 档改换档不缩放。
9. [x] `config/level_long.json` 三段数据（坡度/BPM/灯笼/阵法/波次/门/台基）。
10. [x] `core.py` 读表：长图、波次唤醒、清波推进、Boss 触发、段落 BPM、march_boost、边界去硬编码。
11. [x] `core.py` 火花坐标改走 `p3d.world_to_screen`。
12. [x] `selftest.py` 透视/档位/manifest/往返/共线/剔除/相机/alpha/锐度 + 长图结构断言。
13. [x] `tools/longrun_bench.py` 无头整关渲染实测（总时长/均值/中位/p95/峰值）。
14. [x] 跑 `selftest.py` → `SELFTEST: PASS`；跑 `tools/smoke_test.py` → `SMOKE: PASS`。
15. [x] 跑 `tools/playtest_sim.py`，对比破阵/补打成功率。
16. [x] `tools/perspective_shots.py` 出 38–42 五张图。
17. [x] 更新 `prototype-yingge/README.md` 第十三轮；交付中文简报。

# 任务清单（第 19 轮）

1. [x] `tools/mouse_fuzz.py`：无头复现（`--repro`）、全元素点击（`--all`）、随机模糊（`--fuzz 500`）、坐标映射（`--scale`）。
2. [x] 复现 P0 闪退：`Flow.click()` 实参数量不匹配。
3. [x] `scenes.py`：`Flow.click(x, y, now)` 四场景分派 + `hover` + `hotzones`；Roster 索引范围、锁定格早退。
4. [x] `scene_ui.py`：`logical_pos` 整数反算（1×/1.5×/2×/黑边）；热区与视觉同源；`F2` 1px 覆盖、`F3` 调试层默认关。
5. [x] 指南纯鼠标 6 步：步骤悬停/回跳、下一步禁用态、跳过、校准开始/完成、J/K/L 键位牌可点。
6. [x] 修叠印：头像裁掉烘焙字幕、场景文字去硬投影、最小 10px 网格（输出 20px）；`镲`→`钹`。
7. [x] `tools/gen_assets.py::gen_guide()`：鼓面/锣/钹/绸带/印章/Boss 窄条，整数像素无抗锯齿。
8. [x] `selftest.py` 新增鼠标/映射/热区/探针/字号断言；`SELFTEST: PASS`、`SMOKE: PASS`。
9. [x] `tools/scene_bench.py --1080` 复测；`tools/round19_shots.py` 出 65–70 六张图。
10. [x] 更新 `README.md` 第十九轮；清理临时截图。
