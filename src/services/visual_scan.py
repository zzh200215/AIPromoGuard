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
import json
import re
from pathlib import Path

from src.core.llm.client import extract_findings
from src.core.llm.prompts.registry import get_prompt
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "bmp": "image/bmp"}

_VLM = get_prompt("visual_scan")
_VLM_SYSTEM = _VLM.template


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


def find_ocr_missing(visible_numbers: list[dict], ocr_text: str) -> list[dict]:
    """图片级两路对照（PR-6）：VLM 读到、但图片自身 OCR 文字层未读到的数字.

    这是篡改判定的**上游预筛**：图片 OCR 没读到的数字才有"漏读/被改"的
    歧义；两路都读到的数字（归一相等）直接算一致，不进不一致判定。
    输出条目携带两路信息：value=VLM 读到值，context=紧邻标签（位置）。
    """
    from src.services.tamper_check import extract_text_numbers, is_key_number, norm_number

    ocr_nums = extract_text_numbers([{"text": ocr_text or ""}])
    missing: list[dict] = []
    for item in visible_numbers or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        context = str(item.get("context") or "").strip()
        if not value or not is_key_number(context, value):
            continue
        if norm_number(value) in ocr_nums:
            continue
        missing.append({"value": value, "context": context})
    return missing


def scan_image_visual(
    image_path: str | Path,
    ocr_text: str,
    domain: str | None,
    client=None,
) -> tuple[list[dict], dict | None, list[dict], list[dict]]:
    """视觉层合规分析。返回 (findings, usage, visible_numbers, ocr_missing)。

    visible_numbers 是 VLM 逐字读出的图中关键数字清单（R2-3 交叉篡改检测
    的输入），未启用/失败/模型未输出时降级为 []。ocr_missing 是其子集：
    图片自身 OCR 文字层未读到的数字（PR-6 两路对照的上游预筛），同样降级为 []。
    findings 的未启用/失败降级为 []，不阻断审查（图片仍走 OCR 文本管线）。
    client 供测试注入（需提供 chat.completions.create 接口）；缺省按
    settings 现场构造 OpenAI 兼容客户端（与 QwenClient 同端点，模型独立）。
    """
    if not settings.vlm_enabled or not settings.dashscope_api_key:
        return [], None, [], []
    data_url = _data_url(image_path)
    if data_url is None:
        return [], None, [], []

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
        return [], None, [], []

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
    findings, visible_numbers = _parse_vlm_output(content)
    findings = _normalize(findings if isinstance(findings, list) else [])
    ocr_missing = find_ocr_missing(visible_numbers, ocr_text)
    logger.info(
        "视觉层审查：%s 处视觉风险，%s 个关键数字（其中 %s 个图片 OCR 未读到，%s tokens，%s）",
        len(findings),
        len(visible_numbers),
        len(ocr_missing),
        usage_dict["total_tokens"],
        settings.vlm_model,
    )
    return findings, usage_dict, visible_numbers, ocr_missing


def _parse_vlm_output(content: str) -> tuple[list, list]:
    """宽容解析 VLM 输出 → (findings, visible_numbers)。

    与 client.extract_findings 的差异：这里需要完整 JSON 对象（两个键），
    不能复用只剥 findings 数组的共享解析；坏形态各自降级为空列表。
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = extract_findings(content)  # 兼容模型只给 findings 的旧形态
        return (data or []), []
    if isinstance(data, dict):
        return data.get("findings") or [], data.get("visible_numbers") or []
    if isinstance(data, list):
        return data, []
    return [], []
