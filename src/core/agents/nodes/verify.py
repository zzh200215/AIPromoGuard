"""Verifier 节点（第 3 批：生成-验证对偶）——对 LLM 单独命中做机器侧独立复核。

定位：多智能体的 critic/verifier 形态——生成者（llm_scan）与验证者（本节点）
相互独立，验证者在融合后、人工复核前运行。人机协同从「人兜底一切 LLM 命中」
升级为「机器先自我验证、人只看机器仍有分歧的样本」。

成本与安全护栏：
- **单次批量调用**：全部待验证判定合并成一次 LLM 调用（与监管动态打标同构），
  每任务固定 +1 次调用，不受判定条数影响；
- **只验证 source=llm 的判定**：rule 命中确定性采信、hybrid 已交叉确认、
  vlm 独立通道——验证面就是原本全量进人工复核的那部分；
- **驳回保守**：rejected 且验证置信度 ≥ verifier_reject_min_confidence 才剔除，
  低置信驳回按降级处理（宁少杀不错杀，误报纠正优先于漏检风险）；
- **降级不剔除**：downgraded 只压低 confidence（×0.8），保留人工可见性；
- **优雅降级**：LLM 未配置 / 功能关闭 / 调用失败 / 输出无法解析 → 判定原样
  保留，verification_meta.failed 计数（验证是增强，不是依赖）。

验证结论逐条写入 finding.verification（审计可溯，报告可展示）。
"""

import json
import re

from src.core.agents.state import ReviewState
from src.core.llm.client import get_llm
from src.core.llm.prompts.verifier import VERIFIER_VERSION, build_verifier_messages
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
_DROPPED_KEEP = 5  # meta.dropped 只留前 N 条明细（stage_log 控体积）

_DEFAULTS = {
    "verifier": False,        # 缺省关：与 agentic_retrieval 同先例（LLM 成本类增强）
    "verifier_max_findings": 20,
    "verifier_reject_min_confidence": 0.75,
}


def _cfg() -> dict:
    workflow = settings.app_config("workflow")
    return {**_DEFAULTS, **{k: v for k, v in (workflow or {}).items() if k in _DEFAULTS}}


def _parse_verdicts(content: str) -> list[dict]:
    """宽容解析 verdicts 数组（剥代码围栏；坏条目丢弃）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_OBJECT_RE.search(text)
        if not m:
            return []
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return []
    verdicts = data.get("verdicts") if isinstance(data, dict) else data
    if not isinstance(verdicts, list):
        return []
    out = []
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        verdict = str(v.get("verdict") or "").strip().lower()
        if verdict not in ("upheld", "downgraded", "rejected"):
            continue
        try:
            conf = max(0.0, min(1.0, float(v.get("confidence"))))
        except (TypeError, ValueError):
            conf = 0.5
        out.append(
            {
                "verdict": verdict,
                "confidence": conf,
                "reason": str(v.get("reason") or "")[:200],
                "index": v.get("index"),
            }
        )
    return out


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def verify(state: ReviewState) -> dict:
    """对 merged_findings 中 source=llm 的判定做批量独立验证。"""
    cfg = _cfg()
    if not cfg["verifier"]:
        return {}
    llm = get_llm()
    if llm is None:
        return {"verification_meta": {"skipped": "llm_off"}}

    findings = list(state.get("merged_findings") or [])
    max_findings = int(cfg["verifier_max_findings"])
    reject_min = float(cfg["verifier_reject_min_confidence"])
    targets = [f for f in findings if f.get("source") == "llm"][:max_findings]
    if not targets:
        return {"verification_meta": {"verified": 0, "prompt": f"verifier@{VERIFIER_VERSION}"}}

    messages = build_verifier_messages(targets)
    try:
        completion = llm.complete(messages, temperature=0.2)
    except Exception as exc:  # noqa: BLE001 —— 验证失败降级为未验证（判定原样保留）
        logger.warning("verifier 调用失败，判定原样保留: %s", exc)
        return {
            "verification_meta": {
                "verified": 0,
                "failed": 1,
                "prompt": f"verifier@{VERIFIER_VERSION}",
            }
        }

    verdicts = _parse_verdicts(completion.content)
    by_index = {}
    for v in verdicts:
        idx = _to_int(v.get("index"))
        if idx is not None and 0 <= idx < len(targets):
            by_index[idx] = v

    meta = {
        "verified": len(by_index),
        "upheld": 0,
        "downgraded": 0,
        "rejected_dropped": 0,
        "rejected_kept": 0,
        "failed": 0,
        "dropped": [],
        "prompt": f"verifier@{VERIFIER_VERSION}",
    }

    drop_target_ids = set()
    for i, finding in enumerate(targets):
        v = by_index.get(i)
        if v is None:
            meta["failed"] += 1
            continue
        finding["verification"] = {
            "verdict": v["verdict"],
            "confidence": v["confidence"],
            "reason": v["reason"],
        }
        if v["verdict"] == "upheld":
            meta["upheld"] += 1
        elif v["verdict"] == "downgraded":
            meta["downgraded"] += 1
            finding["confidence"] = round(float(finding.get("confidence") or 0) * 0.8, 3)
        else:  # rejected
            if v["confidence"] >= reject_min:
                meta["rejected_dropped"] += 1
                drop_target_ids.add(id(finding))
                if len(meta["dropped"]) < _DROPPED_KEEP:
                    meta["dropped"].append(
                        {
                            "original_text": (finding.get("original_text") or "")[:60],
                            "reason": v["reason"],
                        }
                    )
            else:
                # 低置信驳回按降级处理（保守：宁少杀不错杀）
                meta["rejected_kept"] += 1
                finding["confidence"] = round(float(finding.get("confidence") or 0) * 0.8, 3)

    if drop_target_ids:
        findings = [f for f in findings if id(f) not in drop_target_ids]

    logger.info(
        "verifier 完成：验证 %d / 维持 %d / 降级 %d / 剔除 %d / 失败 %d",
        meta["verified"], meta["upheld"], meta["downgraded"],
        meta["rejected_dropped"], meta["failed"],
    )
    # 列表未变化（无剔除）时不返回 merged_findings——图 state 保持原引用，
    # 语义上"未改动"与"改动"返回形状一致可判
    out = {"verification_meta": meta}
    if drop_target_ids:
        out["merged_findings"] = findings
    return out
