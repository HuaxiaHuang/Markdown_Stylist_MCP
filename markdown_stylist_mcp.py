#!/usr/bin/env python3
"""
markdown_stylist_mcp — 极简 Mac 风格 Markdown → HTML/PDF 转换器
=================================================================
Model Context Protocol (MCP) 服务端工具。
将原始 Markdown 转化为具有专业排版的结构化报告。

架构:  数据解析 → 模板注入 → 格式转换  (三层 Pipeline)

依赖:  markdown, Jinja2, WeasyPrint, beautifulsoup4
"""

import os
import sys
import json
import hashlib
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── MCP SDK ──
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ── Markdown 解析 ──
import markdown
from markdown.extensions import toc, fenced_code, tables, codehilite

# ── Jinja2 模板 ──
from jinja2 import Environment, FileSystemLoader

# ── HTML 后处理 ──
from bs4 import BeautifulSoup


# ╔══════════════════════════════════════════════════════════════╗
# ║                     CONFIGURATION                            ║
# ╚══════════════════════════════════════════════════════════════╝

PROJECT_ROOT = Path(__file__).parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Markdown 扩展配置
MD_EXTENSIONS = [
    "markdown.extensions.toc",       # 目录生成
    "markdown.extensions.fenced_code",  # 围栏代码块
    "markdown.extensions.tables",    # 表格
    "markdown.extensions.codehilite",   # 代码高亮
    "markdown.extensions.nl2br",     # 换行转 <br>
    "markdown.extensions.sane_lists",   # 智能列表
]

MD_EXTENSION_CONFIGS = {
    "markdown.extensions.toc": {
        "permalink": True,
        "permalink_class": "toc-link",
        "baselevel": 2,
        "toc_depth": "2-4",
    },
    "markdown.extensions.codehilite": {
        "guess_lang": False,
        "use_pygments": False,
    },
}


# 扫描时排除的目录名（避免扫描虚拟环境、版本控制等噪音）
EXCLUDE_DIR_NAMES = {
    ".venv", ".git", "__pycache__", "node_modules",
    ".idea", ".vscode", "venv", "env", ".tox", ".eggs",
    "build", "dist", ".mypy_cache", ".pytest_cache",
}


# ╔══════════════════════════════════════════════════════════════╗
# ║               LAYER 1: DATA PARSING                          ║
# ╚══════════════════════════════════════════════════════════════╝

def discover_md_files(input_path: str) -> list[Path]:
    """发现 MD 文件：支持单个文件或目录递归扫描。自动排除 .venv/.git 等噪音目录。"""
    path = Path(input_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"路径不存在: {input_path}")

    if path.is_file():
        if path.suffix.lower() == ".md":
            return [path]
        else:
            raise ValueError(f"文件不是 Markdown: {path.name}")

    # 目录：递归收集 .md 文件，排除噪音目录
    md_files = []
    for f in path.rglob("*.md"):
        # 跳过排除目录中的文件
        if EXCLUDE_DIR_NAMES & set(f.parts):
            continue
        md_files.append(f)

    if not md_files:
        raise FileNotFoundError(f"目录中未找到 .md 文件: {path}")
    return sorted(md_files)


def parse_markdown(md_text: str) -> dict:
    """将 Markdown 文本解析为 HTML 内容 + 提取 TOC。"""
    md_instance = markdown.Markdown(
        extensions=MD_EXTENSIONS,
        extension_configs=MD_EXTENSION_CONFIGS,
    )
    body_html = md_instance.convert(md_text)

    # 提取 TOC（markdown toc 扩展会把 TOC 写入 md_instance.toc）
    toc_html = getattr(md_instance, "toc", "") or ""

    return {"content_html": body_html, "toc_html": toc_html}


def extract_title(md_text: str, file_path: Path) -> str:
    """从 Markdown 中提取标题：第一个 H1 或文件名。"""
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return file_path.stem.replace("_", " ")


def extract_meta_items(md_text: str) -> list[dict]:
    """从 Markdown 开头的 blockquote 行提取元数据项。"""
    items = []
    in_blockquote = False
    for line in md_text.splitlines()[:30]:
        stripped = line.strip()
        if stripped.startswith("> "):
            in_blockquote = True
            content = stripped[2:].strip()
            # 尝试解析 "label: value" 或 "label：value"
            if ":" in content:
                parts = content.split(":", 1)
                items.append({"label": parts[0].strip(), "value": parts[1].strip()})
            elif "：" in content:
                parts = content.split("：", 1)
                items.append({"label": parts[0].strip(), "value": parts[1].strip()})
        elif in_blockquote and stripped == ">":
            continue
        elif in_blockquote and not stripped.startswith("> "):
            break
    return items


# ╔══════════════════════════════════════════════════════════════╗
# ║            LAYER 2: HTML POST-PROCESSING                     ║
# ╚══════════════════════════════════════════════════════════════╝

def post_process_html(html: str) -> str:
    """
    对 markdown 生成的 HTML 进行 Mac 风格后处理：
    - 给每个 <pre> 包裹 Mac 窗口装饰（三色圆点）
    - 给表格添加所需 class
    - 美化图片为 figure 结构
    """
    soup = BeautifulSoup(html, "lxml")

    # 1. Mac 风格代码块：<pre> 包裹 .code-block-wrapper
    for pre in soup.find_all("pre"):
        wrapper = soup.new_tag("div", attrs={"class": "code-block-wrapper"})
        header = soup.new_tag("div", attrs={"class": "code-block-header"})
        header.append(_make_dot(soup, "red"))
        header.append(_make_dot(soup, "yellow"))
        header.append(_make_dot(soup, "green"))
        label = soup.new_tag("span", attrs={"class": "file-label"})
        label.string = "code"
        header.append(label)
        pre.wrap(wrapper)
        wrapper.insert(0, header)

    # 2. 表格 class（CSS 已通过标签选择器处理，此处不强制加 class）
    for table in soup.find_all("table"):
        if "class" not in table.attrs:
            table.attrs["class"] = []

    # 3. 图片包裹为 figure > img + figcaption（若图片后有 <em> 文本）
    for img in soup.find_all("img"):
        parent = img.parent
        next_sib = img.find_next_sibling()
        if next_sib and next_sib.name == "em" and not img.find_parent("figure"):
            figure = soup.new_tag("figure")
            img.wrap(figure)
            caption = soup.new_tag("figcaption")
            caption.extend(list(next_sib.children))
            figure.append(caption)
            next_sib.decompose()

    return str(soup)


def _make_dot(soup, color: str):
    dot = soup.new_tag("span", attrs={"class": f"mac-dot {color}"})
    return dot


# ╔══════════════════════════════════════════════════════════════╗
# ║         LAYER 3: TEMPLATE RENDERING & PDF CONVERSION         ║
# ╚══════════════════════════════════════════════════════════════╝

def get_jinja_env() -> Environment:
    """获取 Jinja2 环境，加载 templates 目录。"""
    if not TEMPLATES_DIR.exists():
        raise FileNotFoundError(f"模板目录不存在: {TEMPLATES_DIR}")
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def render_html(title: str, content_html: str, toc_html: str,
                meta_items: list[dict]) -> str:
    """用 Jinja2 模板将各部分注入完整 HTML。"""
    env = get_jinja_env()
    template = env.get_template("base.html")

    # TOC 中的 <a> 需要保留；内容已由 markdown 生成 HTML
    return template.render(
        title=title,
        content=content_html,
        toc_html=toc_html,
        meta_items=meta_items,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def check_pdf_support() -> dict:
    """预检 PDF 生成能力。返回 {'ok': True/False, 'reason': ...}"""
    try:
        from weasyprint import HTML
        HTML(string="<p>test</p>").write_pdf()
        return {"ok": True}
    except ImportError:
        return {"ok": False, "reason": "WeasyPrint 未安装。运行: pip install weasyprint"}
    except OSError as e:
        if "gobject" in str(e).lower() or "libgobject" in str(e).lower():
            return {"ok": False,
                    "reason": "缺少 GTK3 系统库。Windows 请安装 GTK3 runtime: "
                              "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases"}
        return {"ok": False, "reason": f"PDF 库加载失败: {e}"}


def convert_to_pdf(html_content: str, output_pdf_path: Path) -> str:
    """使用 WeasyPrint 将 HTML 转换为 PDF。"""
    try:
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(str(output_pdf_path))
        return str(output_pdf_path)
    except ImportError:
        raise ImportError("PDF 转换需要安装 WeasyPrint: pip install weasyprint")
    except OSError as e:
        if "gobject" in str(e).lower() or "libgobject" in str(e).lower():
            raise RuntimeError(
                "PDF 生成需要 GTK3 系统库。Windows: 安装 GTK3 runtime; "
                "macOS: brew install pango; Linux: sudo apt install libpango-1.0-0"
            )
        raise RuntimeError(f"PDF 生成失败: {e}")
    except Exception as e:
        raise RuntimeError(f"PDF 生成失败: {e}")


# ╔══════════════════════════════════════════════════════════════╗
# ║                  CORE CONVERSION PIPELINE                     ║
# ╚══════════════════════════════════════════════════════════════╝

def process_single_file(md_path: Path, output_dir: Path,
                        output_format: str,
                        preserve_structure: bool = False,
                        input_base: Path = None) -> dict:
    """
    处理单个 MD 文件的完整 Pipeline：
      Layer 1: 读取 MD → parse_markdown() → HTML + TOC
      Layer 2: post_process_html() → Mac 风格增强
      Layer 3: render_html() → 完整 HTML → (可选) WeasyPrint PDF

    preserve_structure=True 时，输出目录会保留相对输入路径的目录结构，
    避免不同子目录中同名文件的输出冲突。
    """
    # 读取
    md_text = md_path.read_text(encoding="utf-8")
    if not md_text.strip():
        return {"status": "skipped", "file": str(md_path), "reason": "文件为空"}

    # Layer 1: 解析
    title = extract_title(md_text, md_path)
    meta_items = extract_meta_items(md_text)
    parsed = parse_markdown(md_text)

    # Layer 2: 后处理
    content_html = post_process_html(parsed["content_html"])
    toc_html = parsed["toc_html"]

    # 补充默认元数据
    if not meta_items:
        meta_items = [
            {"label": "文件", "value": md_path.name},
            {"label": "路径", "value": str(md_path.parent)},
        ]
    meta_items.append({"label": "生成时间", "value": datetime.now().strftime("%Y-%m-%d %H:%M")})

    # Layer 3: 渲染
    full_html = render_html(title, content_html, toc_html, meta_items)

    # 输出目录（可选保留目录结构）
    if preserve_structure and input_base is not None:
        try:
            rel_path = md_path.parent.relative_to(input_base)
        except ValueError:
            rel_path = md_path.parent.relative_to(md_path.anchor)
        output_subdir = output_dir / rel_path
    else:
        output_subdir = output_dir
    output_subdir.mkdir(parents=True, exist_ok=True)

    stem = md_path.stem
    result = {"file": str(md_path), "title": title, "outputs": {}}

    # HTML 输出 — 碰撞检测：同名文件用父目录名做后缀
    html_path = output_subdir / f"{stem}.html"
    if html_path.exists():
        parent_tag = md_path.parent.name
        html_path = output_subdir / f"{stem}__{parent_tag}.html"
    if html_path.exists():
        # 仍有冲突则加上完整路径哈希
        import hashlib
        path_hash = hashlib.md5(str(md_path).encode()).hexdigest()[:6]
        html_path = output_subdir / f"{stem}__{path_hash}.html"
    html_path.write_text(full_html, encoding="utf-8")
    result["outputs"]["html"] = str(html_path)

    # PDF 输出
    if output_format in ("pdf", "both"):
        pdf_path = output_subdir / f"{stem}.pdf"
        if pdf_path.exists():
            parent_tag = md_path.parent.name
            pdf_path = output_subdir / f"{stem}__{parent_tag}.pdf"
        try:
            convert_to_pdf(full_html, pdf_path)
            result["outputs"]["pdf"] = str(pdf_path)
        except Exception as e:
            result["outputs"]["pdf_error"] = str(e)

    result["status"] = "success"
    return result


# ╔══════════════════════════════════════════════════════════════╗
# ║                   MCP SERVER                                  ║
# ╚══════════════════════════════════════════════════════════════╝

mcp_server = Server("markdown-stylist")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="discover_md_files",
            description="扫描目录，返回所有发现的 Markdown 文件列表。用于在转换前了解有哪些文件。",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_path": {
                        "type": "string",
                        "description": "要扫描的目录路径或单个 MD 文件路径",
                    },
                },
                "required": ["input_path"],
            },
        ),
        Tool(
            name="convert_markdown",
            description=(
                "将 Markdown 文件转换为具有 Mac 极简风格的专业 HTML/PDF 报告。\n"
                "支持三种输出格式：html（Web 交互版）、pdf（专业打印版）、both（两者都输出）。\n"
                "自动生成目录（TOC）、Mac 风格代码块（三色圆点）、斑马纹表格。\n"
                "支持批量处理：可指定文件列表或目录（自动发现所有 .md 文件）。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "input_path": {
                        "type": "string",
                        "description": "Markdown 文件路径或包含 MD 文件的目录路径",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "输出目录路径（HTML/PDF 文件将保存到此目录）",
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["html", "pdf", "both"],
                        "description": "输出格式：'html'（仅 HTML）、'pdf'（仅 PDF）、'both'（HTML + PDF）",
                        "default": "html",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。指定要转换的文件列表（绝对路径）。如果为空，则自动发现 input_path 下的所有 MD 文件。",
                    },
                    "preserve_structure": {
                        "type": "boolean",
                        "description": "是否保留输入目录结构。true=输出目录镜像源目录层级（避免同名冲突）；false=扁平输出。默认 true。",
                        "default": True,
                    },
                    "batch_all_same": {
                        "type": "boolean",
                        "description": "批量模式下，是否所有文件使用相同输出格式。true=统一格式，false=待扩展。",
                        "default": True,
                    },
                },
                "required": ["input_path", "output_path"],
            },
        ),
        Tool(
            name="check_pdf_support",
            description="预检当前系统是否支持 PDF 生成。检查 WeasyPrint 和 GTK3 系统库是否正常。",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """路由 MCP 工具调用。"""
    try:
        if name == "discover_md_files":
            return await handle_discover(arguments)
        elif name == "convert_markdown":
            return await handle_convert(arguments)
        elif name == "check_pdf_support":
            return await handle_pdf_check()
        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ 错误: {e}\n{traceback.format_exc()}")]


async def handle_discover(args: dict) -> list[TextContent]:
    """处理文件发现请求。"""
    input_path = args["input_path"]
    md_files = discover_md_files(input_path)

    lines = [f"📁 发现 {len(md_files)} 个 Markdown 文件:\n"]
    for i, f in enumerate(md_files, 1):
        size_kb = f.stat().st_size / 1024
        lines.append(f"  {i}. {f.name} ({size_kb:.1f} KB)")
        lines.append(f"     📍 {f}")

    result = "\n".join(lines)

    # 如果是目录，添加交互提示
    if Path(input_path).is_dir() and len(md_files) > 1:
        result += "\n\n---\n"
        result += "💡 **交互提示：**\n"
        result += "检测到多个文件。请询问用户：\n"
        result += '  1. 是否全部统一输出为同一种格式？(Y/N)\n'
        result += "  2. 选择输出格式：HTML / PDF / Both\n"
        result += "然后将用户选择传递给 `convert_markdown` 工具。"

    return [TextContent(type="text", text=result)]


async def handle_pdf_check() -> list[TextContent]:
    """PDF 预检处理器。"""
    status = check_pdf_support()
    if status["ok"]:
        msg = "✅ PDF 生成能力正常，WeasyPrint + GTK3 系统库已就绪。"
    else:
        msg = f"❌ PDF 不可用: {status['reason']}\n\n仅 HTML 输出可用。"
    return [TextContent(type="text", text=msg)]


async def handle_convert(args: dict) -> list[TextContent]:
    """处理 Markdown 转换请求。"""
    input_path = args["input_path"]
    output_path = args["output_path"]
    output_format = args.get("output_format", "html")
    specified_files = args.get("files", [])
    preserve_structure = args.get("preserve_structure", True)
    batch_all_same = args.get("batch_all_same", True)

    input_base = Path(input_path).resolve()
    if input_base.is_file():
        input_base = input_base.parent

    # 发现文件
    if specified_files:
        md_files = [Path(f).resolve() for f in specified_files]
        for f in md_files:
            if not f.exists():
                return [TextContent(type="text", text=f"❌ 文件不存在: {f}")]
    else:
        md_files = discover_md_files(input_path)

    output_dir = Path(output_path).resolve()
    total = len(md_files)

    # 碰撞检测：检查同名 stem 冲突，提前警告
    collision_warning = ""
    if not preserve_structure:
        stems = [f.stem for f in md_files]
        dupes = {s for s in stems if stems.count(s) > 1}
        if dupes:
            collision_warning = ("\n⚠️  检测到同名文件冲突（不同目录中存在同名 Markdown），已使用目录名后缀避免覆盖。\n"
                                 "建议设置 preserve_structure=true 以保留目录结构。\n\n")

    # 进度报告头
    report_lines = [
        f"🚀 Markdown Stylist 转换报告",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"📥 输入: {input_path}",
        f"📤 输出: {output_dir}",
        f"📄 文件数: {total}",
        f"📋 格式: {output_format.upper()}",
        f"📁 保留目录结构: {'是' if preserve_structure else '否'}",
        f"",
    ]
    if collision_warning:
        report_lines.append(collision_warning)

    results = []
    success_count = 0

    for i, md_file in enumerate(md_files, 1):
        report_lines.append(f"[{i}/{total}] ⏳ {md_file.name} ...")
        try:
            result = process_single_file(md_file, output_dir, output_format,
                                         preserve_structure=preserve_structure,
                                         input_base=input_base)
            results.append(result)

            if result["status"] == "success":
                success_count += 1
                outs = result.get("outputs", {})
                html_out = outs.get("html", "")
                pdf_out = outs.get("pdf", "")
                if html_out:
                    report_lines.append(f"       ✅ HTML: {html_out}")
                if pdf_out:
                    report_lines.append(f"       ✅ PDF:  {pdf_out}")
                if "pdf_error" in outs:
                    report_lines.append(f"       ⚠️  PDF 失败: {outs['pdf_error']}")
            else:
                report_lines.append(f"       ⚠️  {result.get('reason', '未知错误')}")
        except Exception as e:
            results.append({"status": "error", "file": str(md_file), "error": str(e)})
            report_lines.append(f"       ❌ 错误: {e}")

    report_lines.append("")
    report_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    report_lines.append(f"✅ 成功: {success_count}/{total}")

    if success_count < total:
        report_lines.append(f"⚠️  失败: {total - success_count} 个文件")

    # 输出目录汇总
    report_lines.append(f"\n📂 所有输出文件位于: {output_dir}")
    if output_format in ("html", "both"):
        report_lines.append(f"   HTML: {output_dir}/*.html")
    if output_format in ("pdf", "both"):
        report_lines.append(f"   PDF:  {output_dir}/*.pdf")

    return [TextContent(type="text", text="\n".join(report_lines))]


# ╔══════════════════════════════════════════════════════════════╗
# ║                     ENTRY POINT                              ║
# ╚══════════════════════════════════════════════════════════════╝

def main():
    """启动 MCP stdio 服务端。"""
    import asyncio
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(read_stream, write_stream,
                                 mcp_server.create_initialization_options())
    asyncio.run(run())


if __name__ == "__main__":
    main()
