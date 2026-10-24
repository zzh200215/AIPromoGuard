"""判定先例记忆（第 2 批能力）：人工复核结论的沉淀、语义召回与审查注入。

闭环链路：
    人工判定（confirm / 误报纠正 / 翻案）
        → sync_after_verdict 落 review_precedents 行 + Chroma 向量（一个 result 至多一条最新先例）
        → llm_scan 对每个扫描单元 recall_precedents 召回 top-K 相似先例
        → build_review_messages 注入"历史人工判定"参考段
        → 误报先例校准"宁缺毋滥"边界、确认先例提示本机构真实风险模式

设计约束：
- **只沉淀真实人工判定**（confirmed_by>0）：系统自动确认不进记忆——
  与采纳率统计同一数据卫生铁律，避免"系统学系统"的循环论证；
- **记忆始终等于最新人工判断**：翻案 upsert 覆盖、撤销复核删除；
- **先例是增强不是依赖**：写入失败只告警不阻塞人工判定主流程；
  召回失败/无先例返回 []，审查主路径行为与无记忆时完全一致；
- 零 LLM 成本：写入与召回都只走本地 embedding（fastembed ONNX）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.infrastructure.database.mysql import SessionLocal
from src.infrastructure.embedding import get_embedder
from src.infrastructure.vectorstore import get_vector_store
from src.models import ReviewPrecedent, ReviewResult, ReviewTask, Rule
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLLECTION = (
    settings.app_config("vectorstore").get("collection_prefix", "legal_") + "precedents"
)

# 单条先例注入 prompt 的文本上限（先例是校准参考，不是证据主体）
_ORIGINAL_MAX = 80
_ISSUE_MAX = 60


def _memory_enabled() -> bool:
    return bool(settings.app_config("workflow").get("precedent_memory", True))


def _precedent_text(original_text: str, issue: str, rule_name: str | None) -> str:
    """先例的向量化载体：违规原文为主，问题描述与规则名为语义补充。"""
    parts = [original_text.strip()]
    if issue and issue.strip():
        parts.append(issue.strip())
    if rule_name:
        parts.append(rule_name)
    return "\n".join(parts)


def _upsert(db: Session, result: ReviewResult) -> None:
    row = (
        db.query(ReviewPrecedent)
        .filter(ReviewPrecedent.result_id == result.id)
        .one_or_none()
    )
    task = db.get(ReviewTask, result.task_id)
    rule_name: str | None = None
    if result.rule_id is not None:
        rule = db.get(Rule, result.rule_id)
        rule_name = rule.rule_name if rule else None

    text = _precedent_text(result.original_text or "", result.description or "", rule_name)
    embedding = get_embedder().embed([text])[0]
    get_vector_store().add(
        COLLECTION,
        ids=[str(result.id)],
        embeddings=[embedding],
        documents=[text],
        metadatas=[
            {
                "verdict": result.status,
                "task_id": int(result.task_id),
                "domain": (task.domain if task else None) or "",
                "rule_name": rule_name or "",
                "document_name": (task.document_name if task else None) or "",
            }
        ],
    )

    fields = dict(
        verdict=result.status,
        violation_type=result.violation_type,
        rule_id=result.rule_id,
        original_text=result.original_text or "",
        issue=result.description or "",
        document_name=task.document_name if task else None,
        domain=task.domain if task else None,
        confirmed_by=result.confirmed_by,
        confirmed_at=result.confirmed_at or datetime.now(),
    )
    if row is None:
        db.add(ReviewPrecedent(result_id=result.id, task_id=result.task_id, **fields))
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    db.commit()


def _drop(db: Session, result_id: int) -> None:
    db.query(ReviewPrecedent).filter(ReviewPrecedent.result_id == result_id).delete()
    get_vector_store().delete(COLLECTION, [str(result_id)])
    db.commit()


def sync_after_verdict(db: Session, result: ReviewResult) -> None:
    """人工判定终态后的先例同步入口（confirm / 翻案 / 撤销统一走这里）。

    - pending_confirm（撤销复核）→ 删除先例；
    - confirmed / false_positive 且 confirmed_by>0 → upsert；
    - 系统自动确认（confirmed_by 为空）不沉淀（数据卫生：避免循环论证）；
    - 任何失败仅告警——先例是增强能力，不允许阻塞人工判定主流程。
    """
    try:
        if result.status == "pending_confirm":
            _drop(db, result.id)
            return
        if result.status not in ("confirmed", "false_positive"):
            return
        if result.confirmed_by is None:
            return
        _upsert(db, result)
    except Exception as exc:  # noqa: BLE001 —— 详见 docstring：记忆失败不阻塞判定
        logger.warning("先例沉淀失败（不影响判定主流程）result=%s: %s", result.id, exc)


def recall_precedents(
    text: str,
    domain: str | None = None,
    top_k: int = 3,
    exclude_task_id: int | None = None,
    store=None,
    embedder=None,
) -> list[dict]:
    """按语义相似度召回同类先例，供 llm_scan 注入审查上下文。

    领域优先：先取同域（或无域标记）先例，不足再跨域补齐——跨领域规则
    差异大，跨域先例仅作次级参考。失败/无先例/功能关闭一律返回 []
    （审查主路径零依赖，行为与无记忆时完全一致）。
    """
    if not _memory_enabled() or not (text or "").strip() or top_k <= 0:
        return []
    try:
        store = store or get_vector_store()
        embedder = embedder or get_embedder()
        embedding = embedder.embed([text.strip()])[0]
        hits = store.query(COLLECTION, embedding, top_k=max(top_k * 3, 10))
    except Exception as exc:  # noqa: BLE001
        logger.warning("先例召回失败（降级为无先例审查）: %s", exc)
        return []

    picked: list[dict] = []
    same_domain: list[dict] = []
    cross_domain: list[dict] = []
    for h in hits:
        meta = h.get("metadata") or {}
        if exclude_task_id is not None and meta.get("task_id") == int(exclude_task_id):
            continue  # 不用本任务自己的结论校准自己
        verdict = meta.get("verdict")
        if verdict not in ("confirmed", "false_positive"):
            continue
        item = {
            "verdict": verdict,
            "original_text": (h.get("document") or "").splitlines()[0][:_ORIGINAL_MAX]
            if h.get("document")
            else "",
            "issue": (h.get("document") or "").splitlines()[1][_ISSUE_MAX]
            if len((h.get("document") or "").splitlines()) > 1
            else "",
            "domain": meta.get("domain") or None,
            "rule_name": meta.get("rule_name") or None,
            "document_name": meta.get("document_name") or None,
            "score": h.get("score"),
        }
        (same_domain if not item["domain"] or not domain or item["domain"] == domain
         else cross_domain).append(item)

    picked = (same_domain + cross_domain)[:top_k]
    return picked


def rebuild_precedent_index() -> int:
    """按 review_precedents 全表重建 Chroma 向量（幂等，管理用）。

    场景：向量库损坏 / collection_prefix 变更 / 模型换代后全量重嵌。
    用法（rebuild 函数无参，直接调用即可）：
        python -c "from src.services.precedent_memory import rebuild_precedent_index as r; r()"
    """
    from src.infrastructure.vectorstore import get_vector_store as _gvs

    store = _gvs()
    store.delete_all(COLLECTION)
    db = SessionLocal()
    try:
        rows = db.query(ReviewPrecedent).all()
        rule_names = {
            r.id: r.rule_name
            for r in db.query(Rule.id, Rule.rule_name).filter(
                Rule.id.in_([p.rule_id for p in rows if p.rule_id])
            ).all()
        }
        texts: list[str] = []
        ids: list[str] = []
        metas: list[dict] = []
        for p in rows:
            rule_name = rule_names.get(p.rule_id) if p.rule_id else None
            text = _precedent_text(p.original_text, p.issue, rule_name)
            texts.append(text)
            ids.append(str(p.result_id))
            metas.append(
                {
                    "verdict": p.verdict,
                    "task_id": int(p.task_id),
                    "domain": p.domain or "",
                    "rule_name": rule_name or "",
                    "document_name": p.document_name or "",
                }
            )
        for i in range(0, len(texts), 32):
            batch = texts[i : i + 32]
            embs = get_embedder().embed(batch)
            store.add(
                COLLECTION,
                ids=ids[i : i + 32],
                embeddings=embs,
                documents=batch,
                metadatas=metas[i : i + 32],
            )
        return len(rows)
    finally:
        db.close()
