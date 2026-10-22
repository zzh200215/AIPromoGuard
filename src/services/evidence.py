"""证据核验服务：LLM 审查结论的法规引用是否可支撑（确定性检查，零 LLM）。

从评估工具（scripts/evaluate/judge.py）提炼进生产流：conflict_resolve 对
llm/hybrid 结论逐条核验"引用的法规是否真的出现在召回条款里"，不可支撑的
结论标记 evidence_supported=False → Markdown 报告可见（⚠️证据待核）且不参与
自动确认，强制走人工复核。这是"证据核验 Agent"的实质：多 Agent 协作中的
交接校验关卡，防止 LLM 幻觉引用直接变成审查结论。

三态语义（与 judge 口径一致）：
- True   引用的法规名能在召回条款中找到
- False  引用了法规但召回条款中找不到（含"根据监管规定"式泛引）
- None   未引用法规 / 召回上下文为空（不参与判定与统计）
"""

import re

_CITE_NAME_RE = re.compile(r"《([^》]{4,40})》")

# 单条结论的证据检索：命中越多噪声越大，2 条足够"一主一辅"
FINDING_EVIDENCE_TOP_K = 2
# bge-small-zh 上的经验阈值：违规原文是短句（"仅限本省客户"），短查询会召回到
# 完全无关的条款（实测匹配到《优先股试点管理办法》），必须收紧到 0.35 并用
# LLM 写的 description 作查询（正式表述，语义完整）。
FINDING_EVIDENCE_MAX_DISTANCE = 0.35


def retrieve_for_findings(
    findings: list[dict],
    top_k: int = FINDING_EVIDENCE_TOP_K,
    max_distance: float = FINDING_EVIDENCE_MAX_DISTANCE,
) -> list[list[dict]]:
    """按每条结论自己的表述检索证据条款（确定性，零 LLM）。

    动机（2026-10-22 实测）：`regulation_match` 只按整篇材料检索一次，5 条召回被
    所有结论共用——一份直播话术材料的 9 条结论里，9 条全引同一部办法同一条，
    而对口的《金融产品网络营销管理办法》虽然被召回却没人引。

    查询口径：**优先用 description（LLM 写的规范表述）**，其次 rule_name，
    最后才退回 original_text。用原文短句作查询在 bge-small-zh 上会严重跑偏
    （"保本保收益" → 《存款保险条例》第三条），这是实测踩过的坑。

    返回与 findings 等长的列表，每项是该结论命中的条款（已按距离过滤）。
    """
    if not findings:
        return []
    from src.services import regulation_service

    out: list[list[dict]] = []
    for f in findings:
        query = " ".join(
            x for x in (f.get("description"), f.get("rule_name"), f.get("original_text")) if x
        ).strip()
        if len(query) < 6:
            out.append([])
            continue
        try:
            hits = regulation_service.search_semantic(query, None, top_k * 3)
        except Exception:  # noqa: BLE001 —— 证据补检失败不应中断审查
            out.append([])
            continue
        kept = [h for h in hits if (1 - float(h.get("score") or 0)) <= max_distance][:top_k]
        out.append(kept)
    return out


def _label(article: dict) -> str:
    return f"《{article.get('regulation_name') or ''}》{article.get('article_no') or ''}"


def attach_finding_evidence(
    findings: list[dict], per_finding: list[list[dict]]
) -> list[dict]:
    """把按结论检索到的条款挂到结论上（每条结论各自的依据）。

    - `related_regulations` 写入本条自己的依据（报告导出器会逐条渲染）；
    - **不并入全局证据池**：核验时用"文档级召回 + 本条自己的检索"，避免别的结论
      的检索结果给本条"串证"（实测过一次：A 条引用的法规由 B 条的检索结果背书）；
    - 不改写 LLM 自己写的 `regulation`，保留可追溯性。
    """
    for finding, hits in zip(findings, per_finding, strict=False):
        if not hits:
            continue
        labels = []
        for h in hits:
            lab = _label(h)
            if lab not in labels:
                labels.append(lab)
        if labels:
            merged = list(finding.get("related_regulations") or [])
            finding["related_regulations"] = merged + [x for x in labels if x not in merged]
    return findings


def citation_supported(finding: dict, articles: list[dict]) -> bool | None:
    """结论引用的法规是否出现在召回上下文。

    结论未引用法规（regulation 为空 / 无可匹配名）→ None（不参与统计）；
    有《书名号》名时按名匹配；否则退化为子串匹配——召回法规名出现在引用
    文本中即支撑；引用文本里找不到任何召回法规名（含"根据监管规定"式泛引）
    记为不可支撑。
    """
    citation = (finding.get("regulation") or "").strip()
    if not citation:
        return None
    recalled = {str(a.get("regulation_name") or "").strip("《》") for a in articles}
    recalled.discard("")
    if not recalled:
        return None
    names = _CITE_NAME_RE.findall(citation)
    if names:
        return any(name in recalled for name in names)
    if len(citation) < 6:
        return None
    return any(name in citation for name in recalled)


def annotate_evidence(findings: list[dict], articles: list[dict]) -> list[dict]:
    """批量核验：给每条 finding 原地写入 evidence_supported 三态标记。"""
    for f in findings:
        f["evidence_supported"] = citation_supported(f, articles)
    return findings
