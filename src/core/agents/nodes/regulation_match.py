"""RegulationMatcher：从知识库召回相关法规条款。

走混合检索（语义 + 关键词融合，生效法规优先）；混合检索失败回退纯关键词。
P2 GraphRAG：图谱"违规模式→条款"多跳召回作为第三路并入 RRF——挖掘规则的
条款级 VIOLATES 关联让语义/关键词都召不回的条款也能进入 LLM 审查上下文。
P3 Agentic RAG（可选，workflow.agentic_retrieval）：LLM 自评召回充分性，
不充分时生成监管术语化补检查询再检索融合；LLM 未配置/失败保持基础召回。
三路定稿后统一补齐法规文号与发布/生效日期（可验证证据链，enrich_regulation_meta）。
"""

from src.core.agents.state import ReviewState
from src.core.llm.client import get_llm
from src.infrastructure.database.mysql import SessionLocal
from src.services import agentic_retrieval, graph_service, regulation_service
from src.services.llm_cache import CachedLLM
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_QUERY_MAX_CHARS = 800  # 查询向量化前截断，避免超长文档稀释语义


def regulation_match(state: ReviewState) -> dict:
    cfg = settings.app_config("workflow")
    top_k = cfg.get("regulation_top_k", 5)
    text = state.get("text", "")
    domain = state.get("domain")
    domain_list = [domain] if domain else None

    db = SessionLocal()
    try:
        try:
            articles = regulation_service.search_hybrid(
                db, text[:_QUERY_MAX_CHARS], domain_list, top_k
            )
            logger.info("混合检索召回 %s 条法规条款", len(articles))
        except Exception:
            logger.exception("混合检索失败，回退关键词检索")
            articles = regulation_service.search_keyword(db, text, domain_list, top_k)

        # 确定性第四路：营销话术→监管术语同义扩展（零 LLM；诊断见
        # regulation_service.MARKETING_SYNONYMS 注释）。逐术语精确短语检索后
        # RRF 融合——桥接"稳赚/翻倍"类营销口语与"承诺收益"类监管书面语的词面鸿沟。
        synonym_terms: list[str] = []
        if cfg.get("synonym_expansion", True):
            synonym_terms = regulation_service.regulatory_synonym_terms(text)
            if synonym_terms:
                try:
                    term_lists = [
                        regulation_service.search_keyword(db, t, domain_list, top_k)
                        for t in synonym_terms
                    ]
                    term_lists = [lst for lst in term_lists if lst]
                    if term_lists:
                        syn_articles = (
                            regulation_service.fuse_route_lists(term_lists, top_k)
                            if len(term_lists) > 1
                            else term_lists[0]
                        )
                        articles = regulation_service.fuse_route_lists(
                            [articles, syn_articles], top_k
                        )
                        logger.info(
                            "同义扩展路召回 %s 条款（触发术语：%s）",
                            len(syn_articles), synonym_terms,
                        )
                except Exception:
                    logger.exception("同义扩展检索失败，跳过该路")
                    synonym_terms = []

        # P3 Agentic RAG（可选）：充分性自评 + 按需补检；未配置 key / 失败时保持基础召回
        retrieval_meta: dict = {}
        retrieval_model: str | None = None
        if cfg.get("agentic_retrieval", False):
            llm = get_llm()
            if llm is not None:
                retrieval_model = getattr(llm, "model", None)
                if cfg.get("llm_cache", False):
                    llm = CachedLLM(llm)  # P5：评估 prompt 确定性，同文档复测零成本
                try:
                    articles, retrieval_meta = agentic_retrieval.agentic_refine(
                        db,
                        llm,
                        text,
                        domain,
                        articles,
                        top_k,
                        max_rounds=int(cfg.get("agentic_max_rounds", 2)),
                    )
                    if retrieval_meta.get("added"):
                        logger.info(
                            "agentic 补检新增 %s 条款（%s 轮，查询：%s）",
                            retrieval_meta["added"],
                            retrieval_meta["rounds"],
                            retrieval_meta["queries"],
                        )
                except Exception:
                    logger.exception("agentic 补检失败，保留基础召回")
                    retrieval_meta = {}

        # 图谱第三路：失败/不在线时 related_articles_for_text 返回空或此处吞掉，主流程不受影响
        if cfg.get("graph_recall", True):
            try:
                graph_articles = graph_service.related_articles_for_text(
                    text[:_QUERY_MAX_CHARS], domain, top_k
                )
            except Exception:
                logger.exception("图谱多跳召回失败，跳过图谱路")
                graph_articles = []
            if graph_articles:
                articles = regulation_service.fuse_graph_route(articles, graph_articles, top_k)
                logger.info(
                    "图谱多跳召回 %s 条，融合后 %s 条", len(graph_articles), len(articles)
                )

        # 可验证证据链收口：语义/关键词/图谱三路定稿后统一补齐文号与发布/生效日期
        # （幂等：混合检索已补过的条款不重查；查询失败时内部静默跳过，不阻断审查）
        articles = regulation_service.enrich_regulation_meta(db, articles)
    finally:
        db.close()

    # agentic 检索的 token 用量并入 llm_usage（state reducer 累加，成本归因覆盖检索侧）
    usage = retrieval_meta.get("usage")
    usage_delta = {**usage, "model": retrieval_model} if usage else None

    return {
        "matched_articles": articles,
        "retrieval_meta": {**retrieval_meta, "synonym_terms": synonym_terms},
        "llm_usage": usage_delta,
    }
