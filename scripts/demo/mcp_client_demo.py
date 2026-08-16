"""MCP 客户端演示：以标准 stdio 协议拉起本项目的 MCP server 并调用工具。

模拟任意 MCP 客户端（Claude Desktop / Claude Code / Cursor）接入后的调用路径：
initialize → list_tools → call_tool(scan_text / search_regulations / review_text)。

用法（仓库根目录）:
    python scripts/demo/mcp_client_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[2]

SAMPLE = (
    "本理财产品由我行全程担保，保本保收益，历史年化收益率12%以上，"
    "已连续五年全额兑付，适合所有投资者购买。"
)


def _print_result(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:1200])


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server.server"],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("server 提供工具:", [t.name for t in tools.tools])

            r1 = await session.call_tool("scan_text", {"text": SAMPLE})
            _print_result("scan_text（规则引擎）", json.loads(r1.content[0].text))

            r2 = await session.call_tool(
                "search_regulations", {"query": "理财产品 承诺保本", "top_k": 3}
            )
            _print_result("search_regulations（混合检索）", json.loads(r2.content[0].text))

            r3 = await session.call_tool(
                "review_text", {"text": SAMPLE, "use_llm": False}
            )
            _print_result("review_text（双引擎，LLM 关闭演示）", json.loads(r3.content[0].text))
    print("\nMCP stdio 全链路演示完成")


if __name__ == "__main__":
    asyncio.run(main())
