#!/usr/bin/env python3
"""
Markdown Stylist MCP
====================

Convert Markdown files into polished, self-contained HTML reports and optional
PDF files. The module supports both an interactive CLI and MCP stdio mode.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import markdown
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


PROJECT_ROOT = Path(__file__).parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"

MD_EXTENSIONS = [
    "markdown.extensions.toc",
    "markdown.extensions.fenced_code",
    "markdown.extensions.tables",
    "markdown.extensions.codehilite",
    "markdown.extensions.nl2br",
    "markdown.extensions.sane_lists",
    "markdown.extensions.attr_list",
]

MD_EXTENSION_CONFIGS = {
    "markdown.extensions.toc": {
        "permalink": False,
        "toc_depth": "1-6",
    },
    "markdown.extensions.codehilite": {
        "guess_lang": False,
        "use_pygments": False,
    },
}

EXCLUDE_DIR_NAMES = {
    ".venv",
    ".git",
    "__pycache__",
    "node_modules",
    ".idea",
    ".vscode",
    "venv",
    "env",
    ".tox",
    ".eggs",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
}


@dataclass
class TocItem:
    id: str
    text: str
    level: int
    children: list["TocItem"]


def discover_md_files(input_path: str) -> list[Path]:
    """Discover Markdown files from a single file or a directory tree."""
    path = Path(input_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {input_path}")

    if path.is_file():
        if path.suffix.lower() == ".md":
            return [path]
        raise ValueError(f"File is not Markdown: {path.name}")

    md_files: list[Path] = []
    for file_path in path.rglob("*.md"):
        if EXCLUDE_DIR_NAMES & set(file_path.parts):
            continue
        md_files.append(file_path)

    if not md_files:
        raise FileNotFoundError(f"No .md files found under: {path}")
    return sorted(md_files)


def read_markdown_text(md_path: Path) -> str:
    """Read Markdown with common UTF encodings and Chinese Windows fallback."""
    raw = md_path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_title(md_text: str, file_path: Path) -> str:
    """Extract the first H1 from Markdown, falling back to the file stem."""
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return file_path.stem.replace("_", " ")


def extract_meta_items(md_text: str) -> list[dict[str, str]]:
    """Extract simple key/value metadata from leading blockquote lines."""
    items: list[dict[str, str]] = []
    in_blockquote = False
    for line in md_text.splitlines()[:30]:
        stripped = line.strip()
        if stripped.startswith("> "):
            in_blockquote = True
            content = stripped[2:].strip()
            sep = ":" if ":" in content else "：" if "：" in content else ""
            if sep:
                label, value = content.split(sep, 1)
                items.append({"label": label.strip(), "value": value.strip()})
        elif in_blockquote and stripped == ">":
            continue
        elif in_blockquote:
            break
    return items


def _protect_fenced_code(md_text: str) -> tuple[str, dict[str, str]]:
    blocks: dict[str, str] = {}
    pattern = re.compile(r"(?ms)^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)[ \t]*$")

    def replace(match: re.Match[str]) -> str:
        token = f"@@CODE_BLOCK_{len(blocks)}@@"
        blocks[token] = match.group(0)
        return token

    return pattern.sub(replace, md_text), blocks


def _restore_tokens(text: str, tokens: dict[str, str]) -> str:
    for token, value in tokens.items():
        text = text.replace(token, value)
    return text


def _render_math(latex: str, display: bool) -> str:
    latex = latex.strip()
    try:
        from latex2mathml.converter import convert

        mathml = convert(latex, display="block" if display else "inline")
        wrapper = "div" if display else "span"
        css_class = "math-display" if display else "math-inline"
        return f'<{wrapper} class="{css_class}">{mathml}</{wrapper}>'
    except Exception:
        escaped = html.escape(latex)
        if display:
            return f'<div class="math-display math-fallback"><code>{escaped}</code></div>'
        return f'<span class="math-inline math-fallback"><code>{escaped}</code></span>'


def _extract_math(md_text: str) -> tuple[str, dict[str, str]]:
    """Replace inline and block LaTeX with HTML placeholders before Markdown."""
    text, code_blocks = _protect_fenced_code(md_text)
    math_tokens: dict[str, str] = {}
    result: list[str] = []
    i = 0

    while i < len(text):
        if text.startswith("$$", i):
            end = text.find("$$", i + 2)
            if end != -1:
                latex = text[i + 2 : end]
                token = f"%%MATHBLOCK{len(math_tokens)}%%"
                math_tokens[token] = _render_math(latex, display=True)
                result.append(token)
                i = end + 2
                continue

        if text[i] == "$" and (i == 0 or text[i - 1] != "\\"):
            if i + 1 < len(text) and text[i + 1].isspace():
                result.append(text[i])
                i += 1
                continue
            end = i + 1
            while end < len(text):
                if text[end] == "$" and text[end - 1] != "\\":
                    break
                if text[end] == "\n":
                    end = -1
                    break
                end += 1
            if end != -1 and end < len(text):
                latex = text[i + 1 : end]
                if latex.strip():
                    token = f"%%MATHINLINE{len(math_tokens)}%%"
                    math_tokens[token] = _render_math(latex, display=False)
                    result.append(token)
                    i = end + 1
                    continue

        result.append(text[i])
        i += 1

    restored = _restore_tokens("".join(result), code_blocks)
    return restored, math_tokens


def _restore_math(html_text: str, math_tokens: dict[str, str]) -> str:
    for token, rendered in math_tokens.items():
        html_text = html_text.replace(token, rendered)
    return html_text


def _slugify(text: str, used_ids: set[str]) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "", text, flags=re.UNICODE).strip()
    base = re.sub(r"\s+", "-", base).strip("-").lower()
    if not base:
        base = "section"
    candidate = base
    counter = 2
    while candidate in used_ids:
        candidate = f"{base}-{counter}"
        counter += 1
    used_ids.add(candidate)
    return candidate


def parse_markdown(md_text: str) -> dict[str, Any]:
    """Parse Markdown to body HTML. Original [TOC] or manual TOCs stay in-place."""
    protected_md, math_tokens = _extract_math(md_text)
    md_instance = markdown.Markdown(
        extensions=MD_EXTENSIONS,
        extension_configs=MD_EXTENSION_CONFIGS,
        output_format="html5",
    )
    body_html = md_instance.convert(protected_md)
    body_html = _restore_math(body_html, math_tokens)
    return {"content_html": body_html}


def post_process_html(
    html_text: str,
    asset_base: Path | None = None,
    document_title: str = "",
) -> dict[str, Any]:
    """Enhance parsed HTML, assign heading ids, and build independent sidebar TOC."""
    soup = BeautifulSoup(html_text, "lxml")
    body = soup.body or soup

    used_ids: set[str] = set()
    headings = []
    title_heading = None
    title_heading_id = ""
    normalized_title = re.sub(r"\s+", " ", document_title).strip()
    for heading in body.find_all(re.compile(r"^h[1-6]$")):
        text = heading.get_text(" ", strip=True).replace("\u00b6", "").strip()
        if not text:
            continue
        level = int(heading.name[1])
        heading_id = heading.get("id") or _slugify(text, used_ids)
        if heading_id in used_ids:
            heading_id = _slugify(text, used_ids)
        else:
            used_ids.add(heading_id)
        heading["id"] = heading_id
        heading["class"] = list(set(heading.get("class", []) + ["section-heading"]))
        headings.append({"id": heading_id, "text": text, "level": level})
        if (
            title_heading is None
            and level == 1
            and normalized_title
            and re.sub(r"\s+", " ", text).strip() == normalized_title
        ):
            title_heading = heading
            title_heading_id = heading_id

    for pre in body.find_all("pre"):
        if pre.find_parent("div", class_="code-block-wrapper"):
            continue
        wrapper = soup.new_tag("div", attrs={"class": "code-block-wrapper"})
        header = soup.new_tag("div", attrs={"class": "code-block-header"})
        for color in ("red", "yellow", "green"):
            header.append(soup.new_tag("span", attrs={"class": f"mac-dot {color}"}))
        label = soup.new_tag("span", attrs={"class": "file-label"})
        code = pre.find("code")
        lang = ""
        if code:
            classes = code.get("class", [])
            lang = next((c.replace("language-", "") for c in classes if c.startswith("language-")), "")
        label.string = lang or "code"
        header.append(label)
        pre.wrap(wrapper)
        wrapper.insert(0, header)

    for table in body.find_all("table"):
        classes = table.get("class", [])
        if "data-table" not in classes:
            classes.append("data-table")
        table["class"] = classes
        if not table.find_parent("div", class_="table-wrapper"):
            wrapper = soup.new_tag("div", attrs={"class": "table-wrapper"})
            table.wrap(wrapper)

    for img in body.find_all("img"):
        src = img.get("src", "")
        if asset_base and src and not re.match(r"^(?:[a-z][a-z0-9+.-]*:|#)", src, re.I):
            img["src"] = (asset_base / src).resolve().as_uri()
        if img.find_parent("figure"):
            continue
        parent = img.parent
        if parent and parent.name == "p" and len(parent.find_all(recursive=False)) == 1:
            parent["class"] = list(set(parent.get("class", []) + ["image-block"]))
        next_sib = img.find_next_sibling()
        if next_sib and next_sib.name == "em":
            figure = soup.new_tag("figure")
            img.wrap(figure)
            caption = soup.new_tag("figcaption")
            caption.extend(list(next_sib.children))
            figure.append(caption)
            next_sib.decompose()

    for para in list(body.find_all("p")):
        children = [child for child in para.contents if str(child).strip()]
        if len(children) == 1:
            child = children[0]
            if getattr(child, "name", None) == "div" and "math-display" in child.get("class", []):
                para.replace_with(child)

    if title_heading is not None:
        title_heading.decompose()

    processed = "".join(str(child) for child in body.children)
    return {
        "content_html": processed,
        "sidebar_toc": _build_toc_tree(headings),
        "document_title_id": title_heading_id,
    }


def _build_toc_tree(headings: list[dict[str, Any]]) -> list[TocItem]:
    root: list[TocItem] = []
    stack: list[tuple[int, TocItem]] = []

    for item in headings:
        node = TocItem(
            id=item["id"],
            text=item["text"],
            level=item["level"],
            children=[],
        )
        while stack and stack[-1][0] >= node.level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            root.append(node)
        stack.append((node.level, node))
    return root


def get_jinja_env() -> Environment:
    if not TEMPLATES_DIR.exists():
        raise FileNotFoundError(f"Template directory does not exist: {TEMPLATES_DIR}")
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
    )


def render_html(
    title: str,
    content_html: str,
    sidebar_toc: list[TocItem],
    meta_items: list[dict[str, str]],
    document_title_id: str = "",
) -> str:
    env = get_jinja_env()
    template = env.get_template("base.html")
    return template.render(
        title=title,
        content=content_html,
        sidebar_toc=sidebar_toc,
        meta_items=meta_items,
        document_title_id=document_title_id,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def _pdf_via_playwright(html_content: str, output_pdf_path: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path=p.chromium.executable_path)
            page = browser.new_page(viewport={"width": 1280, "height": 1600})
            page.set_content(html_content, wait_until="networkidle")
            page.emulate_media(media="print")
            page.pdf(
                path=str(output_pdf_path),
                print_background=True,
                format="A4",
                margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"},
            )
            browser.close()
        return True
    except Exception:
        return False


def _pdf_via_weasyprint(html_content: str, output_pdf_path: Path) -> bool:
    try:
        from weasyprint import HTML

        HTML(string=html_content).write_pdf(str(output_pdf_path))
        return True
    except Exception:
        return False


def check_pdf_support() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path=p.chromium.executable_path)
            page = browser.new_page()
            page.set_content("<p>test</p>")
            page.pdf()
            browser.close()
        return {"ok": True, "engine": "Playwright (Chromium)"}
    except Exception:
        pass

    try:
        from weasyprint import HTML

        HTML(string="<p>test</p>").write_pdf()
        return {"ok": True, "engine": "WeasyPrint"}
    except ImportError:
        return {
            "ok": False,
            "engine": None,
            "reason": (
                "PDF engine is not installed. Recommended: "
                "pip install playwright && python -m playwright install chromium"
            ),
        }
    except Exception as exc:
        return {"ok": False, "engine": None, "reason": f"PDF engine check failed: {exc}"}


def convert_to_pdf(html_content: str, output_pdf_path: Path) -> str:
    if _pdf_via_playwright(html_content, output_pdf_path):
        return str(output_pdf_path)
    if _pdf_via_weasyprint(html_content, output_pdf_path):
        return str(output_pdf_path)
    raise RuntimeError(
        "PDF generation failed: no available engine. "
        "Install Playwright with: pip install playwright && python -m playwright install chromium"
    )


def process_single_file(
    md_path: Path,
    output_dir: Path,
    output_format: str,
    preserve_structure: bool = False,
    input_base: Path | None = None,
) -> dict[str, Any]:
    md_text = read_markdown_text(md_path)
    if not md_text.strip():
        return {"status": "skipped", "file": str(md_path), "reason": "file is empty"}

    title = extract_title(md_text, md_path)
    meta_items = extract_meta_items(md_text)
    parsed = parse_markdown(md_text)
    processed = post_process_html(
        parsed["content_html"],
        asset_base=md_path.parent,
        document_title=title,
    )
    content_html = processed["content_html"]
    sidebar_toc = processed["sidebar_toc"]
    document_title_id = processed.get("document_title_id", "")

    if not meta_items:
        meta_items = [
            {"label": "File", "value": md_path.name},
            {"label": "Path", "value": str(md_path.parent)},
        ]
    meta_items.append({"label": "Generated", "value": datetime.now().strftime("%Y-%m-%d %H:%M")})

    full_html = render_html(title, content_html, sidebar_toc, meta_items, document_title_id)

    if preserve_structure and input_base is not None:
        try:
            rel_path = md_path.parent.relative_to(input_base)
        except ValueError:
            rel_path = Path()
        output_subdir = output_dir / rel_path
    else:
        output_subdir = output_dir
    output_subdir.mkdir(parents=True, exist_ok=True)

    stem = md_path.stem
    result: dict[str, Any] = {"file": str(md_path), "title": title, "outputs": {}}

    html_path = output_subdir / f"{stem}.html"
    if html_path.exists():
        parent_tag = md_path.parent.name
        html_path = output_subdir / f"{stem}__{parent_tag}.html"
    if html_path.exists():
        path_hash = hashlib.md5(str(md_path).encode("utf-8")).hexdigest()[:6]
        html_path = output_subdir / f"{stem}__{path_hash}.html"
    html_path.write_text(full_html, encoding="utf-8")
    result["outputs"]["html"] = str(html_path)

    if output_format in ("pdf", "both"):
        pdf_path = output_subdir / f"{stem}.pdf"
        if pdf_path.exists():
            parent_tag = md_path.parent.name
            pdf_path = output_subdir / f"{stem}__{parent_tag}.pdf"
        try:
            convert_to_pdf(full_html, pdf_path)
            result["outputs"]["pdf"] = str(pdf_path)
        except Exception as exc:
            result["outputs"]["pdf_error"] = str(exc)

    result["status"] = "success"
    return result


mcp_server = Server("markdown-stylist")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="discover_md_files",
            description="Scan a path and return discovered Markdown files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_path": {
                        "type": "string",
                        "description": "Directory path or a single Markdown file path.",
                    }
                },
                "required": ["input_path"],
            },
        ),
        Tool(
            name="convert_markdown",
            description=(
                "Convert Markdown files to polished HTML/PDF reports. "
                "Supports html, pdf, and both. Existing Markdown TOCs stay in the body; "
                "an independent interactive sidebar TOC is generated for HTML."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "input_path": {
                        "type": "string",
                        "description": "Markdown file path or a directory containing Markdown files.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output directory path.",
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["html", "pdf", "both"],
                        "description": "Output format: html, pdf, or both.",
                        "default": "html",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit Markdown file list.",
                    },
                    "preserve_structure": {
                        "type": "boolean",
                        "description": "Preserve source directory structure in the output directory.",
                        "default": True,
                    },
                    "batch_all_same": {
                        "type": "boolean",
                        "description": "Reserved compatibility flag for batch conversions.",
                        "default": True,
                    },
                },
                "required": ["input_path", "output_path"],
            },
        ),
        Tool(
            name="check_pdf_support",
            description="Check whether a PDF engine is available.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "discover_md_files":
            return await handle_discover(arguments)
        if name == "convert_markdown":
            return await handle_convert(arguments)
        if name == "check_pdf_support":
            return await handle_pdf_check()
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as exc:
        return [TextContent(type="text", text=f"Error: {exc}\n{traceback.format_exc()}")]


async def handle_discover(args: dict[str, Any]) -> list[TextContent]:
    md_files = discover_md_files(args["input_path"])
    lines = [f"Discovered {len(md_files)} Markdown file(s):"]
    for i, file_path in enumerate(md_files, 1):
        size_kb = file_path.stat().st_size / 1024
        lines.append(f"  {i}. {file_path.name} ({size_kb:.1f} KB)")
        lines.append(f"     {file_path}")
    return [TextContent(type="text", text="\n".join(lines))]


async def handle_pdf_check() -> list[TextContent]:
    status = check_pdf_support()
    if status["ok"]:
        msg = f"PDF generation is available: {status['engine']}"
    else:
        msg = f"PDF generation is not available: {status['reason']}"
    return [TextContent(type="text", text=msg)]


async def handle_convert(args: dict[str, Any]) -> list[TextContent]:
    input_path = args["input_path"]
    output_path = args["output_path"]
    output_format = args.get("output_format", "html")
    specified_files = args.get("files", [])
    preserve_structure = args.get("preserve_structure", True)

    input_base = Path(input_path).resolve()
    if input_base.is_file():
        input_base = input_base.parent

    if specified_files:
        md_files = [Path(file_path).resolve() for file_path in specified_files]
        missing = [str(file_path) for file_path in md_files if not file_path.exists()]
        if missing:
            return [TextContent(type="text", text=f"Missing file(s): {', '.join(missing)}")]
    else:
        md_files = discover_md_files(input_path)

    output_dir = Path(output_path).resolve()
    report_lines = [
        "Markdown Stylist conversion report",
        f"Input: {input_path}",
        f"Output: {output_dir}",
        f"Files: {len(md_files)}",
        f"Format: {output_format.upper()}",
        f"Preserve structure: {preserve_structure}",
        "",
    ]

    success_count = 0
    for i, md_file in enumerate(md_files, 1):
        report_lines.append(f"[{i}/{len(md_files)}] {md_file.name}")
        try:
            result = process_single_file(
                md_file,
                output_dir,
                output_format,
                preserve_structure=preserve_structure,
                input_base=input_base,
            )
            if result["status"] == "success":
                success_count += 1
                outputs = result.get("outputs", {})
                if outputs.get("html"):
                    report_lines.append(f"  HTML: {outputs['html']}")
                if outputs.get("pdf"):
                    report_lines.append(f"  PDF: {outputs['pdf']}")
                if outputs.get("pdf_error"):
                    report_lines.append(f"  PDF error: {outputs['pdf_error']}")
            else:
                report_lines.append(f"  Skipped: {result.get('reason', 'unknown reason')}")
        except Exception as exc:
            report_lines.append(f"  Error: {exc}")

    report_lines.append("")
    report_lines.append(f"Success: {success_count}/{len(md_files)}")
    return [TextContent(type="text", text="\n".join(report_lines))]


def cli_main() -> None:
    print("=" * 52)
    print("  Markdown Stylist - MD -> HTML/PDF")
    print("=" * 52)
    print()

    while True:
        input_path = input("[INPUT] Markdown file or directory: ").strip().strip('"')
        if not input_path:
            print("[WARN] Input path cannot be empty.\n")
            continue
        source = Path(input_path).resolve()
        if not source.exists():
            print(f"[ERROR] Path does not exist: {source}\n")
            continue
        break

    if source.is_file():
        md_files = [source]
        print(f"   [FILE] {source.name}")
    else:
        md_files = discover_md_files(str(source))
        print(f"   [DIR] Found {len(md_files)} Markdown file(s):")
        for i, file_path in enumerate(md_files, 1):
            size_kb = file_path.stat().st_size / 1024
            print(f"      {i}. {file_path.name} ({size_kb:.1f} KB)")
        print()

    while True:
        output_path = input("[OUTPUT] Output directory: ").strip().strip('"')
        if not output_path:
            print("[WARN] Output path cannot be empty.\n")
            continue
        output_dir = Path(output_path).resolve()
        break

    print()
    print("[FORMAT] Select output format:")
    print("   1. HTML")
    print("   2. PDF")
    while True:
        choice = input("   Enter 1 or 2: ").strip()
        if choice == "1":
            output_format = "html"
            break
        if choice == "2":
            output_format = "pdf"
            break
        print("[WARN] Invalid selection.")

    print()
    print("-" * 52)
    print(f"[START] Format: {output_format.upper()} | Files: {len(md_files)}")
    print("-" * 52)

    input_base = source.parent if source.is_file() else source
    output_dir.mkdir(parents=True, exist_ok=True)
    success = 0
    for i, md_file in enumerate(md_files, 1):
        print(f"[{i}/{len(md_files)}] {md_file.name} ...", end=" ", flush=True)
        try:
            result = process_single_file(
                md_file,
                output_dir,
                output_format,
                preserve_structure=True,
                input_base=input_base,
            )
            if result["status"] == "success":
                outputs = result.get("outputs", {})
                out_path = outputs.get(output_format) or outputs.get("html")
                print(f"OK -> {Path(out_path).name if out_path else 'done'}")
                success += 1
            else:
                print(f"SKIP: {result.get('reason', 'unknown')}")
        except Exception as exc:
            print(f"ERROR: {exc}")

    print()
    print(f"[DONE] Success {success}/{len(md_files)} -> {output_dir}")


def main() -> None:
    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    asyncio.run(run())


if __name__ == "__main__":
    if "--mcp" in sys.argv:
        main()
    else:
        cli_main()
