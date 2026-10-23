"""LLM 语义审查 prompt（PRD §5.4.2）。模板本体在 configs/prompts/registry.yaml。"""

from src.core.llm.prompts.registry import get_prompt

_REVIEW = get_prompt("review")
REVIEW_SYSTEM = _REVIEW.template
REVIEW_VERSION = _REVIEW.version


def build_review_messages(
    block_text: str, articles: list[dict], max_article_chars: int = 2000
) -> list[dict]:
    """构造审查消息。法规条款按相关性截断，控制上下文长度。"""
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
    return [
        {"role": "system", "content": REVIEW_SYSTEM},
        {
            "role": "user",
            "content": f"相关法规条款：\n{article_text}\n\n待审查文档片段：\n{block_text}",
        },
    ]
