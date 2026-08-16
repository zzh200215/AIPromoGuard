"""审查 workflow 的 LangGraph 状态定义。节点间以 dict 传递（可序列化）。"""

from typing import Annotated, Any, TypedDict


def _merge_stage_logs(a: dict | None, b: dict | None) -> dict:
    """stage_log 合并器（LangGraph reducer）：并行分支各自写入的节点耗时记录合并去重。"""
    merged = dict(a or {})
    merged.update(b or {})
    return merged


class ReviewState(TypedDict, total=False):
    task_id: int
    document_path: str
    document_name: str
    doc_type: str | None
    text: str
    blocks: list[dict[str, Any]]
    domain: str | None
    matched_articles: list[dict[str, Any]]
    rule_hits: list[dict[str, Any]]
    llm_findings: list[dict[str, Any]]
    llm_usage: dict[str, Any]  # LLM token 用量/调用统计（成本观测，随报告落盘）
    merged_findings: list[dict[str, Any]]
    diff_changes: list[dict[str, Any]]  # 对比审查变更片段（普通任务不存在）
    report: dict[str, Any]
    report_path: str | None
    error: str | None
    # 各 Agent 节点执行状态/耗时（W14，PRD §11.3），用 reducer 合并并行分支
    stage_log: Annotated[dict[str, dict[str, Any]], _merge_stage_logs]
