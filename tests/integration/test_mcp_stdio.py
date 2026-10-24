"""MCP stdio 集成测试：真实拉起 server 子进程走完整 JSON-RPC 协议。

覆盖生产接入路径（Claude Desktop / 任意 MCP 客户端即此方式）：
    initialize → list_tools → call_tool
以及 stdio 通道卫生：业务日志必须走 stderr，不得污染 stdout 协议流
（此前 SQLAlchemy echo 日志打到 stdout 导致 JSONRPC 解析失败，已修）。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from src.infrastructure.database.mysql import SessionLocal
from src.models import Rule

REPO_ROOT = Path(__file__).resolve().parents[2]

VIOLATION_TEXT = "本理财产品由我行全程担保，保本保收益，历史年化收益率12%以上。"


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.query(Rule).count()
        db.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_stdio_full_roundtrip():
    async def _run() -> dict:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_server.server"],
            cwd=str(REPO_ROOT),
            # MCP 客户端默认只继承白名单环境变量：不含 PYTHONUTF8（中文 Windows
            # 子进程 stdio 退化为 GBK）也不含 MYSQL_*（Linux 上 server 子进程
            # 连不上测试库，工具异常文本破坏 JSON 协议）——两者都显式补上
            env={
                "PYTHONUTF8": "1",
                **{
                    k: os.environ[k]
                    for k in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER",
                              "MYSQL_PASSWORD", "MYSQL_DATABASE")
                    if k in os.environ
                },
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = [t.name for t in tools.tools]

                r1 = await session.call_tool("scan_text", {"text": VIOLATION_TEXT})
                r2 = await session.call_tool(
                    "search_regulations", {"query": "理财产品 承诺保本", "top_k": 2}
                )
                return {
                    "tools": tool_names,
                    "scan": json.loads(r1.content[0].text),
                    "search": json.loads(r2.content[0].text),
                }

    result = asyncio.run(_run())
    assert result["tools"] == ["scan_text", "search_regulations", "review_text"]
    assert result["scan"]["total_hits"] >= 1
    assert any("保本" in h["rule_name"] for h in result["scan"]["hits"])
    assert 1 <= result["search"]["total"] <= 2
    assert result["search"]["articles"][0]["regulation_name"]
