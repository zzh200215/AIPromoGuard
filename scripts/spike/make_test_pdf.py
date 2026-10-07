"""Spike 素材：合成含复杂表格的金融营销 PDF（MinerU 解析质量测试用）.

合成 2 页营销材料风 PDF：封面海报（大字数字+装饰）+ 收益演示表页
（跨行表头/合并单元格式布局/小字风险提示）。ground truth 在脚本尾部打印。

用法："D:/AI/ACD/envs/llmXM/python.exe" scripts/spike/make_test_pdf.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[2] / "data" / "spike_mineru"
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_BD = r"C:\Windows\Fonts\msyhbd.ttc"


def _f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BD if bold else FONT, size)


def page1() -> Image.Image:
    """封面海报页：大字数字 + 金色装饰 + 底部小字。"""
    img = Image.new("RGB", (1240, 1754), (255, 255, 255))  # A4 @150dpi
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1240, 220], fill=(15, 60, 120))
    d.text((60, 70), "XX稳健理财1号（第3期）", font=_f(64, True), fill=(255, 255, 255))
    d.text((60, 300), "近一年年化收益率", font=_f(48), fill=(60, 60, 60))
    d.text((60, 380), "3.85%", font=_f(180, True), fill=(200, 30, 30))
    d.text((60, 650), "业绩比较基准（年化）3.50% - 4.50%", font=_f(40), fill=(60, 60, 60))
    d.text((60, 730), "最低认购金额 50,000 元    持有期限 366 天", font=_f(40), fill=(60, 60, 60))
    d.rectangle([60, 830, 1180, 1000], outline=(180, 140, 30), width=4)
    d.text((100, 870), "★ 认购期：2026年10月8日 至 2026年10月15日 ★", font=_f(42, True), fill=(180, 140, 30))
    d.text((60, 1600), "风险提示：本产品为非保本浮动收益产品，过往业绩不代表未来表现。市场有风险，投资须谨慎。",
           font=_f(28), fill=(130, 130, 130))
    d.text((60, 1650), "产品管理人：XX基金管理有限公司    产品登记编码：C1234567890123",
           font=_f(28), fill=(130, 130, 130))
    return img


def page2() -> Image.Image:
    """收益演示表页：两段表格 + 表头行 + 小字脚注——表格还原的核心考点。"""
    img = Image.new("RGB", (1240, 1754), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((60, 60), "收益演示表（认购金额：100,000 元）", font=_f(48, True), fill=(30, 30, 30))

    # 表 1：按持有期收益演示
    cols = [(60, 460), (460, 760), (760, 1000), (1000, 1180)]
    rows = [
        ("持有时间", "管理费率", "预期收益（元）", "期末金额（元）"),
        ("90 天", "1.20%", "925.00", "100,925.00"),
        ("180 天", "1.20%", "1,868.00", "101,868.00"),
        ("366 天", "1.20%", "3,846.00", "103,846.00"),
    ]
    y = 180
    for ri, row in enumerate(rows):
        bold = ri == 0
        fill = (240, 244, 250) if ri == 0 else (255, 255, 255) if ri % 2 else (250, 250, 250)
        for (x1, x2), cell in zip(cols, row):
            d.rectangle([x1, y, x2, y + 70], fill=fill, outline=(180, 180, 180), width=1)
            d.text((x1 + 14, y + 18), cell, font=_f(30, bold), fill=(30, 30, 30))
        y += 70

    d.text((60, y + 60), "不同情景下的年化收益率演示", font=_f(42, True), fill=(30, 30, 30))
    cols2 = [(60, 400), (400, 660), (660, 920), (920, 1180)]
    rows2 = [
        ("情景", "乐观", "中性", "悲观"),
        ("年化收益率", "4.20%", "3.85%", "2.10%"),
        ("对应收益（元）", "4,200.00", "3,850.00", "2,100.00"),
    ]
    y2 = y + 140
    for ri, row in enumerate(rows2):
        bold = ri == 0
        fill = (240, 244, 250) if ri == 0 else (255, 255, 255) if ri % 2 else (250, 250, 250)
        for (x1, x2), cell in zip(cols2, row):
            d.rectangle([x1, y2, x2, y2 + 70], fill=fill, outline=(180, 180, 180), width=1)
            d.text((x1 + 14, y2 + 18), cell, font=_f(30, bold), fill=(30, 30, 30))
        y2 += 70

    d.text((60, y2 + 80), "注1：上述演示收益为测算值，不代表未来实际收益，不构成收益承诺。",
           font=_f(26), fill=(130, 130, 130))
    d.text((60, y2 + 125), "注2：管理费率 1.20%/年，托管费率 0.25%/年，已在收益测算中扣除。",
           font=_f(26), fill=(130, 130, 130))
    d.text((60, y2 + 170), "注3：测算公式：预期收益 = 认购金额 × 年化收益率 × 持有天数 / 365。",
           font=_f(26), fill=(130, 130, 130))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "test_marketing.pdf"
    page1().save(p, "PDF", save_all=True, append_images=[page2()], resolution=150)
    print(f"saved: {p}")
    print("ground truth:")
    print("  页1: 大字 3.85% / 区间 3.50%-4.50% / 50,000 元 / 366 天 / 认购期 2026.10.08-10.15 / 编码 C1234567890123")
    print("  页2 表1(4列x4行,含表头): 90/180/366 天, 1.20%, 925.00/1,868.00/3,846.00, 100,925.00/101,868.00/103,846.00")
    print("  页2 表2(4列x3行,含表头): 乐观4.20%/中性3.85%/悲观2.10%, 4,200.00/3,850.00/2,100.00")
    print("  页2 脚注: 1.20% 0.25% 公式文字")


if __name__ == "__main__":
    main()
