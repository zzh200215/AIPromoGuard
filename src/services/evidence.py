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
