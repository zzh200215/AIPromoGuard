"""审查 workflow 的 LangGraph 状态定义。节点间以 dict 传递（可序列化）。"""

from typing import Annotated, Any, TypedDict


def _merge_stage_logs(a: dict | None, b: dict | None) -> dict:
    """stage_log 合并器（LangGraph reducer）：并行分支各自写入的节点耗时记录合并去重。"""
    merged = dict(a or {})
    merged.update(b or {})
    return merged


_LLM_USAGE_NUMERIC = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "calls",
    "failed_blocks",
)


def _merge_llm_usage(a: dict | None, b: dict | None) -> dict | None:
    """llm_usage 合并器（reducer）：llm_scan 与 agentic 检索各自累计的 token 用量相加。

    无任何真实用量（全 None/零）时归一为 None，保持 no-LLM 路径下
    state.llm_usage 缺省语义（报告省略字段、API 返回 None）。
    """
    merged = dict(a or {})
    for key in _LLM_USAGE_NUMERIC:
        merged[key] = int(merged.get(key) or 0) + int((b or {}).get(key) or 0)
    if not merged.get("model"):
        merged["model"] = (b or {}).get("model")
    if not merged.get("total_tokens") and not merged.get("calls"):
        return None
    return merged


class ReviewState(TypedDict, total=False):
    task_id: int
    document_path: str
    document_name: str
    doc_type: str | None
    text: str
    blocks: list[dict[str, Any]]
    domain: str | None
    # 审查策略（strict/standard/loose，None=standard），human_review 节点据此覆盖配置
    profile: str | None
    matched_articles: list[dict[str, Any]]
    retrieval_meta: dict[str, Any]  # 检索过程元数据（agentic 轮次/补检查询/token 用量，可观测）
    rule_hits: list[dict[str, Any]]
    llm_findings: list[dict[str, Any]]
    # 工具查证检索到的条款（function calling 模式）——并入证据核验集（2026-10-16）
    tool_articles: list[dict[str, Any]]
    # 先例记忆元数据（第 2 批）：llm_scan 召回注入的先例统计（units/injected）
    precedent_meta: dict[str, Any]
    vlm_findings: list[dict[str, Any]]  # 视觉层审查 findings（VLM，图片文档专用，仅初始态写入）
    # 方案 A：解析脱敏时采集的敏感命中元数据（PII 检测的数据源——
    # 脱敏后文本正则扫不出敏感信息；仅初始态写入）
    mask_spans: list[dict[str, Any]]
    # LLM token 用量/调用统计（成本观测，随报告落盘）；reducer 累加多节点用量
    llm_usage: Annotated[dict[str, Any], _merge_llm_usage]
    merged_findings: list[dict[str, Any]]
    human_review: dict[str, Any]  # 人工复核关卡结果（interrupt 决策记录，未启用时无此键）
    diff_changes: list[dict[str, Any]]  # 对比审查变更片段（普通任务不存在）
    report: dict[str, Any]
    report_path: str | None
    error: str | None
    # 各 Agent 节点执行状态/耗时（W14，PRD §11.3），用 reducer 合并并行分支
    stage_log: Annotated[dict[str, dict[str, Any]], _merge_stage_logs]
