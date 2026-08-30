"""挖掘规则的对抗评估集生成 + 门禁验证（数据飞轮第四步）。

对挖掘产生的规则做"上考场"闭环：
1. 对每条规则让 LLM 生成 2-3 个"保义改写"违规样本（ground_truth 指向该规则）
   与 1 个合规负样本（negative_ground_truth，引擎命中即计误报）；
2. 用 evaluate.py 同款引擎跑 --engine rule 验证：自己规则的标注点必须 100%
   召回（改写后仍能检出），负样本零误报；
3. 不达标的规则自动退回 draft（is_active=0）并从评估集剔除——宁可规则少，
   不让弱规则混进审查引擎；
4. 幸存样本合并进 variant_cases.json（指纹去重，与既有对抗样本互不覆盖）。

人工审核兜底：--auto-activate 会把通过门禁的 draft 规则激活，等于用
"可机检证据"代替人工判断；未配置该开关时只验证已激活规则。

用法（仓库根目录，需 MySQL + DASHSCOPE_API_KEY）:
    python scripts/evaluate/gen_variants.py --auto-activate --limit 40
    python scripts/evaluate/gen_variants.py --verify-only   # 只重跑门禁不生成
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import importlib.util

_ROOT = Path(__file__).resolve().parents[2]
VARIANTS_JSON = _ROOT / "scripts" / "evaluate" / "variant_cases.json"
EVALUATE_PY = _ROOT / "scripts" / "evaluate" / "evaluate.py"


def _load_evaluate():
    """加载 evaluate.py 模块（与其单测同一 importlib 模式），复用引擎与指标口径。"""
    spec = importlib.util.spec_from_file_location("evaluate", EVALUATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_GENERATE_SYSTEM = """你是金融合规测试数据工程师。给定一条审查规则（违规表述模式），
生成营销文案测试样本：
1. variants：2-3 条"保义改写"的违规话术，换说法但仍然是同一种违规，
   规则必须能命中其中违规片段（片段原样出现在话术里）；
2. compliant：1 条合规表述，包含该主题的正常风险提示或否定语境，
   系统会验证任何规则都不应命中它。

只输出 JSON（不要其他文字、不要代码块）：
{"variants": ["违规话术1", "违规话术2"], "compliant": "合规表述"}
违规话术要像真实营销物料（带"本产品""预期""可达"等包装），不要照抄规则的
pattern 字面。"""


def _fingerprint(case: dict) -> str:
    blob = json.dumps(case.get("text") or "", ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _rule_pattern_text(rule) -> str:
    rc = rule.rule_content or {}
    parts: list[str] = []
    for cond in rc.get("conditions") or []:
        if cond.get("type") == "regex":
            parts.append(f"正则：{cond.get('pattern')}")
        elif cond.get("type") == "keyword":
            parts.append(f"关键词：{', '.join(cond.get('keywords') or [])}")
    return "；".join(parts)


def generate_for_rule(llm, rule) -> dict | None:
    """LLM 生成单条规则的变体样本，返回 case dict；失败返回 None。"""
    user = (
        f"规则名：{rule.rule_name}\n规则说明：{rule.description or ''}\n"
        f"匹配模式：{_rule_pattern_text(rule)}\n\n请生成测试样本："
    )
    try:
        raw = llm.chat(
            [
                {"role": "system", "content": _GENERATE_SYSTEM},
                {"role": "user", "content": user},
            ]
        )
    except Exception as exc:
        print(f"  ! LLM 失败: {type(exc).__name__}")
        return None
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    variants = [str(v).strip() for v in (data.get("variants") or []) if str(v).strip()]
    compliant = str(data.get("compliant") or "").strip()
    if len(variants) < 2 or not compliant:
        return None
    severity = rule.severity if rule.severity in ("high", "medium", "low") else "medium"
    text = "\n".join(variants)
    gt = [
        {"text": v, "rule_name": rule.rule_name, "risk_level": severity, "type": "禁止性"}
        for v in variants
    ]
    case = {
        "id": f"mined-{rule.id}-{rule.domain}",
        "domain": rule.domain,
        "document_name": f"挖掘规则验证-{rule.rule_name}",
        "text": text,
        "ground_truth": gt,
        "negative_ground_truth": [{"text": compliant}],
    }
    return case


def load_rules_for_validation(db, limit: int):
    """取挖掘规则清单（draft = 待激活候选，active = 复验对象）。

    注意：此处不做任何激活。draft 规则必须先生成对抗样本并逐规则过门禁，
    通过才激活——此前"先批量激活后验证"的顺序会让没生成到样本的 draft
    绕过门禁直接生效（is_active=1 落库后再退回，门禁形同虚设）。
    """
    from src.models import Rule, RuleRegulationLink

    link_rule_ids = [
        rid for (rid,) in db.query(RuleRegulationLink.rule_id)
        .filter(RuleRegulationLink.source == "reg_mining")
        .distinct()
        .all()
    ]
    rules = db.query(Rule).filter(Rule.id.in_(link_rule_ids)).all() if link_rule_ids else []
    return rules


def verify_cases(cases: list[dict], evaluate) -> tuple[list[dict], list[str]]:
    """逐规则隔离门禁：只用目标规则扫描该 case，避免其他规则的命中误伤归因。

    召回 = 目标规则对自身 gt 标注点的命中（须 100%，改写后仍能检出）；
    误报 = 目标规则在合规负样本上的命中（须 0）。返回 (通过 case, 退回规则名)。"""
    from src.core.rule_engine.engine import rule_scanner
    from src.parsers.base import TextBlock

    passed_cases, failed_rules = [], []
    for case in cases:
        gt = case.get("ground_truth") or []
        negatives = case.get("negative_ground_truth") or []
        target_name = gt[0].get("rule_name") if gt else None
        target = next(
            (r for r in evaluate._load_active_rules() if r.rule_name == target_name), None
        )
        if target is None:
            print(f"  - 找不到目标规则，退回: {target_name}")
            failed_rules.append(target_name or "?")
            continue
        min_conf = evaluate.settings.app_config("rule_engine").get("min_confidence", 0.5)

        def scan(text: str, _rule=target, _case=case):
            block = TextBlock(text=text, page=1, paragraph=1, heading=False)
            return rule_scanner.scan([block], [_rule], domain=_case.get("domain"))

        matched, own_fp = 0, 0
        for line in (case.get("text") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            for hit in scan(line):
                if hit.confidence < min_conf:
                    continue
                span = line[hit.char_start:hit.char_end]
                if any(evaluate._overlaps(span, n.get("text", "")) for n in negatives):
                    own_fp += 1
                    continue
                if any(evaluate._overlaps(span, g.get("text", "")) for g in gt):
                    matched += 1
        recall = min(1.0, matched / len(gt)) if gt else 1.0
        if recall >= 1.0 and own_fp == 0:
            passed_cases.append(case)
        else:
            detail = f"召回 {matched}/{len(gt)} 自身误报 {own_fp}"
            print(f"  - 门禁未过: {target.rule_name} ({detail})")
            failed_rules.append(target.rule_name)
    return passed_cases, failed_rules


def demote_rules(db, rule_names: list[str]) -> int:
    from src.models import Rule

    n = 0
    for name in rule_names:
        rule = db.query(Rule).filter(Rule.rule_name == name).first()
        if rule is not None:
            rule.is_active = 0
            rule.status = "draft"
            n += 1
    db.commit()
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="挖掘规则对抗评估集生成 + 门禁验证")
    parser.add_argument("--auto-activate", action="store_true", help="通过门禁的 draft 自动激活")
    parser.add_argument("--limit", type=int, default=40, help="本次最多处理的规则数")
    parser.add_argument("--verify-only", action="store_true", help="只重跑既有样本门禁")
    args = parser.parse_args()

    from src.core.llm.client import get_llm
    from src.infrastructure.database.mysql import SessionLocal

    db = SessionLocal()
    try:
        rules = load_rules_for_validation(db, limit=args.limit)
        llm = get_llm()
        if llm is None:
            raise SystemExit("未配置 DASHSCOPE_API_KEY")

        # 既有变体集（保留）
        variants_doc = json.loads(VARIANTS_JSON.read_text(encoding="utf-8"))
        existing_fps = {_fingerprint(c) for c in variants_doc.get("cases", [])}

        new_cases: list[dict] = []
        if args.verify_only:
            # 不生成新样本：把既有变体集中属于挖掘规则的 case 原样重跑门禁
            mined_names = {r.rule_name for r in rules}
            new_cases = [
                c
                for c in variants_doc.get("cases", [])
                if (c.get("ground_truth") or [{}])[0].get("rule_name") in mined_names
            ]
            print(f"== verify-only：重跑 {len(new_cases)} 个既有 case 门禁 ==")
        else:
            for rule in rules:
                case = generate_for_rule(llm, rule)
                if case is None:
                    print(f"  - 生成失败跳过: {rule.rule_name}")
                    continue
                if _fingerprint(case) in existing_fps:
                    continue
                new_cases.append(case)

        evaluate = _load_evaluate()
        print(f"== 生成 {len(new_cases)} 个新 case，开始引擎门禁 ==")
        passed, failed = verify_cases(new_cases, evaluate)

        # 门禁通过才激活：只有"本轮生成了对抗样本且全部通过"的 draft 才配生效
        activated = 0
        if args.auto_activate:
            passed_names = {
                c["ground_truth"][0].get("rule_name")
                for c in passed
                if c.get("ground_truth")
            }
            for rule in rules:
                if not rule.is_active and rule.rule_name in passed_names:
                    rule.is_active = 1
                    rule.status = "active"
                    activated += 1
            db.commit()
        n_demoted = 0
        if failed:
            n_demoted = demote_rules(db, failed)
            mode = "退回 draft" if args.auto_activate else "未达标（保持 draft）"
            print(f"{mode} {n_demoted} 条: {failed}")
        if args.auto_activate:
            print(
                f"门禁通过并激活 {activated} 条；"
                f"未生成新样本或未通过的 draft 保持待审（不激活）"
            )

        # 幸存样本合并进 variant_cases.json
        merged = 0
        for case in passed:
            fp = _fingerprint(case)
            if fp not in existing_fps:
                variants_doc.setdefault("cases", []).append(case)
                existing_fps.add(fp)
                merged += 1
        if merged:
            variants_doc["description"] = (
                variants_doc.get("description", "")
                + " | 含挖掘规则对抗样本（gen_variants.py 生成并过门禁）"
            )
            VARIANTS_JSON.write_text(
                json.dumps(variants_doc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        summary = (
            f"\n完成: 通过 {len(passed)} / 生成 {len(new_cases)}，"
            f"合并 {merged} 例进 variant_cases.json"
        )
        print(summary)

        # 终验①：回归基准集按 gate 口径（新激活规则不得破坏既有召回/误报）
        print("== 终验①：eval_cases.json 回归门禁（0.98/0.02）==")
        reg = json.loads(
            (_ROOT / "scripts" / "evaluate" / "eval_cases.json").read_text(encoding="utf-8")
        )
        tp_gt = gt_total = findings_total = fp_total = 0
        for case in reg.get("cases", []):
            r = evaluate._evaluate_case(case, "rule")
            tp_gt += r["tp_gt"]
            gt_total += r["gt_count"]
            fp_total += r["fp"]
            findings_total += r["found_count"]
        recall = tp_gt / gt_total if gt_total else 1.0
        fpr = fp_total / findings_total if findings_total else 0.0
        gate_ok = recall >= 0.98 and fpr <= 0.02
        print(f"回归集: 召回 {recall:.1%} 误报率 {fpr:.1%} → {'PASS' if gate_ok else 'FAIL'}")

        # 终验②：挖掘对抗样本专项统计（全引擎口径，仅观察不作门禁）
        mined_cases = [
            c for c in variants_doc.get("cases", []) if str(c.get("id", "")).startswith("mined-")
        ]
        m_tp = m_gt = m_fp = m_fd = 0
        for case in mined_cases:
            r = evaluate._evaluate_case(case, "rule")
            m_tp += r["tp_gt"]
            m_gt += r["gt_count"]
            m_fp += r["fp"]
            m_fd += r["found_count"]
        print(
            f"终验②：挖掘对抗样本 {len(mined_cases)} case: "
            f"全引擎召回 {m_tp}/{m_gt} 误报 {m_fp}/{m_fd}"
        )
        return 0 if gate_ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
