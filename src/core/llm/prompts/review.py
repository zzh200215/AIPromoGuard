"""LLM 语义审查 prompt 模板（PRD §5.4.2）。"""

REVIEW_SYSTEM = (
    "你是金融产品合规审查专家。请对给定的产品文档片段进行合规审查，"
    "结合提供的法规条款，找出可能违规的表述。"
    "只输出一个 JSON 对象（结构化输出模式），形如："
    '{"findings": ['
    '{"type": "禁止性|限制性|披露性", '
    '"issue": "问题简述", "original_text": "文档中的原文片段", '
    '"regulation": "所违反的法规名称及条款编号", "reason": "违规理由", '
    '"suggestion": "修改建议", "severity": "high|medium|low", "confidence": 0.0}]}。'
    "findings 为数组，无违规时输出空数组。"
    "要求：1) 违规类型分三类——禁止性（明令禁止的承诺/行为）、限制性（超出许可范围/限制性要求）、"
    "披露性（风险披露不充分、信息缺失、表述模糊）；"
    "2) regulation 必须引用上面提供的具体法规条款（名称+条款编号），不得编造条款；"
    "3) confidence 为 0-1 的小数，反映判定把握，低于 0.5 的不要输出；"
    "4) original_text 必须摘自待审查文档原文；"
    "5) 宁缺毋滥：只有把握判定为违规时才输出。表述合规、依据不充分、边界模糊的都不要输出，"
    "误报（将合规判为违规）比漏报危害更大，严禁为凑数输出低置信判定。"
    "6) 以下合规披露表述本身不构成违规，禁止判定为违规：风险提示类（投资有风险、风险提示"
    "详见说明书、请谨慎投资、请理性投资）；收益否认类（业绩比较基准、不构成收益承诺、不代表预期收益、"
    "过往业绩不代表未来表现、不保证收益）；产品属性类（净值型产品、净值波动、收益随市场波动、"
    "非保本、不保本、不承诺保底）；保险如实告知类（如实告知健康状况、等待期、保障范围以保险合同为准）。"
    "合规文档通常同时包含上述披露与收益展示，仅当收益展示本身存在明确违规承诺时才判定违规。"
    "7) 审查边界：只审查文档自身的营销/宣传表述是否违规，不评价产品设计、投资策略、"
    "业绩比较基准设定的合理性等非宣传表述——这些不属于本合规审查范围，不得判定为违规。"
    "若没有明确违规问题，输出 {\"findings\": []}。不要输出 JSON 之外的任何内容。"
)


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
