"""PDF 报告渲染（fpdf2 + CJK 字体）。

开发机用 Windows 中文字体，容器内用 fonts-wqy-zenhei（Dockerfile 已装）。
注意：fpdf2 multi_cell 默认结束位置在右边界，连续调用需显式 new_x="LMARGIN" 重置。
"""

from pathlib import Path
from typing import Any

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

_RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}
_SOURCE_LABEL = {"rule": "规则引擎", "llm": "LLM 语义", "hybrid": "规则+LLM"}


def find_cjk_font() -> str | None:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def render_pdf(report: dict, font_path: str | None = None) -> bytes:
    """将结构化报告渲染为 PDF 字节。"""
    from fpdf import FPDF

    font_path = font_path or find_cjk_font()
    if font_path is None:
        raise RuntimeError("未找到可用的 CJK 字体，无法渲染 PDF 报告")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("cjk", "", font_path)
    pdf.add_page()

    def mc(h: float, text: str, size: int | None = None) -> None:
        if size is not None:
            pdf.set_font("cjk", size=size)
        pdf.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT")

    def heading(text: str) -> None:
        pdf.set_font("cjk", size=12)
        pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("cjk", size=16)
    pdf.cell(0, 10, "金融产品合规审查报告", new_x="LMARGIN", new_y="NEXT")
    doc_line = (
        f"文档：{_s(report.get('document_name'))}   领域：{_s(report.get('domain')) or '未识别'}   "
        f"任务 ID：{report.get('task_id')}   生成时间：{_s(report.get('generated_at'))}"
    )
    mc(6, doc_line, size=10)
    pdf.ln(3)

    summary = report.get("summary", {})
    heading("一、审查摘要")
    summary_line = (
        f"共发现 {summary.get('total_violations', 0)} 处潜在违规，其中高风险 "
        f"{summary.get('high_risk', 0)} 处、中风险 {summary.get('medium_risk', 0)} 处、"
        f"低风险 {summary.get('low_risk', 0)} 处。"
    )
    mc(6, summary_line, size=10)
    if not report.get("llm_usage"):
        # 降级透明：导出文件必须如实反映引擎覆盖范围
        mc(
            6,
            "⚠️ 本次审查未调用 LLM 语义引擎（未配置 API Key 或已降级），结果仅来自规则引擎。",
            size=10,
        )

    # AI 风险综述（review_copilot 生成后随报告落盘；结论变化后标记过期）
    ai = report.get("ai_summary")
    if isinstance(ai, dict) and ai.get("text"):
        stale_note = "（已过期，仅供参考）" if ai.get("stale") else ""
        heading("AI 风险综述")
        mc(6, f"{_s(ai['text'])}{stale_note}", size=10)
        mc(
            5,
            f"（AI 生成，仅供参考 · 模型 {_s(ai.get('model'))} · {_s(ai.get('generated_at'))}）",
            size=9,
        )
        pdf.ln(2)

    so = report.get("sign_off")
    if so:
        # PDF 内嵌 CJK 字体缺 emoji 字形，用方括号标记代替 ✅/⛔
        verdict = "[同意放行]" if so.get("decision") == "released" else "[驳回整改]"
        sign_line = (
            f"审核签发：{verdict} — 签发人 {_s(so.get('username'))}"
            f" · {_s(so.get('created_at'))}"
        )
        if so.get("note"):
            sign_line += f" · 意见：{_s(so.get('note'))}"
        mc(6, sign_line, size=10)
    pdf.ln(3)
    heading("二、违规明细")
    violations = report.get("violations", [])
    if not violations:
        mc(6, "未发现明显违规表述。", size=10)
    for i, v in enumerate(violations, 1):
        risk = _RISK_LABEL.get(v.get("risk_level"), v.get("risk_level"))
        src = _SOURCE_LABEL.get(v.get("source"), v.get("source"))
        loc = f"第{v.get('page') or '-'}页/第{v.get('paragraph') or '-'}段"
        mc(7, f"{i}. [{risk}风险] {_s(v.get('rule_name') or v.get('description'))}", size=11)
        detail_line = (
            f"来源：{src} | 类型：{_s(v.get('type'))} | 位置：{loc} | "
            f"置信度：{v.get('confidence', '-')}"
        )
        mc(5, detail_line, size=9)
        mc(5, f"违规原文：{_s(v.get('original_text'))}", size=9)
        mc(5, f"修改建议：{_s(v.get('suggestion')) or '—'}", size=9)
        cases = v.get("related_cases") or []
        if cases:
            top = cases[0]
            mc(
                5,
                f"关联案例：{_s(top.get('case_name'))}（{_s(top.get('penalty_org'))}，"
                f"{_s(top.get('penalty_result'))}，相似度 {top.get('similarity', '-')}）"
                + (f" 等 {len(cases)} 起" if len(cases) > 1 else ""),
                size=9,
            )
        pdf.ln(2)

    pdf.ln(2)
    heading("三、相关法规")
    related = _collect_regulations(violations)
    if related:
        for reg in related:
            mc(6, f"- {_s(reg)}", size=10)
    else:
        mc(6, "无明确关联法规。", size=10)

    pdf.ln(3)
    diff = report.get("diff_changes") or []
    if diff:
        heading("附：版本变更对照")
        _LABEL = {"added": "新增", "removed": "删除", "modified": "修改"}
        for c in diff:
            marker = _LABEL.get(c.get("change_type"), c.get("change_type"))
            mc(6, f"- [{marker}] {_s(c.get('change_id'))}", size=10)
            if c.get("old_text"):
                mc(5, f"  旧版：{_s(c.get('old_text'))[:100]}", size=9)
            if c.get("new_text"):
                mc(5, f"  新版：{_s(c.get('new_text'))[:100]}", size=9)

    pdf.ln(3)
    mc(5, "本报告由金融产品合规智能审查系统生成，结果供人工复核确认。", size=8)

    return pdf.output()


def _collect_regulations(violations: list[dict]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for v in violations:
        for reg in [v.get("regulation")] + list(v.get("related_regulations") or []):
            if reg and reg not in seen:
                seen.add(reg)
                result.append(reg)
    return result


def _s(text: Any) -> str:
    return str(text or "")
