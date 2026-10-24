"""LLM 语义审查 prompt（PRD §5.4.2）。模板本体在 configs/prompts/registry.yaml。"""

from src.core.llm.prompts.registry import get_prompt

_REVIEW = get_prompt("review")
REVIEW_SYSTEM = _REVIEW.template
REVIEW_VERSION = _REVIEW.version


def _precedents_section(precedents: list[dict]) -> str:
    """先例注入段：同类材料的历史人工判定（误报纠正 + 确认违规）。"""
    lines = []
    for p in precedents:
        head = (
            "人工确认违规"
            if p.get("verdict") == "confirmed"
            else "人工判定合规（系统曾误报，已被人工纠正）"
        )
        rule = f"；依据规则: {p['rule_name']}" if p.get("rule_name") else ""
        lines.append(f"- [{head}] {p.get('original_text', '')}{rule}")
    return "同类材料历史人工判定（参考先例，非法规依据，结论仍以法规条款为准）：\n" + "\n".join(
        lines
    )


def build_review_messages(
    block_text: str,
    articles: list[dict],
    max_article_chars: int = 2000,
    precedents: list[dict] | None = None,
) -> list[dict]:
    """构造审查消息。法规条款按相关性截断，控制上下文长度。

    precedents 非空时在法规条款与待审文本之间注入"历史人工判定"参考段
    （判定先例记忆，第 2 批能力）；为 None/空时输出与历史版本逐字节一致，
    保证无记忆场景下 prompt 可回归对比。
    """
    article_lines = []
    used = 0
    for art in articles:
        reg_name = art.get("regulation_name", "")
        no = art.get("article_no", "")
        content = art.get("content", "")
        line = f"[{reg_name} {no}] {content}"
        if used + len(line) > max_article_chars:
            break
        article_lines.append(line)
        used += len(line)

    article_text = "\n".join(article_lines) if article_lines else "（未召回相关条款）"
    sections = [f"相关法规条款：\n{article_text}"]
    if precedents:
        sections.append(_precedents_section(precedents))
    sections.append(f"待审查文档片段：\n{block_text}")
    return [
        {"role": "system", "content": REVIEW_SYSTEM},
        {"role": "user", "content": "\n\n".join(sections)},
    ]
