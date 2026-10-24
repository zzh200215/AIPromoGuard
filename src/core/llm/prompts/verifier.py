"""Verifier 消息构造（第 3 批：生成-验证对偶）。模板本体在 configs/prompts/registry.yaml。"""

from src.core.llm.prompts.registry import get_prompt

_VERIFIER = get_prompt("verifier")
VERIFIER_SYSTEM = _VERIFIER.template
VERIFIER_VERSION = _VERIFIER.version

_ORIGINAL_MAX = 120
_REASON_MAX = 120


def build_verifier_messages(findings: list[dict]) -> list[dict]:
    """构造批量验证消息：一次 LLM 调用独立复核全部待验证判定（配额友好）。

    findings 为待验证的 merged findings（source=llm），带 index 透传回应用层。
    """
    lines = []
    for i, f in enumerate(findings):
        lines.append(
            f"{i}. 原文：{(f.get('original_text') or '')[:_ORIGINAL_MAX]}\n"
            f"   判定：{f.get('rule_name') or ''}（类型 {f.get('type')}，"
            f"severity {f.get('severity')}，置信度 {f.get('confidence')}）\n"
            f"   理由：{(f.get('description') or '')[:_REASON_MAX]}\n"
            f"   法规依据：{f.get('regulation') or '（无）'}"
        )
    user = (
        "以下是 LLM 语义引擎单独检出（规则引擎未命中）的违规判定，"
        "请逐条独立复核并按系统指令输出 verdicts JSON：\n\n" + "\n".join(lines)
    )
    return [
        {"role": "system", "content": VERIFIER_SYSTEM},
        {"role": "user", "content": user},
    ]
