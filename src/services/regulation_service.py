"""法规检索服务：关键词 / 语义 / 混合三种模式（PRD §3.2.5、§11.6）。

- keyword：条款内容 + 法规标题关键词匹配，命中加权
- semantic：ChromaDB 向量语义召回
- hybrid：语义 + 关键词两路结果 RRF（Reciprocal Rank Fusion）融合，
  生效法规优先；可选 cross-encoder rerank 精排（vectorstore.rerank）

融合演进：早期实现直接比较两路原始分数取 max——语义相似度（0-1）与
关键词累加分（可 >1）量纲不统一，跨路比较无意义。RRF 只用排名不用分值，
天然免疫量纲问题：fused(d) = Σ 1/(k + rank_i(d))。
"""

import re
from collections import Counter

from sqlalchemy.orm import Session

from src.infrastructure.embedding import get_embedder
from src.infrastructure.vectorstore import get_vector_store
from src.models import Article, Regulation
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_COLLECTION = (
    settings.app_config("vectorstore").get("collection_prefix", "legal_") + "articles"
)

_RRF_K = 60  # RRF 平滑常数（业界经验值 60，抑制头部排名主导）

# 长查询（整段文档文本）不可能整段出现在条款内容里，子串匹配恒为空。
# 超过该长度时先抽取关键词，再按逐关键词命中计分——
# 同时修复 hybrid 关键词分支（传入 text 前 800 字）与降级检索（传入全文）两条路径。
_LONG_QUERY_CHARS = 40
_EXTRACT_MAX_CHARS = 4000  # 关键词抽取的扫描上限，防超大文档拖慢检索
_KEYWORD_LIMIT = 8

# 高频虚词二元组：无领域区分度，粗滤避免挤占领域关键词名额
_STOP_BIGRAMS = frozenset(
    {
        "我们", "你们", "他们", "可以", "应该", "已经", "没有", "这个", "那个",
        "这些", "那些", "以及", "对于", "但是", "如果", "因此", "其中", "以下",
        "以上", "如下", "进行", "予以", "有关", "本公", "公司",
    }
)


def _extract_keywords(text: str, limit: int = _KEYWORD_LIMIT) -> list[str]:
    """从长文本提取检索关键词：高频 CJK 二元组 + 英文单词/数字串（按频次/出现序）。"""
    segment = text[:_EXTRACT_MAX_CHARS]
    bigrams: Counter[str] = Counter()
    for run in re.findall(r"[\u4e00-\u9fff]+", segment):
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in _STOP_BIGRAMS:
                bigrams[bg] += 1
    keywords = [kw for kw, _ in bigrams.most_common(limit)]
    for token in re.findall(r"[A-Za-z]{2,}|\d+(?:\.\d+)?%?", segment):
        if len(keywords) >= limit:
            break
        if token not in keywords:
            keywords.append(token)
    return keywords


def _highlight(content: str, query: str, window: int = 80) -> str:
    idx = content.find(query)
    if idx < 0:
        return ""
    start = max(0, idx - window // 2)
    snippet = content[start : start + window]
    return snippet.replace(query, f"<em>{query}</em>", 1)


def search_semantic(query: str, domain: list[str] | None, top_k: int) -> list[dict]:
    """向量语义召回，返回条款级结果（按相似度降序）。

    已废止/演示数据（status=deprecated）不参与召回——它们在语义上往往与查询很近
    （实测演示法规在"承诺保本高收益"查询里排 Top-1），一旦被检索到就会被当成依据。
    过滤后可能不足 top_k，因此上游多取几条候选再截断。
    """
    store = get_vector_store()
    embedder = get_embedder()
    vec = embedder.embed([query])[0]
    where = {"domain": {"$in": domain}} if domain else None
    results = store.query(_COLLECTION, vec, top_k=top_k + 5, where=where)
    kept = [r for r in results if r["metadata"].get("status") != "deprecated"][:top_k]
    return [
        {
            "article_id": int(r["metadata"]["article_id"]),
            "regulation_id": int(r["metadata"]["regulation_id"]),
            "regulation_name": r["metadata"]["regulation_name"],
            "article_no": r["metadata"]["article_no"],
            "content": r["document"],
            "status": r["metadata"].get("status", "effective"),
            "score": r["score"],
            "highlight": _highlight(r["document"], query),
        }
        for r in kept
    ]


def search_keyword(db: Session, query: str, domain: list[str] | None, top_k: int) -> list[dict]:
    """关键词检索条款内容与法规标题，命中加权排序。

    短查询（用户检索框）按整词子串匹配；长文本（审查工作流传入的文档片段）
    自动抽取关键词后按逐关键词命中数计分。
    """
    keywords = _extract_keywords(query) if len(query) > _LONG_QUERY_CHARS else [query]
    rows = (
        db.query(Article, Regulation)
        .join(Regulation, Article.regulation_id == Regulation.id)
        .all()
    )
    scored: list[tuple[float, Article, Regulation, str]] = []
    for article, regulation in rows:
        if domain and regulation.domain not in domain:
            continue
        if regulation.status == "deprecated":  # 废止/演示数据不进召回，与语义通道同口径
            continue
        score = 0.0
        first_hit = ""
        for kw in keywords:
            if kw in article.content:
                score += 1.0
                first_hit = first_hit or kw
            if kw in regulation.regulation_name:
                score += 0.6
            if kw in (article.article_no or ""):
                score += 0.3
        if score == 0:
            continue
        if regulation.status == "effective":
            score += 0.1
        scored.append((score, article, regulation, first_hit))
    scored.sort(key=lambda item: -item[0])

    return [
        {
            "article_id": article.id,
            "regulation_id": regulation.id,
            "regulation_name": regulation.regulation_name,
            "article_no": article.article_no or "",
            "content": article.content,
            "status": regulation.status,
            "score": score,
            "highlight": _highlight(article.content, first_hit or query[:_LONG_QUERY_CHARS]),
        }
        for score, article, regulation, first_hit in scored[:top_k]
    ]


def _normalize(values: list[float]) -> list[float]:
    """min-max 归一化到 0-1（退化序列返回全 1，保序）。"""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _rrf_fuse(result_lists: list[list[dict]], k: int = _RRF_K) -> list[dict]:
    """Reciprocal Rank Fusion：多路检索结果按排名倒数融合。

    fused(d) = Σ 1/(k + rank_i(d))，归一化到 0-1 写入 rrf_score；
    同一条款（article_id）多路命中时分数叠加（这正是"双路都认为相关"的信号），
    条款字段保留原始分更高的一路。返回按 rrf_score 降序。
    """
    fused: dict[int, float] = {}
    best: dict[int, dict] = {}
    for lst in result_lists:
        for rank, item in enumerate(lst, start=1):
            aid = item["article_id"]
            fused[aid] = fused.get(aid, 0.0) + 1.0 / (k + rank)
            cur = best.get(aid)
            if cur is None or item.get("score", 0) > cur.get("score", 0):
                best[aid] = dict(item)
    if not fused:
        return []
    max_fused = max(fused.values())
    for aid, item in best.items():
        item["rrf_score"] = round(fused[aid] / max_fused, 6) if max_fused else 0.0
        item["score"] = item["rrf_score"]
    return sorted(best.values(), key=lambda x: -x["rrf_score"])


# ---- 可选 rerank（cross-encoder 精排）----
# 模型体积大（bge-reranker-base 约 1GB），默认关闭（configs/app.yaml rerank.enabled），
# 加载失败/未启用时静默回退 RRF 排序，不影响主流程。
_reranker = None
_reranker_failed = False


def _apply_rerank(query: str, items: list[dict]) -> list[dict]:
    """RRF 候选上做 cross-encoder 精排：final = w*rerank_norm + (1-w)*rrf。"""
    global _reranker, _reranker_failed
    cfg = settings.app_config("vectorstore").get("rerank", {})
    if not cfg.get("enabled") or _reranker_failed or len(items) < 2:
        return items

    if _reranker is None:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _reranker = TextCrossEncoder(
                model_name=cfg.get("model", "BAAI/bge-reranker-base"),
                cache_dir=settings.embedding_cache_dir,
            )
        except Exception as exc:
            _reranker_failed = True
            logger.warning("rerank 模型加载失败，本次起跳过重排: %s", exc)
            return items

    try:
        texts = [f"{i['regulation_name']} {i.get('article_no', '')}\n{i['content']}" for i in items]
        raw = [float(s) for s in _reranker.rerank(query, texts)]
    except Exception as exc:
        logger.warning("rerank 调用失败，回退 RRF 排序: %s", exc)
        return items

    weight = float(cfg.get("weight", 0.7))
    for rn, item in zip(_normalize(raw), items, strict=False):
        item["rerank_score"] = round(rn, 6)
        item["score"] = round(weight * rn + (1 - weight) * item.get("rrf_score", 0.0), 6)
    items.sort(key=lambda x: -x["score"])
    return items


_EMPTY_REG_META = {"regulation_no": None, "publish_date": None, "effective_date": None}


def enrich_regulation_meta(db: Session, articles: list[dict]) -> list[dict]:
    """检索结果补法规文号与发布/生效日期（可验证证据链：不只给条款号，还给版本信息）。

    语义路与图谱路的产物只带向量/图谱元数据，没有库表里的文号与日期；
    融合定稿后按 regulation_id 一次批量查询补齐。幂等（已带字段的不重查），
    查询失败静默跳过——证据链是增强信息，不能因补齐失败阻断审查主流程。
    """
    if articles and all("regulation_no" in a for a in articles):
        return articles
    reg_ids = {a["regulation_id"] for a in articles if a.get("regulation_id")}
    if not reg_ids:
        return articles
    try:
        rows = db.query(Regulation).filter(Regulation.id.in_(reg_ids)).all()
    except Exception:
        logger.warning("法规元数据补齐失败，本次跳过文号/日期透出")
        return articles
    meta = {
        r.id: {
            "regulation_no": r.regulation_no,
            "publish_date": r.publish_date.isoformat() if r.publish_date else None,
            "effective_date": r.effective_date.isoformat() if r.effective_date else None,
        }
        for r in rows
    }
    for a in articles:
        a.update(meta.get(a.get("regulation_id")) or _EMPTY_REG_META.copy())
    return articles


def _cap_per_regulation(items: list[dict], cap: int) -> list[dict]:
    """按法规去重：同一部法规最多保留 cap 条（保留其在原排序中的靠前者）。

    动机（2026-10-22 实测）：Top-K 名额常被同一部法规的多条近似条款占满——
    一场理财直播材料召回 5 条里有 3 条来自《商业银行理财业务监督管理办法》，
    而真正对口的《金融产品网络营销管理办法》排在第 6 位、进不了 Top-5。
    审查场景需要"多部法规各出一条"，而非"一部法规出三条"。
    """
    if cap <= 0:
        return items
    picked: list[dict] = []
    seen: dict[str, int] = {}
    for item in items:
        name = item.get("regulation_name") or ""
        if seen.get(name, 0) >= cap:
            continue
        seen[name] = seen.get(name, 0) + 1
        picked.append(item)
    return picked


def search_hybrid(db: Session, query: str, domain: list[str] | None, top_k: int) -> list[dict]:
    """混合检索：语义 + 关键词 RRF 融合（量纲无关），可选 rerank 精排，生效法规优先。

    `workflow.regulation_dedup_per_doc`（默认 0=关闭）：同一部法规最多保留 N 条。
    开启时上游多取候选（top_k*3），去重后再截断，避免去重把名额截空。
    """
    cap = int(settings.app_config("workflow").get("regulation_dedup_per_doc", 0) or 0)
    fetch_k = top_k * 3 if cap > 0 else top_k
    fused = _rrf_fuse(
        [
            search_semantic(query, domain, fetch_k),
            search_keyword(db, query, domain, fetch_k),
        ]
    )
    fused = _apply_rerank(query, fused)
    fused.sort(key=lambda item: (item.get("status") != "effective", -item.get("score", 0)))
    fused = _cap_per_regulation(fused, cap)
    return enrich_regulation_meta(db, fused[:top_k])


def fuse_route_lists(
    result_lists: list[list[dict]], top_k: int, cap: int | None = None
) -> list[dict]:
    """多路检索结果 RRF 融合 + 生效法规优先排序（agentic 补检等场景的通用入口）。

    与 `search_hybrid` 一样受 `workflow.regulation_dedup_per_doc` 约束：图谱/agentic
    融合会把同法规的多条近似条款重新摊平，若只在混合检索处去重会被这一步抵消。
    `cap` 显式传入可覆盖配置（测试/特殊场景用）。
    """
    fused = _rrf_fuse(result_lists)
    fused.sort(key=lambda item: (item.get("status") != "effective", -item.get("score", 0)))
    if cap is None:
        cap = int(settings.app_config("workflow").get("regulation_dedup_per_doc", 0) or 0)
    fused = _cap_per_regulation(fused, cap)
    return fused[:top_k]


def fuse_graph_route(hybrid: list[dict], graph_articles: list[dict], top_k: int) -> list[dict]:
    """图谱多跳召回作为第三路并入混合检索结果（P2 GraphRAG）。

    与语义/关键词两路相同走 RRF 排名融合：同时被混合检索与图谱召回的条款
    排名叠加增强；仅图谱召回的条款（如挖掘规则的条款级 VIOLATES 关联）也能
    进入候选。图谱条款按模式相似度降序传入即为其"排名"，排序仍保持生效法规优先。
    """
    if not graph_articles:
        return hybrid[:top_k]
    return fuse_route_lists([hybrid, graph_articles], top_k)


def search(
    db: Session, query: str, search_type: str, domain: list[str] | None, top_k: int
) -> list[dict]:
    if search_type == "keyword":
        return enrich_regulation_meta(db, search_keyword(db, query, domain, top_k))
    if search_type == "semantic":
        return enrich_regulation_meta(db, search_semantic(query, domain, top_k))
    return search_hybrid(db, query, domain, top_k)


def annotate_citation_links(db: Session, results: list[dict]) -> list[dict]:
    """补充检索结果的证据链注记：被 N 条规则引用 / 关联 N 起真实处罚案例。

    - 规则引用：rule_regulation_links 按条款级（article_id）与法规级
      （article_id 为空的关联）合并计数，去重到规则数；
    - 处罚案例：penalty_cases.related_regulations（法规 id 数组，全表 ≤ 百量级
      内存判断，避免 JSON 数组的方言相关查询）。
    """
    from sqlalchemy import or_

    from src.models import PenaltyCase, RuleRegulationLink

    article_ids = {r.get("article_id") for r in results if r.get("article_id")}
    regulation_ids = {r.get("regulation_id") for r in results if r.get("regulation_id")}

    art_rules: dict[int, set] = {}
    reg_rules: dict[int, set] = {}
    if article_ids or regulation_ids:
        rows = (
            db.query(
                RuleRegulationLink.article_id,
                RuleRegulationLink.regulation_id,
                RuleRegulationLink.rule_id,
            )
            .filter(
                or_(
                    RuleRegulationLink.article_id.in_(article_ids),
                    RuleRegulationLink.regulation_id.in_(regulation_ids),
                )
            )
            .all()
        )
        for aid, rid, rule_id in rows:
            if aid:
                art_rules.setdefault(aid, set()).add(rule_id)
            else:
                reg_rules.setdefault(rid, set()).add(rule_id)

    case_rows = db.query(PenaltyCase.id, PenaltyCase.related_regulations).all()
    reg_cases: dict[int, list] = {}
    for cid, regs in case_rows:
        for rid in regs or []:
            reg_cases.setdefault(rid, []).append(cid)

    for r in results:
        rules = art_rules.get(r.get("article_id"), set()) | reg_rules.get(
            r.get("regulation_id"), set()
        )
        r["cited_rules"] = len(rules)
        r["cited_cases"] = len(reg_cases.get(r.get("regulation_id"), []))
    return results
