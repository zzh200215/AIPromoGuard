"""Markdown 报告渲染（PRD §3.2.8：任务信息 / 审查摘要 / 违规明细 / 相关法规）。"""

from typing import Any

_RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}
_SOURCE_LABEL = {"rule": "规则引擎", "llm": "LLM 语义", "hybrid": "规则+LLM"}


def _escape(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    lines = [
        "# 金融产品合规审查报告",
        "",
        f"- **文档**：{_escape(report.get('document_name'))}",
        f"- **领域**：{_escape(report.get('domain')) or '未识别'}",
        f"- **任务 ID**：{report.get('task_id')}",
        f"- **生成时间**：{_escape(report.get('generated_at'))}",
        "",
        "## 一、审查摘要",
        "",
        f"共发现 **{summary.get('total_violations', 0)}** 处潜在违规，其中高风险 "
        f"**{summary.get('high_risk', 0)}** 处、中风险 **{summary.get('medium_risk', 0)}** 处、"
        f"低风险 **{summary.get('low_risk', 0)}** 处。",
        "",
    ]

    usage = report.get("llm_usage")
    if usage:
        lines.append(
            f"LLM 用量：{usage.get('model', '-')} 共 {usage.get('calls', 0)} 次调用 / "
            f"{usage.get('total_tokens', 0)} tokens"
            + (
                f"（{usage.get('failed_blocks', 0)} 块降级）"
                if usage.get("failed_blocks")
                else ""
            )
        )
        lines.append("")

    lines += [
        "## 二、违规明细",
        "",
    ]

    violations = report.get("violations", [])
    if not violations:
        lines.append("未发现明显违规表述。")
    else:
        lines.append("| 风险 | 来源 | 类型 | 置信度 | 问题 | 位置 | 违规原文 | 修改建议 |")
        lines.append("| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |")
        for v in violations:
            # page/paragraph 值可能为 None（txt/docx 块无页码），get 默认值对 None 不生效
            location = f"第{v.get('page') or '-'}页/第{v.get('paragraph') or '-'}段"
            source = _SOURCE_LABEL.get(v.get("source"), v.get("source"))
            if v.get("evidence_supported") is False:
                # 证据核验交接关卡：引用的法规不在召回条款中（含泛引）→ 强制人工复核
                source = f"{source} ⚠️证据待核"
            lines.append(
                f"| {_RISK_LABEL.get(v.get('risk_level'), v.get('risk_level'))} "
                f"| {source} "
                f"| {_escape(v.get('type')) or '—'} "
                f"| {v.get('confidence', '—')} "
                f"| {_escape(v.get('rule_name') or v.get('description'))} "
                f"| {location} "
                f"| {_escape(v.get('original_text'))[:40]} "
                f"| {_escape(v.get('suggestion')) or '—'} |"
            )

    related = _collect_regulations(violations)
    lines += ["", "## 三、相关法规", ""]
    if related:
        for reg in related:
            lines.append(f"- {reg}")
    else:
        lines.append("无明确关联法规。")

    lines += ["", "## 四、关联处罚案例", ""]
    cases = _collect_cases(violations)
    if cases:
        for c in cases:
            lines.append(
                f"- **{_escape(c.get('case_name'))}**（{_escape(c.get('penalty_org'))}，"
                f"{_escape(c.get('penalty_date'))}）相似度 {c.get('similarity', '-')} —— "
                f"{_escape(c.get('penalty_result'))}"
            )
    else:
        lines.append("知识图谱未匹配到关联处罚案例（Neo4j 图谱未启用或该领域无对应案例）。")

    diff = report.get("diff_changes") or []
    if diff:
        lines += ["", "## 附：版本变更对照", ""]
        _LABEL = {"added": "新增", "removed": "删除", "modified": "修改"}
        for c in diff:
            marker = _LABEL.get(c.get("change_type"), c.get("change_type"))
            lines.append(f"- **{marker}** `{c.get('change_id')}`")
            if c.get("old_text"):
                lines.append(f"  - 旧版：{_escape(c.get('old_text'))[:100]}")
            if c.get("new_text"):
                lines.append(f"  - 新版：{_escape(c.get('new_text'))[:100]}")

    lines += ["", "---", "*本报告由金融产品合规智能审查系统生成，结果供人工复核确认。*"]
    return "\n".join(lines)


def _collect_regulations(violations: list[dict]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for v in violations:
        reg = v.get("regulation")
        if reg and reg not in seen:
            seen.add(reg)
            result.append(reg)
        for r in v.get("related_regulations") or []:
            if r not in seen:
                seen.add(r)
                result.append(r)
    return result


def _collect_cases(violations: list[dict]) -> list[dict]:
    """汇总所有违规点的关联处罚案例（去重，按相似度降序）。"""
    seen: dict[str, dict] = {}
    for v in violations:
        for c in v.get("related_cases") or []:
            name = c.get("case_name")
            if name and (
                name not in seen or c.get("similarity", 0) > seen[name].get("similarity", 0)
            ):
                seen[name] = c
    return sorted(seen.values(), key=lambda x: x.get("similarity", 0), reverse=True)
