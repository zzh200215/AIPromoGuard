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


async def _scan_block(llm, block: dict, articles: list[dict]) -> tuple[list[dict], int, dict]:
    """审查单个文档块：结构化调用 + 逐条校验，返回 (findings, 丢弃数, usage)。"""
    messages = build_review_messages(block.get("text", ""), articles)
    data, usage = await llm.achat_json(messages)
    findings = []
    for item in data:
        valid = _validate_finding(item, block)
        if valid is not None:
            findings.append(valid)
    return findings, len(data) - len(findings), usage


def llm_scan(state: ReviewState) -> dict:
    llm = get_llm()
    if llm is None:
        logger.info("未配置 DASHSCOPE_API_KEY，跳过 LLM 语义审查")
        return {"llm_findings": [], "llm_usage": None}

    articles = state.get("matched_articles", [])
    workflow_cfg = settings.app_config("workflow")
    concurrency = max(1, int(workflow_cfg.get("llm_concurrency", _DEFAULT_CONCURRENCY)))
    max_chunks = int(workflow_cfg.get("llm_max_chunks", 0))  # 0 = 审查全部块

    blocks = [b for b in state.get("blocks", []) if (b.get("text") or "").strip()]
    if max_chunks > 0:
        blocks = blocks[:max_chunks]

    async def _run() -> list:
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(b: dict):
            async with sem:
                try:
                    return await _scan_block(llm, b, articles)
                except Exception:  # 单块失败不影响整体，降级跳过
                    logger.exception("LLM 审查块失败，降级跳过")
                    return [], 0, None

        return await asyncio.gather(*(_guarded(b) for b in blocks))

    results = asyncio.run(_run())

    findings: list[dict] = []
    dropped = 0
    failed = 0
    usages: list[dict] = []
    for block_findings, block_dropped, usage in results:
        findings.extend(block_findings)
        dropped += block_dropped
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
    return {"llm_findings": findings, "llm_usage": usage_summary}
