"""引用可支撑率审计（零 API 配额）：对历史完成报告重算支撑率并归因。

背景：首战实测网关 RPM≈3，重跑评估集（judge.py 需逐例 LLM 审查）不可行。
本工具换路径——用**已有报告**（DB 151 个完成任务）+ **本地重跑召回**
（regulation_match 走本地 embedding，零配额）重算 citation_supported，
并对"不可支撑"案例做三类归因：

  归因 A 口径假阴性：引用名与召回名仅存在名称变体差异（暂行/试行/空格/全称简称）
         → 修 evidence 匹配逻辑即可
  归因 B 召回缺失：引用名在知识库全量检索可命中（法规真实存在）但不在该任务
         top-k 召回上下文 → 修召回（GraphRAG 直达 / top-k）
  归因 C 库外引用：引用名在库内检索不到（含"真实法规未入库"与"模型幻觉"两种，
         输出清单供人工研判）→ 修库扩覆盖或修提示词

用法（仓库根目录）：
    python scripts/evaluate/citation_audit.py --limit 10   # 小样本
    python scripts/evaluate/citation_audit.py              # 全量（较慢）
输出：
    data/eval/citation_audit.json（统计 + 逐条案例）+ 终端摘要
"""

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.agents.nodes.regulation_match import regulation_match  # noqa: E402
from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.models import ReviewTask  # noqa: E402
from src.services import evidence, regulation_service  # noqa: E402
from src.services.evidence import citation_supported  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "data" / "eval" / "citation_audit.json"
MATCHED_CAP = 400  # 单文本重跑召回的处理上限（与生产同源逻辑）

_VARIANT_NOISE = re.compile(r"[（(].*?[)）]|暂行办法|暂行规定|试行|实施|修订|^\s*《|》\s*$")


def _normalize(name: str) -> str:
    """名称归一化：去括号注释/暂行/试行/书名号/空白 —— 仅用于归因判断，不改生产口径。"""
    s = _VARIANT_NOISE.sub("", name or "")
    return re.sub(r"\s+", "", s)


def _extract_cites(finding: dict) -> str:
    return (finding.get("regulation") or "").strip()


def _name_in_citation(name: str, citation: str) -> bool:
    return bool(name) and (name in citation)


def audit_one(db, task: ReviewTask) -> dict | None:
    report_path = Path(task.report_path or "")
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    findings = [
        v for v in (report.get("violations") or [])
        if v.get("source") in ("llm", "hybrid") and _extract_cites(v)
    ]
    if not findings:
        return None

    doc_path = Path(task.document_path or "")
    if not doc_path.exists():
        return None
    text = doc_path.read_text(encoding="utf-8", errors="ignore")[:MATCHED_CAP * 40]

    # 本地重跑召回（同源逻辑；零 API 配额）
    matched = regulation_match({"text": text, "domain": task.domain})
    articles = matched.get("matched_articles") or []
    recalled_names = [str(a.get("regulation_name") or "").strip("《》") for a in articles]

    # 新口径：生产已改为"每条结论各自的证据池"（conflict_resolve 里的 per-finding 检索），
    # 审计必须同步，否则会把"本条自己检索到的依据"仍判为不可支撑（口径假阴性）。
    per_finding = evidence.retrieve_for_findings(findings)

    items = []
    for idx, f in enumerate(findings):
        citation = _extract_cites(f)
        supported_doc = citation_supported(f, articles)
        own_pool = articles + (per_finding[idx] if idx < len(per_finding) else [])
        supported = citation_supported(f, own_pool)
        own = per_finding[idx] if idx < len(per_finding) else []
        item = {
            "original_text": (f.get("original_text") or "")[:60],
            "citation": citation[:120],
            "supported": supported,
            "supported_doc_only": supported_doc,
            "own_evidence": [f"《{h.get('regulation_name')}》{h.get('article_no')}" for h in own],
        }
        items.append(item)
        if supported is False:
            # 归因：A 口径假阴性 → 归一化后命中任一召回名
            cit_norm = _normalize(citation)
            if any(n and _normalize(n) and _normalize(n) in cit_norm for n in recalled_names):
                item["attribution"] = "A_variant_match"
            else:
                # B 召回缺失（库内有）/ C 库外引用（库内无，待人工研判真实法规未入库 or 幻觉）
                probe = re.split(r"[\s第]", citation.replace("《", "").replace("》", ""))[0][:30]
                hit = False
                try:
                    found = regulation_service.search_keyword(db, probe, None, top_k=3)
                    hit = bool(found)
                except Exception:
                    pass
                item["attribution"] = "B_recall_miss" if hit else "C_library_gap"
        items.append(item)

    n_checked = sum(1 for i in items if i["supported"] is not None)
    n_support = sum(1 for i in items if i["supported"] is True)
    n_doc_checked = sum(1 for i in items if i["supported_doc_only"] is not None)
    n_doc_support = sum(1 for i in items if i["supported_doc_only"] is True)
    return {
        "task_id": task.id,
        "document_name": task.document_name,
        "domain": task.domain,
        "recalled_count": len(articles),
        "checked": n_checked,
        "supported": n_support,
        "support_rate": round(n_support / n_checked, 3) if n_checked else None,
        # 旧口径（仅整篇召回池）对照，便于说明"改了什么、涨了多少"
        "checked_doc_only": n_doc_checked,
        "supported_doc_only": n_doc_support,
        "support_rate_doc_only": round(n_doc_support / n_doc_checked, 3) if n_doc_checked else None,
        "items": items,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="只审计最近 N 个完成任务的报告")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = (
            db.query(ReviewTask)
            .filter(ReviewTask.status == "completed", ReviewTask.report_path.isnot(None))
            .order_by(ReviewTask.id.desc())
        )
        tasks = q.limit(args.limit).all() if args.limit else q.all()
        print(f"待审计完成任务数: {len(tasks)}")

        results, skipped = [], 0
        for i, t in enumerate(tasks, 1):
            try:
                r = audit_one(db, t)
            except Exception as exc:
                print(f"  [{i}] #{t.id} 审计异常: {exc}")
                traceback.print_exc()
                continue
            if r is None:
                skipped += 1
                continue
            results.append(r)
            if i % 10 == 0:
                print(f"  ...已审计 {i}/{len(tasks)}")

        total_checked = sum(r["checked"] for r in results)
        total_support = sum(r["supported"] for r in results)
        attr = {}
        for r in results:
            for item in r["items"]:
                if item.get("attribution"):
                    attr[item["attribution"]] = attr.get(item["attribution"], 0) + 1

        summary = {
            "audited_tasks": len(results),
            "skipped_tasks": skipped,
            "checked_findings": total_checked,
            "supported_findings": total_support,
            "support_rate": round(total_support / total_checked, 3) if total_checked else None,
            "attribution": attr,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps({"summary": summary, "tasks": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("\n=== 审计摘要 ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"\n输出: {OUT}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
