# markdown_stylist_mcp — 极简 Mac 风格 Markdown 渲染工具

将原始 Markdown 文本转化为具有 **极简、专业、Mac 风格** 的结构化报告（HTML + PDF）。

---

## 核心能力

| 特性 | 说明 |
|------|------|
| 📑 自动目录 (TOC) | 左侧 5px 浅蓝装饰线，层级缩进，锚点跳转 |
| 📊 斑马纹表格 | 奇偶行交替 #fff / #f9f9f9，1px 细边框 |
| 💻 Mac 风格代码块 | 深色背景 #282c34，红/黄/绿三色圆点装饰 |
| 📋 元数据属性卡 | 浅蓝背景引用块，记录生成日期、路径等 |
| 🖨️ HTML + PDF 双输出 | 浏览器可交互 + 打印级 PDF |

---

## 架构

```
数据解析 → 模板注入 → 格式转换 (三层 Pipeline)

Layer 1: markdown 库解析 MD → HTML 片段 + TOC
Layer 2: BeautifulSoup 后处理 → Mac 代码块装饰
Layer 3: Jinja2 渲染完整 HTML → (可选) WeasyPrint → PDF
```

---

## 安装

### 1. 环境要求

- Python 3.11+
- Windows / macOS / Linux

### 2. 安装依赖

```bash
cd I:\Claude_Project\WechatOfficialAccount_MCP
pip install -r requirements.txt
```

### 3. WeasyPrint 额外依赖（PDF 输出）

**Windows**：下载并安装 [GTK3 runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)

**macOS**：
```bash
brew install pango
```

**Linux**：
```bash
sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0
```

---

## 作为 MCP 服务端使用

### Claude Code 配置

在 Claude Code 的 MCP 配置中添加 `config.json` 中的内容：

```json
{
  "mcpServers": {
    "markdown-stylist": {
      "command": "python",
      "args": ["markdown_stylist_mcp.py"],
      "cwd": "I:/Claude_Project/WechatOfficialAccount_MCP",
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

### 可用工具

#### `discover_md_files`
扫描目录，列出所有 MD 文件。

**参数**：`input_path` — 目录或文件路径

**返回**：文件列表 + 交互提示

#### `convert_markdown`
将 MD 文件转换为 Mac 风格的 HTML/PDF。

**参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `input_path` | string | ✅ | MD 文件或目录路径 |
| `output_path` | string | ✅ | 输出目录 |
| `output_format` | string | ❌ | `"html"` / `"pdf"` / `"both"`，默认 `"html"` |
| `files` | string[] | ❌ | 指定文件列表，为空则自动发现 |
| `batch_all_same` | boolean | ❌ | 统一格式，默认 `true` |

---

## 典型工作流

```
1. discover_md_files("I:/project/output/")
   → 返回 3 个文件，询问用户

2. 用户选择: "统一输出为 both 格式"

3. convert_markdown(
     input_path="I:/project/output/",
     output_path="I:/project/rendered/",
     output_format="both",
     batch_all_same=true
   )
   → 生成 3 × 2 = 6 个文件 (HTML + PDF)
```

---

## 输出示例

```
rendered/
  ├── article_1.html        # 交互版网页
  ├── article_1.pdf         # 打印版 PDF
  ├── article_2.html
  └── article_2.pdf
```

---

## 文件清单

| 文件 | 用途 |
|------|------|
| `markdown_stylist_mcp.py` | MCP 服务端主程序（含三层 Pipeline） |
| `templates/base.html` | Jinja2 HTML 模板（含完整 CSS） |
| `style.css` | 独立 CSS 样式表（参考用） |
| `config.json` | MCP 服务端配置示例 |
| `requirements.txt` | Python 依赖清单 |
| `README.md` | 本文件 |

---

## 独立使用（不通过 MCP）

也可以直接作为 Python 模块调用：

```python
from markdown_stylist_mcp import process_single_file
from pathlib import Path

result = process_single_file(
    md_path=Path("article.md"),
    output_dir=Path("./output"),
    output_format="both",
)
print(result)
# {'status': 'success', 'file': 'article.md',
#  'outputs': {'html': 'output/article.html', 'pdf': 'output/article.pdf'}}
```
