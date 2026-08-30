"""法规条款 → 审查规则候选挖掘（数据飞轮第三步）。

与 src/core/impact/mining.py（罚单挖掘）同一套落地纪律：LLM 只产出规则草稿
（status=draft, is_active=0），人工在规则库审核发布后才进入审查引擎；挖掘本身
不参与任何风险决策。区别在于溯源精度：罚单挖掘挂法规级，这里挂条款级
（RuleRegulationLink(source='reg_mining') + rule_content.related_regulations
精确到《法规》第X条，图谱 VIOLATES 边也随之到条款）。

落地前三重预校验（引擎对非法 pattern 静默返回空，必须拦截）：
1. regex 预编译——编译失败的候选直接丢弃；
2. 自证命中冒烟测试——LLM 必须同时给出"违规话术应命中"与"合规表述不应命中"
   的正反例，用真实 RuleScanner 引擎跑一遍：正例不中/反例误中的候选丢弃。
   关键约束写进 prompt：规则匹配的是营销话术本身（文案不带"不得/应当"），
   引擎的否定语境抑制天然放行"我们不承诺保本保收益"这类合规声明；
3. 查重——与库内现有规则（含此前挖掘的 draft）同名或同条件跳过，保证幂等。

用法（仓库根目录，需 MySQL 已导入法规 + DASHSCOPE_API_KEY）:
    python scripts/crawl/mine_rules_from_regulations.py [--domain banking]
        [--limit 40] [--dry-run]
    python scripts/crawl/mine_rules_from_regulations.py export-approved
        [--out scripts/init_data/rules_mined.json]   # 人工审核激活后导出给 CI 种子
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parents[2]

_MINE_SYSTEM = """你是金融合规规则工程师。给定一条监管法规条款，把它转成 1-2 条可直接在
营销文案上做文本匹配的审查规则候选。

核心约束：规则要在"违规话术"上命中，而不是在条款原文上命中。营销文案不会
出现"不得/应当/严禁"等立法用语，pattern 必须直接匹配违规表述本身
（如"保本保收益""稳赚不赔""预期收益率可达"）。流程类/资质类义务（如
"应当建立XX制度"）无法转成文本规则，跳过。

要求：
1. domain 只能是 banking/fund/insurance，按条款适用的业务判断；
2. regex 用 Python re 中文正则（| 分支），禁止嵌套量词，长度不超过 120 字；
   keyword 给 2-6 个词（词是文案里会原样出现的字面量）；
3. severity: high（承诺保本/保收益/保赔付类）、medium（夸大宣传/误导表述）、
   low（其他轻微）；
4. examples_hit 给 1-2 条典型违规话术，必须是营销文案里会出现的句子
   （系统会用引擎实测命中并自动做合规反例测试，不用你提供反例）。

只输出一个 JSON 数组，不要任何其他文字、不要代码块：
[{"rule_name": "禁止xx表述", "rule_type": "regex", "pattern": "保本|稳赚",
  "keywords": [], "severity": "high", "description": "依据：《xx办法》第X条",
  "examples_hit": ["本产品保本保收益"]}]
rule_type 为 keyword 时填 keywords 留空 pattern。"""

_VALID_DOMAINS = {"banking", "fund", "insurance"}
_VALID_SEVERITY = {"high", "medium", "low"}
# 营销合规相关条款预过滤：命中其一才送 LLM（控成本 + 过滤纯流程条款）
_MARKETING_RE = re.compile(
    r"不得|禁止|严禁|宣传|推介|营销|误导|承诺|保本|保收益|披露|风险揭示|适当性"
)

# 内置合规声明语料（行业通用风险提示，自写非法规文本）：规则在合规文案上
# 误命中即拒绝。反例不信任 LLM——实测它会把违规话术填进 examples_miss。
_COMPLIANT_CORPUS = {
    "banking": [
        "本产品不保本，投资者可能因市场波动遭受损失，投资需谨慎。",
        "理财产品过往业绩不预示其未来表现，理财非存款，产品有风险。",
        "预期收益率不代表未来实际收益，具体以产品合同约定为准。",
        "本行将根据您的风险承受能力推荐适当的产品，销售过程全程录音录像。",
        "结构性存款不同于一般性存款，具有投资风险，请仔细阅读产品说明书。",
        "分期业务年化利率以合同展示为准，请理性消费、量入为出。",
    ],
    "fund": [
        "基金有风险，投资需谨慎，基金过往业绩不预示未来表现。",
        "基金管理人不保证基金一定盈利，也不保证最低收益。",
        "投资者应当认真阅读基金合同、招募说明书及基金产品资料概要。",
        "基金评级机构出具的评级仅供参考，不构成投资建议。",
        "赎回款项将按照合同约定的时限支付，具体到账时间以登记机构确认为准。",
        "定投不等于储蓄，净值波动可能造成短期亏损。",
    ],
    "insurance": [
        "保单利益具有不确定性，分红水平不保证，具体以保险公司实际经营状况为准。",
        "投保人应当如实告知健康状况，未如实告知的部分将影响理赔。",
        "免除保险人责任的条款已在投保页面作出明确提示，请您仔细阅读。",
        "本产品提供十五日犹豫期，犹豫期内解除合同无手续费。",
        "既往理赔数据不构成对未来理赔结果的承诺。",
        "保险产品与银行存款、理财产品存在本质区别，请根据自身需求审慎选择。",
    ],
}


def _blocks(text: str):
    from src.parsers.base import TextBlock

    return [TextBlock(text=text)]


def smoke_test(candidate: dict) -> tuple[bool, str]:
    """引擎级冒烟测试：LLM 正例必须命中；确定性反例（否定变体 + 内置合规语料）
    必须全部不命中。返回 (ok, 原因)。"""
    from types import SimpleNamespace

    from src.core.rule_engine.engine import RuleScanner

    scanner = RuleScanner()
    rule = SimpleNamespace(
        id=0,
        domain=candidate["domain"],
        rule_name=candidate["rule_name"],
        rule_type=candidate["rule_type"],
        rule_content=candidate["rule_content"],
        severity=candidate["severity"],
        description=candidate.get("description"),
        is_active=1,
    )

    def hits(text: str) -> list:
        return scanner.scan(_blocks(text), [rule], domain=candidate["domain"])

    # 反例①：内置合规语料（同领域）
    for text in _COMPLIANT_CORPUS.get(candidate["domain"], []):
        if hits(text):
            return False, f"合规语料误命中: {text[:30]}"
    # 反例②：正例的否定变体（验证否定语境抑制放行合规声明）
    for positive in candidate.get("examples_hit") or []:
        probe = scanner.scan(_blocks(positive), [rule], domain=candidate["domain"])
        if not probe:
            return False, f"正例未命中: {positive[:30]}"
        for hit in probe[:2]:
            negated = f"本产品不{hit.matched_text}"
            if hits(negated):
                return False, f"否定变体误命中: {negated[:30]}"
    return True, ""


def parse_candidates(content: str | None) -> list[dict]:
    """解析 LLM 输出并做结构校验（regex 预编译在这里完成），坏条目跳过。"""
    if not content:
        return []
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match is None:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    candidates: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("rule_name") or "").strip()
        rule_type = item.get("rule_type")
        if not name or rule_type not in ("regex", "keyword"):
            continue
        pattern = str(item.get("pattern") or "").strip()
        keywords = [str(k).strip() for k in (item.get("keywords") or []) if str(k).strip()]
        if rule_type == "regex":
            if not pattern or len(pattern) > 120:
                continue
            try:
                re.compile(pattern)  # 引擎对编译失败静默返回空，这里提前拦截
            except re.error:
                continue
            condition = {"type": "regex", "pattern": pattern}
        else:
            if not keywords:
                continue
            condition = {
                "type": "keyword",
                "keywords": keywords,
                "match_mode": "any",
                "context_window": 15,
            }
        examples_hit = [str(e).strip() for e in (item.get("examples_hit") or []) if str(e).strip()]
        if not examples_hit:
            continue  # 不提供违规正例的候选无法自证，直接拒绝
        candidates.append(
            {
                "domain": item.get("domain") if item.get("domain") in _VALID_DOMAINS else None,
                "rule_name": name[:128],
                "rule_type": rule_type,
                "rule_content": {"operator": "OR", "conditions": [condition]},
                "severity": (
                    item["severity"] if item.get("severity") in _VALID_SEVERITY else "medium"
                ),
                "description": str(item.get("description") or "")[:512] or None,
                "examples_hit": examples_hit,
            }
        )
    return candidates[:2]


def _domain_of(article_domain: str) -> str:
    return article_domain if article_domain in _VALID_DOMAINS else "banking"


def _match_literals(rule_content: dict) -> set[str]:
    """提取规则的可匹配字面量（regex 分支 + keyword 词），供语义重叠查重。"""
    literals: set[str] = set()
    for cond in rule_content.get("conditions") or []:
        if cond.get("type") == "regex":
            for branch in str(cond.get("pattern") or "").split("|"):
                token = re.sub(r"[()\[\]?*+.^${}\\]", "", branch).strip()
                if len(token) >= 2:
                    literals.add(token)
        elif cond.get("type") == "keyword":
            literals.update(k for k in cond.get("keywords") or [] if len(k) >= 2)
    return literals


def _semantically_duplicate(candidate: dict, existing_literal_sets: list[set[str]]) -> bool:
    """候选与任一现有规则的字面量重叠 ≥60% 视为语义重复（保本保收益的 N 种写法）。"""
    cand_literals = _match_literals(candidate["rule_content"])
    if not cand_literals:
        return False
    for group in existing_literal_sets:
        if not group:
            continue
        if len(cand_literals & group) / len(cand_literals) >= 0.6:
            return True
    return False


def mine_from_regulations(
    db,
    limit: int,
    dry_run: bool,
    domain: str | None,
    keyword: str | None = None,
    focus: str | None = None,
) -> list[dict]:
    """主挖掘流程：选条款 → LLM 提炼 → 三重预校验 → 落 draft 规则。"""
    from src.core.llm.client import get_llm
    from src.core.llm.usage_ledger import recording_llm
    from src.models import Article, Regulation, Rule, RuleRegulationLink

    llm = recording_llm(get_llm())
    if llm is None:
        raise SystemExit("未配置 DASHSCOPE_API_KEY，无法挖掘规则候选")

    # 库内现有规则指纹（含此前挖掘的 draft），查重用
    existing_rules = db.query(Rule).all()
    seen_names = {r.rule_name for r in existing_rules}
    seen_conditions = {
        json.dumps(r.rule_content.get("conditions"), sort_keys=True, ensure_ascii=False)
        for r in existing_rules
        if isinstance(r.rule_content, dict)
    }
    seen_literals = [_match_literals(r.rule_content) for r in existing_rules
                     if isinstance(r.rule_content, dict)]

    query = (
        db.query(Article, Regulation)
        .join(Regulation, Article.regulation_id == Regulation.id)
        .filter(Regulation.status == "effective")
    )
    if domain:
        query = query.filter(Regulation.domain == domain)
    rows = query.all()

    # 条款预过滤：只把营销合规相关条款送 LLM
    candidates_articles = [
        (a, reg)
        for a, reg in rows
        if a.content and _MARKETING_RE.search(a.content) and len(a.content) > 30
    ]
    if keyword:
        # 主题定向挖掘：只挖包含关键词的条款（如"适当性"），避免全量重扫的 LLM 开销
        candidates_articles = [(a, reg) for a, reg in candidates_articles if keyword in a.content]
        print(f"主题过滤「{keyword}」后候选 {len(candidates_articles)} 条")
    print(f"候选条款 {len(candidates_articles)} / 全部条款 {len(rows)}（营销合规相关预过滤）")

    report: list[dict] = []
    created = 0
    for article, reg in candidates_articles:
        if created >= limit:
            break
        user = (
            f"《{reg.regulation_name}》{article.article_no}（domain={reg.domain}）：\n"
            f"{article.content[:1200]}\n\n请提炼规则候选："
        )
        if focus:
            user += f"\n本次挖掘聚焦：{focus}（条款内其他已覆盖主题不要重复产出）"
        try:
            content = llm.chat(
                [
                    {"role": "system", "content": _MINE_SYSTEM},
                    {"role": "user", "content": user},
                ]
            )
        except Exception as exc:
            print(f"  ! LLM 失败跳过 {article.article_no}: {type(exc).__name__}")
            continue
        for cand in parse_candidates(content):
            if created >= limit:
                break
            if cand["domain"] is None:
                cand["domain"] = _domain_of(reg.domain)
            name, reason = cand["rule_name"], ""
            if name in seen_names:
                reason = "同名已存在"
            elif (
                json.dumps(
                    cand["rule_content"]["conditions"], sort_keys=True, ensure_ascii=False
                )
                in seen_conditions
            ):
                reason = "同条件已存在"
            elif _semantically_duplicate(cand, seen_literals):
                reason = "与现有规则语义重叠"
            else:
                ok, smoke_reason = smoke_test(cand)
                if not ok:
                    reason = f"冒烟失败({smoke_reason})"
            if reason:
                print(f"  - 跳过 {name[:30]}: {reason}")
                report.append({"name": name, "status": reason})
                continue
            seen_names.add(name)
            seen_conditions.add(
                json.dumps(
                    cand["rule_content"]["conditions"], sort_keys=True, ensure_ascii=False
                )
            )
            seen_literals.append(_match_literals(cand["rule_content"]))
            created += 1
            citation = f"《{reg.regulation_name}》{article.article_no}"
            print(f"  + draft {cand['severity']}/{cand['domain']}: {name} ← {citation}")
            report.append({"name": name, "status": "draft", "citation": citation})
            if dry_run:
                continue
            rule = Rule(
                domain=cand["domain"],
                rule_name=cand["rule_name"],
                rule_type=cand["rule_type"],
                rule_content=cand["rule_content"],
                severity=cand["severity"],
                description=cand["description"],
                is_active=0,
                status="draft",
            )
            db.add(rule)
            db.flush()
            db.add(
                RuleRegulationLink(
                    rule_id=rule.id,
                    regulation_id=reg.id,
                    article_id=article.id,
                    citation=citation[:255],
                    source="reg_mining",
                )
            )
    if not dry_run:
        db.commit()
    print(f"\n完成: 新增 draft 规则 {created} 条（dry-run={dry_run}）")
    return report


def export_approved(out_path: Path) -> None:
    """人工审核激活后的规则导出为 CI 种子 JSON（与 rules.json 同 schema）。"""
    from src.infrastructure.database.mysql import SessionLocal
    from src.models import Rule, RuleRegulationLink

    db = SessionLocal()
    try:
        links = (
            db.query(RuleRegulationLink, Rule)
            .join(Rule, RuleRegulationLink.rule_id == Rule.id)
            .filter(RuleRegulationLink.source == "reg_mining", Rule.is_active == 1)
            .all()
        )
        seen: set[int] = set()
        rules = []
        for _link, rule in links:
            if rule.id in seen:
                continue
            seen.add(rule.id)
            rules.append(
                {
                    "domain": rule.domain,
                    "rule_name": rule.rule_name,
                    "rule_type": rule.rule_type,
                    "severity": rule.severity,
                    "description": rule.description,
                    "rule_content": rule.rule_content,
                }
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"导出 {len(rules)} 条已激活的挖掘规则 → {out_path}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="法规条款 → 规则候选挖掘")
    sub = parser.add_subparsers(dest="command")
    exp = sub.add_parser("export-approved", help="导出已激活的挖掘规则为 CI 种子")
    exp.add_argument("--out", default=str(_ROOT / "scripts" / "init_data" / "rules_mined.json"))
    parser.add_argument("--domain", choices=sorted(_VALID_DOMAINS), default=None)
    parser.add_argument(
        "--keyword", default=None, help="主题定向：只挖包含该关键词的条款（如 适当性）"
    )
    parser.add_argument(
        "--focus",
        default=None,
        help="聚焦提示：告诉 LLM 本次要挖的违规话术方向，避免重复产出已覆盖主题",
    )
    parser.add_argument("--limit", type=int, default=40, help="本次最多新增 draft 规则数")
    parser.add_argument("--dry-run", action="store_true", help="只打印候选不落库")
    args = parser.parse_args()

    if args.command == "export-approved":
        export_approved(Path(args.out))
        return

    from src.core.llm.usage_ledger import print_cost_summary
    from src.infrastructure.database.mysql import SessionLocal

    db = SessionLocal()
    try:
        mine_from_regulations(
            db,
            limit=args.limit,
            dry_run=args.dry_run,
            domain=args.domain,
            keyword=args.keyword,
            focus=args.focus,
        )
    finally:
        db.close()
    print_cost_summary("规则挖掘")


if __name__ == "__main__":
    main()
