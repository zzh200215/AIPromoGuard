"""为"没有法规依据"的规则回填 related_regulations（提案制，默认只打印）。

背景（2026-10-22 实测）：79 条现役规则里 **29 条（37%）的 `rule_content.related_regulations`
为空**——它们全是挖掘流水线产出的规则。后果是这些规则一旦命中，报告里"依据"一栏空白，
拉低引用支撑率（同一份材料按 `regulation` 统计 38%，合并口径 81%，差额就来自这里）。

做法（零 LLM、零配额）：
1. 取 `status=active and is_active=1` 且 related_regulations 为空的规则；
2. 用规则名 + 描述 + 首个正则片段拼成查询，走**向量语义检索**取 Top-N 条款；
3. 距离低于阈值才作为提案（`《法规名》第X条`），否则标记"需人工"；
4. 默认 dry-run 打印；`--apply` 才写库，且先把旧值 dump 到 data/eval/ 便于回滚。

用法：
    python scripts/maintenance/backfill_rule_citations.py --dry-run
    python scripts/maintenance/backfill_rule_citations.py --apply
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.infrastructure.embedding import get_embedder  # noqa: E402
from src.infrastructure.vectorstore import get_vector_store  # noqa: E402
from src.models import Rule  # noqa: E402

COLLECTION = "legal_articles"

# 关键词重合校验用：规则名里的高频虚词/通用词，不能作为"对口"证据
_STOP = {
    "禁止", "不得", "表述", "使用", "进行", "相关", "产品", "金融", "机构",
    "行为", "情形", "规定", "管理", "应当", "以及", "或者", "有关",
}
# 连接词：按它切开规则名，才能得到"保本""刚性兑付"这类真正有区分度的词
_SPLIT = re.compile(
    r"禁止|不得|严禁|或者|以及|或|及|与|和|的|等|中|表述|使用|宣传|进行|有关|相关|规定|行为"
)


def _keywords(rule_name: str) -> list[str]:
    """从规则名切出 2 字以上的关键词（按连接词切、去虚词），用于"条款是否真的对口"。"""
    parts = [p for p in _SPLIT.split(rule_name or "") if len(p) >= 2]
    return [p for p in parts if p not in _STOP]


def _keyword_hit(rule_name: str, content: str) -> bool:
    """条款正文里至少出现一个规则关键词，才算"对口"。

    动机：纯向量匹配会被字面撞车骗过——"禁止混淆投资收益与存款本息"曾匹配到
    《存款保险条例》第十七条（讲存款保险基金管理机构的建议权），只因都含"存款"。
    """
    kws = _keywords(rule_name)
    if not kws:
        return True  # 抽不出关键词时不设卡，交给人看
    return any(k in (content or "") for k in kws)


def _query_of(rule: Rule) -> str:
    """规则 → 检索查询：规则名 + 描述 + 首个正则片段（去掉正则元字符）。"""
    parts = [rule.rule_name or ""]
    if rule.description:
        parts.append(rule.description)
    content = rule.rule_content if isinstance(rule.rule_content, dict) else {}
    for cond in content.get("conditions") or []:
        pat = (cond or {}).get("pattern") or ""
        if pat:
            cleaned = re.sub(r"[\[\](){}|\\^$*+?.]", " ", pat)
            parts.append(re.sub(r"\s+", " ", cleaned).strip()[:80])
            break
    return " ".join(p for p in parts if p).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="规则法规引用回填（默认 dry-run）")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", dest="do_apply", action="store_true")
    ap.add_argument("--top-n", type=int, default=3, help="每规则取前 N 个候选")
    ap.add_argument("--max-distance", type=float, default=0.42, help="余弦距离阈值，越小越严")
    ap.add_argument(
        "--skip-flagged",
        action="store_true",
        help="跳过关键词校验未通过的提案（⚠ 待核），只写通过校验的那批",
    )
    args = ap.parse_args()

    db = SessionLocal()
    store, embedder = get_vector_store(), get_embedder()
    rules = db.query(Rule).filter(Rule.status == "active", Rule.is_active == 1).all()

    todo = []
    for r in rules:
        content = r.rule_content if isinstance(r.rule_content, dict) else {}
        if not (content.get("related_regulations") or []):
            todo.append(r)

    print(f"现役规则 {len(rules)} 条，无引用 {len(todo)} 条，阈值 distance<={args.max_distance}\n")

    proposals, manual = [], []
    for r in todo:
        q = _query_of(r)
        vec = embedder.embed([q])[0]
        hits = store.query(COLLECTION, vec, top_k=args.top_n)
        picked = [h for h in hits if (1 - h["score"]) <= args.max_distance]
        if not picked:
            manual.append((r, hits[0] if hits else None))
            continue
        best = picked[0]
        label = f"《{best['metadata']['regulation_name']}》{best['metadata']['article_no']}"
        proposals.append(
            (
                r,
                label,
                1 - best["score"],
                picked,
                _keyword_hit(r.rule_name, best.get("document") or ""),
            )
        )

    print(f"=== 可自动回填 {len(proposals)} 条 ===")
    for r, label, dist, _, kw_ok in proposals:
        flag = "" if kw_ok else "  ⚠ 待核(条款正文无规则关键词)"
        print(f"  #{r.id} {r.rule_name[:22]:24s} → {label[:44]}  (d={dist:.3f}){flag}")
    print(f"\n=== 需人工 {len(manual)} 条（无候选低于阈值）===")
    for r, best in manual:
        d = f"d={1 - best['score']:.3f}" if best else "无候选"
        if best:
            near = f"《{best['metadata']['regulation_name']}》{best['metadata']['article_no']}"
        else:
            near = "-"
        print(f"  #{r.id} {r.rule_name[:22]:24s} 最近: {near[:40]} ({d})")

    if not args.do_apply:
        print("\n[dry-run] 未写库。确认后加 --apply 执行（会先把旧值 dump 到 data/eval/）。")
        db.close()
        return

    to_apply = [p for p in proposals if p[4]] if args.skip_flagged else proposals

    backup_path = Path("data/eval") / f"rule_citations_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(
        json.dumps(
            [{"rule_id": r.id, "rule_content": r.rule_content} for r, _, _, _, _ in to_apply],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for rule, _label, _dist, picked, _kw_ok in to_apply:
        content = dict(rule.rule_content or {})
        # 主引用 + Top3 备选（证据卡可展开看多条依据）
        content["related_regulations"] = [
            f"《{h['metadata']['regulation_name']}》{h['metadata']['article_no']}" for h in picked
        ]
        rule.rule_content = content
    db.commit()
    print(f"\n已回填 {len(to_apply)} 条规则（跳过 {len(proposals) - len(to_apply)} 条⚠待核）；"
          f"旧值备份：{backup_path}")
    db.close()


if __name__ == "__main__":
    main()
