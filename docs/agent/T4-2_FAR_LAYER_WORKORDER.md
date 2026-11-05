# T4-2 远景层重做出图工单（李玉赫）

> 任务编号：T4-2（另案 A）｜状态：出图中｜负责人：李玉赫
> 背景：T4-2 技术修复已完成（`hud.py` 保留 `far*` 不裁剪分支），但现有 `远景层_1~4` 因与中景祠堂街景气质冲突，视觉验收未通过，已回退为 `cloud1 + mid` 两层视差。本工单为 U-11 案 A：保留中景，重做远景出图。

## 一、验收标准（必须先读）

1. **场景主体唯一**：远景不得出现任何建筑、屋顶、街道、人物——那些元素只属于中景 `level_map.png`。远景只能有「天空 / 云 / 远山 / 飞鸟」。
2. **空间关系**：远景在中景屋顶线**后方**透出，视觉上是一条「天空带 + 山形剪影」，约占画面上方 40% 区域。
3. **风格一致**：与 `level_map.png` 的天空色温、云的画法保持一致——暖晨光照、软边白云、蓝绿色调，禁止写实摄影感、禁止另一种插画风格。
4. **剪影克制**：山必须是低饱和蓝绿剪影（参考色域 #7FA98C ~ #A8C4B5），不能比中景建筑更抢眼。
5. **可被程序使用**：横向可平铺（`_blit_layer` 镜像拼接），天空部分为实色或渐变，不依赖透明通道。

## 二、画布与命名

| 项 | 规格 |
|---|---|
| 画布 | 2560×1440（16:9），与生成样张一致 |
| 交付格式 | PNG（RGB，无透明通道也可） |
| 文件名 | `far_new.png`（定稿后放 `drumbeat-m0/assets/environment/`） |
| 缩放接入 | 接入时 `hud.PARALLAX_LAYERS` 加一行 `("far_new", 0.30, ~0.55, "top", 0.0, None)`，由代码组（陈圣源）负责，李玉赫不改代码 |

## 三、生成提示词（样张 draft1 所用，可迭代）

```
Game background layer for a 2D side-scrolling action game: distant background
layer only, designed to sit BEHIND a pixel-art Chaoshan ancestral-hall street
scene. Content restricted to the upper sky band and far horizon: a bright
cyan-blue sky with a few soft white clouds, gentle drifting birds, and a low
band of pale green-blue distant mountains at the bottom edge. Absolutely no
buildings, no rooftops, no people, no trees in the foreground, no ground, no
text. Style: warm 2D game illustration, flat soft shading, slightly desaturated
and brighter than the foreground; mountains in muted blue-green silhouette,
sky in soft cyan-blue gradient, clouds pure white with soft warm edges. The
bottom 15% of the image should be only the mountain silhouettes so a rooftop
layer can overlay it cleanly. Clean horizontal composition, seamless
left-right continuity preferred.
```

迭代方向（如样张不过审）：
- 天太蓝 → 加 "softer pastel sky, less saturated cyan"
- 云太多 → 改 "only two or three small clouds"
- 山太高 → 改 "bottom 10% only, very low mountain band"

## 四、验收命令与输出

```powershell
# 在 drumbeat-m0/ 下，陈圣源接入后执行；李玉赫只负责交图
python tools\smoke_test.py            # 期望：SMOKE: PASS
python tools\preview.py preview_out\t4_2_redo 14   # 出图，肉眼检查远景是否压在中景屋顶后、无场景切换感
```

视觉验收清单（李玉赫自查）：
- [ ] 远景内零建筑 / 零人物 / 零地面
- [ ] 山剪影饱和度低于中景屋顶
- [ ] 与 `preview_out\t4_2_before` 对比：场景氛围未改变，只是天空更丰富
- [ ] 横向平铺 3 次无突兀断点

## 五、当前进度

- 2026-10-28：试产样张 `art-out/far_layer_draft1.jpg` 已生成（蓝天 / 白云 / 飞鸟 / 底部远山），李玉赫视觉确认通过。
- 2026-10-28：样张已接入为 `far_new.png`（`assets.py` 新增键 + `hud.py` 视差层 `("far_new", 0.30, 0.50, "top", -0.50, None)`，利用 `far*` 不裁剪分支）；smoke_test PASS，preview `t4_2_redo` 确认山脊压在中景屋顶后方、场景主体未切换。
