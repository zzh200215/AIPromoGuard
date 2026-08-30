"""视觉层合规审查（VLM）：营销图片的排版/图形暗示风险识别。

图片审查的 OCR 链路（parsers.ocr_parser）只覆盖文字内容；海报的视觉层
违规——收益数字放大强调、"保本"红字视觉强化、盾牌/上升箭头图形暗示、
风险提示小字角落化、名人形象背书——文字引擎天然看不到。本模块把图片
发给多模态模型（默认 qwen-vl-plus，settings.vlm_model 可覆盖）做视觉
合规分析，产出与 LLM 路同 schema 的 findings，经 conflict_resolve 以
source=vlm 合入报告（永不自动确认，进待核验清单）。

文字层违规由规则引擎/LLM 语义路负责，提示词明确要求不重复报文字违规。
VLM 失败/未配置时优雅降级为空（图片仍走 OCR 文本管线），不阻断审查。
"""

import base64
from pathlib import Path

from src.core.llm.client import extract_findings
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "bmp": "image/bmp"}

_VLM_SYSTEM = (
    "你是金融营销材料的视觉合规审查员。给定宣传图片与其中识别出的文字（OCR），"
    "只审查视觉层风险，文字内容的违规由其他引擎负责，不要重复报告：\n"
    "1) 收益/利率数字的放大、变色、居中等视觉强调；\n"
    "2) '保本''稳赚''零风险'等文字的视觉强化（大字/红色/图形底衬）；\n"
    "3) 图形符号暗示（盾牌=保障、上升箭头=收益承诺、钱袋金币=保本兜底）；\n"
    "4) 风险提示的视觉弱化（字号远小于收益宣传、置于角落、浅色低对比度）或缺失；\n"
    "5) 名人/专家/权威机构形象的收益背书暗示。\n"
    '只输出 JSON 对象：{"findings": [{"issue": "问题短标题", "reason": "判定依据", '
    '"original_text": "对应的OCR文字片段或视觉元素描述", "severity": "high|medium|low", '
    '"confidence": 0到1的小数, "suggestion": "整改建议"}]}。'
    '没有视觉层问题时输出 {"findings": []}。'
)


def _data_url(image_path: str | Path) -> str | None:
    ext = Path(image_path).suffix.lstrip(".").lower()
    mime = _MIME.get(ext)
    if mime is None:
        return None
    try:
        data = Path(image_path).read_bytes()
    except OSError:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _normalize(items: list) -> list[dict]:
    """模型输出 → 与 LLM 路同 schema 的 findings（坏条目丢弃，字段夹取）。"""
    findings = []
    for item in items:
        if not isinstance(item, dict):
            continue
        issue = str(item.get("issue") or "").strip()
        if not issue:
            continue
        severity = str(item.get("severity") or "medium").lower()
        if severity not in ("high", "medium", "low"):
            severity = "medium"
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence") or 0.7)))
        except (TypeError, ValueError):
            confidence = 0.7
        findings.append(
            {
                "issue": issue,
                "reason": str(item.get("reason") or "").strip(),
                "original_text": (str(item.get("original_text") or "").strip() or issue)[:200],
                "severity": severity,
                "confidence": confidence,
                "suggestion": str(item.get("suggestion") or "").strip() or None,
                "page": 1,
            }
        )
    return findings


def scan_image_visual(
    image_path: str | Path,
    ocr_text: str,
    domain: str | None,
    client=None,
) -> tuple[list[dict], dict | None]:
    """视觉层合规分析。返回 (findings, usage)；未启用/失败降级为 ([], None)。

    client 供测试注入（需提供 chat.completions.create 接口）；缺省按
    settings 现场构造 OpenAI 兼容客户端（与 QwenClient 同端点，模型独立）。
    """
    if not settings.vlm_enabled or not settings.dashscope_api_key:
        return [], None
    data_url = _data_url(image_path)
    if data_url is None:
        return [], None

    user_text = (
        f"领域：{domain or '未识别'}\n图片 OCR 文字：\n{ocr_text[:1500]}\n\n"
        "请审查该营销图片的视觉层合规风险："
    )
    messages = [
        {"role": "system", "content": _VLM_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    try:
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout,
            )
        resp = client.chat.completions.create(
            model=settings.vlm_model,
            messages=messages,
            temperature=0.2,
        )
    except Exception as exc:
        logger.warning("视觉层审查调用失败（降级跳过）: %s", exc)
        return [], None

    usage = getattr(resp, "usage", None)
    usage_dict = {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }
    content = ""
    choices = getattr(resp, "choices", None)
    if choices:
        content = choices[0].message.content or ""
    data = extract_findings(content)
    findings = _normalize(data if isinstance(data, list) else [])
    logger.info(
        "视觉层审查：%s 处视觉风险（%s tokens，%s）",
        len(findings),
        usage_dict["total_tokens"],
        settings.vlm_model,
    )
    return findings, usage_dict
