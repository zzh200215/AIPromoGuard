"""深查通道多工具箱（第 4 批：受限多工具 ReAct）。

标准通道只有 1 个工具（search_regulations，回合 2/调用 4）；深查通道把工具箱
扩到 4 个并把预算升格（回合 6/调用 8，workflow.deep_tool_*）：

- search_regulations：法规条款检索（复用 MCP 同一实现，行为一致）
- search_penalty_cases：真实处罚案例语义检索（本地向量，零 LLM）
- search_precedents：判定先例检索（第 2 批记忆库，零 LLM）
- get_document_context：**跨块取证**——在同一文档内按探针文本定位相关段落
  （确定性 2-gram 重叠，零 LLM）。深查的核心能力：发现 A 块收益承诺 →
  主动调取 B 块风险提示核对，披露完整性/勾稽类问题由此可查。

设计约束：
- 工具循环的护栏（回合/调用上限、异常回退）全部沿用 client.achat_json，
  本模块只提供工具 schema + 确定性执行器，不引入新的循环；
- 罚单/先例检索结果只作判定上下文，不进证据核验集（只有法规条款参与
  citation 核验——罚单/先例不是法规依据，语义上就不该当引用）。
"""

from __future__ import annotations

import json

from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_EXCERPT_PAD = 60  # 跨块取证的原文摘录半径（字符）


def _penalty_collection() -> str:
    prefix = settings.app_config("vectorstore").get("collection_prefix", "legal_")
    return prefix + "penalty_cases"


def search_penalty_cases(query: str, top_k: int = 3) -> dict:
    """真实处罚案例语义检索（本地向量，零 LLM；失败降级为空结果）。"""
    from src.infrastructure.embedding import get_embedder
    from src.infrastructure.vectorstore import get_vector_store

    top_k = max(1, min(int(top_k or 3), 5))
    try:
        embedding = get_embedder().embed([query])[0]
        hits = get_vector_store().query(_penalty_collection(), embedding, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 —— 工具失败降级为空（不中断审查）
        logger.warning("search_penalty_cases 失败，降级空结果: %s", exc)
        return {"cases": []}
    cases = []
    for h in hits:
        document = (h.get("document") or "").strip()
        name, _, summary = document.partition("。")
        cases.append(
            {
                "case_name": name[:80],
                "violation_summary": summary[:120],
                "domain": (h.get("metadata") or {}).get("domain") or None,
            }
        )
    return {"cases": cases}


def search_precedents(query: str, top_k: int = 3) -> dict:
    """同类材料的历史人工判定先例（第 2 批记忆库；零 LLM）。"""
    from src.services.precedent_memory import recall_precedents

    precedents = recall_precedents(query, domain=None, top_k=max(1, min(int(top_k or 3), 5)))
    return {
        "precedents": [
            {
                "verdict": (
                    "人工确认违规" if p["verdict"] == "confirmed"
                    else "人工判定合规（误报纠正）"
                ),
                "original_text": p.get("original_text") or "",
                "rule_name": p.get("rule_name"),
            }
            for p in precedents
        ]
    }


def get_document_context(blocks: list[dict], probe: str, max_blocks: int = 3) -> dict:
    """跨块取证：按探针文本在本文档内定位相关段落（确定性 2-gram 重叠）。

    供披露完整性核对（收益承诺 vs 风险提示是否同框）、跨段勾稽类判断取证。
    """
    probe = (probe or "").strip()
    if not probe:
        return {"blocks": []}
    grams = {probe[i : i + 2] for i in range(len(probe) - 1)}
    if not grams:
        grams = {probe}

    scored = []
    for b in blocks or []:
        text = b.get("text") or ""
        hits = [g for g in grams if g in text]
        if hits:
            scored.append((len(hits), b, text, hits))
    scored.sort(key=lambda x: -x[0])

    out = []
    limit = max(1, min(int(max_blocks or 3), 5))
    for _score, b, text, hits in scored[:limit]:
        anchor = text.find(hits[0])
        start = max(0, anchor - _EXCERPT_PAD)
        out.append(
            {
                "page": b.get("page"),
                "paragraph": b.get("paragraph"),
                "excerpt": text[start : anchor + _EXCERPT_PAD],
            }
        )
    return {"blocks": out}


def _schema(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


def deep_tool_config(blocks: list[dict]) -> tuple[list, object]:
    """深查通道工具箱：4 工具 schema + 确定性执行器（复用法规检索实现）。"""

    def execute(name: str, args: str) -> dict | str:
        kwargs = json.loads(args or "{}")
        if name == "search_regulations":
            from src.mcp_server import tools as mcp_tools

            return mcp_tools.search_regulations(**kwargs)
        if name == "search_penalty_cases":
            return search_penalty_cases(
                query=str(kwargs.get("query") or ""), top_k=int(kwargs.get("top_k") or 3)
            )
        if name == "search_precedents":
            return search_precedents(
                query=str(kwargs.get("query") or ""), top_k=int(kwargs.get("top_k") or 3)
            )
        if name == "get_document_context":
            return get_document_context(
                blocks, probe=str(kwargs.get("probe") or ""),
                max_blocks=int(kwargs.get("max_blocks") or 3),
            )
        return f"未知工具: {name}"

    from src.mcp_server import tools as mcp_tools

    schemas = [
        mcp_tools.search_regulations_schema(),
        _schema(
            "search_penalty_cases",
            "检索真实监管处罚案例（金监总局/证监会官方罚单）。当需要判断某类表述在"
            "监管实践中是否被实际处罚、评估风险严重程度时调用。",
            {
                "query": {"type": "string", "description": "违规情形描述或营销表述"},
                "top_k": {"type": "integer", "description": "返回案例数，默认 3"},
            },
            ["query"],
        ),
        _schema(
            "search_precedents",
            "检索本系统历史上的人工复核判定（确认违规/误报纠正先例）。当同类表述"
            "曾被人工判定过时调用，用于校准判定尺度。",
            {
                "query": {"type": "string", "description": "营销表述或违规描述"},
                "top_k": {"type": "integer", "description": "返回先例数，默认 3"},
            },
            ["query"],
        ),
        _schema(
            "get_document_context",
            "在当前待审文档的其他段落中定位与探针文本相关的内容（跨块取证）。"
            "用于核对披露完整性（如某处承诺收益后，风险提示是否在文档其他位置披露）、"
            "跨段数字勾稽等需要全文视角的判断。",
            {
                "probe": {"type": "string", "description": "要定位的相关内容关键词或表述"},
                "max_blocks": {"type": "integer", "description": "返回段落数，默认 3"},
            },
            ["probe"],
        ),
    ]
    return schemas, execute


def deep_tool_budget() -> dict:
    """深查通道的工具预算（覆盖 client 默认的回合/调用上限）。"""
    cfg = settings.app_config("workflow") or {}
    return {
        "max_tool_rounds": int(cfg.get("deep_tool_rounds", 6)),
        "max_tool_calls_total": int(cfg.get("deep_tool_calls", 8)),
    }
