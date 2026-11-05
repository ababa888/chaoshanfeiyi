// 《踏鼓》项目汇报 PPT 生成器（PptxGenJS）
// 用法：cd tools && npm run ppt
// 输出：../docs/汇报/踏鼓-项目汇报.pptx
const path = require("path");
const fs = require("fs");
const PptxGenJS = require("pptxgenjs");

const OUT_DIR = path.resolve(__dirname, "..", "docs", "汇报");
const OUT = path.join(OUT_DIR, "踏鼓-英歌舞非遗数字化-项目汇报.pptx");
const SHOT = (n) => path.resolve(__dirname, "..", "docs", "screenshots", n);

// ─────────────────────────────── 设计令牌（暖色调）
const T = {
  paper: "FBF3E4",      // 宣纸米黄（底）
  paperDeep: "F4E4C6",  // 次级底
  dark: "43291F",       // 深暖棕（章节页底 / 标题）
  ink: "35251C",        // 正文主色
  muted: "7C6855",      // 次要文字
  accent: "C8302E",     // 英歌红（强调）
  gold: "C08A2A",       // 暖金（数据 / 描边）
  brick: "D1702C",      // 砖橙（辅助）
  cream: "FFF7E9",      // 深底上的浅字
  hair: "E3D0B2",       // 细线
  ok: "4C7A3F",         // 状态：完成
  doing: "C08A2A",      // 状态：进行中
  todo: "9A8877",       // 状态：未开始
};
const F = "Microsoft YaHei";
const FN = "Arial";
const W = 13.333, H = 7.5, M = 0.62, CW = W - M * 2;

const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "第 8 小组";
pptx.title = "踏鼓 · 英歌舞非遗数字化项目汇报";

// ─────────────────────────────── 基元
function token(slide, text, o) {
  slide.addText(text, Object.assign({
    fontFace: FN, margin: 0, wrap: false, vert: "horz", fit: "shrink", align: "left",
  }, o));
}
function note(slide, text) { slide.addNotes(text); }
function hairline(slide, x, y, w, color = T.hair, h = 0.02) {
  slide.addShape(pptx.ShapeType.rect, { x, y, w, h, fill: { color } });
}
// 页眉：章节标签 + 结论式标题
function head(slide, label, claim) {
  slide.addText(label, {
    x: M, y: 0.42, w: CW, h: 0.28, fontFace: F, fontSize: 11.5, bold: true,
    color: T.accent, charSpacing: 1.6,
  });
  slide.addText(claim, {
    x: M, y: 0.72, w: CW, h: 0.62, fontFace: F, fontSize: 25, bold: true, color: T.ink,
  });
  hairline(slide, M, 1.46, CW);
}
// 页脚：页码 + 项目名
function foot(slide, idx) {
  slide.addText("踏鼓 / Project Drumbeat  ·  潮汕英歌舞非遗数字化传承与创新实践 · 第 8 小组", {
    x: M, y: 6.98, w: CW - 0.8, h: 0.26, fontFace: F, fontSize: 9, color: T.muted,
  });
  token(slide, String(idx).padStart(2, "0"), {
    x: W - M - 0.6, y: 6.94, w: 0.6, h: 0.3, fontFace: FN, fontSize: 11, bold: true,
    color: T.gold, align: "right",
  });
}
function blank(deep = false) {
  const s = pptx.addSlide();
  s.background = { color: deep ? T.paperDeep : T.paper };
  return s;
}

// ─────────────────────────────── 版式：封面
function cover() {
  const s = pptx.addSlide();
  s.background = { color: T.dark };
  s.addImage({ path: SHOT("02_combat.png"), x: 0, y: 0, w: W, h: H });
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: "2A150C", transparency: 26 } });
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 3.05, w: W, h: 3.1, fill: { color: "1E0F08", transparency: 12 } });
  hairline(s, M, 1.02, 1.5, T.gold, 0.045);
  s.addText("潮汕英歌舞非遗数字化传承与创新实践 · 第 8 小组", {
    x: M, y: 1.18, w: CW, h: 0.3, fontFace: F, fontSize: 13, color: T.cream, charSpacing: 1.4,
  });
  s.addText("踏 鼓", {
    x: M, y: 2.98, w: CW, h: 1.0, fontFace: F, fontSize: 54, bold: true, color: T.cream, charSpacing: 6,
  });
  s.addText("Project Drumbeat", {
    x: M, y: 3.98, w: CW, h: 0.4, fontFace: FN, fontSize: 19, bold: true, color: T.gold, charSpacing: 2,
  });
  s.addText("一款跟着锣鼓鼓点打的英歌舞横版动作闯关游戏", {
    x: M, y: 4.52, w: CW, h: 0.4, fontFace: F, fontSize: 17, color: T.cream,
  });
  s.addText("技艺教学 + 数字开发 二元实践 ｜ 两项核心产出 ｜ 7 次课完成原型", {
    x: M, y: 5.06, w: CW, h: 0.36, fontFace: F, fontSize: 12.5, color: "E8D9C2",
  });
  s.addText("课程：服务型劳动课——非遗数字化　　策划日期：2026 年 10 月", {
    x: M, y: 5.92, w: CW, h: 0.32, fontFace: F, fontSize: 11.5, color: "C9B79C",
  });
  note(s, "开场：这是英歌舞主题的游戏《踏鼓》。一句话——鼓点是节拍器，合拍就是伤害倍率。");
}

// ─────────────────────────────── 版式：导览
function agenda(items) {
  const s = blank();
  head(s, "REPORT CONTENT", "汇报内容");
  const y0 = 2.05, rh = 0.82;
  items.forEach((it, i) => {
    const y = y0 + i * rh;
    token(s, String(i + 1).padStart(2, "0"), {
      x: M, y: y + 0.02, w: 0.75, h: 0.42, fontFace: FN, fontSize: 22, bold: true, color: T.gold,
    });
    s.addText(it[0], { x: M + 0.95, y, w: 3.4, h: 0.42, fontFace: F, fontSize: 17, bold: true, color: T.ink });
    s.addText(it[1], { x: M + 4.5, y: y + 0.06, w: CW - 4.5, h: 0.34, fontFace: F, fontSize: 12.5, color: T.muted });
    hairline(s, M, y + 0.56, CW, T.hair, 0.012);
  });
  foot(s, 2);
  note(s, "六个板块：先讲做什么，再讲怎么分工、怎么做、创新在哪、做到什么程度、最后成果与展望。");
}

// ─────────────────────────────── 版式：结论 + 条目
function bullets(label, claim, items, idx) {
  const s = blank();
  head(s, label, claim);
  const y0 = 2.02, rh = Math.min(1.06, 4.5 / items.length);
  items.forEach((it, i) => {
    const y = y0 + i * rh;
    s.addShape(pptx.ShapeType.rect, { x: M, y: y + 0.06, w: 0.055, h: 0.62, fill: { color: T.accent } });
    s.addText(
      [
        { text: it[0], options: { bold: true, color: T.ink, fontFace: F, fontSize: 15, breakLine: true } },
        { text: it[1], options: { color: T.muted, fontFace: F, fontSize: 13 } },
      ],
      { x: M + 0.26, y: y - 0.02, w: CW - 0.3, h: 0.8, valign: "top", lineSpacingMultiple: 1.05 },
    );
  });
  foot(s, idx);
  return s;
}

// ─────────────────────────────── 版式：四卡
function cards(label, claim, list, idx) {
  const s = blank();
  head(s, label, claim);
  const n = list.length, gap = 0.28;
  const cw = (CW - gap * (n - 1)) / n, y = 2.15, ch = 3.5;
  list.forEach((c, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pptx.ShapeType.rect, { x, y, w: cw, h: ch, fill: { color: T.cream }, line: { color: T.hair, width: 1 } });
    s.addShape(pptx.ShapeType.rect, { x, y, w: cw, h: 0.075, fill: { color: i % 2 ? T.gold : T.accent } });
    if (c.token) token(s, c.token, {
      x: x + 0.26, y: y + 0.34, w: cw - 0.5, h: 0.62, fontFace: FN, fontSize: 30, bold: true, color: T.accent,
    });
    s.addText(c.head, {
      x: x + 0.26, y: y + (c.token ? 1.02 : 0.36), w: cw - 0.5, h: 0.4,
      fontFace: F, fontSize: 16, bold: true, color: T.ink,
    });
    s.addText(c.text, {
      x: x + 0.26, y: y + (c.token ? 1.5 : 0.86), w: cw - 0.5, h: ch - 1.8,
      fontFace: F, fontSize: 12, color: T.muted, lineSpacingMultiple: 1.15, valign: "top",
    });
  });
  foot(s, idx);
  return s;
}

// ─────────────────────────────── 版式：时间线
function timeline(label, claim, steps, idx) {
  const s = blank();
  head(s, label, claim);
  const y = 3.0, x0 = M + 0.90, span = CW - 1.80, gap = span / (steps.length - 1);
  hairline(s, x0, y, span, T.hair, 0.035);
  steps.forEach((st, i) => {
    const x = x0 + i * gap;
    const on = i < 7;
    s.addShape(pptx.ShapeType.ellipse, {
      x: x - 0.16, y: y - 0.14, w: 0.32, h: 0.32,
      fill: { color: on ? (i < 6 ? T.gold : T.accent) : T.todo },
    });
    token(s, String(i + 1), {
      x: x - 0.16, y: y - 0.11, w: 0.32, h: 0.26, fontFace: FN, fontSize: 12, bold: true,
      color: T.cream, align: "center",
    });
    const up = i % 2 === 0;
    s.addText(st[0], {
      x: x - 0.95, y: up ? y - 0.92 : y + 0.34, w: 1.9, h: 0.34,
      fontFace: F, fontSize: 13, bold: true, color: T.ink, align: "center",
    });
    s.addText(st[1], {
      x: x - 0.95, y: up ? y - 0.62 : y + 0.64, w: 1.9, h: 0.6,
      fontFace: F, fontSize: 10.5, color: T.muted, align: "center", lineSpacingMultiple: 1.05,
    });
  });
  s.addText("第 1–6 次课完成教学与开发推进，第 7 次课成果展示与总结", {
    x: M, y: 5.05, w: CW, h: 0.36, fontFace: F, fontSize: 13, color: T.ink, align: "center",
  });
  foot(s, idx);
  note(s, "七次课是双线并行的：教学线逐次加动作，开发线逐次推进原型。");
}

// ─────────────────────────────── 版式：双栏
function twoCol(label, claim, left, right, idx) {
  const s = blank();
  head(s, label, claim);
  const y = 2.05, ch = 4.3, cw = (CW - 0.4) / 2;
  [left, right].forEach((col, ci) => {
    const x = M + ci * (cw + 0.4);
    s.addShape(pptx.ShapeType.rect, { x, y, w: cw, h: ch, fill: { color: T.cream }, line: { color: T.hair, width: 1 } });
    s.addShape(pptx.ShapeType.rect, { x, y, w: cw, h: 0.62, fill: { color: ci ? T.brick : T.accent } });
    s.addText(col.title, {
      x: x + 0.26, y: y + 0.08, w: cw - 0.5, h: 0.46, fontFace: F, fontSize: 15.5, bold: true, color: T.cream,
    });
    col.items.forEach((it, i) => {
      const yy = y + 0.86 + i * 0.62;
      s.addText(it[0], { x: x + 0.26, y: yy, w: 1.25, h: 0.3, fontFace: F, fontSize: 13, bold: true, color: T.accent });
      s.addText(it[1], { x: x + 1.5, y: yy, w: cw - 1.76, h: 0.5, fontFace: F, fontSize: 11.5, color: T.muted, lineSpacingMultiple: 1.0, valign: "top" });
    });
    if (col.foot) s.addText(col.foot, {
      x: x + 0.26, y: y + ch - 0.72, w: cw - 0.5, h: 0.6, fontFace: F, fontSize: 11, italic: true, color: T.muted,
    });
  });
  foot(s, idx);
  return s;
}

// ─────────────────────────────── 版式：表格
function tableSlide(label, claim, header, rows, idx) {
  const s = blank();
  head(s, label, claim);
  const data = [
    header.map((h) => ({ text: h, options: { bold: true, color: T.cream, fill: { color: T.accent }, fontFace: F, fontSize: 12.5 } })),
    ...rows.map((r, i) => r.map((c, ci) => ({
      text: c,
      options: {
        color: ci === 0 ? T.ink : T.muted, bold: ci === 0, fontFace: F, fontSize: 11.5,
        fill: { color: i % 2 ? T.paperDeep : T.cream },
      },
    }))),
  ];
  s.addTable(data, {
    x: M, y: 1.95, w: CW, colW: header.map((_, i) => (i === 0 ? 1.7 : (i === 1 ? 2.6 : CW - 4.3))),
    rowH: 0.62, border: { type: "solid", color: T.hair, pt: 0.75 }, valign: "middle",
    margin: 0.11,
  });
  foot(s, idx);
  return s;
}

// ─────────────────────────────── 版式：图 + 要点
function imageSlide(label, claim, img, caption, items, idx) {
  const s = blank();
  head(s, label, claim);
  const iw = 7.2, ih = iw * 9 / 16, iy = 1.95;
  s.addShape(pptx.ShapeType.rect, { x: M, y: iy, w: iw, h: ih, fill: { color: T.dark } });
  s.addImage({ path: img, x: M, y: iy, w: iw, h: ih });
  s.addShape(pptx.ShapeType.rect, { x: M, y: iy + ih - 0.02, w: iw, h: 0.02, fill: { color: T.gold } });
  s.addText(caption, { x: M, y: iy + ih + 0.1, w: iw, h: 0.3, fontFace: F, fontSize: 10.5, italic: true, color: T.muted });
  const x2 = M + iw + 0.5, w2 = CW - iw - 0.5;
  items.forEach((it, i) => {
    const y = iy + 0.12 + i * 1.16;
    s.addShape(pptx.ShapeType.rect, { x: x2, y, w: 0.05, h: 0.9, fill: { color: T.gold } });
    s.addText([
      { text: it[0], options: { bold: true, color: T.ink, fontFace: F, fontSize: 13.5, breakLine: true } },
      { text: it[1], options: { color: T.muted, fontFace: F, fontSize: 11.5 } },
    ], { x: x2 + 0.22, y, w: w2 - 0.3, h: 1.02, valign: "top", lineSpacingMultiple: 1.08 });
  });
  foot(s, idx);
  return s;
}

// ─────────────────────────────── 版式：章节页
function divider(num, label, title, line) {
  const s = pptx.addSlide();
  s.background = { color: T.dark };
  s.addShape(pptx.ShapeType.ellipse, { x: W - 2.6, y: -1.5, w: 5.2, h: 5.2, fill: { color: T.accent, transparency: 82 } });
  s.addShape(pptx.ShapeType.ellipse, { x: W - 1.6, y: 4.6, w: 3.4, h: 3.4, fill: { color: T.gold, transparency: 86 } });
  hairline(s, M, 2.62, 1.2, T.gold, 0.045);
  token(s, String(num).padStart(2, "0"), {
    x: M, y: 1.72, w: 1.4, h: 0.7, fontFace: FN, fontSize: 30, bold: true, color: T.gold,
  });
  s.addText(label, { x: M, y: 2.76, w: CW, h: 0.3, fontFace: F, fontSize: 12, color: T.cream, charSpacing: 1.6 });
  s.addText(title, { x: M, y: 3.06, w: CW, h: 0.9, fontFace: F, fontSize: 32, bold: true, color: T.cream });
  s.addText(line, { x: M, y: 4.1, w: CW - 2, h: 0.5, fontFace: F, fontSize: 13, color: "D8C6AC" });
  return s;
}

// ─────────────────────────────── 版式：结束页
function closing() {
  const s = pptx.addSlide();
  s.background = { color: T.dark };
  s.addImage({ path: SHOT("03_cleared.png"), x: 0, y: 0, w: W, h: H });
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: "2A150C", transparency: 34 } });
  hairline(s, M, 2.3, 1.5, T.gold, 0.045);
  s.addText("收阵 · 谢谢", { x: M, y: 2.44, w: CW, h: 0.9, fontFace: F, fontSize: 38, bold: true, color: T.cream });
  s.addText("欢迎试玩《踏鼓》，一起把英歌舞的节奏打出来", {
    x: M, y: 3.4, w: CW, h: 0.4, fontFace: F, fontSize: 15, color: "E8D9C2",
  });
  s.addText("游戏工程开源：https://github.com/shuda-li/YingGeGame", {
    x: M, y: 4.05, w: CW, h: 0.34, fontFace: FN, fontSize: 12, color: T.gold,
  });
  s.addText("第 8 小组 ｜ 李舒达（组长）· 李玉赫 · 陈圣源 · 陈东阳 · 李佳泰 · 沈豫辉 · 梁铭贵 · 孙政彰 · 吴彩云 · 翁泽荣", {
    x: M, y: 6.3, w: CW, h: 0.34, fontFace: F, fontSize: 10.5, color: "C9B79C",
  });
  note(s, "收尾：邀请老师和其他小组同学试玩，现场收集反馈。");
}

// ─────────────────────────────── 组页
cover();
agenda([
  ["项目概述", "两项核心产出与二元实践路径"],
  ["小组分工", "教学组 5 人 · 开发组 6 人，职责到人"],
  ["游戏方案", "合拍判定 · 数据驱动 · 三关设计"],
  ["方案创新点", "以非遗鼓点为核心判定机制"],
  ["进度与可行性", "已完成两个里程碑，风险有应对"],
  ["成果与展望", "从课堂走向校园与网页平台"],
]);

divider(1, "OVERVIEW", "项目概述与目标", "以国家级非遗英歌舞为核心对象，技艺教学与数字开发并行推进");
cards("PROJECT GOALS", "四个目标都可量化核对", [
  { token: "2", head: "总目标", text: "7 次课（14 课时）内完成两项核心产出：一套动作教学体系、一款含 3 关的可玩游戏" },
  { head: "教学目标", text: "节选握槌、转槌、击槌、后抬腿提颠步、马步背槌、旋槌等简单动作分解教学；零基础同学可完整展示一套短组合" },
  { head: "游戏目标", text: "玩家踩着锣鼓鼓点完成「跑、跳、击槌」与对击弹反，通关 3 个关卡；踩准判定点可获得伤害倍率" },
  { head: "传播目标", text: "教学与游戏成果推广至校内其他班级或社团，并发布至网页平台供更多人体验" },
], 3);

bullets("CORE OUTPUTS", "两项核心产出：教得会，也玩得起来", [
  ["英歌舞基础动作教学体系：", "从英歌舞中节选简单、易上手的动作做分解教学，形成教学讲义与教学视频"],
  ["英歌主题横版动作闯关游戏：", "以真实英歌像素素材与锣鼓鼓点为核心，完成 3 个关卡的可玩版本"],
  ["二元实践路径：", "技艺教学与数字开发同步推进，教学动作直接对应游戏招式，两条产出互相支撑"],
  ["真实素材驱动：", "游戏素材由本组用豆包图像模型生成，再经抠图、分帧、像素化处理接入游戏"],
], 4);

timeline("SCHEDULE", "七次课双线并行，任务量匹配课时", [
  ["文化认知", "项目启动 · 文化讲座 · 握槌体验"],
  ["基本动作一", "转槌 · 击槌 · 后抬腿提颠步"],
  ["基本动作二", "弓步背槌 · 旋槌 · 组合初成"],
  ["组合 + 开发", "双抢槌等组合 · 素材接入游戏"],
  ["复习 + 关卡", "动作成套 · 三关设计讨论"],
  ["整合彩排", "成果排练 · 录宣传视频 · 游戏测试"],
  ["展示总结", "集体展演 · 游戏演示 · 汇报"],
], 5);

divider(2, "TEAM", "小组分工与协作机制", "10 人分两组，职责到人，进度公开可查");
twoCol("TEAM ROLES", "分工到人，职责清晰", {
  title: "英歌舞动作教学组（5 人）",
  items: [
    ["梁铭贵", "握槌与转槌的分解教学与示范"],
    ["孙政彰", "击槌基础动作的分解教学与示范"],
    ["吴彩云", "后抬腿提颠步等基础步伐教学"],
    ["翁泽荣", "马步背槌、旋槌等进阶段动作教学"],
    ["李舒达", "教学编排与进度把控，成套组合串联"],
  ],
  foot: "小老师现场示范、逐组纠错，先单手后双手、先原地后行进。",
}, {
  title: "英歌游戏开发组（6 人）",
  items: [
    ["李舒达", "总体架构、合拍判定与音频时钟"],
    ["李玉赫", "美术与素材（角色 / 场景 / UI）"],
    ["陈圣源", "运动手感与三个关卡设计"],
    ["陈东阳", "战斗系统、对击弹反与敌人"],
    ["李佳泰", "锣鼓音效、板式切换与节拍校验"],
    ["沈豫辉", "测试、手感调参、打包与宣传"],
  ],
  foot: "每周例会 + 课后任务到人 + 进度记录在仓库《项目进度.md》。",
}, 6);

divider(3, "GAME DESIGN", "游戏开发方案", "把英歌舞的节奏感，翻译成可上手的操作");
imageSlide("CORE MECHANIC", "踩准锣鼓鼓点出招，伤害更高", SHOT("01_start.png"),
  "实机截图：祠堂廊柱赛段，判定圈随鼓点收缩", [
    ["踩点即倍率：", "判定点固定落在每小节第 1、3 拍，踩准可获得伤害倍率"],
    ["按键帧锚点：", "完美窗口 ±40ms、合拍窗口 ±80ms，反馈在按键帧立即触发"],
    ["音频时钟驱动：", "判定由音频时钟计算，帧率波动不影响判定结果"],
    ["空挥不惩罚伤害：", "空挥仍保留音效与判定反馈，只是不给伤害与鼓劲"],
  ], 8);

cards("TECH STACK", "数据驱动 + 素材驱动，零基础也能推进", [
  { token: "Py", head: "技术栈", text: "Python 3 + pygame + numpy + sounddevice，全部免费；可打包 Windows 可执行文件或发布网页" },
  { token: "5", head: "数据表", text: "手感、节奏、动作帧、关卡、辅助参数全部写成 JSON 表；改数值不改代码" },
  { token: "31", head: "像素素材", text: "玩家 7 + 敌人 8 + 环境 13 + UI 3，统一抠图、分帧与整数倍缩放" },
  { token: "AI", head: "开发方式", text: "Trae + AI 模型辅助编程；把「如何用 AI 一步步做完」固化为带验收标准的路线图" },
], 9);

tableSlide("SIX SYSTEMS", "六大玩法系统，玩法闭环完整", ["编号", "系统", "规则要点"], [
  ["S1", "合拍判定", "按键帧锚点；完美 ±40ms / 合拍 ±80ms；音频时钟驱动"],
  ["S2", "锣鼓板式", "慢板 90 / 中板 110 / 快板 140 / 极板 150 BPM；仅在小节边界换板"],
  ["S3", "运动手感", "固定步长 1/120s；疾行、腾跃、二段跳、抢步、矮子步"],
  ["S4", "帧数据战斗", "挥槌三段、凌空挥槌两段、劈山、对击；取消窗口在 recovery 后 40%"],
  ["S5", "对击弹反", "敌人命中前 100ms 内按攻击触发；成功硬直并加鼓劲"],
  ["S6", "鼓劲与满堂彩", "疾行 + 命中 + 合拍倍率 + 弹反叠加；满槽且连段 ≥4 释放"],
], 10);

cards("LEVELS", "三关递进：从教学到 Boss 战", [
  { token: "L1", head: "英歌初醒", text: "慢板 90 BPM；教学移动 + 击槌 + 合拍判定；巡逻兵 ×2；祠堂廊柱" },
  { token: "L2", head: "双龙出海", text: "中板 110 → 快板 140；教学跳跃、对击弹反与抢步；骑楼街景" },
  { token: "L3", head: "战舞传承", text: "快板 140 → 极板 150；综合运用 + 满堂彩终结；关底 Boss（英歌领队）" },
], 11);

divider(4, "INNOVATION", "方案创新点", "以非遗鼓点作为核心判定机制，是本方案最独特的地方");
bullets("INNOVATION", "六个创新点，从机制到流程", [
  ["节奏化操作机制：", "把英歌锣鼓鼓点直接当作判定节拍器，踩准每小节第 1、3 拍出招即可获得伤害倍率"],
  ["判定由音频时钟驱动：", "帧率波动不影响判定结果，手感稳定可预期"],
  ["真实素材驱动：", "像素素材由本组用 AI 生成，并配套抠图、分帧、统一缩放的标准化处理流程"],
  ["数据驱动架构：", "手感、节奏、动作帧、关卡全部走 JSON 数据表，便于借助 AI 快速迭代"],
  ["教学与游戏双向验证：", "教学动作对应游戏招式，游戏又可反过来展示教学成果"],
  ["AI 协作开发流程：", "把「如何用 AI 一步步做完」固化为带验收标准的里程碑路线图"],
], 13);

divider(5, "PROGRESS", "开发进度与可行性", "已完成两个里程碑，关键指标经过实跑验证");
imageSlide("PROGRESS", "M0 / M1 已完成，指标经实测", SHOT("03_cleared.png"),
  "实机截图：收阵结算界面", [
    ["M0 可玩原型（已完成）：", "单赛段可通关、敌人全清、完美合拍率 86%、判定误差均值 −3.4ms"],
    ["M1 素材接入（已完成）：", "31 项像素素材落位，角色、敌人、场景全部换成像素贴图，缺图自动回退"],
    ["M2 玩法补全（进行中）：", "补齐招式动画与敌人种类，完成第 2、3 关与结算界面"],
    ["M3 音频与发布（未开始）：", "四档板式锣鼓音频、真人试玩调参、打包发布与展示物料"],
  ], 15);

bullets("FEASIBILITY", "工具免费、任务已拆解、预算可控", [
  ["技术可行：", "全部工具免费（Trae、Python、pygame），零基础可上手；合拍判定、音频时钟等关键技术已在原型中跑通"],
  ["时间可行：", "7 次课 14 课时的教学与开发任务已按次课拆解，开发已完成两个里程碑"],
  ["经费可行：", "总预算 400 元，仅用于英歌槌与耗材；软件与素材生成无额外支出"],
  ["素材风险 → 应对：", "先出「定妆图」，之后每个动作状态都以定妆图 + 妆造照片为参考图生成，避免角色长相漂移"],
  ["进度风险 → 应对：", "按「先跑通原型 → 再接入素材 → 最后补内容」推进，保证任何时候都有可演示版本"],
  ["范围风险 → 应对：", "7 次课内只做 3 个关卡，不做成长系统与联网功能"],
], 16);

bullets("OUTCOME", "成果产出与项目展望", [
  ["成果产出：", "一套英歌舞简单动作组合教学（含讲义与视频）、一款含 3 关的英歌主题游戏原型、教学影像资料、宣传推文与短视频"],
  ["开源归档：", "源码、像素素材与设计文档托管于 GitHub（含《项目进度.md》记录问题与下一步）"],
  ["短期目标：", "7 次课后完成两项核心产出的原型版本，在课程成果展示中呈现"],
  ["中期展望：", "推广至校内其他班级或社团；游戏发布至网页平台供更多人体验"],
  ["长期价值：", "探索「非遗 + 数字技术」的融合模式，为潮汕非遗的年轻化传播提供可复制的实践案例"],
], 17);

closing();

// ─────────────────────────────── 输出
fs.mkdirSync(OUT_DIR, { recursive: true });
pptx.writeFile({ fileName: OUT }).then(() => {
  console.log("已生成:", OUT);
  console.log("幻灯片数:", pptx.slides ? pptx.slides.length : "(见文件)");
});
