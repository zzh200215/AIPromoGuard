"""发布后内容巡检（R3-1，对标 Red Marker Web Reports）.

已批准材料上线后可能被擅自改动（P 图改收益率、删风险提示、换活动条款）
——发布前审查管不住"发布后失控窗口"。本服务定期抓取台账登记的发布渠道
（官网直链等**已授权的自有渠道**，不做第三方爬取），与批准版内容指纹做
相似度比对，三档判定：

- similarity >= 0.98  ok       未变更
- 0.90 ~ 0.98         drift    轻微漂移（动态内容/排版噪声），观察不告警
- < 0.90              changed  实质变更 → 自动创建复审任务（复用审查管线）
- 抓取 404/下线        gone     发布状态异常 → 驾驶舱告警
- 抓取异常             error    网络等暂时性失败，不改状态只记日志

设计约束：
- **相似度比对而非精确 hash**（方案 v2.1 修正）：网页渲染文本与批准版
  解析文本天然不一致（空白/顺序/动态时间戳），精确 hash 会天天误报；
- 规范化（去空白/归一标点/去实体）+ difflib 序列相似度，与 diff_service
  同一技术栈；
- changed 触发的复审任务 created_by=None（系统发起）；任务 document 为
  抓取内容存档 txt（upload/patrol/），人工可在任务详情看到线上现文与
  批准版 diff（复用 base_document_path 对比审查）；
- fingerprint 基线：材料关联 document 的规范化文本（首次巡检时若指纹为
  空则从批准版文档建立基线并回写台账）。
"""

from __future__ import annotations

import difflib
import html as html_mod
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from src.models import ProductMaterial, ReviewTask
from src.services.document_service import document_service
from src.services.tamper_check import NUM_RE, norm_number
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_OK_THRESHOLD = 0.98
_DRIFT_THRESHOLD = 0.90

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S
)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_BASIC = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"'}
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_KEEP = re.compile(r"[^\w\u4e00-\u9fff%.]+")


class PatrolError(Exception):
    """抓取失败（含 404 下线与网络错误），带 status 属性供分类。"""

    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status = status  # gone / error
        self.detail = detail


def fetch_published(url: str, timeout: float = 15.0) -> str:
    """抓取已发布页面并转纯文本。非 200 视为 gone（下线/404）。"""
    import httpx

    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "CompliancePatrol/1.0"},
        )
    except Exception as exc:  # noqa: BLE001 — 网络/DNS/超时统一归 error
        raise PatrolError("error", f"抓取失败: {exc}") from exc
    if resp.status_code == 404 or resp.status_code == 410:
        raise PatrolError("gone", f"页面已下线（HTTP {resp.status_code}）")
    if resp.status_code != 200:
        raise PatrolError("error", f"非预期状态码 HTTP {resp.status_code}")
    return html_to_text(resp.text)


def html_to_text(html: str) -> str:
    """HTML → 纯文本：去 script/style、剥标签、解基础实体、压缩空白。"""
    text = _SCRIPT_STYLE_RE.sub(" ", html or "")
    text = _TAG_RE.sub("\n", text)
    for ent, ch in _ENTITY_BASIC.items():
        text = text.replace(ent, ch)
    text = html_mod.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def normalize_for_compare(text: str) -> str:
    """规范化：去空白、保留中英文数字与 %.，压成可比对的紧凑串。"""
    s = (text or "").translate(str.maketrans("０１２３４５６７８９．％", "0123456789.%"))
    s = _WHITESPACE_RE.sub("", s)
    return _PUNCT_KEEP.sub("", s)


def similarity(baseline: str, current: str) -> float:
    a, b = normalize_for_compare(baseline), normalize_for_compare(current)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def containment(baseline: str, current: str) -> float:
    """基线内容在线上文本中的保留率（0~1）。

    合规语义下用 containment 而非双向 ratio：巡检回答的问题是"批准的
    内容还在不在"，不是"两边像不像"——网页导航/页脚/动态时间戳属于
    无关噪声，双向 ratio 对短基线极其敏感（会大面积误报）。
    实现：归一化后 SequenceMatcher 匹配块总长 / 基线长度。
    """
    a, b = normalize_for_compare(baseline), normalize_for_compare(current)
    if not a:
        return 1.0
    if not b:
        return 0.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched / len(a)


@dataclass
class PatrolOutcome:
    material_id: int
    name: str
    status: str  # ok/drift/changed/gone/error/skip
    similarity: float | None = None
    detail: str = ""
    review_task_id: int | None = None


def build_fingerprint_from_document(material: ProductMaterial) -> str | None:
    """从批准版文档建立规范化文本基线（材料 document_id → 上传文件解析）。"""
    if not material.document_id:
        return None
    matches = list(
        Path(settings.upload_dir).glob(f"**/{material.document_id}.*")
    )
    if not matches:
        return None
    try:
        # mask=False：巡检比对对象是"线上抓取的原文"，基线若用脱敏文本会
        # 因口径不一致产生数字缺失假阳性（→ 永远判 changed）。10-07 修复。
        parsed = document_service.parse(matches[0], mask=False)
    except Exception as exc:  # noqa: BLE001 — 解析失败返回 None，巡检报 skip
        logger.warning("批准版文档解析失败 %s: %s", material.document_id, exc)
        return None
    return normalize_for_compare(parsed.text)


def _create_review_task(
    db: Session, material: ProductMaterial, current_text: str
) -> int | None:
    """变更触发复审：抓取内容存档 txt → 创建任务（created_by=None 系统发起）
    → 挂批准版文档为对比基线（任务详情可见 diff）。"""
    try:
        patrol_dir = Path(settings.upload_dir) / "patrol"
        patrol_dir.mkdir(parents=True, exist_ok=True)
        doc_id = f"doc_patrol_{material.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        dest = patrol_dir / f"{doc_id}.txt"
        dest.write_text(current_text, encoding="utf-8")

        base_matches = list(
            Path(settings.upload_dir).glob(f"**/{material.document_id}.*")
        ) if material.document_id else []
        task = ReviewTask(
            task_name=f"[巡检] {material.name} 线上内容变更复审",
            document_name=dest.name,
            document_path=str(dest),
            document_type="txt",
            domain=None,
            status="pending",
            created_by=None,
            base_document_name=base_matches[0].name if base_matches else None,
            base_document_path=str(base_matches[0]) if base_matches else None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        # 复用审查管线（线程池启动，与 API 创建任务同路径）
        from src.services.review_service import start_review

        start_review(task.id)
        return task.id
    except Exception:  # noqa: BLE001 — 复审任务失败不影响巡检状态落库
        logger.exception("巡检复审任务创建失败: material=%s", material.id)
        db.rollback()
        return None


def _missing_key_numbers(baseline: str, current: str) -> list[str]:
    """基线中的数字在线上文本中消失的清单（数字被删/被改的高危信号）。"""
    base_nums = {norm_number(n) for n in NUM_RE.findall(normalize_for_compare(baseline))}
    curr_nums = {norm_number(n) for n in NUM_RE.findall(normalize_for_compare(current))}
    base_nums.discard("")
    curr_nums.discard("")
    return sorted(base_nums - curr_nums)


def patrol_one(
    db: Session, material: ProductMaterial, fetched_text: str | None
) -> PatrolOutcome:
    """单材料巡检（fetched_text 为 None 时表示抓取失败，状态已在异常里）。"""
    baseline = material.content_fingerprint or build_fingerprint_from_document(material)
    if baseline is None:
        material.patrol_status = "error"
        material.patrol_checked_at = datetime.now()
        return PatrolOutcome(
            material.id, material.name, "error", detail="无法建立巡检基线（缺批准版文档）"
        )
    if material.content_fingerprint is None:
        material.content_fingerprint = baseline  # 首巡建基线回写

    sim = containment(baseline, fetched_text or "")
    # 双层判定（R2-3 互校模式的复用）：字符级 containment 对"只改关键数字"
    # 不敏感（3.85→9.85 仅差 1 字符、相似度仍达 0.98）——因此数字缺失检查
    # 必须先于相似度判定。原实现把 missing 放在 sim < OK 分支内，与该判定
    # 意图不符："只改数字"的篡改会被判 ok 漏过（10-07 DB 用例跑通时暴露）。
    missing = _missing_key_numbers(baseline, fetched_text or "")
    if missing:
        status = "changed"
        task_id = _create_review_task(db, material, fetched_text or "")
    elif sim >= _OK_THRESHOLD:
        status = "ok"
        task_id = None
    elif sim < _DRIFT_THRESHOLD:
        status = "changed"
        task_id = _create_review_task(db, material, fetched_text or "")
    else:
        status = "drift"
        task_id = None
    material.patrol_status = status
    material.patrol_checked_at = datetime.now()
    # 字段名是 review_task_id（dataclass 定义），曾误写 task_id= 导致正常比对
    # 路径（ok/drift/changed）全部 TypeError——由 10-07 的 DB 用例首次跑通时暴露
    return PatrolOutcome(
        material.id, material.name, status, round(sim, 4), review_task_id=task_id
    )


def patrol_materials(
    db: Session, material_ids: list[int] | None = None, fetcher=None
) -> dict:
    """批量巡检台账中登记了 publish_url 的材料。

    fetcher 可注入（测试用）；默认 fetch_published。dry_run 语义：
    本函数不提供 dry_run——巡检状态落库幂等，重复执行安全。
    """
    fetch = fetcher or fetch_published
    query = db.query(ProductMaterial).filter(
        ProductMaterial.publish_url.isnot(None),
        ProductMaterial.status == "active",
    )
    if material_ids:
        query = query.filter(ProductMaterial.id.in_(material_ids))
    materials = query.all()

    outcomes: list[dict] = []
    counts = {"ok": 0, "drift": 0, "changed": 0, "gone": 0, "error": 0, "skip": 0}
    for m in materials:
        try:
            text = fetch(m.publish_url)
        except PatrolError as exc:
            m.patrol_status = exc.status
            m.patrol_checked_at = datetime.now()
            counts[exc.status] += 1
            outcomes.append(
                {
                    "material_id": m.id, "name": m.name, "status": exc.status,
                    "similarity": None, "detail": exc.detail, "review_task_id": None,
                }
            )
            continue
        outcome = patrol_one(db, m, text)
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        outcomes.append(
            {
                "material_id": outcome.material_id,
                "name": outcome.name,
                "status": outcome.status,
                "similarity": outcome.similarity,
                "detail": outcome.detail,
                "review_task_id": outcome.review_task_id,
            }
        )
    db.commit()
    logger.info("发布后巡检完成：%s", counts)
    return {"checked": len(materials), "counts": counts, "outcomes": outcomes}
