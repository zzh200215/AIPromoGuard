"""Markdown 报告渲染（PRD §3.2.8：任务信息 / 审查摘要 / 违规明细 / 相关法规）。"""

from typing import Any

from src.core.profiles import PROFILE_LABELS

_RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}
_SOURCE_LABEL = {"rule": "规则引擎", "llm": "LLM 语义", "hybrid": "规则+LLM", "vlm": "视觉模型"}
_HUMAN_LABEL = {
    "pending_confirm": "待复核",
    "confirmed": "已确认",
    "false_positive": "误报剔除",
}


def _human_label(v: dict) -> str:
    """人工结论列：自动确认（confirmed_by=0）单独标注，无人工数据时为 —。"""
    status = v.get("human_status")
    if not status:
        return "—"
    if status == "confirmed" and v.get("human_confirmed_by") == 0:
        return "已确认（自动）"
    return _HUMAN_LABEL.get(status, status)


def _reg_label(reg: dict) -> str | None:
    name = reg.get("regulation_name") or ""
    if not name:
        return None
    label = name if "《" in name else f"《{name}》"
    if reg.get("regulation_no"):
        label += f"（{reg['regulation_no']}）"
    return label


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

    profile = report.get("profile")
    if profile:
        lines.insert(
            5, f"- **审查策略**：{profile}（{PROFILE_LABELS.get(profile, profile)}）"
        )

    usage = report.get("llm_usage")
    if usage:
        usage_line = (
            f"LLM 用量：{usage.get('model', '-')} 共 {usage.get('calls', 0)} 次调用 / "
            f"{usage.get('total_tokens', 0)} tokens"
        )
        cost = usage.get("estimated_cost_cny")
        if cost is not None:
            usage_line += f" / 预估 ¥{cost:.2f}（按牌价）"
        if usage.get("failed_blocks"):
            usage_line += f"（{usage.get('failed_blocks', 0)} 块降级）"
        lines += [usage_line, ""]
    else:
        # 降级透明：个人/新部署常没配 LLM Key，必须让人一眼看出引擎覆盖范围
        lines += [
            "⚠️ 本次审查未调用 LLM 语义引擎（未配置 API Key 或已降级），结果仅来自规则引擎。",
            "",
        ]

    # 人工复核结论（report_service 合并）：报告结论与人工判定保持一致
    hr = report.get("human_review")
    if hr:
        lines += [
            f"人工复核：已确认 **{hr.get('confirmed', 0)}** 处、剔除误报 "
            f"**{hr.get('false_positive', 0)}** 处、待复核 **{hr.get('pending_confirm', 0)}** 处"
            f"（含系统自动确认 {hr.get('auto_confirmed', 0)} 处）。",
            f"剔除误报后，最终确认违规 **{hr.get('final_total', 0)}** 处"
            f"（高 {hr.get('final_high', 0)} / 中 {hr.get('final_medium', 0)} / "
            f"低 {hr.get('final_low', 0)}）。",
        ]
        if hr.get("last_confirmed_at"):
            lines.append(f"结论截至：{hr['last_confirmed_at']}。本报告已与最新人工复核结论同步。")
        lines.append("")

    # AI 风险综述（review_copilot 生成后随报告落盘；结论变化后标记过期）
    ai = report.get("ai_summary")
    if isinstance(ai, dict) and ai.get("text"):
        stale_note = "（已过期，仅供参考）" if ai.get("stale") else ""
        meta = (
            f"（AI 生成，仅供参考 · 模型 {_escape(ai.get('model'))}"
            f" · {_escape(ai.get('generated_at'))}）"
        )
        lines += [
            f"> **AI 风险综述**{stale_note}：{_escape(ai['text'])}",
            "",
            meta,
            "",
        ]

    # 审核签发（report_service 实时合并）：报告的正式放行/驳回结论
    so = report.get("sign_off")
    if so:
        verdict = "✅ 同意放行" if so.get("decision") == "released" else "⛔ 驳回整改"
        sign_line = (
            f"审核签发：**{verdict}** — 签发人 {so.get('username', '—')}"
            f" · {so.get('created_at', '—')}"
        )
        if so.get("note"):
            sign_line += f" · 意见：{so['note']}"
        lines += [sign_line, ""]

    lines += [
        "## 二、违规明细",
        "",
    ]

    violations = report.get("violations", [])
    if not violations:
        lines.append("未发现明显违规表述。")
    else:
        lines.append("| 风险 | 人工 | 来源 | 类型 | 置信度 | 问题 | 位置 | 违规原文 | 修改建议 |")
        lines.append("| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |")
        for v in violations:
            # page/paragraph 值可能为 None（txt/docx 块无页码），get 默认值对 None 不生效
            location = f"第{v.get('page') or '-'}页/第{v.get('paragraph') or '-'}段"
            source = _SOURCE_LABEL.get(v.get("source"), v.get("source"))
            if v.get("evidence_supported") is False:
                # 证据核验交接关卡：引用的法规不在召回条款中（含泛引）→ 强制人工复核
                source = f"{source} ⚠️证据待核"
            lines.append(
                f"| {_RISK_LABEL.get(v.get('risk_level'), v.get('risk_level'))} "
                f"| {_human_label(v)} "
                f"| {source} "
                f"| {_escape(v.get('type')) or '—'} "
                f"| {v.get('confidence', '—')} "
                f"| {_escape(v.get('rule_name') or v.get('description'))} "
                f"| {location} "
                f"| {_escape(v.get('original_text'))[:40]} "
                f"| {_escape(v.get('suggestion')) or '—'} |"
            )

    # 结构化法规引用优先（带文号、可点跳转）；旧报告无该字段时退回名称字符串
    structured = [
        label for label in (_reg_label(r) for r in report.get("regulations") or []) if label
    ]
    related = structured or _collect_regulations(violations)
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

    lines += ["", "## 五、待人工核验清单", ""]
    pending = report.get("pending_verification") or []
    if pending:
        lines.append("以下各项自动核验未覆盖或需业务材料佐证，请人工确认后再对外发布结论：")
        lines.append("")
        for item in pending:
            location = f"第{item.get('page') or '-'}页/第{item.get('paragraph') or '-'}段"
            lines.append(
                f"- **[{_RISK_LABEL.get(item.get('risk_level'), item.get('risk_level') or '—')}]** "
                f"{_escape(item.get('original_text'))[:60]} —— "
                f"{'；'.join(item.get('reasons') or [])}（{location}）"
            )
    else:
        lines.append("无。本报告没有需要人工补充核验的存疑项。")

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
