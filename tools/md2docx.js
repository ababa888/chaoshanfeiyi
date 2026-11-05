// 《踏鼓》文档工具：Markdown → DOCX
// 支持：多级标题 / 无序列表（含 2 空格缩进的二级嵌套）/ 有序列表 / 表格 / 代码块 / 引用 / 行内 **粗体** 与 `代码`
//
// 用法（在 tools 目录下）：
//   npm install
//   npm run docx -- <输入.md> <输出.docx>
//
// 例：
//   npm run docx -- ../docs/策划案/project-drumbeat-game-design-proposal.md ../docs/策划案/project-drumbeat-game-design-proposal.docx
//
// 说明：正文中文用 Microsoft YaHei；若本机无该字体，Word 会自动回退到其他中文字体。
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, WidthType, BorderStyle, ShadingType, LevelFormat, HeadingLevel,
} = require("docx");

const CJK = "Microsoft YaHei";
const fBody = { ascii: "Arial", hAnsi: "Arial", eastAsia: CJK };
const fMono = { ascii: "Consolas", hAnsi: "Consolas", eastAsia: CJK };
const BODY = 22, SMALL = 20, MONO_SZ = 18, CELL = 20;   // 半磅：22 = 11pt
const CONTENT_W = 9026;   // A4 宽 11906 DXA - 左右页边距各 1440

// ---------------------------------------------------------------- 行内解析
function inline(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  const size = base.size || BODY;
  let last = 0, m;
  const push = (t, extra = {}) => out.push(new TextRun(Object.assign({ text: t, size, font: fBody }, base, extra)));
  while ((m = re.exec(text))) {
    if (m.index > last) push(text.slice(last, m.index));
    const tk = m[0];
    if (tk.startsWith("**")) push(tk.slice(2, -2), { bold: true });
    else push(tk.slice(1, -1), { font: fMono, color: "7A3E00" });
    last = m.index + tk.length;
  }
  if (last < text.length) push(text.slice(last));
  return out;
}

// ---------------------------------------------------------------- 块级解析
function parse(md) {
  const raw = md.replace(/\r\n/g, "\n").split("\n");
  const tokens = [];
  const numRefs = [];
  let lastKind = null;

  for (let i = 0; i < raw.length; i++) {
    const line = raw[i];
    if (/^\s*$/.test(line)) continue;              // 空行
    if (/^-{3,}$/.test(line.trim())) continue;     // 分隔线

    if (line.trim().startsWith("```")) {           // 代码块
      const buf = [];
      i++;
      while (i < raw.length && !raw[i].trim().startsWith("```")) { buf.push(raw[i]); i++; }
      tokens.push({ t: "code", lines: buf });
      lastKind = "code";
      continue;
    }
    let m;
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {   // 标题
      tokens.push({ t: "h", level: m[1].length, text: m[2].trim() });
      lastKind = "h" + m[1].length;
      continue;
    }
    if (line.startsWith("> ")) {                   // 引用
      tokens.push({ t: "quote", text: line.slice(2).trim() });
      lastKind = "quote";
      continue;
    }
    if (line.trim().startsWith("|")) {             // 表格
      const rows = [];
      while (i < raw.length && raw[i].trim().startsWith("|")) {
        const cells = raw[i].trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((s) => s.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      i--;
      tokens.push({ t: "table", rows });
      lastKind = "table";
      continue;
    }
    if ((m = line.match(/^(\s*)[-*]\s+(.*)$/))) {  // 无序列表（2 空格 = 二级）
      tokens.push({ t: "ul", level: Math.min(Math.floor(m[1].length / 2), 1), text: m[2].trim() });
      lastKind = "ul";
      continue;
    }
    if ((m = line.match(/^(\s*)\d+\.\s+(.*)$/))) { // 有序列表（每段独立编号，从 1 重新开始）
      if (lastKind !== "ol") numRefs.push("num" + numRefs.length);
      tokens.push({ t: "ol", ref: numRefs[numRefs.length - 1], text: m[2].trim() });
      lastKind = "ol";
      continue;
    }
    tokens.push({ t: "p", text: line.trim() });    // 普通段落
    lastKind = "p";
  }
  return { tokens, numRefs };
}

// ---------------------------------------------------------------- 生成 DOCX
function build(tokens, numRefs) {
  const children = [];
  const border = { style: BorderStyle.SINGLE, size: 2, color: "BFBFBF" };
  const borders = { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border };

  for (const tk of tokens) {
    if (tk.t === "h") {
      if (tk.level === 1) {
        children.push(new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 200, after: 200 },
          children: [new TextRun({ text: tk.text, bold: true, size: 40, font: fBody })],
        }));
      } else {
        const lvl = tk.level === 2 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2;
        children.push(new Paragraph({ heading: lvl, children: [new TextRun({ text: tk.text, bold: true, font: fBody })] }));
      }
    } else if (tk.t === "p") {
      children.push(new Paragraph({ spacing: { before: 40, after: 40, line: 300 }, children: inline(tk.text) }));
    } else if (tk.t === "quote") {
      children.push(new Paragraph({
        spacing: { before: 80, after: 120, line: 300 },
        indent: { left: 300 },
        border: { left: { style: BorderStyle.SINGLE, size: 12, color: "C00000", space: 8 } },
        children: inline(tk.text, { italics: true, color: "595959", size: SMALL }),
      }));
    } else if (tk.t === "ul") {
      children.push(new Paragraph({
        numbering: { reference: "bul", level: tk.level },
        spacing: { before: 20, after: 20, line: 300 },
        children: inline(tk.text, { size: tk.level ? SMALL : BODY }),
      }));
    } else if (tk.t === "ol") {
      children.push(new Paragraph({
        numbering: { reference: tk.ref, level: 0 },
        spacing: { before: 20, after: 20, line: 300 },
        children: inline(tk.text),
      }));
    } else if (tk.t === "code") {
      tk.lines.forEach((ln, idx) => {
        children.push(new Paragraph({
          spacing: { before: idx === 0 ? 80 : 0, after: idx === tk.lines.length - 1 ? 120 : 0, line: 240 },
          indent: { left: 240 },
          shading: { type: ShadingType.CLEAR, fill: "F4F4F4" },
          children: [new TextRun({ text: ln || " ", font: fMono, size: MONO_SZ })],
        }));
      });
    } else if (tk.t === "table") {
      const cols = Math.max(...tk.rows.map((r) => r.length));
      const base = Math.floor(CONTENT_W / cols);
      const widths = new Array(cols).fill(base);
      widths[cols - 1] += CONTENT_W - base * cols;   // 余数补给末列，保证列宽之和 = 表宽
      const rows = tk.rows.map((cells, ri) => new TableRow({
        tableHeader: ri === 0,
        cantSplit: true,
        children: cells.map((c, ci) => new TableCell({
          borders,
          width: { size: widths[ci], type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: ri === 0 ? "E7E6E6" : undefined },
          margins: { top: 60, bottom: 60, left: 110, right: 110 },
          children: [new Paragraph({ spacing: { before: 20, after: 20, line: 260 }, children: inline(c, { size: CELL, bold: ri === 0 }) })],
        })),
      }));
      children.push(new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths, rows }));
      children.push(new Paragraph({ spacing: { before: 0, after: 100 }, children: [new TextRun({ text: "", size: 2 })] }));
    }
  }

  const numbering = [{
    reference: "bul",
    levels: [
      { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 220 } } } },
      { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 900, hanging: 220 } } } },
    ],
  }];
  numRefs.forEach((r) => numbering.push({
    reference: r,
    levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 220 } } } }],
  }));

  return new Document({
    styles: {
      default: { document: { run: { font: fBody, size: BODY } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 32, bold: true, font: fBody, color: "1F3864" },
          paragraph: { spacing: { before: 260, after: 140 }, outlineLevel: 0, keepNext: false, keepLines: false } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 26, bold: true, font: fBody, color: "2E5496" },
          paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1, keepNext: false, keepLines: false } },
      ],
    },
    numbering: { config: numbering },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
      children,
    }],
  });
}

// ---------------------------------------------------------------- 入口
function main() {
  const [inPath, outPath] = process.argv.slice(2);
  if (!inPath || !outPath) {
    console.error("用法: npm run docx -- <输入.md> <输出.docx>");
    process.exit(1);
  }
  const { tokens, numRefs } = parse(fs.readFileSync(inPath, "utf8"));
  Packer.toBuffer(build(tokens, numRefs)).then((buf) => {
    fs.writeFileSync(outPath, buf);
    console.log(`已生成: ${outPath}（${buf.length} 字节，块 ${tokens.length} 个，表格 ${tokens.filter((t) => t.t === "table").length} 张）`);
  });
}

main();
