"""审查任务编排服务：解析文档 → 后台跑 LangGraph workflow → 持久化结果与报告。

任务执行后端（B2）：
- 默认进程内线程池（MVP，免运维）；压测后升级为 Celery/Redis 队列。
- start_review 探测 Redis broker 上是否有 worker 存活（ping，30s 缓存）：
  有 → send_task 入队（worker 独占执行，api 不再跑审查，避免多进程并发写 ChromaDB）；
  无 → 回退线程池，保持单进程行为。
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.exc import OperationalError

from src.core.agents.graph import run_review
from src.core.agents.runtime import (
    cleanup_task_checkpoints,
    resume_review,
    saver_is_persistent,
    start_review_with_hil,
    thread_id_for_task,
)
from src.core.profiles import effective_auto_confirm, resolve_human_review, safe_profile
from src.infrastructure.database.mysql import SessionLocal
from src.models import (
    Article,
    ProductMaterial,
    ReviewBatch,
    ReviewResult,
    ReviewTask,
    RuleRegulationLink,
)
from src.services import tamper_check
from src.services.diff_service import build_review_blocks, diff_documents
from src.services.document_service import document_service
from src.services.visual_scan import find_ocr_missing, scan_image_visual
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


def _human_review_enabled() -> bool:
    return (settings.app_config("workflow").get("human_review") or {}).get("enabled", False)


def _task_profile(task_id: int) -> str | None:
    """读任务的审查策略（DB 只读一次，失败回退 standard）。"""
    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        return safe_profile(task.profile) if task else None
    except Exception:
        logger.warning("task %s 读取 profile 失败，按 standard 处理", task_id, exc_info=True)
        return None
    finally:
        db.close()


def recover_orphan_tasks() -> dict:
    """启动自愈：回收上一进程崩溃遗留的 running 任务（API lifespan 调用）。

    线程池执行模型下 running 任务的线程随进程消亡，不回收会永远卡住：
    - checkpoint 显示图停在 human_review 中断 → 恢复 awaiting_review，
      人工决策仍可从持久化 checkpoint 续跑；
    - 其余（跑图中途崩溃 / 无 checkpoint）→ 置 failed 并同步批次计数。
    Celery worker 在线时跳过——执行权在 worker 进程，API 不能误杀在跑任务。
    """
    if _use_celery():
        logger.info("Celery worker 在线，孤儿任务回收交给 worker 进程（跳过）")
        return {"skipped": "celery"}

    from src.core.agents import runtime

    db = SessionLocal()
    outcome: dict = {"recovered": 0, "failed": 0}
    try:
        orphans = db.query(ReviewTask).filter(ReviewTask.status == "running").all()
        if not orphans:
            return outcome

        graph = None
        if _human_review_enabled() or any(safe_profile(t.profile) == "strict" for t in orphans):
            # strict 任务即使全局 HIL 关闭也会在关卡中断，checkpoint 恢复同样可达
            graph = runtime.get_hil_graph()
        for task in orphans:
            recovered = False
            if graph is not None:
                try:
                    state = graph.get_state(
                        {"configurable": {"thread_id": runtime.thread_id_for_task(task.id)}}
                    )
                except Exception:
                    state = None
                if state is not None and state.next == ("human_review",):
                    # 从中断 payload 重建待复核清单（拿不到则给空表，续跑不受影响）
                    pending: list = []
                    for pregel_task in state.tasks or ():
                        for interrupt in getattr(pregel_task, "interrupts", ()) or ():
                            value = getattr(interrupt, "value", None)
                            if isinstance(value, list):
                                pending.extend(value)
                    task.status = "awaiting_review"
                    task.progress = 80
                    task.stages = {"human_review": {"status": "awaiting", "pending": pending}}
                    db.commit()
                    outcome["recovered"] += 1
                    logger.info(
                        "task %s 启动自愈：恢复 awaiting_review（checkpoint 命中，待复核 %s 条）",
                        task.id,
                        len(pending),
                    )
                    recovered = True
            if not recovered:
                task.status = "failed"
                task.progress = 100
                db.commit()
                _update_batch_counts(db, task)
                runtime.cleanup_task_checkpoints(task.id)
                outcome["failed"] += 1
                logger.warning("task %s 启动自愈：无可用 checkpoint，置为 failed", task.id)
        return outcome
    finally:
        db.close()

# 系统自动确认的 actor 表达（PR-7）：NULL=无人工 actor（原为哨兵值 0——0 不是
# 合法 users.id，与 fk_review_results_confirmed_by 冲突，故改用 NULL；
# "是否自动确认"统一由 ReviewResult.auto_confirmed 派生，勿再手写 0 比较）。
_AUTO_CONFIRM_BY: int | None = None
_AUTO_CONFIRM_SOURCES = {"rule", "hybrid"}

_QUEUE_BACKEND: str | None = None  # "celery" | "thread"
_LAST_CHECK = 0.0
_CHECK_TTL = 30.0
_QUEUE_CHECK_LOCK = threading.Lock()  # 探测串行化：celery control.ping 非线程安全


def _use_celery() -> bool:
    """探测 Celery worker 是否可用（ping，结果缓存 30s，避免每请求开销）。

    探测加锁串行化：celery control.ping 的 pidbox/连接在多线程并发调用下
    有概率挂死（PR-9 并发实测：20 线程并发首次探测卡住提交阶段 100s+，
    20 个任务全量 pending）——锁内双检，等锁线程直接复用探测结果。
    """
    global _QUEUE_BACKEND, _LAST_CHECK
    now = time.monotonic()
    if _QUEUE_BACKEND and now - _LAST_CHECK < _CHECK_TTL:
        return _QUEUE_BACKEND == "celery"
    with _QUEUE_CHECK_LOCK:
        # 双检：等锁期间可能有其他线程已完成探测并刷新缓存
        now = time.monotonic()
        if _QUEUE_BACKEND and now - _LAST_CHECK < _CHECK_TTL:
            return _QUEUE_BACKEND == "celery"
        try:
            from src.infrastructure.queue.celery_app import celery_app

            workers = celery_app.control.ping(timeout=0.5)
            _QUEUE_BACKEND = "celery" if workers else "thread"
        except Exception:
            _QUEUE_BACKEND = "thread"
        _LAST_CHECK = now
        logger.info("审查队列后端: %s", _QUEUE_BACKEND)
        return _QUEUE_BACKEND == "celery"


def start_review(task_id: int) -> None:
    """提交审查任务：优先 Celery 队列，无 worker 时回退线程池。

    人工复核（HIL）任务要求 checkpointer 跨进程可读：默认 MySQLCheckpointSaver
    满足，可正常入队 Celery；DB 不可用回退 InMemorySaver 时强制线程池，
    保证 resume 发生在同进程（API 侧）。strict 策略强制 HIL（全局关闭也拦）。
    """
    hil = resolve_human_review(_task_profile(task_id), _human_review_enabled())
    if _use_celery():
        if hil and not saver_is_persistent():
            logger.warning(
                "task %s: checkpointer 非持久（DB 回退），HIL 任务强制线程池执行",
                task_id,
            )
        else:
            from src.infrastructure.queue.celery_app import celery_app

            celery_app.send_task("review.run_review", args=[task_id], queue="review_tasks")
            return
    _executor.submit(execute_review, task_id)


def reset_failed_task_for_retry(db, task: ReviewTask) -> None:
    """失败任务重试前的状态复位：清终态痕迹 + 批次 failed_count 回退。

    结果落库（_persist_results）本身先删后插，重跑天然幂等；
    这里只负责任务行与批次计数回到可重跑状态。批次回到 running：
    重试完成后 _update_batch_counts 会重新判定终态，计数保持守恒
    （failed_count-1，完成后 completed_count+1）。
    """
    task.status = "pending"
    task.progress = 0
    task.stages = None
    task.llm_usage = None
    task.report_path = None
    task.started_at = None
    task.completed_at = None
    if task.batch_id and db.get(ReviewBatch, task.batch_id) is not None:
        db.execute(
            update(ReviewBatch)
            .where(ReviewBatch.id == task.batch_id)
            .values(failed_count=func.greatest(ReviewBatch.failed_count - 1, 0))
        )
        batch = db.get(ReviewBatch, task.batch_id)
        batch.status = "running"
        batch.completed_at = None
    db.flush()


def sync_material_review_status(db, task: ReviewTask) -> None:
    """任务终态后回写材料台账最近审查状态（document_path → document_id 匹配）。

    此前只有影响批次的回写（sync_batch_to_assessment），普通任务完成后台账
    "最近审查结果"失真；现在所有终态任务统一回写，口径一致
    （completed+有违规=violation / completed 零违规=clean / failed=failed）。
    影响批次的整改清单闭环仍由 sync_batch_to_assessment 负责。
    """
    from src.services.impact_service import _doc_id_from_path

    doc_id = _doc_id_from_path(task.document_path)
    if not doc_id:
        return
    violations = (
        db.query(func.count(ReviewResult.id)).filter(ReviewResult.task_id == task.id).scalar()
        or 0
    )
    if task.status == "completed":
        review_status = "violation" if violations else "clean"
    else:
        review_status = "failed"
    materials = (
        db.query(ProductMaterial)
        .filter(ProductMaterial.document_id == doc_id, ProductMaterial.status == "active")
        .all()
    )
    for material in materials:
        material.last_review_status = review_status
        material.last_reviewed_at = datetime.now()
    if materials:
        db.commit()
        logger.info("task %s 已回写 %s 条台账材料状态=%s", task.id, len(materials), review_status)


def _update_batch_counts(db, task: ReviewTask) -> None:
    """任务到达终态后同步材料台账与批次计数；无批次归属时跳过计数。

    计数用原子 UPDATE 累加（多线程并发时读-改-写会丢失更新），
    提交后再读最新计数判断批次是否全部终态，置终态为幂等操作。
    """
    sync_material_review_status(db, task)
    if not task.batch_id:
        return
    if db.get(ReviewBatch, task.batch_id) is None:
        return
    if task.status == "completed":
        db.execute(
            update(ReviewBatch)
            .where(ReviewBatch.id == task.batch_id)
            .values(completed_count=ReviewBatch.completed_count + 1)
        )
    elif task.status == "failed":
        db.execute(
            update(ReviewBatch)
            .where(ReviewBatch.id == task.batch_id)
            .values(failed_count=ReviewBatch.failed_count + 1)
        )
    else:
        return
    db.commit()

    batch = db.get(ReviewBatch, task.batch_id)
    if batch.completed_count + batch.failed_count >= batch.total_count:
        batch.status = "completed" if batch.failed_count == 0 else "failed"
        batch.completed_at = datetime.now()
        db.commit()
        # 影响中心的复审批次：终态后回写材料台账并生成整改清单（失败不影响批次状态）
        if batch.source_type == "impact_assessment":
            try:
                from src.services.impact_service import sync_batch_to_assessment

                sync_batch_to_assessment(db, batch.id)
            except Exception:
                logger.exception("影响评估回写失败 batch=%s", batch.id)
        # 站内通知：批次终态触达创建人（尽力而为）
        try:
            from src.services.notification_service import notify_batch_terminal

            notify_batch_terminal(db, batch)
        except Exception:
            logger.exception("批次终态通知失败 batch=%s", batch.id)


def _block_to_dict(block) -> dict:
    return {
        "text": block.text,
        "page": block.page,
        "paragraph": block.paragraph,
        "heading": block.heading,
    }


def _raw_blocks_for_tamper(path: str) -> tuple[list[dict], str]:
    """篡改比对的文字口径（PR-6）= **未脱敏**解析块 + 原文。

    解析层脱敏把金额抹成 "***元"（"50,000元"→"50,***元"），用脱敏文本做
    "图片读数 vs 文字材料"比对会给每个带单位金额报假篡改（真机验证实证）——
    与巡检基线 10-07 的"两侧口径不一致"同类问题，参见 document_service.parse
    注释。此处返回的内容只进数字比对，不进 LLM 上下文（隐私面不变）。
    """
    raw = document_service.parse(path, mask=False)
    return [_block_to_dict(b) for b in raw.blocks], raw.text


def execute_review(task_id: int) -> None:
    """执行一次完整审查（线程池与 Celery worker 共用入口）。"""
    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        if task is None:
            return
        task.status = "running"
        task.progress = 10
        task.started_at = datetime.now()
        db.commit()

        parsed = document_service.parse(task.document_path)
        blocks = [_block_to_dict(b) for b in parsed.blocks]
        diff_changes = None
        review_text = parsed.text
        review_blocks = blocks
        if task.base_document_path:
            # 对比模式：旧版解析 → diff → 只审变更块 + 上下文窗口
            base_parsed = document_service.parse(task.base_document_path)
            base_blocks = [_block_to_dict(b) for b in base_parsed.blocks]
            changes = diff_documents(base_blocks, blocks)
            diff_changes = [c.to_dict() for c in changes]
            task.diff_changes = diff_changes
            db.commit()
            review_blocks = build_review_blocks(blocks, changes)
            review_text = "\n".join(b["text"] for b in review_blocks)
        task.progress = 20
        db.commit()

        profile = safe_profile(task.profile)

        # 图片文档：OCR 文本管线之外叠加视觉层审查（VLM，失败降级为空不阻断）
        vlm_findings: list = []
        vlm_usage = None
        doc_ext = (task.document_path or "").rsplit(".", 1)[-1].lower()
        if doc_ext in {"png", "jpg", "jpeg", "bmp"}:
            vlm_findings, vlm_usage, visible_numbers, _ = scan_image_visual(
                task.document_path, parsed.text, task.domain
            )
            # R2-3 交叉篡改检测（PR-6 三分支）：VLM 关键数字 vs 文字材料数字集——
            # 同位置有数字但不等 = 疑似篡改（一票 changed）；文字层未读到也无对应
            # 位置 = 降级"待人工核验"（最可能是 OCR 漏读小字）。
            #
            # 比对必须用**未脱敏**口径（PR-6 真机验证发现）：解析层脱敏把金额抹成
            # "***元"（"50,000元"→"50,***元"），用脱敏文本比对会给每个带单位金额
            # 报假篡改——与巡检基线 10-07"两侧口径不一致"同类问题（见
            # document_service.parse 注释）。仅在有数字可比对时才做第二遍解析
            # （OCR 成本按需支付）；未脱敏文本只进比对、不进 LLM 上下文，隐私面不变。
            raw_blocks: list[dict] = []
            if visible_numbers:
                raw_blocks, raw_text = _raw_blocks_for_tamper(task.document_path)
            if raw_blocks:
                ocr_missing = find_ocr_missing(visible_numbers, raw_text)
                vlm_findings = vlm_findings + tamper_check.check_tamper(
                    visible_numbers, raw_blocks, page=1, ocr_missing=ocr_missing
                )

        initial_state = {
            "task_id": task.id,
            "document_path": task.document_path,
            "document_name": task.document_name,
            "doc_type": task.document_type,
            "text": review_text,
            "blocks": review_blocks,
            "diff_changes": diff_changes,
            "profile": profile,
            "vlm_findings": vlm_findings,
            # 方案 A：解析脱敏时采集的敏感命中元数据（PII 检测的数据源——
            # 脱敏后文本已无法用正则扫出敏感信息）
            "mask_spans": getattr(parsed, "mask_spans", []) or [],
            # 预置视觉模型用量：reducer 与 llm_scan 的文本扫描用量相加（成本归因覆盖视觉层）
            "llm_usage": vlm_usage,
        }

        if resolve_human_review(profile, _human_review_enabled()):
            outcome = start_review_with_hil(initial_state, thread_id_for_task(task.id))
            if outcome["interrupted"]:
                # 图在 human_review 暂停：任务挂起等人，决策经
                # resume_human_review 从 checkpoint 续跑（risk_assess → report）
                task.status = "awaiting_review"
                task.progress = 80
                task.stages = {
                    "human_review": {"status": "awaiting", "pending": outcome["pending"]}
                }
                db.commit()
                logger.info(
                    "task %s 等待人工复核（%s 条待确认）", task_id, len(outcome["pending"])
                )
                return
            result = outcome["result"]
        else:
            result = run_review(initial_state)

        _finalize_task(db, task, result)
    except Exception:
        db.rollback()
        task = db.get(ReviewTask, task_id)
        if task is not None:
            task.status = "failed"
            task.progress = 100
            db.commit()
            _update_batch_counts(db, task)
            try:
                from src.services.notification_service import notify_task_failed

                notify_task_failed(db, task)
            except Exception:
                logger.exception("任务失败通知失败 task=%s", task_id)
        cleanup_task_checkpoints(task_id)
        logger.exception("task %s 审查失败", task_id)
    finally:
        db.close()


_DEADLOCK_ERRNO = 1213
_FINALIZE_RETRIES = 3


def _finalize_task(db, task: ReviewTask, result: dict) -> None:
    """图跑完后的落库：结果明细、节点耗时、报告路径与任务终态。

    并发任务批量落库在 REPEATABLE READ 隔离级别下仍可能遇 1213 死锁
    （子表索引 gap 锁交叉，PR-9 并发实测）——落库幂等（_persist_results 先清
    后插），对死锁做有限重试兜底；非死锁异常照抛。
    """
    report_data = result.get("report") or {}
    findings = report_data.get("violations", [])
    for attempt in range(_FINALIZE_RETRIES):
        try:
            _persist_results(db, task.id, findings, profile=safe_profile(task.profile))
            task.stages = result.get("stage_log")  # 各 Agent 节点耗时（W14）
            task.llm_usage = result.get("llm_usage")  # token 用量/预估成本（成本归因）
            task.report_path = result.get("report_path")
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.now()
            db.commit()
            break
        except OperationalError as exc:
            db.rollback()
            errno = exc.orig.args[0] if exc.orig is not None and exc.orig.args else None
            if errno != _DEADLOCK_ERRNO or attempt >= _FINALIZE_RETRIES - 1:
                raise
            logger.warning("task %s 落库遇死锁（1213），第 %s 次重试", task.id, attempt + 1)
            time.sleep(0.1 * (attempt + 1))
            task = db.get(ReviewTask, task.id)
            if task is None:
                raise
    _update_batch_counts(db, task)
    cleanup_task_checkpoints(task.id)  # 图已到终点，checkpoint 不再需要
    logger.info("task %s 审查完成，命中 %s 条违规", task.id, len(findings))


def resume_human_review(task_id: int, rejected_indexes: list[int]) -> dict:
    """人工提交复核决策后，从 checkpoint 续跑剩余图并落库（同步执行，剩余节点无 LLM 调用）。

    返回续跑后的任务摘要；任务不存在或状态非 awaiting_review 时抛 AppError。
    """
    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        if task is None:
            raise AppError(ErrorCode.TASK_NOT_FOUND)
        if task.status != "awaiting_review":
            raise AppError(
                ErrorCode.TASK_INVALID_STATE, f"任务当前状态 {task.status}，不接受人工复核决策"
            )

        # 原子抢占：并发双击提交时只有一个请求能把状态改走，另一个直接 409，
        # 避免两次续跑重复落库 _persist_results
        claimed = db.execute(
            update(ReviewTask)
            .where(ReviewTask.id == task_id, ReviewTask.status == "awaiting_review")
            .values(status="running")
        )
        db.commit()
        if claimed.rowcount == 0:
            raise AppError(
                ErrorCode.TASK_INVALID_STATE, "决策已被提交处理，请刷新页面查看最新结果"
            )
        db.refresh(task)

        result = resume_review(
            thread_id_for_task(task_id), {"rejected_indexes": list(rejected_indexes)}
        )
        _finalize_task(db, task, result)
        return {
            "task_id": task_id,
            "status": task.status,
            "human_review": result.get("human_review"),
            "total_violations": (result.get("report") or {}).get("summary", {}).get(
                "total_violations"
            ),
        }
    except AppError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        task = db.get(ReviewTask, task_id)
        if task is not None:
            task.status = "failed"
            task.progress = 100
            db.commit()
            _update_batch_counts(db, task)
        cleanup_task_checkpoints(task_id)
        logger.exception("task %s 人工复核续跑失败", task_id)
        raise
    finally:
        db.close()


def _auto_confirm(finding: dict, cfg: dict) -> tuple[str, datetime | None, int | None]:
    """人审分流：规则/双引擎高置信命中自动确认，其余进人工队列。

    - violation_type in (rule, hybrid) 且 confidence >= threshold → 自动 confirmed，
      confirmed_by=None（无人工 actor，PR-7 起以 NULL 表达"系统自动"，派生见
      ReviewResult.auto_confirmed），confirmed_at 记录自动确认时刻。
    - evidence_supported=False（引用的法规不在召回条款中，证据核验关卡标记）
      → 即使 hybrid 高置信也强制 pending_confirm：引用幻觉必须由人工裁决。
    - 其余（纯 llm、低于阈值的 rule/hybrid）→ pending_confirm。
    - cfg 为空或 enabled=false 时全部 pending_confirm（开关回退）。
    """
    if not cfg.get("enabled", True):
        return "pending_confirm", None, None
    if finding.get("evidence_supported") is False:
        return "pending_confirm", None, None
    threshold = float(cfg.get("threshold", 0.85))
    vtype = str(finding.get("violation_type", "rule"))
    confidence = float(finding.get("confidence", 0))
    if vtype in _AUTO_CONFIRM_SOURCES and confidence >= threshold:
        return "confirmed", datetime.now(), _AUTO_CONFIRM_BY
    return "pending_confirm", None, None


def _bigrams(s: str) -> set[str]:
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _citation_for_rule(
    db, rule_id: int | None, text: str
) -> tuple[int | None, int | None]:
    """规则 → (regulation_id, article_id) 结构化溯源。

    优先取影响中心沉淀的规则-法规关联（带 article_id 的最精确）；
    关联只到法规时，按 finding 文本与条款内容的二元组重叠挑最相关条款
    （确定性启发式，不引入 LLM）。无关联的规则返回 (None, None)。
    """
    if not rule_id:
        return None, None
    link = (
        db.query(RuleRegulationLink)
        .filter(RuleRegulationLink.rule_id == rule_id)
        .order_by(RuleRegulationLink.article_id.is_(None), RuleRegulationLink.id)
        .first()
    )
    if link is None or link.regulation_id is None:
        return None, None
    if link.article_id:
        return link.regulation_id, link.article_id
    articles = (
        db.query(Article).filter(Article.regulation_id == link.regulation_id).all()
    )
    if not articles:
        return link.regulation_id, None
    grams = _bigrams(text)
    if not grams:
        return link.regulation_id, articles[0].id
    best = max(articles, key=lambda a: len(grams & _bigrams(a.content[:500])))
    return link.regulation_id, best.id


def _persist_results(db, task_id: int, findings: list[dict], profile: str | None = None) -> None:
    # 幂等：任务重跑/消息重投前清掉旧结果，避免同一任务结果重复追加。
    # 先探测再删：空 DELETE 会在 idx_task_id 索引上加 supremum gap 锁（被删行
    # 不存在时扫到索引末尾），并发任务各自 INSERT 时插入意向锁交叉等待 →
    # 1213 死锁（PR-9 并发实测 4 档稳定复现）；无旧结果时跳过删除即无此锁。
    has_old = (
        db.query(ReviewResult.id).filter(ReviewResult.task_id == task_id).first() is not None
    )
    if has_old:
        db.query(ReviewResult).filter(ReviewResult.task_id == task_id).delete()
    auto_cfg = effective_auto_confirm(
        profile, settings.app_config("workflow").get("auto_confirm", {})
    )
    for item in findings:
        status, confirmed_at, confirmed_by = _auto_confirm(item, auto_cfg)
        # 内置维度（PII/勾稽/篡改）与视觉层的 rule_name 不落库（ReviewResult 无该列），
        # 并入 description 头部成 "[rule_name] 原文"——前端据此渲染维度标签（finding_kind）。
        # 范围：rule 路内置（rule_id=None）+ vlm 路；普通 DSL 命中与 LLM 命中不动（存量兼容）。
        desc = item.get("description") or ""
        rule_name = item.get("rule_name")
        is_builtin_rule = item.get("violation_type") == "rule" and item.get("rule_id") is None
        is_vlm = item.get("violation_type") == "vlm"
        if rule_name and (is_builtin_rule or is_vlm) and not desc.startswith(f"[{rule_name}]"):
            desc = f"[{rule_name}] {desc}"
        reg_id, art_id = _citation_for_rule(
            db,
            item.get("rule_id"),
            desc + (item.get("original_text") or ""),
        )
        db.add(
            ReviewResult(
                task_id=task_id,
                violation_type=item.get("violation_type", "rule")[:16],
                risk_level=item.get("risk_level", "low")[:8],
                original_text=(item.get("original_text") or "")[:2000],
                location_page=item.get("page"),
                location_paragraph=item.get("paragraph"),
                rule_id=item.get("rule_id"),
                regulation_id=reg_id,
                article_id=art_id,
                confidence_score=item.get("confidence", 0),
                description=desc[:1000],
                suggestion=(item.get("suggestion") or "")[:1000],
                status=status,
                confirmed_at=confirmed_at,
                confirmed_by=confirmed_by,
            )
        )
