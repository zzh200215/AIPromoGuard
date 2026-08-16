"""RegulationMatcher：从知识库召回相关法规条款。

走混合检索（语义 + 关键词融合，生效法规优先）；混合检索失败回退纯关键词。
"""

from src.core.agents.state import ReviewState
from src.infrastructure.database.mysql import SessionLocal
from src.services import regulation_service
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
    finally:
        db.close()
    return {"matched_articles": articles}
