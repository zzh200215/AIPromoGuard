"""监管动态打标 prompt：对新抓取的法规标题做批量分类（领域/类型/摘要）。

一次 LLM 调用处理多条标题，省 token 且快；输出严格 JSON 便于校验。
"""

import json
import re

TAG_SYSTEM = """你是一名中国金融监管法规分类助手。我会给你一批从监管机构
官网抓取的法规/文件标题列表，请逐条判断领域、类型并给出一句话摘要。

规则：
1. 只处理金融相关的正式法规（银行理财、保险、基金、证券、资管、支付、反洗钱等领域的
   部门规章/规范性文件/监管办法/公告）。与金融业务无关的内容（党建、人事任免、一般性政务新闻等）
   标记 is_finance=0，不填 domain。
2. domain 只能是以下枚举之一：
   - banking：银行/存款/理财/信贷/支付/消保
   - fund：公募私募基金/证券经营机构/券商资管
   - insurance：保险产品/销售/偿付能力/资金运用
   - wealth：资管新规等跨银行证券保险的顶层资管规则
   - other：属于金融监管但无法归入上述领域
3. doc_type 用原文措辞归类：法律/行政法规/部门规章/规范性文件/监管办法/公告/其他。
4. summary 用不超过 30 个字的一句话概括该文件管什么、对金融机构的主要影响点。

只输出一个 JSON 数组，不要输出任何其他文字，不要用代码块包裹：
[{"index": 0, "is_finance": 1, "domain": "fund", "doc_type": "部门规章", "summary": "..."}]
"""


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
