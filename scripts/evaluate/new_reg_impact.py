"""新法规入库的效果验证：以《金融产品网络营销管理办法》为例。

做法（全部确定性，零 LLM 调用、零配额）：
1. 构造 10 条"网络营销典型违规表述"探针，每条人工标注它应命中的条款；
2. 对每条探针跑**混合检索**（hybrid），记录 Top-K 命中的法规；
3. 用"剔除该法规"的方式模拟入库前的状态，对比**覆盖缺口**；
4. 顺带用 `RuleScanner` 跑一遍活跃规则，看规则引擎能独立覆盖多少（区分"靠规则"还是"靠法规检索"）。

输出：控制台表格 + `data/eval/new_reg_impact_<法规简称>.json`

用法：
    python scripts/evaluate/new_reg_impact.py
    python scripts/evaluate/new_reg_impact.py --topk 5 --json data/eval/xxx.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from src.core.agents.nodes.regulation_match import regulation_match  # noqa: E402
from src.core.rule_engine.engine import RuleScanner  # noqa: E402
from src.infrastructure.embedding import get_embedder  # noqa: E402
from src.infrastructure.vectorstore import get_vector_store  # noqa: E402
from src.models import Rule  # noqa: E402
from src.parsers.base import TextBlock  # noqa: E402
from src.services import regulation_service  # noqa: E402
from src.utils.config import settings  # noqa: E402

TARGET = "金融产品网络营销管理办法"

# (探针文本, 期望条款, 说明)
PROBES: list[tuple[str, str, str]] = [
    ("本产品保本保收益，年化收益6.8%，稳赚不赔，闭眼买入", "第十条", "保本/承诺收益"),
    ("全网最强理财产品，收益碾压同行，数据来自内部测算", "第十条", "虚假或未经核实的数据"),
    ("直播带货金融产品，主播口播承诺保本高收益，无任何风险提示", "第七条",
     "营销内容审核与风险提示"),
    ("点击支付页面即可直接购买理财产品，无需跳转银行APP", "第十二条", "支付工具不得承载资管营销"),
    ("本平台未取得金融业务资质，代为推广小额贷款产品", "第六条", "为非法金融活动提供营销"),
    ("限时秒杀，仅限本省客户（页面未提示经营区域限制）", "第五条", "许可范围与区域限制提示"),
    ("本机构理财产品仅在第三方平台展示，官网无任何披露", "第九条", "官方渠道披露义务"),
    ("宣传材料风险提示用小字置底，产品名称与合同不一致", "第八条", "内容须与合同一致且醒目"),
    ("股票配资，十倍杠杆，稳赚不赔，加微信详聊", "第六条", "非法金融活动网络营销"),
    ("首月0利率，后续利率以实际为准（未披露真实年化成本）", "第八条", "关键信息须清晰准确"),
]

MARKETING_KW = ("营销", "宣传", "推介", "广告", "销售", "信息披露", "消费者")

# 合成材料：直播带货金融产品话术（既含新规覆盖的行为，也含规则引擎能抓的老问题）
DOC_TEXT = (
    "【直播话术】各位家人晚上好！今天给大家带来一款王牌理财，"
    "本产品保本保收益，年化收益6.8%，稳赚不赔，闭眼买入就行。"
    "全网最强理财产品，收益碾压同行，数据来自我们内部测算。"
    "直播间下单更方便，点击支付页面即可直接购买理财产品，无需跳转银行APP。"
    "本场限时秒杀，仅限本省客户，先到先得。"
    "首月0利率，后续利率以实际为准。"
    "我们平台虽然没有金融业务资质，但可以代为推广小额贷款产品，利息很低。"
    "宣传页面的风险提示用小字放在最底部，产品名称以直播间口径为准。"
)



def _is_marketing_reg(name: str) -> bool:
    return any(k in (name or "") for k in MARKETING_KW)


def _semantic_without(db: Session, query: str, exclude_reg_id: int, top_k: int) -> list[dict]:
    """模拟"该法规尚未入库"：语义检索加 where regulation_id != exclude。"""
    store = get_vector_store()
    vec = get_embedder().embed([query])[0]
    res = store.query(
        "legal_articles", vec, top_k=top_k, where={"regulation_id": {"$ne": exclude_reg_id}}
    )
    return [
        {
            "regulation_name": r["metadata"].get("regulation_name", ""),
            "article_no": r["metadata"].get("article_no", ""),
            "score": r["score"],
        }
        for r in res
    ]


def doc_level_check(db: Session, scanner, active_rules, top_k: int) -> dict:
    """文档级验证：对齐生产口径（regulation_match 吃整篇材料前 800 字）。"""
    print("\n=== 文档级（合成直播话术，对齐 regulation_match 口径）===")
    print(f"材料长度 {len(DOC_TEXT)} 字（生产只取前 800 字做查询）")

    result = regulation_match({"text": DOC_TEXT, "domain": None})
    matched = result.get("matched_articles", [])[:top_k]
    print(f"\n整篇召回 Top{len(matched)}：")
    for a in matched:
        flag = "★" if a.get("regulation_name") == TARGET else " "
        print(
            f"  {flag} {a.get('regulation_name','')[:22]:24s} {a.get('article_no',''):6s} "
            f"{(a.get('content') or '')[:38]}"
        )
    target_cnt = sum(1 for a in matched if a.get("regulation_name") == TARGET)

    # 若无新规：语义通道排除该法规后的 Top5
    reg_id = db.execute(
        text("SELECT id FROM regulations WHERE regulation_name=:n"), {"n": TARGET}
    ).scalar()
    without = _semantic_without(db, DOC_TEXT[:800], reg_id, top_k) if reg_id else []
    print(f"\n若该法规未入库（语义通道排除后 Top{top_k}）：")
    for a in without:
        print(f"    {a['regulation_name'][:22]:24s} {a['article_no']:6s} score={a['score']:.3f}")

    # 查询扩写对照：材料口语是"直播带货"，法规术语是"网络营销"——术语错配能否被扩写补上
    expanded_query = (
        DOC_TEXT[:800] + " 网络营销 互联网营销 直播营销 宣传推介 营销内容 第三方互联网平台"
    )
    matched_exp = regulation_match({"text": expanded_query, "domain": None}).get(
        "matched_articles", []
    )[:top_k]
    exp_target = sum(1 for a in matched_exp if a.get("regulation_name") == TARGET)
    print(f"\n查询扩写后 Top{len(matched_exp)}（新规占 {exp_target} 条）：")
    for a in matched_exp:
        flag = "★" if a.get("regulation_name") == TARGET else " "
        print(
            f"  {flag} {a.get('regulation_name','')[:22]:24s} {a.get('article_no',''):6s} "
            f"{(a.get('content') or '')[:38]}"
        )

    # 规则引擎在这份材料上的检出
    dets = scanner.scan([TextBlock(text=DOC_TEXT)], active_rules)
    print(f"\n规则引擎检出 {len(dets)} 条：")
    for d in dets[:8]:
        print(f"    [{getattr(d, 'severity', '?')}] {getattr(d, 'rule_name', '')[:34]}")

    return {
        "doc_len": len(DOC_TEXT),
        "matched_top": [
            {
                "regulation_name": a.get("regulation_name"),
                "article_no": a.get("article_no"),
                "score": a.get("score"),
                "is_target": a.get("regulation_name") == TARGET,
            }
            for a in matched
        ],
        "target_in_top": target_cnt,
        "without_target_top": without,
        "expanded_target_in_top": exp_target,
        "expanded_top": [
            {
                "regulation_name": a.get("regulation_name"),
                "article_no": a.get("article_no"),
                "is_target": a.get("regulation_name") == TARGET,
            }
            for a in matched_exp
        ],
        "rule_hits": [
            {"rule_name": getattr(d, "rule_name", ""), "severity": getattr(d, "severity", "")}
            for d in dets
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="新法规入库效果验证")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    engine = create_engine(settings.mysql_url)
    db = Session(engine)

    scanner = RuleScanner()
    active_rules = db.query(Rule).filter(Rule.status == "active", Rule.is_active == 1).all()
    print(f"活跃规则 {len(active_rules)} 条 · 探针 {len(PROBES)} 条 · Top-{args.topk}\n")

    rows, after_hit, before_hit, rule_hit = [], 0, 0, 0
    for probe, expect, label in PROBES:
        hits = regulation_service.search(db, probe, "hybrid", None, args.topk)
        names = [h.get("regulation_name") or "" for h in hits]

        hit_after = TARGET in names
        # 入库前模拟：剔除目标法规，剩下的命中里还有没有"营销相关"法规可引
        others = [n for n in names if n != TARGET]
        hit_before = any(_is_marketing_reg(n) for n in others)

        # 规则引擎独立覆盖（不看法规检索）
        dets = scanner.scan([TextBlock(text=probe)], active_rules)
        hit_rule = bool(dets)

        after_hit += hit_after
        before_hit += hit_before
        rule_hit += hit_rule
        rows.append(
            {
                "probe": probe,
                "expect_article": expect,
                "label": label,
                "after_top": names,
                "hit_target": hit_after,
                "before_has_marketing_reg": hit_before,
                "rule_engine_hit": hit_rule,
                "rule_names": [getattr(d, "rule_name", "") for d in dets][:3],
            }
        )

    w = 34
    print(f"{'探针':<{w}} {'期望':<6} 新规命中 旧口径有替代 规则独立")
    for r in rows:
        p = (r["probe"][: w - 2] + "…") if len(r["probe"]) > w else r["probe"]
        print(
            f"{p:<{w}} {r['expect_article']:<6} "
            f"{'✓' if r['hit_target'] else '✗':<6} "
            f"{'✓' if r['before_has_marketing_reg'] else '✗':<10} "
            f"{'✓' if r['rule_engine_hit'] else '✗'}"
        )

    n = len(PROBES)
    print("\n=== 汇总 ===")
    print(f"新规 Top{args.topk} 命中率        : {after_hit}/{n} = {after_hit / n:.0%}")
    print(f"入库前(剔除新规)有营销类法规可引 : {before_hit}/{n} = {before_hit / n:.0%}")
    print(f"规则引擎独立覆盖                 : {rule_hit}/{n} = {rule_hit / n:.0%}")
    gap = sum(1 for r in rows if r["hit_target"] and not r["before_has_marketing_reg"])
    print(f"仅靠新规才有的覆盖缺口           : {gap} 条探针")

    doc = doc_level_check(db, scanner, active_rules, args.topk)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(
                {
                    "target": TARGET,
                    "topk": args.topk,
                    "total": n,
                    "after_hit": after_hit,
                    "before_hit": before_hit,
                    "rule_hit": rule_hit,
                    "gap": gap,
                    "rows": rows,
                    "doc_level": doc,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"报告已写入: {args.json}")

    db.close()


if __name__ == "__main__":
    main()
