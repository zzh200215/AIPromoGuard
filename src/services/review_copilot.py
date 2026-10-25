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
from src.models import Article, CopilotMessage, Regulation, ReviewResult, ReviewTask, Rule
from src.services.regulation_service import search_hybrid
from src.services.report_service import refresh_report
from src.utils.errors import AppError, ErrorCode
from src.utils.logger import get_logger

logger = get_logger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
_MAX_VIOLATIONS = 8
_ORIGINAL_MAX = 80
_ARTICLE_MAX = 300
# 多轮上下文携带的历史消息条数（user/assistant 各算一条，10 条 ≈ 5 轮追问）
_HISTORY_TURNS = 10

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


# ---- P3 Copilot 工具化：真 Function Calling 受限循环 ----
# 与深查通道（deep_tools）同护栏纪律：回合/调用双上限，异常回退普通路径。
# 改写建议不进工具箱：它是生成型能力且已有独立端点（/results/{id}/rewrite），
# 嵌套 LLM 调用成本翻倍；问答场景罚单检索的引用价值更高。
_COPILOT_TOOL_ROUNDS = 4
_COPILOT_TOOL_CALLS = 8


def _tool_schema(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description,
                     "parameters": {"type": "object", "properties": props, "required": required}},
    }


def _copilot_tools(db: Session, task: ReviewTask) -> tuple[list, object, set]:
    """四工具 schema + 确定性执行器；valid_ids 收集法规检索命中（引用校验池）。"""
    valid_ids: set = set()

    def execute(name: str, args: str) -> dict | str:
        import json as _json

        try:
            kwargs = _json.loads(args or "{}")
        except _json.JSONDecodeError:
            return {"error": "参数不是合法 JSON"}
        if name == "search_regulations":
            from src.mcp_server import tools as mcp_tools

            out = mcp_tools.search_regulations(
                query=str(kwargs.get("query") or ""), top_k=int(kwargs.get("top_k") or 5)
            )
            for a in out.get("articles") or []:
                if a.get("regulation_id") is not None:
                    valid_ids.add(a.get("regulation_id"))
            return out
        if name == "get_task_results":
            report = refresh_report(db, task)
            return {
                "document": task.document_name,
                "status": task.status,
                "violations": [
                    {
                        "result_id": v.get("result_id"),
                        "risk": v.get("risk_level"),
                        "type": v.get("type"),
                        "original": (v.get("original_text") or "")[:_ORIGINAL_MAX],
                        "human_status": v.get("human_status"),
                    }
                    for v in (report.get("violations") or [])[:_MAX_VIOLATIONS]
                ],
            }
        if name == "get_result_trail":
            rid = kwargs.get("result_id")
            result = (
                db.query(ReviewResult)
                .filter(ReviewResult.id == rid, ReviewResult.task_id == task.id)
                .first()
            )
            if result is None:
                return {"error": f"result_id={rid} 不属于本任务或不存在"}
            return {
                "result_id": result.id,
                "risk_level": result.risk_level,
                "status": result.status,
                "confirmed_by": result.confirmed_by,
                "confidence": float(result.confidence_score or 0),
                "description": (result.description or "")[:200],
                "suggestion": (result.suggestion or "")[:200],
            }
        if name == "search_penalty_cases":
            from src.core.llm.deep_tools import search_penalty_cases

            return search_penalty_cases(
                query=str(kwargs.get("query") or ""), top_k=int(kwargs.get("top_k") or 3)
            )
        return f"未知工具: {name}"

    schemas = [
        _tool_schema(
            "search_regulations",
            "检索法规条款原文（混合检索）。回答需要法规依据、核对条款原文时调用。",
            {
                "query": {"type": "string", "description": "监管主题或违规描述"},
                "top_k": {"type": "integer", "description": "返回条款数，默认 5"},
            },
            ["query"],
        ),
        _tool_schema(
            "get_task_results",
            "获取本任务的结构化违规清单（含 result_id/风险/人工状态）。需要引用"
            "具体第几条违规或核对人工复核状态时调用。",
            {},
            [],
        ),
        _tool_schema(
            "get_result_trail",
            "查询单条违规结论的判定轨迹与当前状态（须先用 get_task_results 拿 result_id）。",
            {"result_id": {"type": "integer", "description": "违规结论 ID"}},
            ["result_id"],
        ),
        _tool_schema(
            "search_penalty_cases",
            "检索真实监管处罚案例（官方罚单）。评估某表述在监管实践中的处罚先例时调用。",
            {
                "query": {"type": "string", "description": "违规情形描述"},
                "top_k": {"type": "integer", "description": "返回案例数，默认 3"},
            },
            ["query"],
        ),
    ]
    return schemas, execute, valid_ids


def _copilot_agent_answer(
    llm, db: Session, task: ReviewTask, question: str, history_rows: list[dict],
    context: str, valid_ids: set,
) -> tuple[str, dict, int]:
    """工具循环直到产出最终回答；预算耗尽回退一次无工具补全（保证有答案）。

    返回（回答文本, 合并 usage, 实际工具调用次数）。
    """
    tools, execute, _ = _copilot_tools(db, task)
    messages = [
        {"role": "system", "content": _ASK_SYSTEM},
        *[{"role": h["role"], "content": h["content"]} for h in history_rows],
        {"role": "user", "content": f"{context}\\n\\n## 用户问题\n{question}"},
    ]
    cur = list(messages)
    call_count = 0
    usages: list[dict] = []
    final: str | None = None
    for _ in range(_COPILOT_TOOL_ROUNDS + 1):
        result = llm.complete(cur, temperature=0.3, tools=tools, tool_choice="auto")
        usages.append(result.usage)
        if not result.tool_calls:
            final = result.content
            break
        call_count += len(result.tool_calls)
        if call_count > _COPILOT_TOOL_CALLS:
            logger.warning("copilot 工具调用超护栏 %s 次，终止循环", _COPILOT_TOOL_CALLS)
            break
        cur.append({
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in result.tool_calls
            ],
        })
        for tc in result.tool_calls:
            try:
                out = execute(tc["name"], tc["arguments"])
            except Exception as exc:  # noqa: BLE001 —— 单工具失败不中断问答
                out = f"调用失败: {exc}"
            cur.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(out, ensure_ascii=False),
            })
    if final is None:
        # 预算耗尽/循环未收敛：无工具补全一次，保证回答
        completion = llm.complete(messages, temperature=0.3)
        usages.append(completion.usage)
        final = completion.content
    from src.core.llm.client import merge_usage

    return final or "", merge_usage(*usages), call_count


def ask_review_question(db: Session, task: ReviewTask, question: str) -> dict:
    """任务审查问答：报告上下文 + 混合检索 → 带法规引用的回答（多轮）。

    会话记忆（第 2 批）：最近 _HISTORY_TURNS 条历史随任务落 copilot_messages，
    每轮携带进上下文——回答可正确解析"上一条说的第 3 条违规"这类指代；
    回答成功后本轮 user/assistant 双双落库，失败不落（保持成对干净数据）。
    """
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
    history_rows = load_copilot_history(db, task.id, limit=_HISTORY_TURNS)
    base_ids = {a.get("regulation_id") for a in articles}
    try:
        content, usage, tools_used = _copilot_agent_answer(
            llm, db, task, question, history_rows, context, base_ids
        )
    except AppError:
        raise
    except Exception as exc:
        logger.warning("审查问答 LLM 调用失败: %s", exc)
        raise AppError(ErrorCode.LLM_CALL_FAILED, http_status=502) from exc

    data = _parse_object(content)
    if not data or not isinstance(data.get("answer"), str):
        result = {
            "answer": (content or "").strip() or "（AI 未返回内容）",
            "refs": [],
            "usage": usage,
            "tools_used": tools_used,
        }
        _persist_turn(db, task.id, question, result)
        return result

    # 引用校验：regulation_id 必须来自本次检索结果，防模型张冠李戴
    valid_ids = base_ids
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
    result = {
        "answer": str(data["answer"])[:4000],
        "refs": refs[:8],
        "usage": usage,
        "tools_used": tools_used,
    }
    _persist_turn(db, task.id, question, result)
    return result


def load_copilot_history(db: Session, task_id: int, limit: int = 50) -> list[dict]:
    """任务的问答历史（时间正序），refs 已从 JSON 反序列化。"""
    rows = (
        db.query(CopilotMessage)
        .filter(CopilotMessage.task_id == task_id)
        .order_by(CopilotMessage.id.desc())
        .limit(limit)
        .all()
    )
    out: list[dict] = []
    for r in reversed(rows):
        refs = None
        if r.refs_json:
            try:
                refs = json.loads(r.refs_json)
            except json.JSONDecodeError:
                refs = None
        out.append(
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "refs": refs or [],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def _persist_turn(db: Session, task_id: int, question: str, result: dict) -> None:
    """回答成功后落 user/assistant 一对（失败调用不落，保持成对干净数据）。"""
    try:
        db.add(CopilotMessage(task_id=task_id, role="user", content=question[:2000]))
        db.add(
            CopilotMessage(
                task_id=task_id,
                role="assistant",
                content=result["answer"][:4000],
                refs_json=json.dumps(result.get("refs") or [], ensure_ascii=False)
                if result.get("refs")
                else None,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 —— 历史落库失败不阻断回答返回
        db.rollback()
        logger.warning("问答历史落库失败（不影响回答）task=%s: %s", task_id, exc)


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
