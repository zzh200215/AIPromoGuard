"""Spike：VLM 数字读数准确率验证（R2-3 交叉篡改检测的前置立项判据）.

假设：qwen-vl 能可靠读出营销海报中的数字（准确率 >= 95%）。
方法：PIL 合成 10 张已知 ground truth 的测试海报（大字数字/表格数字/小字数字/
艺术化干扰各覆盖），逐张调 VLM 提取全部数字，比对计算：
  - 检出率 = 读对数字数 / 图中实际数字数（按值匹配，百分比数值归一后比）
  - 幻觉数 = VLM 报告但图中不存在的数字
输出：data/spike_vlm/report.json + 控制台摘要。

判据（R2-3 立项门禁）：
  数字级准确率 >= 95% 且幻觉总数 = 0  -> 立项（VLM 直读方案）
  否则                               -> 降级两段式（VLM 定位区域 + OCR 精读）或砍

用法（项目环境）：
  "D:/AI/ACD/envs/llmXM/python.exe" scripts/spike/vlm_number_reading.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT_DIR = ROOT / "data" / "spike_vlm"
FONT_PATHS = [
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",    # 加粗
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
]

SYSTEM_PROMPT = (
    "你是图像数字提取器。提取图中出现的所有数字（含百分比、金额、天数、日期），"
    '只输出 JSON：{"numbers": [{"value": "数字本身(不带单位)", '
    '"context": "该数字紧邻的文字标签(10字内)"}]}。'
    "严格只报图中真实可见的数字，禁止推测或补全。"
)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = ([FONT_PATHS[1]] if bold else []) + FONT_PATHS
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _poster(name: str, lines: list[tuple[str, int, tuple[int, int, int], bool]],
            w: int = 800, h: int = 1000, bg: tuple = (255, 255, 255)) -> Path:
    """按 (文本, 字号, 颜色, 加粗) 逐行画海报，返回保存路径。"""
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    y = 40
    for text, size, color, bold in lines:
        d.text((40, y), text, font=_font(size, bold), fill=color)
        y += int(size * 1.8)
    path = OUT_DIR / f"{name}.png"
    img.save(path)
    return path


def build_fixtures() -> list[dict]:
    """合成 10 张海报，返回 [{name, path, gt_numbers}]。gt = ground truth 数字集。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RED, DARK, GRAY, GOLD = (200, 30, 30), (30, 30, 30), (130, 130, 130), (180, 140, 30)
    fx = []

    def add(name: str, lines: list[tuple], gt: list[str]):
        p = _poster(name, lines)
        fx.append({"name": name, "path": str(p), "gt_numbers": gt})

    # 1. 大字单一利率（最理想场景）
    add("p01_big_rate", [
        ("XX稳健理财1号", 44, DARK, True),
        ("年化收益率", 36, DARK, False),
        ("3.85%", 110, RED, True),
        ("历史业绩不代表未来", 24, GRAY, False),
    ], gt=["3.85", "1"])

    # 2. 表格数字（本金/收益/合计）
    add("p02_table", [
        ("收益演示表", 40, DARK, True),
        ("期初本金  50000 元", 34, DARK, False),
        ("预期年化收益率  4.20 %", 34, DARK, False),
        ("持有期收益  2100 元", 34, DARK, False),
        ("期末合计  52100 元", 34, DARK, True),
    ], gt=["50000", "4.20", "2100", "52100"])

    # 3. 小字风险提示中的日期与费率
    add("p03_small_print", [
        ("XX基金宣传单", 42, DARK, True),
        ("管理费率 1.20% 托管费率 0.25%", 26, DARK, False),
        ("风险提示：本产品为R3级中风险产品，", 20, GRAY, False),
        ("过往业绩统计区间为2023年1月1日至2025年12月31日，", 20, GRAY, False),
        ("业绩比较基准年化为 3.50%-4.50%，不构成收益承诺。", 20, GRAY, False),
    ], gt=["1.20", "0.25", "3", "2023", "1", "1", "2025", "12", "31", "3.50", "4.50"])

    # 4. 艺术化金色大数字（干扰：金色渐变感 + 装饰符号）
    add("p04_artistic", [
        ("★ 限时专属 ★", 36, GOLD, True),
        ("七日年化", 30, DARK, False),
        ("7.2%", 130, GOLD, True),
        (">>> 立即抢购 <<<", 30, RED, True),
    ], gt=["7.2"])

    # 5. 期限+门槛组合
    add("p05_terms", [
        ("XX保险年金险", 44, DARK, True),
        ("最低投保门槛 1000 元", 32, DARK, False),
        ("持有期限 366 天", 32, DARK, False),
        ("演示利率 2.5%", 32, RED, True),
        ("保单编号示例 NO.20260388", 20, GRAY, False),
    ], gt=["1000", "366", "2.5", "20260388"])

    # 6. 多数字密集海报
    add("p06_dense", [
        ("XX灵活宝", 40, DARK, True),
        ("七日年化 2.35%", 36, RED, True),
        ("万份收益 0.6412 元", 30, DARK, False),
        ("1万元持有30天收益约 19.24 元", 28, DARK, False),
        ("近一年涨幅 2.41% 成立以来 3.12%", 24, GRAY, False),
    ], gt=["2.35", "0.6412", "1", "30", "19.24", "2.41", "3.12"])

    # 7. 深色底反白字（对比度场景）
    add("p07_dark_bg", [
        ("XX私人银行", 40, (255, 255, 255), True),
        ("专享年化 5.10%", 60, (255, 215, 0), True),
        ("认购起点 100 万元", 30, (220, 220, 220), False),
        ("名额有限 88 席", 30, (220, 220, 220), False),
    ], gt=["5.10", "100", "88"])

    # 8. 斜体/装饰框数字
    add("p08_italic", [
        ("XX月月盈", 42, DARK, True),
        ("┌─────────────┐", 30, GOLD, False),
        ("  预期年化 4.8%  ", 56, RED, True),
        ("└─────────────┘", 30, GOLD, False),
        ("每30天开放申赎", 24, GRAY, False),
    ], gt=["4.8", "30"])

    # 9. 含小数点与千分位
    add("p09_thousands", [
        ("XX券商收益凭证", 40, DARK, True),
        ("募集规模上限 3,000,000 元", 30, DARK, False),
        ("年化基准 3.15%", 44, RED, True),
        ("单笔认购下限 50,000 元", 26, GRAY, False),
    ], gt=["3,000,000", "3.15", "50,000"])

    # 10. 手机宣传图（小尺寸整体缩放，模拟低分辨率）
    p = _poster("p10_lowres_inner", [
        ("XX零钱宝", 34, DARK, True),
        ("年化 2.88%", 50, RED, True),
        ("1分钱起购", 26, GRAY, False),
    ], w=400, h=300)
    small = Image.open(p).resize((200, 150))
    lowres = OUT_DIR / "p10_lowres.png"
    small.save(lowres)
    (OUT_DIR / "p10_lowres_inner.png").unlink()
    fx.append({"name": "p10_lowres", "path": str(lowres), "gt_numbers": ["2.88", "1"]})

    return fx


def call_vlm(image_path: str) -> list[dict]:
    """调 qwen-vl 提取数字（复用项目 settings / OpenAI 兼容链路）。"""
    import base64

    from openai import OpenAI
    from src.utils.config import settings

    if not settings.dashscope_api_key:
        raise SystemExit("DASHSCOPE_API_KEY 未配置，spike 无法执行")
    data = Path(image_path).read_bytes()
    ext = "png"
    data_url = f"data:image/{ext};base64,{base64.b64encode(data).decode()}"
    client = OpenAI(api_key=settings.dashscope_api_key,
                    base_url=settings.llm_base_url, timeout=settings.llm_timeout)
    resp = client.chat.completions.create(
        model=settings.vlm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "提取图中全部数字"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        temperature=0.0,
    )
    content = resp.choices[0].message.content or ""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return [n for n in obj.get("numbers", []) if isinstance(n, dict)]
    except (ValueError, json.JSONDecodeError):
        return []


def norm(v: str) -> str:
    """数值归一：去千分位逗号/百分号/前导零，统一小数字符串比较。"""
    s = str(v).strip().replace(",", "").replace("%", "").replace("，", "")
    try:
        f = float(s)
        return f"{f:g}"
    except ValueError:
        return s


def main() -> None:
    fixtures = build_fixtures()
    total_gt, total_hit, total_hallu = 0, 0, 0
    per_image = []

    for f in fixtures:
        try:
            got = call_vlm(f["path"])
        except Exception as exc:  # noqa: BLE001
            per_image.append({"name": f["name"], "error": str(exc)})
            print(f"[{f['name']}] 调用失败: {exc}")
            continue
        got_vals = [norm(g.get("value", "")) for g in got if str(g.get("value", "")).strip()]
        gt_vals = [norm(g) for g in f["gt_numbers"]]
        hit = sum(1 for g in gt_vals if g in got_vals)
        hallu = [v for v in got_vals if v not in gt_vals]
        total_gt += len(gt_vals)
        total_hit += hit
        total_hallu += len(hallu)
        per_image.append({
            "name": f["name"], "gt_count": len(gt_vals), "hit": hit,
            "missed": [g for g in gt_vals if g not in got_vals],
            "hallucinated": hallu, "vlm_raw": got,
        })
        print(f"[{f['name']}] 检出 {hit}/{len(gt_vals)}"
              + (f" 幻觉: {hallu}" if hallu else ""))

    recall = total_hit / total_gt if total_gt else 0.0
    precision = total_hit / (total_hit + total_hallu) if (total_hit + total_hallu) else 0.0
    verdict = "PASS -> VLM 直读方案立项" if (recall >= 0.95 and total_hallu == 0) else \
              "FAIL -> 降级两段式（VLM 定位 + OCR 精读）或砍"
    summary = {
        "model_image_count": len(fixtures),
        "total_gt_numbers": total_gt, "total_hit": total_hit,
        "total_hallucinated": total_hallu,
        "number_recall": round(recall, 4), "number_precision": round(precision, 4),
        "verdict": verdict,
        "per_image": per_image,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n===== Spike 结论 =====")
    print(f"数字检出率: {recall:.1%} ({total_hit}/{total_gt})  "
          f"幻觉总数: {total_hallu}")
    print(f"判据: >=95% 且零幻觉\n结果: {verdict}")
    print(f"明细: {OUT_DIR / 'report.json'}")


if __name__ == "__main__":
    main()
