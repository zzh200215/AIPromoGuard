"""金融合规审查 MCP Server（stdio 传输）。

启动:
    python -m src.mcp_server.server          # 仓库根目录执行

MCP 客户端接入（以 Claude Desktop 为例，见 docs/mcp.md）:
    {"mcpServers": {"fcr-compliance": {
        "command": "python", "args": ["-m", "src.mcp_server.server"],
        "cwd": "<仓库根目录>"}}}

暴露三个工具（实现见 src/mcp_server/tools.py）:
    - scan_text          规则引擎字面扫描（确定性、毫秒级）
    - search_regulations 法规条款混合检索（RRF 融合）
    - review_text        双引擎完整审查（规则 + LLM 语义 + 融合）
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP

from src.mcp_server import tools

mcp = FastMCP("fcr-compliance-review")


def _redirect_logs_to_stderr() -> None:
    """stdio 模式下 stdout 是 JSON-RPC 通道，业务日志必须全部改走 stderr。

    项目 setup_logging 的 root handler 绑定 sys.stdout，SQLAlchemy echo
    等所有 stdlib 日志都会经由它输出——不重定向会污染协议消息。
    """
    for handler in logging.getLogger().handlers:
        if getattr(handler, "stream", None) is sys.stdout:
            handler.stream = sys.stderr


@mcp.tool()
def scan_text(text: str, domain: str | None = None) -> dict:
    """规则引擎扫描金融产品文本，返回字面规则命中清单（确定性、毫秒级）。

    Args:
        text: 待审查的金融产品文本（宣传材料/合同条款/产品说明书等）。
        domain: 可选领域过滤（banking/fund/insurance），为空则全领域规则。
    """
    return tools.scan_text(text, domain)


@mcp.tool()
def search_regulations(query: str, domain: str | None = None, top_k: int = 5) -> dict:
    """混合检索法规条款：向量语义 + 关键词 RRF 融合，生效法规优先。

    Args:
        query: 检索问题或条款描述（如"理财产品能否承诺保本"）。
        domain: 可选领域过滤（banking/fund/insurance）。
        top_k: 返回条款数，默认 5，最大 20。
    """
    return tools.search_regulations(query, domain, top_k)


@mcp.tool()
def review_text(text: str, domain: str | None = None, use_llm: bool = True) -> dict:
    """双引擎完整审查：规则扫描 + 法规召回 + LLM 语义审查 + 结果融合。

    Args:
        text: 待审查的金融产品文本。
        domain: 可选领域过滤（banking/fund/insurance）。
        use_llm: 是否叠加 LLM 语义审查（默认 True；需服务端配置
            DASHSCOPE_API_KEY，长文本耗时数十秒，快速筛查可传 False）。
    """
    return tools.review_text(text, domain, use_llm)


if __name__ == "__main__":
    _redirect_logs_to_stderr()
    mcp.run()
