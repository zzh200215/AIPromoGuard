"""知识图谱查询服务（W9 周四，PRD §3.2.6 / §5.5）。

提供三类查询：
- query_graph：违规点 → 关联违规模式 / 法规条款 / 历史处罚案例
- similar_cases：相似案例推荐（W10 增强为 语义 + 关键词 + 图谱 三路融合）
- graph_stats：图谱节点与关系计数（验证用）

Neo4j / ChromaDB 不在线时各路径优雅降级（返回空），调用方无需处理异常。
"""

from src.infrastructure.database.mysql import SessionLocal
from src.infrastructure.database.neo4j_client import run_cypher
from src.infrastructure.embedding import get_embedder
from src.infrastructure.vectorstore import get_vector_store
from src.models import PenaltyCase, Regulation
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_DOMAIN_LABEL = {"banking": "银行理财", "fund": "基金销售", "insurance": "保险产品"}

# 相似案例推荐（W10）：三路融合权重
_CASE_COLLECTION = (
    settings.app_config("vectorstore").get("collection_prefix", "legal_") + "penalty_cases"
)
_W_SEMANTIC = 0.5   # 向量语义召回（案例向量索引，index_cases.py 生成）
_W_KEYWORD = 0.3    # 字符 bigram 关键词（直接对案例名/摘要）
_W_GRAPH = 0.2      # 图谱关联（违规模式 → 案例）
_CASE_FALLBACK_THRESHOLD = 0.2


def _bigram_score(query: str, text: str) -> float:
    """字符 bigram 重叠打分（中文免分词），用于违规点与违规模式的相似度。"""
    q = query.strip()
    t = text.strip()
    if not q or not t:
        return 0.0
    q_grams = {q[i : i + 2] for i in range(len(q) - 1)}
    t_grams = {t[i : i + 2] for i in range(len(t) - 1)}
    if not q_grams:
        return 0.0
    return len(q_grams & t_grams) / len(q_grams)


def _load_patterns(domain: str | None) -> list[dict]:
    """加载违规模式节点（可含领域过滤）。"""
    if domain:
        rows = run_cypher(
            "MATCH (v:ViolationPattern {domain: $d}) "
            "RETURN v.id AS id, v.pattern_name AS pattern_name, v.description AS description, "
            "v.domain AS domain, v.severity AS severity",
            {"d": domain},
        )
    else:
        rows = run_cypher(
            "MATCH (v:ViolationPattern) "
            "RETURN v.id AS id, v.pattern_name AS pattern_name, v.description AS description, "
            "v.domain AS domain, v.severity AS severity"
        )
    return rows


def _linked_regulations(pattern_id: int) -> list[dict]:
    """违规模式 → 关联法规条款（经 VIOLATES + HAS_ARTICLE）。"""
    return run_cypher(
        "MATCH (a:Article)-[:VIOLATES]->(v:ViolationPattern {id: $id}),"
        "(r:Regulation)-[:HAS_ARTICLE]->(a) "
        "RETURN r.id AS regulation_id, r.name AS regulation_name, r.domain AS domain, "
        "collect(DISTINCT a.article_no) AS article_nos ORDER BY regulation_id",
        {"id": pattern_id},
    )


def _linked_cases(pattern_id: int) -> list[dict]:
    """违规模式 → 关联处罚案例（经 INVOLVES_VIOLATION）。"""
    return run_cypher(
        "MATCH (c:PenaltyCase)-[:INVOLVES_VIOLATION]->(v:ViolationPattern {id: $id}) "
        "RETURN c.case_name AS case_name, c.penalty_org AS penalty_org, "
        "c.penalty_date AS penalty_date, c.penalty_result AS penalty_result, "
        "c.summary AS summary",
        {"id": pattern_id},
    )


def query_graph(query: str, domain: str | None = None, top_k: int = 10) -> dict:
    """违规点 → 关联违规模式 / 法规条款 / 历史处罚案例。"""
    patterns = _load_patterns(domain)
    scored: list[tuple[float, dict]] = []
    for p in patterns:
        score = max(
            _bigram_score(query, p.get("pattern_name", "")),
            _bigram_score(query, p.get("description", "")),
        )
        if score > 0.2:
            scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    result = {
        "query": query,
        "domain": domain,
        "total_matched": len(top),
        "patterns": [],
        "regulations": [],
        "cases": [],
    }
    seen_regs: set[tuple[int, str]] = set()
    seen_cases: set[str] = set()
    for score, p in top:
        result["patterns"].append(
            {
                "pattern_name": p.get("pattern_name"),
                "domain": p.get("domain"),
                "severity": p.get("severity"),
                "similarity": round(score, 3),
            }
        )
        for reg in _linked_regulations(p.get("id")):
            key = (reg.get("regulation_id"), reg.get("regulation_name"))
            if key in seen_regs:
                continue
            seen_regs.add(key)
            result["regulations"].append(
                {
                    "regulation_name": reg.get("regulation_name"),
                    "domain": reg.get("domain"),
                    "article_nos": reg.get("article_nos", [])[:20],
                }
            )
        for case in _linked_cases(p.get("id")):
            name = case.get("case_name")
            if name in seen_cases:
                continue
            seen_cases.add(name)
            result["cases"].append(
                {
                    "case_name": name,
                    "penalty_org": case.get("penalty_org"),
                    "penalty_date": case.get("penalty_date"),
                    "penalty_result": case.get("penalty_result"),
                    "similarity": round(score, 3),
                }
            )
    # 法规 / 案例按相似度降序
    result["regulations"].sort(
        key=lambda x: _bigram_score(query, x["regulation_name"]), reverse=True
    )
    return result


def _semantic_cases(text: str, domain: str | None, top_k: int) -> list[dict]:
    """向量语义召回：违规点文本编码后查案例向量索引（legal_penalty_cases）。"""
    try:
        embedder = get_embedder()
        store = get_vector_store()
    except Exception:
        return []
    try:
        vec = embedder.embed([text[:800]])[0]
        where = {"domain": {"$in": [domain]}} if domain else None
        results = store.query(_CASE_COLLECTION, vec, top_k=top_k, where=where)
        return [
            {
                "case_name": r["metadata"]["case_name"],
                "penalty_org": r["metadata"].get("penalty_org", ""),
                "penalty_date": r["metadata"].get("penalty_date", ""),
                "penalty_result": r["metadata"].get("penalty_result", ""),
                "summary": r["document"][:120],
                "score": r["score"],
            }
            for r in results
        ]
    except Exception:
        logger.exception("案例语义召回失败")
        return []


def _all_cases(domain: str | None) -> list[dict]:
    """从 MySQL 加载处罚案例（用于关键词路兜底）。

    案例表无 domain 字段，按关联法规所属领域过滤。
    """
    db = SessionLocal()
    try:
        query = db.query(PenaltyCase)
        if domain:
            domain_reg_ids = [
                r.id
                for r in db.query(Regulation.id).filter(Regulation.domain == domain).all()
            ]
            case_ids = {
                c.id
                for c in db.query(PenaltyCase.id, PenaltyCase.related_regulations).all()
                if any(rid in domain_reg_ids for rid in (c.related_regulations or []))
            }
            if not case_ids:
                return []
            query = query.filter(PenaltyCase.id.in_(case_ids))
        cases = query.all()
        return [
            {
                "case_name": c.case_name,
                "penalty_org": c.penalty_org or "",
                "penalty_date": c.penalty_date.isoformat() if c.penalty_date else "",
                "penalty_result": c.penalty_result or "",
                "summary": c.violation_summary or "",
            }
            for c in cases
        ]
    finally:
        db.close()


def similar_cases(text: str, domain: str | None = None, top_k: int = 5) -> list[dict]:
    """基于违规内容相似度推荐历史处罚案例（辅助风险评估，PRD §3.2.6 相似案例推荐）。

    三路融合（W10 增强）：
    1. 向量语义召回（权重 0.5）——案例向量索引 legal_penalty_cases
    2. 关键词 bigram（权重 0.3）——直接匹配案例名 / 违规摘要
    3. 图谱关联（权重 0.2）——违规模式 → 关联案例
    按 case_name 去重，取加权分最高者；无向量索引或图谱时自动退化为可用路径。
    """
    best: dict[str, tuple[float, dict]] = {}

    def merge(case: dict, score: float, weight: float) -> None:
        name = case.get("case_name")
        if not name:
            return
        weighted = score * weight
        if weighted >= _CASE_FALLBACK_THRESHOLD and (name not in best or weighted > best[name][0]):
            best[name] = (weighted, case)

    # 1. 语义路
    for c in _semantic_cases(text, domain, top_k * 3):
        merge(c, c.get("score", 0), _W_SEMANTIC)

    # 2. 关键词路（直接对案例文本，不依赖图谱）
    for c in _all_cases(domain):
        score = max(
            _bigram_score(text, c.get("case_name", "")),
            _bigram_score(text, c.get("summary", "")),
        )
        merge(c, score, _W_KEYWORD)

    # 3. 图谱路：违规模式 → 关联案例
    for score, p in _scored_patterns(text, domain, top_k * 2):
        for case in _linked_cases(p.get("id")):
            merge(
                {
                    "case_name": case.get("case_name"),
                    "penalty_org": case.get("penalty_org"),
                    "penalty_date": case.get("penalty_date"),
                    "penalty_result": case.get("penalty_result"),
                    "summary": case.get("summary", ""),
                },
                score,
                _W_GRAPH,
            )

    result = []
    for name, (score, case) in sorted(best.items(), key=lambda x: x[1][0], reverse=True)[:top_k]:
        result.append(
            {
                "case_name": name,
                "penalty_org": case.get("penalty_org"),
                "penalty_date": case.get("penalty_date"),
                "penalty_result": case.get("penalty_result"),
                "summary": (case.get("summary") or "")[:120],
                "similarity": round(score, 3),
            }
        )
    return result


def _scored_patterns(text: str, domain: str | None, top_k: int) -> list[tuple[float, dict]]:
    """违规模式按 bigram 相似度打分（图谱路用）。"""
    scored: list[tuple[float, dict]] = []
    for p in _load_patterns(domain):
        score = max(
            _bigram_score(text, p.get("pattern_name", "")),
            _bigram_score(text, p.get("description", "")),
        )
        if score > 0.2:
            scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


def graph_stats() -> dict:
    """图谱节点与关系计数（验证 / 健康检查用）。"""
    node_counts = {}
    for label in ("Regulation", "Article", "ViolationPattern", "ProductType", "PenaltyCase"):
        rows = run_cypher(f"MATCH (n:{label}) RETURN count(n) AS c")
        node_counts[label] = rows[0]["c"] if rows else 0
    rel_counts = {}
    for rel in (
        "HAS_ARTICLE",
        "VIOLATES",
        "APPLIES_TO",
        "BASED_ON_REGULATION",
        "INVOLVES_VIOLATION",
    ):
        rows = run_cypher(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
        rel_counts[rel] = rows[0]["c"] if rows else 0
    return {"nodes": node_counts, "relationships": rel_counts, "available": bool(node_counts)}
