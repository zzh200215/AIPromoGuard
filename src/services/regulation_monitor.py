"""监管动态追踪服务：抓取监管机构发布源 → 去重 → LLM 打标 → 待确认 → 人工确认入库。

- fetch_sources：逐源抓列表页解析出法规条目，与 regulations / regulation_updates 双重去重，
  新条目入库 status=pending，随后批量 LLM 打标（领域/类型/摘要，未配 key 或失败降级留空）。
- confirm_update：确认入库，创建 Regulation（无条款，条款走法规库人工补充后向量化）。
- ignore_update / create_manual：忽略 / 半自动兜底录入（源爬不动时人工录入）。
"""

import json
import re
from dataclasses import dataclass
from datetime import date

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.llm.client import get_llm
from src.core.llm.prompts.monitor import build_tag_messages, parse_tag_response
from src.models import Regulation, RegulationUpdate
from src.services.regulation_service import search_hybrid
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SOURCE_LABELS = {
    "nfra": "国家金融监督管理总局",
    "csrc": "中国证监会",
    "pbc": "中国人民银行",
}
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_DOC_NO_RE = re.compile(r"[〔\[]\s*\d{4}\s*[〕\]]\s*第?\s*\d+\s*号")


@dataclass
class RegulationItem:
    source: str
    title: str
    url: str
    doc_no: str | None = None
    publish_date: str | None = None  # ISO 日期字符串


def _monitor_cfg() -> dict:
    return settings.app_config("regulation_monitor")


def _fetch(url: str, timeout: int) -> bytes:
    resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers=_HEADERS)
    resp.raise_for_status()
    return resp.content


def _extract_doc_no(title: str) -> str | None:
    m = _DOC_NO_RE.search(title)
    return m.group(0) if m else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_pbc(html: bytes) -> list[RegulationItem]:
    """中国人民银行条法司·政策法规列表页（静态 HTML，已探测确认结构）。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[RegulationItem] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        title = re.sub(r"\s+", " ", a.get_text()).strip()
        if not title:
            continue
        if not href.startswith("/tiaofasi/144941/144957/") or not href.endswith("/index.html"):
            continue
        # 栏目导航不是文件（2026-10-19 修复：#62 曾把栏目名"部门规章"当文档入库）：
        # 排除列表页自指链接与纯栏目名
        if href.rstrip("/") in _PBC_LISTING_HREFS or title in _PBC_NAV_LABELS:
            continue
        items.append(
            RegulationItem(
                source="pbc",
                title=title[:255],
                url="http://www.pbc.gov.cn" + href,
                doc_no=_extract_doc_no(title),
            )
        )
    return items


def _parse_nfra(html: bytes) -> list[RegulationItem]:
    """国家金融监督管理总局·政策法规栏目（JSON 接口，itemUUids=910303 含子栏目）。

    接口: /cbircweb/DocInfo/SelectDocByItemUUIdsAndChild?itemUUids=910303&pageIndex=1&pageSize=50
    返回 data[]: {docTitle, publishDate, docId, itemId}。
    """
    try:
        data = json.loads(html.decode("utf-8")).get("data") or []
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("nfra 响应非 JSON，跳过")
        return []
    items: list[RegulationItem] = []
    for doc in data:
        if not isinstance(doc, dict):
            continue
        title = re.sub(r"\s+", " ", str(doc.get("docTitle") or "")).strip()
        if not title:
            continue
        doc_id = doc.get("docId")
        item_id = doc.get("itemId")
        url = (
            f"https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId={doc_id}&itemId={item_id}"
            if doc_id and item_id
            else ""
        )
        publish = str(doc.get("publishDate") or "")[:10]
        items.append(
            RegulationItem(
                source="nfra",
                title=title[:255],
                url=url,
                doc_no=_extract_doc_no(title),
                publish_date=publish or None,
            )
        )
    return items


def _csrc_reg_name(title: str) -> str:
    """从规章库标题提取纯法规名（首个"（YYYY年"之前，兼容半角/全角括号与 19xx/20xx 年份）。"""
    m = re.match(r"^(.+?)[（(]\s*\d{4}年", title)
    return m.group(1).strip() if m else title


def _csrc_doc_no(title: str) -> str | None:
    m = re.search(r"证监会令第(\d+)号", title)
    return f"证监会令第{m.group(1)}号" if m else None


def _csrc_date(title: str) -> str | None:
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _parse_csrc(html: bytes) -> list[RegulationItem]:
    """中国证监会·规章库列表页（静态 HTML，标题含公布日期与证监会令文号）。

    注意：规章库收录现行有效规章（更新略滞后于最新发布），作为"存量补全"源；
    新发布法规在列入规章库前需手动录入兜底。
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[RegulationItem] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        title = re.sub(r"\s+", " ", a.get_text()).strip()
        if not href.startswith("/csrc/c106256/") or not href.endswith("/content.shtml"):
            continue
        if "年度报告" in title:
            continue
        items.append(
            RegulationItem(
                source="csrc",
                title=_csrc_reg_name(title)[:255],
                url="http://www.csrc.gov.cn" + href,
                doc_no=_csrc_doc_no(title),
                publish_date=_csrc_date(title),
            )
        )
    return items


# pbc 列表页的栏目导航（不是文件）：命中即跳过，防栏目名被当标题入库
_PBC_NAV_LABELS = {"部门规章", "行政法规", "规范性文件", "规章", "政策法规", "法律法规", "更多"}
_PBC_LISTING_HREFS = {"/tiaofasi/144941/144957/index.html"}

_PARSERS = {"pbc": _parse_pbc, "nfra": _parse_nfra, "csrc": _parse_csrc}


def _in_regulations(db: Session, title: str) -> bool:
    return db.query(Regulation.id).filter(Regulation.regulation_name == title).first() is not None


def _exists_update(db: Session, source: str, title: str) -> bool:
    return (
        db.query(RegulationUpdate.id)
        .filter(RegulationUpdate.source == source, RegulationUpdate.title == title)
        .first()
        is not None
    )


def _insert_pending(db: Session, item: RegulationItem) -> None:
    db.add(
        RegulationUpdate(
            source=item.source,
            title=item.title,
            doc_no=item.doc_no,
            publish_date=_parse_date(item.publish_date),
            url=item.url,
            status="pending",
            match_type="fetch",
        )
    )


def _llm_tag_titles(db: Session, items: list[RegulationItem]) -> None:
    llm = get_llm()
    if llm is None:
        logger.info("未配置 DASHSCOPE_API_KEY，跳过监管动态打标")
        return
    batch_size = int(_monitor_cfg().get("llm_batch_size", 20))
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        payload = [
            {
                "title": it.title,
                "doc_no": it.doc_no,
                "publish_date": it.publish_date,
            }
            for it in batch
        ]
        try:
            content = llm.chat(build_tag_messages(payload))
        except Exception as exc:  # noqa: BLE001 — 打标失败不阻塞抓取，但须显性可诊断
            logger.error("LLM 打标调用失败，跳过本批 %s 条：%s", len(batch), exc)
            continue
        tags = parse_tag_response(content)
        if not tags:
            logger.warning(
                "LLM 打标输出解析为空（响应 %s 字符），跳过本批 %s 条",
                len(content or ""),
                len(batch),
            )
        for idx, item in enumerate(batch):
            tag = tags.get(idx)
            if not tag or not tag.get("is_finance"):
                continue
            upd = (
                db.query(RegulationUpdate)
                .filter(
                    RegulationUpdate.source == item.source,
                    RegulationUpdate.title == item.title,
                )
                .first()
            )
            if upd is None:
                continue
            upd.domain = tag.get("domain") or None
            upd.doc_type = tag.get("doc_type") or None
            upd.llm_summary = tag.get("summary") or None


def fetch_sources(db: Session, dry_run: bool = False) -> dict:
    """抓取所有启用的监管源，返回每源统计与错误列表。dry_run 只统计不落库不调 LLM。"""
    cfg = _monitor_cfg()
    if not cfg.get("enabled", True):
        return {"sources": {}, "errors": ["regulation_monitor disabled"]}
    timeout = int(cfg.get("request_timeout", 20))
    max_items = int(cfg.get("max_items_per_source", 50))
    result: dict[str, dict] = {}
    errors: list[str] = []

    for src in cfg.get("sources", []):
        name = src.get("name")
        if not name or not src.get("enabled", True):
            continue
        stats = {"fetched": 0, "new": 0, "duplicate": 0, "in_db": 0, "error": None}
        new_items: list[RegulationItem] = []
        seen_titles: set[tuple[str, str]] = set()
        try:
            html = _fetch(src["list_url"], timeout)
            items = _PARSERS[name](html)
            stats["fetched"] = len(items)
            for item in items[:max_items]:
                key = (item.source, item.title)
                if key in seen_titles:
                    stats["duplicate"] += 1
                    continue
                if _in_regulations(db, item.title):
                    stats["in_db"] += 1
                    continue
                if _exists_update(db, item.source, item.title):
                    stats["duplicate"] += 1
                    continue
                stats["new"] += 1
                seen_titles.add(key)
                if not dry_run:
                    _insert_pending(db, item)
                    new_items.append(item)
            if new_items:
                db.commit()
                if not dry_run:
                    _llm_tag_titles(db, new_items)
                    db.commit()
        except Exception as exc:
            logger.warning("抓取源 %s 失败: %s", name, exc)
            stats["error"] = str(exc)[:200]
            errors.append(f"{name}: {exc}")
        result[name] = stats
    return {"sources": result, "errors": errors}


def _match_regulations(db: Session, title: str, top_k: int = 5) -> list[dict]:
    """用法规标题做混合检索，找库内可能相关的法规条款（去重到法规级）。"""
    try:
        hits = search_hybrid(db, title, None, top_k)
    except Exception:
        logger.warning("法规匹配检索失败，matched_regulations 留空")
        return []
    seen: dict[int, dict] = {}
    for hit in hits:
        rid = hit["regulation_id"]
        if rid not in seen:
            seen[rid] = {
                "regulation_id": rid,
                "regulation_name": hit["regulation_name"],
                "article_no": hit.get("article_no") or "",
                "status": hit.get("status", "effective"),
            }
    return list(seen.values())[:top_k]


def confirm_update(
    db: Session,
    update_id: int,
    domain_override: str | None = None,
    effective_date: date | None = None,
) -> Regulation:
    """确认入库：创建 Regulation（无条款），记录 matched_regulations 与状态流转。"""
    upd = db.get(RegulationUpdate, update_id)
    if upd is None:
        raise AppError(ErrorCode.REGULATION_UPDATE_NOT_FOUND)
    if upd.status != "pending":
        raise AppError(ErrorCode.UPDATE_NOT_PENDING, f"当前状态: {upd.status}")

    existing = db.query(Regulation).filter(Regulation.regulation_name == upd.title).first()
    if existing is not None:
        upd.status = "imported"
        upd.match_type = "confirm"
        db.commit()
        return existing

    reg = Regulation(
        domain=domain_override or upd.domain or "other",
        regulation_name=upd.title,
        regulation_no=upd.doc_no,
        issuer=_SOURCE_LABELS.get(upd.source),
        publish_date=upd.publish_date,
        effective_date=effective_date,
        status="effective",
    )
    db.add(reg)
    upd.matched_regulations = _match_regulations(db, upd.title)
    upd.status = "imported"
    upd.match_type = "confirm"
    db.commit()
    db.refresh(reg)
    return reg


def ignore_update(db: Session, update_id: int) -> None:
    upd = db.get(RegulationUpdate, update_id)
    if upd is None:
        raise AppError(ErrorCode.REGULATION_UPDATE_NOT_FOUND)
    if upd.status != "pending":
        raise AppError(ErrorCode.UPDATE_NOT_PENDING, f"当前状态: {upd.status}")
    upd.status = "ignored"
    db.commit()


def create_manual(
    db: Session,
    source: str,
    title: str,
    url: str | None = None,
    doc_no: str | None = None,
    publish_date: str | None = None,
) -> RegulationUpdate:
    """半自动兜底：管理员手动录入一条待确认法规。"""
    if source not in _SOURCE_LABELS:
        raise AppError(ErrorCode.PARAM_ERROR, f"不支持的来源: {source}")
    if _in_regulations(db, title):
        raise AppError(ErrorCode.UPDATE_NOT_PENDING, "该法规已存在法规库中")
    upd = RegulationUpdate(
        source=source,
        title=title,
        url=url,
        doc_no=doc_no,
        publish_date=_parse_date(publish_date),
        status="pending",
        match_type="manual",
    )
    db.add(upd)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(ErrorCode.UPDATE_NOT_PENDING, "该条目已存在待确认列表中") from None
    db.refresh(upd)
    return upd
