"""Agentic RAG（P3）：法规检索的充分性自评与按需补检。

regulation_match 的基础召回（混合检索 + 图谱第三路）是"文本相似"驱动的，
对换说法、跨主题的营销文档可能漏掉关键监管主题。本模块引入一个有界 agent 循环：
LLM 自评当前召回条款对文档的覆盖充分性 → 不充分时生成监管术语化补检查询 →
再检索并 RRF 融合 → 复评，直至充分、无新增条款或触及轮次上限。

成本护栏（设计上限：每次审查任务 2 次 LLM 评估 + 2 次补检查询）：
- 轮次上限 max_rounds（默认 2，即基础召回后至多 1 轮补检）
- 每轮补检查询数上限 _MAX_FOLLOW_UPS
- 补检结果与既有召回全为重复条款时立即收敛
- LLM 未配置 / 调用失败 / 输出无法解析 → 原样返回基础召回（优雅降级）
- 功能由 workflow.agentic_retrieval 显式开启（缺省关，与 rerank 同为先例：
  LLM 成本/延迟属可选增强，不在检索主路径强加）
"""

import json
import re

from sqlalchemy.orm import Session

from src.core.llm.client import merge_usage
from src.utils.logger import get_logger

logger = get_logger(__name__)

_ASSESS_SYSTEM = (
    "你是法规检索质量评估员。给定金融产品营销文档片段和当前召回的法规条款，"
    "判断这些条款是否足以支撑对该文档的全面合规审查。"
    "只有当前条款已覆盖文档涉及的主要监管主题（如收益承诺、风险揭示、投资者适当性、"
    "信息披露、宣传方式等）时才判定充分；不要因为条款数量多就判定充分。"
    "判定不充分时，给出 1-3 个补充检索查询：使用监管术语或法规主题词"
    "（如\"销售适当性管理\"\"风险提示义务\"），不要复述文档原句。"
    '只输出一个 JSON 对象：{"sufficient": true, "reason": "一句话理由", '
    '"follow_up_queries": ["查询1", "查询2"]}。'
)

_ASSESS_DOC_CHARS = 600      # 评估用文档片段截断
_ASSESS_ARTICLE_CHARS = 60   # 评估用条款内容截断
_ASSESS_ARTICLE_LIMIT = 8    # 评估提示词中的条款条数上限
_MAX_FOLLOW_UPS = 2
_QUERY_MAX_CHARS = 200       # 补检查询截断（术语化短语不需要长查询）
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


def parse_verdict(content: str) -> dict | None:
    """宽容解析 LLM 的充分性判定 JSON（剥代码围栏 / 提取首个 JSON 对象）。"""
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    follow = data.get("follow_up_queries")
    follow = (
        [str(q).strip() for q in follow if str(q).strip()] if isinstance(follow, list) else []
    )
    return {
        "sufficient": bool(data.get("sufficient")),
        "reason": str(data.get("reason") or ""),
        "follow_up_queries": follow[:_MAX_FOLLOW_UPS],
    }


def assess_sufficiency(
    llm, document: str, articles: list[dict]
) -> tuple[dict | None, dict | None]:
    """LLM 自评召回充分性。返回 (verdict, usage)；评估失败返回 (None, usage)。"""
    lines = [
        f"- 《{a.get('regulation_name', '')}》{a.get('article_no', '')}:"
        f" {(a.get('content') or '')[:_ASSESS_ARTICLE_CHARS]}"
        for a in articles[:_ASSESS_ARTICLE_LIMIT]
    ]
    user = (
        "当前召回的法规条款：\n" + ("\n".join(lines) if lines else "（无）")
        + f"\n\n营销文档片段：\n{document[:_ASSESS_DOC_CHARS]}"
    )
    messages = [
        {"role": "system", "content": _ASSESS_SYSTEM},
        {"role": "user", "content": user},
    ]
    usage = None
    for attempt in range(2):
        try:
            result = llm.complete(messages)
        except Exception:
            logger.exception("检索充分性评估 LLM 调用失败")
            return None, usage
        usage = merge_usage(usage, result.usage)
        verdict = parse_verdict(result.content)
        if verdict is not None:
            return verdict, usage
        if attempt == 0:  # 自纠错重试一次
            messages = messages + [
                {"role": "assistant", "content": result.content},
                {
                    "role": "user",
                    "content": "上面的输出不是合法 JSON。只输出一个 JSON 对象，不要任何其他内容。",
                },
            ]
    logger.warning("检索充分性评估两次输出均无法解析，放弃补检")
    return None, usage


def agentic_refine(
    db: Session,
    llm,
    text: str,
    domain: str | None,
    base_articles: list[dict],
    top_k: int,
    max_rounds: int = 2,
) -> tuple[list[dict], dict]:
    """对基础召回做有界补检循环。返回 (articles, meta)，任何失败不抛异常。

    meta: rounds（检索轮数）/ queries（补检查询）/ added（新增条款数）/
    sufficient（最终判定；None=评估失败）/ usage（LLM token 累计）。
    """
    from src.services import regulation_service  # 延迟导入，避免模块加载环

    meta: dict = {"rounds": 1, "queries": [], "added": 0, "sufficient": None, "usage": None}
    articles = list(base_articles)
    seen_ids = {a.get("article_id") for a in articles}

    for round_no in range(1, max(1, max_rounds)):
        verdict, usage = assess_sufficiency(llm, text, articles)
        meta["usage"] = merge_usage(meta["usage"], usage)
        if verdict is None:
            break
        meta["verdict_reason"] = verdict["reason"]
        meta["sufficient"] = verdict["sufficient"]
        if verdict["sufficient"] or not verdict["follow_up_queries"]:
            break

        # 按需补检：逐查询混合检索，与既有召回 RRF 融合
        domain_list = [domain] if domain else None
        new_lists: list[list[dict]] = []
        for query in verdict["follow_up_queries"][:_MAX_FOLLOW_UPS]:
            try:
                rows = regulation_service.search_hybrid(
                    db, query[:_QUERY_MAX_CHARS], domain_list, top_k
                )
            except Exception:
                logger.exception("补检查询失败: %s", query)
                continue
            meta["queries"].append(query)
            new_lists.append(rows)
        fresh = [
            a
            for lst in new_lists
            for a in lst
            if a.get("article_id") not in seen_ids
        ]
        if not fresh:
            break  # 补检无新增条款，提前收敛
        articles = regulation_service.fuse_route_lists([articles] + new_lists, top_k)
        seen_ids.update(a["article_id"] for a in fresh)
        meta["added"] += len(fresh)
        meta["rounds"] = round_no + 1
    return articles, meta
