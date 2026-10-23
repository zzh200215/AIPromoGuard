"""监管动态打标 prompt：对新抓取的法规标题做批量分类（领域/类型/摘要）。

一次 LLM 调用处理多条标题，省 token 且快；输出严格 JSON 便于校验。
模板本体在 configs/prompts/registry.yaml。
"""

import json
import re

from src.core.llm.prompts.registry import get_prompt

_TAG = get_prompt("monitor_tag")
TAG_SYSTEM = _TAG.template
TAG_VERSION = _TAG.version


def build_tag_messages(items: list[dict]) -> list[dict]:
    """items: [{title, doc_no?, publish_date?}]。返回 OpenAI messages 列表。"""
    lines = []
    for i, item in enumerate(items):
        parts = [f"{i}. {item.get('title', '')}"]
        if item.get("doc_no"):
            parts.append(f"文号:{item['doc_no']}")
        if item.get("publish_date"):
            parts.append(f"日期:{item['publish_date']}")
        lines.append("  ".join(parts))
    user = "请对以下法规标题逐条分类，index 与输入顺序一一对应：\n" + "\n".join(lines)
    return [
        {"role": "system", "content": TAG_SYSTEM},
        {"role": "user", "content": user},
    ]


def parse_tag_response(content: str) -> dict[int, dict]:
    """解析打标输出，返回 {index: {is_finance, domain, doc_type, summary}}；解析失败返回空 dict。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}

    result: dict[int, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        result[idx] = {
            "is_finance": 1 if item.get("is_finance") else 0,
            "domain": str(item.get("domain") or "").strip(),
            "doc_type": str(item.get("doc_type") or "").strip(),
            "summary": str(item.get("summary") or "").strip()[:512],
        }
    return result
