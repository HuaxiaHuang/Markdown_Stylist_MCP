# Markdown Stylist MCP

将 Markdown 文件转化为 **Mac 极简风格** 的专业 HTML / PDF 报告。支持 CLI 交互式使用和 MCP 协议（AI Agent 调用）两种模式。

---

## 特性

- **自动目录 (TOC)** — 层级缩进，锚点跳转，左侧浅蓝装饰线
- **斑马纹表格** — 奇偶行交替底色，hover 高亮
- **Mac 风格代码块** — 深色背景 + 红/黄/绿三色圆点装饰
- **元数据卡片** — 自动提取文件信息，浅蓝背景属性栏
- **HTML + PDF 双输出** — 浏览器可交互 + A4 打印级 PDF
- **智能批量处理** — 递归扫描目录，保留目录结构，自动解决同名冲突

---

## 安装

```bash
git clone https://github.com/HuaxiaHuang/Markdown_Stylist_MCP.git
cd Markdown_Stylist_MCP
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt     # macOS / Linux
```

**PDF 输出需要浏览器引擎**：

```bash
.venv\Scripts\python -m playwright install chromium
```

> 也可使用 WeasyPrint 作为 PDF 引擎，但 Windows 需额外安装 GTK3 runtime。

---

## 使用方式一：CLI 交互模式（人直接使用）

```bash
python markdown_stylist_mcp.py
```

交互式问答，输入路径 → 输出路径 → 格式，即可完成转换。

### 示例：单文件 → HTML

```
====================================================
  Markdown Stylist — 极简 Mac 风格 MD -> HTML/PDF
====================================================

[INPUT] 请输入 Markdown 文件或目录路径: I:\articles\report.md
   [FILE] 单文件模式: report.md
[OUTPUT] 请输入输出目录路径: I:\output

[FORMAT] 请选择输出格式:
   1. HTML（网页交互版）
   2. PDF（专业打印版）
   请输入 1 或 2: 1

----------------------------------------------------
[START] 开始转换 | 格式: HTML | 文件数: 1
----------------------------------------------------
[1/1] report.md ... OK -> report.html

[DONE] 成功 1/1  ->  I:\output
```

### 示例：目录 → PDF

```
[INPUT] 请输入 Markdown 文件或目录路径: I:\articles
   [DIR] 目录模式: 发现 5 个 Markdown 文件:
      1. intro.md (12.3 KB)
      2. methods.md (18.7 KB)
      3. results.md (25.1 KB)
      4. discussion.md (32.4 KB)
      5. conclusion.md (8.9 KB)

[OUTPUT] 请输入输出目录路径: I:\output
[FORMAT] 请选择输出格式:
   1. HTML（网页交互版）
   2. PDF（专业打印版）
   请输入 1 或 2: 2

----------------------------------------------------
[START] 开始转换 | 格式: PDF | 文件数: 5
----------------------------------------------------
[1/5] intro.md ... OK -> intro.pdf
[2/5] methods.md ... OK -> methods.pdf
[3/5] results.md ... OK -> results.pdf
[4/5] discussion.md ... OK -> discussion.pdf
[5/5] conclusion.md ... OK -> conclusion.pdf

[DONE] 成功 5/5  ->  I:\output
```

输入目录时自动递归发现所有 `.md` 文件，自动排除 `.venv`、`.git`、`node_modules` 等噪音目录，输出保留源目录结构。

---

## 使用方式二：MCP 模式（AI Agent 调用）

在 Claude Code 中添加此 MCP Server，之后可直接对 AI 说"把 xx 目录的 md 文件渲染成 HTML"。

### 添加配置

```bash
claude mcp add --scope user markdown-stylist -- \
  /path/to/.venv/Scripts/python.exe \
  /path/to/markdown_stylist_mcp.py \
  --mcp
```

> 注意末尾的 `--mcp` 参数，用于启动 MCP 服务端模式。

### MCP 工具列表

| 工具 | 说明 |
|------|------|
| `discover_md_files` | 扫描目录，列出所有 Markdown 文件 |
| `convert_markdown` | 将 MD 文件转换为 HTML/PDF |
| `check_pdf_support` | 检测当前系统 PDF 引擎可用性 |

### `convert_markdown` 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| `input_path` | string | 是 | — | MD 文件或目录路径 |
| `output_path` | string | 是 | — | 输出目录路径 |
| `output_format` | string | 否 | `html` | `html` / `pdf` |
| `files` | string[] | 否 | — | 指定文件列表，为空则自动发现 |
| `preserve_structure` | boolean | 否 | `true` | 是否保留源目录层级 |

---

## PDF 引擎

脚本内置双引擎，按优先级自动选择：

| 引擎 | 安装 | 平台 |
|------|------|------|
| **Playwright** (首选) | `pip install playwright` + `playwright install chromium` | Windows / macOS / Linux 通用 |
| WeasyPrint (回退) | `pip install weasyprint` + GTK3 runtime | Windows 需额外安装系统库 |

运行 `python markdown_stylist_mcp.py` 后选 `2`（PDF 格式），脚本会自动检测可用引擎并生成 PDF。

---

## 项目结构

```
Markdown_Stylist_MCP/
├── markdown_stylist_mcp.py   # 主程序（CLI + MCP 双模式入口）
├── templates/
│   └── base.html             # Jinja2 模板（含完整 CSS）
├── requirements.txt          # Python 依赖
├── config.json               # MCP 配置示例
├── style.css                 # 独立 CSS 参考
└── README.md
```

---

## 架构

```
Markdown 文本
    │
    ▼
Layer 1: markdown 库解析 → HTML 片段 + TOC
    │
    ▼
Layer 2: BeautifulSoup 后处理 → Mac 代码块 / 表格 / 图片增强
    │
    ▼
Layer 3: Jinja2 模板注入 → 完整 HTML → (可选) Playwright / WeasyPrint → PDF
```

---

## License

MIT
