import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    params = StdioServerParameters(
        command="python",
        args=[str(ROOT / "markdown_stylist_mcp.py"), "--mcp"],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"discover_md_files", "convert_markdown", "check_pdf_support"} <= names
            pdf_status = await session.call_tool("check_pdf_support", {})
            assert pdf_status.content
            result = await session.call_tool(
                "convert_markdown",
                {
                    "input_path": str(ROOT / "tests" / "fixtures" / "no_toc_basic.md"),
                    "output_path": str(ROOT / "output" / "mcp_validation"),
                    "output_format": "html",
                    "preserve_structure": True,
                },
            )
            text = result.content[0].text
            assert "Success: 1/1" in text, text


asyncio.run(main())
print("mcp-stdio-validation=pass")
