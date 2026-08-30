"""ReportGenerator 节点：生成报告（JSON 结构化 + Markdown 可读版）并落盘。"""

import json
from pathlib import Path

from src.core.agents.state import ReviewState
from src.core.report.generator import build_report
from src.core.report.markdown import render_markdown
from src.utils.config import settings


def report(state: ReviewState) -> dict:
    report_data = build_report(
        task_id=state["task_id"],
        document_name=state.get("document_name", ""),
        domain=state.get("domain"),
        findings=state.get("merged_findings", []),
        diff_changes=state.get("diff_changes"),
        llm_usage=state.get("llm_usage"),
        profile=state.get("profile"),
    )
    base = Path(settings.report_dir) / f"task_{state['task_id']}"
    json_path = base.with_suffix(".json")
    json_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text(render_markdown(report_data), encoding="utf-8")
    return {"report": report_data, "report_path": str(json_path)}
