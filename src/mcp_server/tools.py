"""MCP 工具实现：与 FastMCP 装饰解耦的纯函数层，可直接单测。

三个工具复用 workflow 节点本身（rule_scan / regulation_match / llm_scan /
conflict_resolve 均为接收 state dict 的纯函数），保证 MCP 通道与 API 通道
行为一致——同一份规则引擎、同一套 RRF 混合检索，不另起炉灶。
"""

from src.core.agents.nodes.conflict_resolve import conflict_resolve
from src.core.agents.nodes.llm_scan import llm_scan
from src.core.agents.nodes.regulation_match import regulation_match
from src.core.agents.nodes.rule_scan import rule_scan
from src.core.llm.client import get_llm
from src.utils.logger import get_logger

logger = get_logger(__name__)

_CONTENT_SNIPPET = 200


def _block(text: str) -> list[dict]:
    """整段文本压成单块（MCP 场景输入通常是短文本，无需再切分）。"""
    return [{"text": text, "page": 1, "paragraph": 1, "heading": False}]


def scan_text(text: str, domain: str | None = None) -> dict:
    """规则引擎扫描：对文本执行全部 active 规则（正则/关键词 DSL），返回字面命中。

    确定性结果，毫秒级，适合作为 LLM 客户端的第一道快速筛查。
    """
    state = {"text": text, "blocks": _block(text), "domain": domain}
    hits = rule_scan(state).get("rule_hits", [])
    return {
        "total_hits": len(hits),
        "hits": [
            {
                "rule_name": h.get("rule_name"),
                "severity": h.get("severity"),
                "matched_text": h.get("matched_text"),
                "confidence": h.get("confidence"),
                "related_regulations": h.get("related_regulations", []),
                "description": h.get("description"),
            }
            for h in hits
        ],
    }


def search_regulations(query: str, domain: str | None = None, top_k: int = 5) -> dict:
    """法规条款混合检索：向量语义 + 关键词 RRF 融合，生效法规优先。

    与审查 workflow 的 regulation_match 节点同一条代码路径，
    检索失败自动降级纯关键词检索。
    """
    state = {"text": query, "domain": domain}
    cfg_top_k = 5
    if top_k and top_k > 0:
        cfg_top_k = min(int(top_k), 20)
    articles = regulation_match(state).get("matched_articles", [])[:cfg_top_k]
    return {
        "total": len(articles),
        "articles": [
            {
                "regulation_name": a.get("regulation_name"),
                "article_no": a.get("article_no"),
                "content": (a.get("content") or "")[:_CONTENT_SNIPPET],
                "score": round(float(a.get("score") or 0.0), 4),
                "status": a.get("status"),
            }
            for a in articles
        ],
    }


def review_text(text: str, domain: str | None = None, use_llm: bool = True) -> dict:
    """双引擎完整审查：规则扫描 + 法规召回 + LLM 语义审查 + 结果融合。

    use_llm=False 时纯规则引擎；True 时叠加 LLM 语义审查（需配置
    DASHSCOPE_API_KEY，文本较长时耗时数十秒）。返回融合后的违规清单，
    source=rule/hybrid/llm 分别对应采信/交叉确认/建议关注。
    """
    state: dict = {"text": text, "blocks": _block(text), "domain": domain}

    state.update(regulation_match(state))
    state.update(rule_scan(state))

    llm_usage = None
    if use_llm and get_llm() is not None:
        state.update(llm_scan(state))
        llm_usage = state.get("llm_usage")
    else:
        state["llm_findings"] = []

    state.update(conflict_resolve(state))
    findings = state.get("merged_findings", [])

    return {
        "total_findings": len(findings),
        "rule_engine_hits": len(state.get("rule_hits", [])),
        "llm_enabled": use_llm and get_llm() is not None,
        "llm_usage": llm_usage,
        "findings": [
            {
                "source": f.get("source"),
                "description": f.get("description"),
                "original_text": f.get("original_text"),
                "severity": f.get("severity"),
                "confidence": f.get("confidence"),
                "regulation": f.get("regulation"),
                "suggestion": f.get("suggestion"),
                "flag": f.get("flag"),
            }
            for f in findings
        ],
    }
