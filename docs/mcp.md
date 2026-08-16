# MCP Server 接入指南

本项目把核心审查能力封装为标准 [MCP](https://modelcontextprotocol.io)（Model Context
Protocol）工具，任何 MCP 客户端（Claude Desktop / Claude Code / Cursor / 自研 Agent）
接入后即可直接调用，不需要走 HTTP API。

## 提供的工具

| 工具 | 能力 | 耗时 |
| --- | --- | --- |
| `scan_text` | 规则引擎字面扫描（regex/keyword DSL，确定性命中） | 毫秒级 |
| `search_regulations` | 法规条款混合检索（向量语义 + 关键词 RRF 融合，生效法规优先） | 毫秒级 |
| `review_text` | 双引擎完整审查（规则 + LLM 语义 + conflict_resolve 融合） | `use_llm=True` 时数十秒 |

工具实现（`src/mcp_server/tools.py`）直接复用 LangGraph workflow 的节点函数
（`rule_scan` / `regulation_match` / `llm_scan` / `conflict_resolve`），
保证 MCP 通道与 Web API 通道行为完全一致——同一份规则、同一套检索，不另起炉灶。

## 启动

```bash
# 仓库根目录（需 MySQL 等依赖服务已启动、.env 已配置）
python -m src.mcp_server.server
```

stdio 传输。注意：stdio 模式下 stdout 是 JSON-RPC 通道，server 启动时会把全部
业务日志重定向到 stderr（否则 SQLAlchemy echo 等日志会污染协议流），并强制把
进程 stdio reconfigure 为 UTF-8——MCP 客户端出于安全只给子进程传白名单环境
变量（不含 `PYTHONUTF8`），中文 Windows 上子进程 stdio 会退化为 GBK，中文
响应/日志会被客户端按 UTF-8 解码失败。自研客户端拉起时建议同样传
`env={"PYTHONUTF8": "1"}`（见下方示例）。

## 客户端接入

### Claude Desktop / Claude Code

配置文件加入（`command` 用绝对路径的 Python，`cwd` 为本仓库根目录）：

```json
{
  "mcpServers": {
    "fcr-compliance": {
      "command": "D:/AI/ACD/envs/llmXM/python.exe",
      "args": ["-m", "src.mcp_server.server"],
      "cwd": "D:/AI/llmXM/AI金融审查助手"
    }
  }
}
```

接入后可以直接对话，例如：

> 帮我审一下这段理财宣传文案是否合规：“本产品保本保收益，历史年化12%”

客户端会自动调用 `scan_text` / `review_text` 并结合 `search_regulations` 召回的
法条原文给出结论。

### 任意 Python 客户端（SDK 示例）

```python
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server.server"],
        cwd="<仓库根目录>",
        env={"PYTHONUTF8": "1"},  # 防中文 Windows 子进程 stdio 退化为 GBK
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "scan_text", {"text": "本产品保本保收益"}
            )
            print(result.content[0].text)

asyncio.run(main())
```

完整可运行示例见 `scripts/demo/mcp_client_demo.py`（覆盖 initialize →
list_tools → 三个工具的调用全链路）。

## 测试

```bash
python -m pytest tests/unit/test_mcp_tools.py tests/integration/test_mcp_stdio.py -v
```

- 单测：工具层参数透传、输出结构、LLM 打桩下的双引擎融合；
- 集成：真实拉起 server 子进程走完整 stdio JSON-RPC 协议。
