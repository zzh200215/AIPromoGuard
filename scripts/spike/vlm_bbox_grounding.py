"""Spike：VLM bbox 坐标输出能力验证（F2-2 v2 像素级框选的前置立项判据）.

假设：qwen-vl 能对图中指定文字元素输出可靠的边界框。
方法：PIL 合成海报——元素绘制位置即 ground truth（textbbox 精确计算，
无人工标注误差）；逐元素调 VLM 请求 bbox，计算 IoU。
坐标约定：prompt 明确要"原图像素坐标"；评估时同时按 像素 / 归一化0-1 /
归一化0-1000 三种约定解码取最优（能力评估取最宽容解码——若适配其原生
约定仍低分，才说明能力缺失）。
输出：data/spike_vlm/bbox_report.json + bbox_overlay/*.png（标注图供人工复核）。

判据（前端升级方案.md F2-2）：命中率（IoU≥0.5）≥ 80% 且过半严格达标（IoU≥0.8）
  -> 立项 v2 像素级框选
否则 -> 维持文本锚定（v1 现状），诚实砍掉 v2

用法："D:/AI/ACD/envs/llmXM/python.exe" scripts/spike/vlm_bbox_grounding.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT_DIR = ROOT / "data" / "spike_vlm"
OVERLAY_DIR = OUT_DIR / "bbox_overlay"
# 紧致框变体（SPIKE_BBOX_TIGHT=1）：显式要求贴合笔画外沿——主运行用默认提示，
# 变体用于区分"能力缺失"与"提示词欠佳"（2026-10-07 实测：标准场景显著提升，
# 艺术化字体反而下降——能力对提示词敏感的实证）
_TIGHT = os.environ.get("SPIKE_BBOX_TIGHT") == "1"
FONT_PATHS = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]

SYSTEM_PROMPT = (
    "你是图像元素定位器。给定图片与目标文字/元素清单，输出每个目标在**原图"
    "像素坐标系**下的边界框 [x1, y1, x2, y2]（左上角与右下角像素坐标）。"
    '只输出 JSON：{"boxes": [{"text": "目标原文", "bbox": [x1, y1, x2, y2]}]}。'
    "定位不到的目标不要编造，直接跳过。"
)
if _TIGHT:
    SYSTEM_PROMPT = SYSTEM_PROMPT.replace(
        "下的边界框 [x1, y1, x2, y2]（左上角与右下角像素坐标）。",
        "下的紧致边界框 [x1, y1, x2, y2]——框必须恰好贴合文字笔画外沿，"
        "不要包含上下多余空白或相邻行。",
    )

RED, DARK, GRAY = (200, 30, 30), (30, 30, 30), (130, 130, 130)
GOLD, WHITE = (180, 140, 30), (245, 245, 245)
GREEN = (20, 130, 60)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _draw_poster(
    name: str, lines: list[tuple], width: int = 900, bg: tuple = (255, 255, 255)
) -> tuple[Path, list[dict]]:
    """绘制海报；返回 (路径, 目标清单)。target 行的 bbox 由 textbbox 精确计算。"""
    img = Image.new("RGB", (width, 760), bg)
    d = ImageDraw.Draw(img)
    y = 50
    targets: list[dict] = []
    for text, size, color, bold, is_target in lines:
        f = _font(size, bold)
        d.text((50, y), text, font=f, fill=color)
        if is_target:
            bbox = d.textbbox((50, y), text, font=f)
            targets.append({"text": text, "gt": list(bbox)})
        y += int(size * 2.0)
    path = OUT_DIR / f"{name}.png"
    img.save(path)
    return path, targets


def build_fixtures() -> list[dict]:
    """5 类场景（大字/表格行/小字/深色底反白/艺术化），每张 1-2 个定位目标。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fixtures: list[dict] = []

    def add(name: str, lines: list[tuple], bg: tuple = (255, 255, 255)):
        path, targets = _draw_poster(name, lines, bg=bg)
        fixtures.append({"name": name, "path": str(path), "targets": targets})

    # 1. 大字数字（最理想场景）：定位放大的收益数字
    add("b01_big_rate", [
        ("XX稳健理财1号", 44, DARK, True, False),
        ("年化收益率", 36, DARK, False, False),
        ("3.85%", 110, RED, True, True),
        ("历史业绩不代表未来", 24, GRAY, False, False),
    ])

    # 2. 表格行数字：定位表格行中的金额
    add("b02_table_row", [
        ("收益演示表", 40, DARK, True, False),
        ("期初本金  50000 元", 34, DARK, False, True),
        ("预期年化收益率  4.20 %", 34, DARK, False, False),
        ("期末合计  52100 元", 34, DARK, True, False),
    ])

    # 3. 小字风险提示：定位小字中的风险等级
    add("b03_small_print", [
        ("XX基金宣传单", 42, DARK, True, False),
        ("管理费率 1.20% 托管费率 0.25%", 26, DARK, False, False),
        ("风险提示：本产品为R3级中风险产品，", 20, GRAY, False, True),
        ("过往业绩不代表未来表现。", 20, GRAY, False, False),
    ])

    # 4. 深色底反白字（低对比度干扰）
    add("b04_dark_bg", [
        ("XX私人银行", 40, WHITE, True, False),
        ("演示利率 2.5%", 60, WHITE, True, True),
        ("本产品不保本", 26, (170, 170, 170), False, False),
    ], bg=(20, 26, 40))

    # 5. 艺术化金色大数字
    add("b05_artistic", [
        ("★ 限时专属 ★", 36, GOLD, True, False),
        ("七日年化", 30, DARK, False, False),
        ("7.2%", 130, GOLD, True, True),
        (">>> 立即抢购 <<<", 30, RED, True, False),
    ])

    return fixtures


def call_vlm(image_path: str, width: int, height: int, targets: list[str]) -> list[dict]:
    """调 VLM 请求目标 bbox；失败返回空列表（由调用方记录 error）。"""
    from openai import OpenAI
    from src.utils.config import settings

    if not settings.dashscope_api_key:
        raise SystemExit("DASHSCOPE_API_KEY 未配置，spike 无法执行")
    data = Path(image_path).read_bytes()
    data_url = f"data:image/png;base64,{base64.b64encode(data).decode()}"
    client = OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
    )
    prompt = (
        f"图片尺寸 {width}x{height} 像素。请定位以下目标并输出像素坐标边界框："
        + json.dumps(targets, ensure_ascii=False)
    )
    resp = client.chat.completions.create(
        model=settings.vlm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        temperature=0.0,
    )
    content = (resp.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = content.strip("`").lstrip("json").strip()
    try:
        obj = json.loads(content[content.index("{"): content.rindex("}") + 1])
        return [b for b in obj.get("boxes", []) if isinstance(b, dict)]
    except (ValueError, json.JSONDecodeError):
        return []


def iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _decode_variants(pred: list[float], w: int, h: int) -> dict[str, list[float]]:
    """三种坐标约定解码（取最优——能力评估取最宽容解码）。"""
    return {
        "pixel": list(pred),
        "norm1000": [v / 1000 * d for v, d in zip(pred, (w, h, w, h), strict=False)],
        "norm1": [pred[0] * w, pred[1] * h, pred[2] * w, pred[3] * h],
    }


def _vlm_model_name() -> str:
    from src.utils.config import settings

    return getattr(settings, "vlm_model", "unknown")


def main() -> None:
    fixtures = build_fixtures()
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    per_target: list[dict] = []

    for fx in fixtures:
        img = Image.open(fx["path"])
        w, h = img.size
        try:
            boxes = call_vlm(fx["path"], w, h, [t["text"] for t in fx["targets"]])
        except Exception as exc:  # noqa: BLE001
            print(f"[{fx['name']}] 调用失败: {exc}")
            for t in fx["targets"]:
                per_target.append({"image": fx["name"], "text": t["text"], "error": str(exc)})
            continue

        draw = ImageDraw.Draw(img)
        for t in fx["targets"]:
            # 按文本匹配模型返回的 box（去空格/百分号差异）
            key = t["text"].replace(" ", "").replace("%", "")
            match = next(
                (
                    b
                    for b in boxes
                    if str(b.get("text", "")).replace(" ", "").replace("%", "") == key
                ),
                None,
            )
            if match is None or not isinstance(match.get("bbox"), list) or len(match["bbox"]) != 4:
                per_target.append(
                    {"image": fx["name"], "text": t["text"], "iou": 0.0, "note": "未返回该目标"}
                )
                print(f"[{fx['name']}] {t['text']}: 未返回 bbox")
                continue
            pred = [float(v) for v in match["bbox"]]
            variants = _decode_variants(pred, w, h)
            ious = {k: round(iou(v, t["gt"]), 3) for k, v in variants.items()}
            best_k = max(ious, key=ious.get)
            best = variants[best_k]
            per_target.append({
                "image": fx["name"],
                "text": t["text"],
                "gt": t["gt"],
                "pred_raw": pred,
                "iou_by_convention": ious,
                "best_convention": best_k,
                "iou": ious[best_k],
            })
            # 标注图：绿=ground truth，红=预测（best）
            draw.rectangle(t["gt"], outline=(0, 160, 0), width=3)
            draw.rectangle([round(v) for v in best], outline=(220, 0, 0), width=3)
            print(f"[{fx['name']}] {t['text']}: IoU={ious[best_k]} (约定 {best_k}) 各约定 {ious}")
        img.save(OVERLAY_DIR / f"{fx['name']}_overlay.png")

    ok = [t for t in per_target if t.get("iou", 0) >= 0.5]
    strict = [t for t in per_target if t.get("iou", 0) >= 0.8]
    n = len(per_target)
    hit_rate = len(ok) / n if n else 0.0
    strict_rate = len(strict) / n if n else 0.0
    verdict = "PASS" if (hit_rate >= 0.8 and strict_rate > 0.5) else "FAIL"

    report = {
        "vlm_model": _vlm_model_name(),
        "prompt_variant": "tight" if _TIGHT else "default",
        "targets": per_target,
        "hit_rate_iou50": round(hit_rate, 3),
        "strict_rate_iou80": round(strict_rate, 3),
        "verdict": verdict,
        "note": "解码取最宽容约定（pixel/norm1000/norm1）；判据：命中率≥0.8 且严格率>0.5",
    }
    report_name = "bbox_report_tight.json" if _TIGHT else "bbox_report.json"
    (OUT_DIR / report_name).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print()
    print(
        f"目标数 {n} | 命中(IoU≥0.5) {len(ok)} ({hit_rate:.0%})"
        f" | 严格(IoU≥0.8) {len(strict)} ({strict_rate:.0%})"
    )
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
