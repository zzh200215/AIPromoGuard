"""LLMScanner 节点：调用 QWEN 对全部文档块做并发语义审查。

- 未配置 API Key 或单块调用失败时优雅降级（PRD：LLM 超时仅输出规则引擎结果）；
- asyncio.Semaphore 并发审查全部文档块（workflow.llm_concurrency，默认 4），
  workflow.llm_max_chunks 为显式成本护栏（默认 0 = 不截断；早期版本静默
  只审前 5 块的问题已移除，长文档不再漏审）；
- 结构化输出（json mode + 自纠错重试）+ Pydantic schema 校验；
- 输出经幻觉抑制过滤（PRD §3.2.3）：无法规依据的判定丢弃、置信度低于阈值丢弃；
- token 用量累计到 state.llm_usage（随报告落盘，成本可观测）。
"""

import asyncio

from pydantic import BaseModel, ConfigDict, field_validator

from src.core.agents.state import ReviewState
from src.core.llm.client import extract_findings, get_llm, merge_usage
from src.core.llm.prompts.review import build_review_messages
from src.services.precedent_memory import recall_precedents
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_CONCURRENCY = 4
_VALID_TYPES = {"禁止性", "限制性", "披露性"}
_VALID_SEVERITY = {"high", "medium", "low"}


class LLMFinding(BaseModel):
    """单条 LLM 判定的结构化输出 schema（Pydantic 校验层）。

    非法枚举/置信度自动归位默认值；issue/original_text/regulation 三个
    关键字段的缺失由 _validate_finding 前置丢弃（幻觉抑制，不宽松归位）。
    """

    model_config = ConfigDict(extra="ignore")

    type: str = "披露性"
    issue: str
    original_text: str
    regulation: str
    reason: str = ""
    suggestion: str = ""
    severity: str = "medium"
    confidence: float = 0.5

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        return v if v in _VALID_TYPES else "披露性"

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, v: str) -> str:
        return v if v in _VALID_SEVERITY else "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


def _validate_finding(item, block: dict) -> dict | None:
    """单条 LLM 判定的校验与过滤，不合规返回 None。"""
    if not isinstance(item, dict):
        return None
    # 幻觉抑制：违规描述/原文/法规依据任一缺失，判定无效丢弃
    if (
        not str(item.get("issue") or "").strip()
        or not str(item.get("original_text") or "").strip()
        or not str(item.get("regulation") or "").strip()
    ):
        return None
    try:
        parsed = LLMFinding.model_validate(item)
    except Exception:
        return None

    threshold = settings.app_config("workflow").get("llm_confidence_threshold", 0.5)
    if parsed.confidence < threshold:
        return None

    return {
        "type": parsed.type,
        "issue": parsed.issue,
        "original_text": parsed.original_text,
        "regulation": parsed.regulation,
        "reason": parsed.reason,
        "suggestion": parsed.suggestion,
        "severity": parsed.severity,
        "confidence": parsed.confidence,
        "paragraph": block.get("paragraph"),
        "page": block.get("page"),
    }


def _parse_raw(content: str) -> list:
    """兼容入口：解析模型输出为列表，解析失败返回空列表。"""
    return extract_findings(content) or []


async def _scan_block(
    llm, block: dict, articles: list[dict], domain: str | None = None,
    precedents: list[dict] | None = None, deep_tools: tuple | None = None,
) -> tuple[list[dict], int, dict]:
    """审查单个文档块：结构化调用 + 逐条校验，返回 (findings, 丢弃数, usage, tool_articles)。

    enable_tool_calls=True 时启用真 function calling：LLM 主动调 search_regulations
    查证法规再判定（configs/app.yaml llm.tool_calling 控制护栏与开关），domain 透传给检索。
    tool_articles 为工具查证检索到的条款（并入证据核验集）。
    precedents 为召回的同类判定先例（None/空 = 不注入，prompt 与历史版本一致）。
    _FakeLLM.achat_json 签名 (messages, temperature=None) 兼容新增关键字参数。
    """
    messages = build_review_messages(
        block.get("text", ""), articles, precedents=precedents
    )
    tc_cfg = (settings.app_config("llm") or {}).get("tool_calling") or {}
    use_tools = bool(tc_cfg.get("enabled", True))
    # 深查通道（第 4 批）：注入 4 工具箱 + 升格预算（受限多工具 ReAct）；
    # deep_tools 为 (schemas, execute) 元组，由 llm_scan 按通道一次性构建
    kwargs = {}
    if deep_tools is not None:
        from src.core.llm.deep_tools import deep_tool_budget

        kwargs = {
            "tools": deep_tools[0],
            "execute_tool": deep_tools[1],
            "tool_budget": deep_tool_budget(),
        }
    data, usage, tool_articles = await llm.achat_json(
        messages,
        enable_tool_calls=use_tools,
        domain=domain,
        **kwargs,
    )
    findings = []
    for item in data:
        valid = _validate_finding(item, block)
        if valid is not None:
            findings.append(valid)
    return findings, len(data) - len(findings), usage, tool_articles


def _scan_units(blocks: list[dict], max_chars: int) -> list[dict]:
    """把相邻小段合并成一个"扫描单元"：一个单元一次 LLM 调用。

    动机（2026-10-22 实测）：llm_scan 原本按段落逐块调用，583 字的营销话术被切成 6 段
    → 6 次串行 LLM（每次 20-160s，prompt 里 1.4k tokens 是固定系统提示）。
    真实材料几十段时，审查时间直接以小时计。合并后调用数与段落数解耦。

    - max_chars <= 0：保持历史行为（一 block 一单元）；
    - 标题段总是新单元开头（章节边界，避免跨章节混判）；
    - 单元保留 `_parts` 原始段落，供结论回定位（page/paragraph 不丢精度）。
    """
    if max_chars <= 0:
        return [{**b, "_parts": [b]} for b in blocks]

    units: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for b in blocks:
        text = b.get("text") or ""
        if cur and (b.get("heading") or size + len(text) > max_chars):
            units.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += len(text)
    if cur:
        units.append(cur)

    return [
        {
            "text": "\n".join(p.get("text") or "" for p in parts),
            "page": parts[0].get("page"),
            "paragraph": parts[0].get("paragraph"),
            "_parts": parts,
        }
        for parts in units
    ]


def _relocate(finding: dict, parts: list[dict]) -> dict:
    """把结论定位回原始段落——合并扫描后仍要告诉用户"哪一段"出的问题。"""
    if len(parts) <= 1:
        return finding
    text = finding.get("original_text") or ""
    for probe in (text, text[:12]):
        if not probe:
            continue
        for p in parts:
            if probe in (p.get("text") or ""):
                finding["page"] = p.get("page")
                finding["paragraph"] = p.get("paragraph")
                return finding
    return finding


def llm_scan(state: ReviewState) -> dict:
    llm = get_llm()
    if llm is None:
        logger.info("未配置 DASHSCOPE_API_KEY，跳过 LLM 语义审查")
        return {"llm_findings": [], "llm_usage": None, "scan_meta": {"channel": "none"}}

    # 执行强度分级（第 4 批）：light 只走规则引擎——短文本且零风险信号词，
    # 语义违规必然承载风险性语言（见 classify._scan_intensity 的护栏说明），
    # 纯口号类内容由确定性引擎覆盖即可，配额留给真正需要语义审查的材料
    intensity = state.get("scan_intensity") or "standard"
    if intensity == "light":
        logger.info("轻量通道：零风险信号短文本，跳过 LLM 语义审查（规则引擎结果为准）")
        return {
            "llm_findings": [],
            "llm_usage": None,
            "scan_meta": {"channel": "light", "skipped": "light"},
        }

    articles = state.get("matched_articles", [])
    domain = state.get("domain")
    workflow_cfg = settings.app_config("workflow")
    concurrency = max(1, int(workflow_cfg.get("llm_concurrency", _DEFAULT_CONCURRENCY)))
    max_chunks = int(workflow_cfg.get("llm_max_chunks", 0))  # 0 = 审查全部块

    blocks = [b for b in state.get("blocks", []) if (b.get("text") or "").strip()]
    # 小段合并成扫描单元（llm_scan_chunk_chars<=0 时保持历史的一段落一调用）
    max_scan_chars = int(workflow_cfg.get("llm_scan_chunk_chars", 0) or 0)
    units = _scan_units(blocks, max_scan_chars)
    if max_chunks > 0:
        units = units[:max_chunks]

    # 判定先例记忆（第 2 批）：按扫描单元召回同类历史人工判定注入审查上下文。
    # 零 LLM 成本（本地 embedding 查询）；失败/无先例降级为无先例审查，主路径不受影响。
    memory_on = bool(workflow_cfg.get("precedent_memory", True))
    precedent_top_k = int(workflow_cfg.get("precedent_top_k", 3))
    task_id = state.get("task_id")

    # 深查通道工具箱：一次构建、全部扫描单元共用（同一文档的 blocks）
    deep_tools_cfg = None
    if intensity == "deep":
        from src.core.llm.deep_tools import deep_tool_config

        deep_tools_cfg = deep_tool_config(blocks)

    async def _run() -> list:
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(unit: dict):
            async with sem:
                try:
                    precedents = None
                    if memory_on and precedent_top_k > 0:
                        precedents = recall_precedents(
                            unit.get("text") or "",
                            domain=domain,
                            top_k=precedent_top_k,
                            exclude_task_id=task_id,
                        )
                    found, dropped_cnt, usage, tool_arts = await _scan_block(
                        llm, unit, articles, domain, precedents=precedents,
                        deep_tools=deep_tools_cfg,
                    )
                    parts = unit.get("_parts") or [unit]
                    return (
                        [_relocate(f, parts) for f in found],
                        dropped_cnt,
                        usage,
                        tool_arts,
                        len(precedents or []),
                    )
                except Exception:  # 单块失败不影响整体，降级跳过
                    logger.exception("LLM 审查块失败，降级跳过")
                    return [], 0, None, [], 0

        return await asyncio.gather(*(_guarded(u) for u in units))

    results = asyncio.run(_run())

    findings: list[dict] = []
    dropped = 0
    failed = 0
    usages: list[dict] = []
    tool_articles: list[dict] = []
    precedents_injected = 0
    for block_findings, block_dropped, usage, block_tool_articles, unit_precedents in results:
        findings.extend(block_findings)
        dropped += block_dropped
        tool_articles.extend(block_tool_articles or [])
        precedents_injected += unit_precedents
        if usage is None:
            failed += 1
        else:
            usages.append(usage)

    usage_summary = merge_usage(*usages) if usages else None
    if usage_summary is not None:
        usage_summary["failed_blocks"] = failed
        usage_summary["model"] = llm.model
        logger.info(
            "LLM 审查完成：%d 块 / %d 条判定 / 丢弃 %d / 失败 %d 块 / %d tokens",
            len(blocks), len(findings), dropped, failed, usage_summary["total_tokens"],
        )
    elif blocks:
        logger.warning("LLM 审查全部 %d 块调用失败，降级为空结果", len(blocks))
    if dropped:
        logger.info("LLM 审查丢弃 %s 条无效/低置信度判定", dropped)
    return {
        "llm_findings": findings,
        "llm_usage": usage_summary,
        "tool_articles": tool_articles,
        # 先例记忆元数据（stage_log 可观测：本任务注入了多少条历史判定先例）
        "precedent_meta": {"units": len(units), "injected": precedents_injected},
        # 执行通道元数据（第 4 批）：standard / deep（light/none 在函数前部早退）
        "scan_meta": {"channel": intensity},
    }
