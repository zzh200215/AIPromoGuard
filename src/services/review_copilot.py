"""审查问答 Copilot 与合规改写（AI 提效层）。

- ask_review_question：以任务报告（违规清单 + 关联法规）为内联上下文，混合检索
  补充法规依据，LLM 生成带引用的回答——合规场景要求答案必须可溯源；
- rewrite_compliant：对单条违规原文生成合规改写文案与逐条修改说明。

设计约束：
- LLM 未配置（get_llm() 返回 None）抛 LLM_CALL_FAILED / 503，由前端显式提示，
  不做静默降级（交互式功能静默失败比报错更伤信任）；
- 模型输出解析失败优雅降级：answer/rewritten 直接采用原始文本，引用/说明置空，
  弱模型下功能仍可用；
- 上下文有界：违规清单截 8 条、条款正文截 300 字，控制单次调用 token 成本。
"""

import json
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from src.core.llm.client import get_llm
from src.core.llm.prompts.registry import get_prompt
from src.core.report.markdown import render_markdown
from src.models import Article, Regulation, ReviewResult, ReviewTask, Rule
from src.services.regulation_service import search_hybrid
from src.services.report_service import refresh_report
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger

logger = get_logger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
_MAX_VIOLATIONS = 8
_ORIGINAL_MAX = 80
_ARTICLE_MAX = 300

_HUMAN_LABEL = {
    "pending_confirm": "待复核",
    "confirmed": "已确认",
    "false_positive": "已剔除误报",
}
_RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}

_ASK = get_prompt("copilot_ask")
_ASK_SYSTEM = _ASK.template

_REWRITE = get_prompt("copilot_rewrite")
_REWRITE_SYSTEM = _REWRITE.template

_SUMMARY = get_prompt("copilot_summary")
_SUMMARY_SYSTEM = _SUMMARY.template

_ADVICE = get_prompt("copilot_advice")
_ADVICE_SYSTEM = _ADVICE.template


def _parse_object(content: str) -> dict | None:
    """宽容解析模型输出中的首个 JSON 对象（剥代码围栏）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _require_llm():
    llm = get_llm()
    if llm is None:
        raise AppError(ErrorCode.LLM_CALL_FAILED, http_status=503)
    return llm


def _violations_context(db: Session, task: ReviewTask) -> str:
    report = refresh_report(db, task)
    lines = []
    for v in (report.get("violations") or [])[:_MAX_VIOLATIONS]:
        risk = _RISK_LABEL.get(v.get("risk_level") or "", "中")
        human = _HUMAN_LABEL.get(v.get("human_status") or "", "—")
        original = (v.get("original_text") or "")[:_ORIGINAL_MAX]
        vtype = v.get("type") or "—"
        rule = v.get("rule_name") or "—"
        lines.append(f"- [{risk}风险] {original}（类型: {vtype}；规则: {rule}；人工状态: {human}）")
    regulations = [
        f"- 《{r.get('regulation_name')}》{r.get('regulation_no') or ''}"
        for r in (report.get("regulations") or [])[:6]
    ]
    parts = ["违规清单：", *lines] if lines else ["违规清单：（无违规记录）"]
    if regulations:
        parts += ["报告关联法规：", *regulations]
    return "\n".join(parts)


def ask_review_question(db: Session, task: ReviewTask, question: str) -> dict:
    """任务审查问答：报告上下文 + 混合检索 → 带法规引用的回答。"""
    llm = _require_llm()

    domain = [task.domain] if getattr(task, "domain", None) else None
    try:
        articles = search_hybrid(db, question, domain, top_k=5)
    except Exception as exc:
        logger.warning("问答法规检索失败，降级为无检索上下文: %s", exc)
        articles = []

    article_lines = []
    for a in articles:
        reg_id = a.get("regulation_id")
        name = a.get("regulation_name")
        head = f"【{name} {a.get('article_no') or ''}】(regulation_id={reg_id}) "
        article_lines.append(head + (a.get("content") or "")[:_ARTICLE_MAX])
    context = (
        f"## 审查任务\n文档：{task.document_name}"
        f"（领域：{task.domain or '—'}，状态：{task.status}）\n\n"
        f"## {_violations_context(db, task)}\n\n"
        f"## 检索到的法规条款\n" + ("\n".join(article_lines) or "（无）")
    )
    messages = [
        {"role": "system", "content": _ASK_SYSTEM},
        {"role": "user", "content": f"{context}\n\n## 用户问题\n{question}"},
    ]
    try:
        completion = llm.complete(messages, temperature=0.3)
    except Exception as exc:
        logger.warning("审查问答 LLM 调用失败: %s", exc)
        raise AppError(ErrorCode.LLM_CALL_FAILED, http_status=502) from exc

    data = _parse_object(completion.content)
    if not data or not isinstance(data.get("answer"), str):
        return {
            "answer": (completion.content or "").strip() or "（AI 未返回内容）",
            "refs": [],
            "usage": completion.usage,
        }

    # 引用校验：regulation_id 必须来自本次检索结果，防模型张冠李戴
    valid_ids = {a.get("regulation_id") for a in articles}
    refs = []
    for ref in data.get("refs") or []:
        if not isinstance(ref, dict):
            continue
        try:
            rid = int(ref.get("regulation_id")) if ref.get("regulation_id") is not None else None
        except (TypeError, ValueError):
            rid = None
        refs.append(
            {
                "regulation_id": rid if rid in valid_ids else None,
                "name": str(ref.get("name") or "")[:120],
                "article_no": str(ref.get("article_no") or "")[:40] or None,
                "quote": str(ref.get("quote") or "")[:200] or None,
            }
        )
    return {
        "answer": str(data["answer"])[:4000],
        "refs": refs[:8],
        "usage": completion.usage,
    }


def rewrite_compliant(db: Session, result: ReviewResult) -> dict:
    """单条违规的合规改写：原文 + 问题说明 + 法规要点 → 改写文案与改动说明。"""
    llm = _require_llm()

    rule_name = None
    if result.rule_id:
        rule = db.get(Rule, result.rule_id)
        rule_name = rule.rule_name if rule else None
    reg_name = reg_no = article_excerpt = None
    if result.regulation_id:
        reg = db.get(Regulation, result.regulation_id)
        if reg:
            reg_name, reg_no = reg.regulation_name, reg.regulation_no
    if result.article_id:
        article = db.get(Article, result.article_id)
        article_excerpt = article.content[:200] if article else None

    context = (
        f"原文：{result.original_text}\n"
        f"违规类型 / 风险等级：{result.violation_type} / {result.risk_level}\n"
        f"问题说明：{(result.description or '')[:200] or '—'}\n"
        f"系统建议：{(result.suggestion or '')[:200] or '—'}\n"
        f"命中规则：{rule_name or '—'}\n"
        f"关联法规：{reg_name or '—'}{(' ' + reg_no) if reg_no else ''}\n"
        f"条款要点：{article_excerpt or '—'}"
    )
    messages = [
        {"role": "system", "content": _REWRITE_SYSTEM},
        {"role": "user", "content": context},
    ]
    try:
        completion = llm.complete(messages, temperature=0.4)
    except Exception as exc:
        logger.warning("合规改写 LLM 调用失败: %s", exc)
        raise AppError(ErrorCode.LLM_CALL_FAILED, http_status=502) from exc

    data = _parse_object(completion.content)
    if not data or not isinstance(data.get("rewritten"), str):
        return {
            "rewritten": (completion.content or "").strip(),
            "changes": [],
            "usage": completion.usage,
        }
    raw_changes = data.get("changes") or []
    changes = [str(c)[:120] for c in raw_changes if isinstance(c, str) and c.strip()]
    return {
        "rewritten": str(data["rewritten"])[:2000],
        "changes": changes[:6],
        "usage": completion.usage,
    }


def summarize_report(db: Session, task: ReviewTask, force: bool = False) -> dict:
    """报告 AI 风险综述：生成后随报告落盘（json + md），进导出留档链路。

    - 综述存在且未过期 → 直接返回已有内容，不重复调用 LLM（成本护栏）；
    - 人工结论/签发变化会触发报告重算并把综述标记 stale（见 report_service），
      此时本函数自动重新生成；
    - force=True 供前端「重新生成」按钮强制刷新。
    """
    llm = _require_llm()
    report = refresh_report(db, task)
    existing = report.get("ai_summary")
    fresh = isinstance(existing, dict) and existing.get("text") and not existing.get("stale")
    if not force and fresh:
        return existing

    context = (
        f"## 审查任务\n文档：{task.document_name}"
        f"（领域：{task.domain or '—'}，状态：{task.status}）\n\n"
        f"## {_violations_context(db, task)}"
    )
    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": context},
    ]
    try:
        completion = llm.complete(messages, temperature=0.3)
    except Exception as exc:
        logger.warning("风险综述 LLM 调用失败: %s", exc)
        raise AppError(ErrorCode.LLM_CALL_FAILED, http_status=502) from exc

    data = _parse_object(completion.content)
    summary = data.get("summary") if data else None
    if not isinstance(summary, str) or not summary.strip():
        summary = (completion.content or "").strip() or "（AI 未返回内容）"

    summary_obj = {
        "text": summary[:800],
        "model": completion.model,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stale": False,
    }

    # 落盘回写：报告 json + md 同步更新，与人工结论刷新共用同一条留档链路
    if task.report_path:
        path = Path(task.report_path)
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["ai_summary"] = summary_obj
            path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
            path.with_suffix(".md").write_text(render_markdown(stored), encoding="utf-8")
    return summary_obj


def verdict_advice(db: Session, result: ReviewResult) -> dict:
    """判定辅助：AI 预判该检出成立（confirmed）还是误报（false_positive）。

    仅作人工判定的参考预填，不写回 results 表，最终结论仍以人工提交为准。
    """
    llm = _require_llm()

    rule_name = None
    if result.rule_id:
        rule = db.get(Rule, result.rule_id)
        rule_name = rule.rule_name if rule else None
    reg_name = article_excerpt = None
    if result.regulation_id:
        reg = db.get(Regulation, result.regulation_id)
        reg_name = reg.regulation_name if reg else None
    if result.article_id:
        article = db.get(Article, result.article_id)
        article_excerpt = article.content[:200] if article else None

    context = (
        f"原文：{result.original_text}\n"
        f"违规类型 / 风险等级：{result.violation_type} / {result.risk_level}\n"
        f"问题说明：{(result.description or '')[:200] or '—'}\n"
        f"命中规则：{rule_name or '—'}\n"
        f"关联法规：{reg_name or '—'}\n"
        f"条款要点：{article_excerpt or '—'}"
    )
    messages = [
        {"role": "system", "content": _ADVICE_SYSTEM},
        {"role": "user", "content": context},
    ]
    try:
        completion = llm.complete(messages, temperature=0.2)
    except Exception as exc:
        logger.warning("判定辅助 LLM 调用失败: %s", exc)
        raise AppError(ErrorCode.LLM_CALL_FAILED, http_status=502) from exc

    data = _parse_object(completion.content)
    if not data or data.get("suggested_verdict") not in ("confirmed", "false_positive"):
        return {
            "suggested_verdict": "confirmed",
            "confidence": 0.5,
            "reasons": ["AI 输出无法解析，请人工判断"],
            "usage": completion.usage,
        }
    try:
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    raw_reasons = data.get("reasons") or []
    reasons = [str(r)[:150] for r in raw_reasons if isinstance(r, str) and r.strip()]
    return {
        "suggested_verdict": str(data["suggested_verdict"]),
        "confidence": round(confidence, 2),
        "reasons": reasons[:4] or ["（未给出理由）"],
        "usage": completion.usage,
    }
