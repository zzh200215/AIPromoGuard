"""公开营销材料一次性收集（合规审查验证用素材库）。

用途：从**公开可访问**的页面收集真实金融营销相关材料（银行/基金/保险），
保存为 txt 供审查系统上传做首次实战验证。性质说明：
- **一次性归档**（非持续抓取/非第三方监控，不触犯巡检"已授权自有渠道"红线）；
- 仅公开页面（无登录/无付费墙/不做反爬对抗）；
- 来源 URL 与抓取时间记录于 manifest.json，全程可溯源；
- 抓取复用 content_patrol.fetch_published（同口径的正文转文本）。

用法（仓库根目录）：
    python scripts/crawl/collect_marketing.py                # 抓取全部候选
    python scripts/crawl/collect_marketing.py --only bank    # 仅银行类
    python scripts/crawl/collect_marketing.py --delay 3      # 请求间隔（默认 2s）

输出：
    data/real_materials/{type}_{nn}_{slug}.txt  材料正文
    data/real_materials/manifest.json           来源与结果清单
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from src.services.content_patrol import fetch_published  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "real_materials"

# 候选源（2026-10-12 检索；机构/媒体公开页面。type: bank/fund/insurance）
SOURCES: list[dict] = [
    # ---- 银行 / 存款 / 理财 ----
    {"type": "bank", "url": "https://new.qq.com/rain/a/20260908A0A7WC00",
     "note": "银行理财选择指南（腾讯网软文）"},
    {"type": "bank", "url": "https://news.qq.com/rain/a/20260212A048VS00",
     "note": "春节理财攻略（腾讯新闻）"},
    {"type": "bank", "url": "https://shenlanbao.com/wenda/topics/1085686",
     "note": "银行理财产品分类科普（深蓝保）"},
    {"type": "bank", "url": "https://news.qq.com/rain/a/20260226A0203Z00",
     "note": "银行春节专属理财产品（腾讯新闻）"},
    {"type": "bank", "url": "https://finance.cctv.com/2026/07/30/ARTIiYLJQIuAGIk2Yjg12re2260730.shtml",
     "note": "5年期大额存单（央视网财经）"},
    {"type": "bank", "url": "https://finance.sina.com.cn/jinrong/yh/2026-10-09/doc-iniurruh1067291.shtml",
     "note": "大额存单2%利率（新浪财经）"},
    {"type": "bank", "url": "http://www.ce.cn/xwzx/gnsz/gdxw/202608/t20260804_3126848.shtml",
     "note": "大行重启5年期大额存单（中国经济网）"},
    # ---- 基金 / 销售 / 费率 ----
    {"type": "fund", "url": "https://new.qq.com/rain/a/20260915A05RI900",
     "note": "基金长跑业绩推介（九派财经/腾讯网）"},
    {"type": "fund", "url": "https://news.qq.com/rain/a/20261002A07YJM00",
     "note": "公募长跑成绩单（中国基金报转载）"},
    {"type": "fund", "url": "https://new.qq.com/rain/a/20251120A05H3J00",
     "note": "常胜牛基业绩盘点（腾讯网）"},
    {"type": "fund", "url": "https://epaper.cs.com.cn/zgzqb/html/2026-05/21/nw.D110000zgzqb_20260521_7-B053.htm",
     "note": "基金费率优惠公告（中国证券报）"},
    {"type": "fund", "url": "https://epaper.cs.com.cn/zgzqb/wap/html/2026-01/20/nw.D110000zgzqb_20260120_5-B042.htm",
     "note": "基金0折费率公告（中国证券报）"},
    {"type": "fund", "url": "http://i3.ce.cn/finance/jjpd/jjpdgd/202601/t20260109_2690613.shtml",
     "note": "基金降费让利报道（中国经济网）"},
    # ---- 保险 / 增额寿 / 分红年金 ----
    {"type": "insurance", "url": "https://www.financialnews.com.cn/2025-05/14/content_424986.html",
     "note": "增额终身寿险科普（中国金融新闻网）"},
    {"type": "insurance", "url": "https://nbb.ycbrokers.com/wenda/26593.html",
     "note": "增额寿产品推介（奶爸保）"},
    {"type": "insurance", "url": "https://www.naibabao.com/ketang/56611.html",
     "note": "增额寿排名与收益对比（奶爸保）"},
    {"type": "insurance", "url": "https://m.naibabao.com/wenda/26535.html",
     "note": "增额寿产品对比（奶爸保）"},
    {"type": "insurance", "url": "https://www.pulanbx.com/bxzs/228292.html",
     "note": "增额寿实测对比（谱蓝保）"},
    {"type": "insurance", "url": "https://app.xinhuanet.com/news/article.html?articleId=5ff46304dd93294c8e90ca2d27a13ebe",
     "note": "中国人寿分红险品宣稿（新华网客户端）"},
    {"type": "insurance", "url": "https://www.news.cn/money/20251127/abaa295a100140aab65b81cdc40794a5/c.html",
     "note": "人保寿险分红年金品宣稿（新华网）"},
    {"type": "insurance", "url": "https://caijing.chinadaily.com.cn/a/202608/20/WS6a86a742a3105d3d7a27bfe0.html",
     "note": "中荷人寿年金险品宣稿（中国日报网）"},
    {"type": "insurance", "url": "https://m.eeo.com.cn/2026/0220/798617.shtml",
     "note": "分红险销售实务深度（经济观察报）"},
]


def _slug(text: str, fallback: str) -> str:
    """从正文首行提取文件名 slug（中文保留，长度受限）。"""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    core = re.sub(r"[\\/:*?\"<>|\s]+", "", first)[:30]
    return core or fallback


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["bank", "fund", "insurance"], help="只抓某一类")
    ap.add_argument("--delay", type=float, default=2.0, help="请求间隔秒数（默认 2s）")
    args = ap.parse_args()

    sources = [s for s in SOURCES if not args.only or s["type"] == args.only]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    counters: dict[str, int] = {}
    ok = fail = 0

    for i, src in enumerate(sources, 1):
        counters[src["type"]] = counters.get(src["type"], 0) + 1
        seq = counters[src["type"]]
        print(f"[{i}/{len(sources)}] {src['type']}#{seq} {src['url']}")
        try:
            text = fetch_published(src["url"])
        except Exception as exc:  # 单源失败不中断（记 manifest 供补抓）
            print(f"    FAIL: {exc}")
            manifest.append({**src, "status": "fail", "error": str(exc)})
            fail += 1
            time.sleep(args.delay)
            continue

        fname = f"{src['type']}_{seq:02d}_{_slug(text, 'material')}.txt"
        (OUT_DIR / fname).write_text(text, encoding="utf-8")
        manifest.append({
            **src,
            "file": fname,
            "status": "ok",
            "chars": len(text),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        })
        print(f"    OK {len(text)} chars -> {fname}")
        ok += 1
        time.sleep(args.delay)

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "collected_at": datetime.now().isoformat(timespec="seconds"),
                "purpose": "公开营销材料一次性归档（合规审查验证）；来源 URL 可溯",
                "total": len(sources),
                "ok": ok,
                "fail": fail,
                "items": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n完成：成功 {ok} / 失败 {fail}；清单 {manifest_path}")


if __name__ == "__main__":
    main()
