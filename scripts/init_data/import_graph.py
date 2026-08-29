"""知识图谱基础导入（W9 周二）：将 MySQL 现有法规/条款/规则同步进 Neo4j。

图谱 Schema 对齐 PRD §5.3.3：
- 节点: Regulation / Article / ViolationPattern / ProductType / PenaltyCase
- 关系: HAS_ARTICLE / VIOLATES / APPLIES_TO / PENALIZED_BY /
  BASED_ON_REGULATION / INVOLVES_VIOLATION

幂等: 通过唯一约束 + MERGE 实现，重复执行不产生重复节点/关系。
用法:
    python scripts/init_data/import_graph.py            # 法规/条款/规则
    python scripts/init_data/import_graph.py --penalty   # 处罚案例（周三）
    python scripts/init_data/import_graph.py --rebuild   # 先清空全部图谱再导入
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.infrastructure.database.neo4j_client import run_cypher_strict
from src.models import Article, PenaltyCase, Regulation, Rule, RuleRegulationLink

# 领域 → 产品类型（ProductType 节点，PRD 图谱五元之一）
PRODUCT_TYPES = {
    "banking": ("银行理财", "banking"),
    "fund": ("基金销售", "fund"),
    "insurance": ("保险产品", "insurance"),
}


def ensure_schema() -> None:
    """创建唯一约束（幂等），保证 MERGE 语义。"""
    for label, key in (
        ("Regulation", "id"),
        ("Regulation", "name"),
        ("Article", "id"),
        ("ViolationPattern", "id"),
        ("ViolationPattern", "pattern_name"),
        ("ProductType", "type_name"),
        ("PenaltyCase", "id"),
    ):
        run_cypher_strict(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        )
    run_cypher_strict(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Regulation) REQUIRE n.regulation_no IS UNIQUE"
    )
    print("Schema 约束已就绪")


def _match_regulation_name(ref: str) -> str | None:
    """从规则 related_regulations 引用（如《××办法》第×条）提取法规名。

    返回 regulations 表中实际存在的名称（含《》），匹配不到返回 None。
    """
    stripped = ref.strip()
    if not (stripped.startswith("《") and "》" in stripped):
        return None
    name = stripped[: stripped.index("》") + 1]
    # 法规名可能带书名号差异，统一去掉书名号比对
    core = name[1:-1]
    if len(core) < 4:
        return None
    return core


def _load_regulations() -> dict[str, int]:
    """返回 {法规名核心: regulation_id} 映射（用于 Article→ViolationPattern 关联）。"""
    db = SessionLocal()
    try:
        rows = db.query(Regulation.id, Regulation.regulation_name).all()
        return {r.regulation_name: r.id for r in rows}
    finally:
        db.close()


def import_regulations() -> int:
    """导入法规 + 条款，建立 HAS_ARTICLE 关系。"""
    db = SessionLocal()
    try:
        regs = db.query(Regulation).all()
        for reg in regs:
            props = {
                "name": reg.regulation_name,
                "regulation_no": reg.regulation_no or "",
                "domain": reg.domain,
                "status": reg.status,
            }
            if reg.publish_date:
                props["publish_date"] = reg.publish_date.isoformat()
            run_cypher_strict(
                """
                MERGE (r:Regulation {id: $id})
                ON CREATE SET r += $props
                ON MATCH SET r += $props
                """,
                {"id": reg.id, "props": props},
            )

            articles = db.query(Article).filter(Article.regulation_id == reg.id).all()
            for art in articles:
                aprops = {
                    "regulation_id": reg.id,
                    "chapter_no": art.chapter_no or "",
                    "article_no": art.article_no or "",
                    "content": art.content,
                }
                run_cypher_strict(
                    """
                    MERGE (a:Article {id: $id})
                    ON CREATE SET a += $props
                    ON MATCH SET a += $props
                    """,
                    {"id": art.id, "props": aprops},
                )
                run_cypher_strict(
                    """
                    MATCH (r:Regulation {id: $rid}), (a:Article {id: $aid})
                    MERGE (r)-[:HAS_ARTICLE]->(a)
                    """,
                    {"rid": reg.id, "aid": art.id},
                )
        print(f"法规 {len(regs)} 部、条款已导入")
        return len(regs)
    finally:
        db.close()


def import_rules() -> tuple[int, int]:
    """规则 → ViolationPattern 节点；按领域关联 ProductType。

    返回 (规则数, 关联到的条款数)。规则 related_regulations 引用到具体法规时，
    建立 Article -[:VIOLATES]-> ViolationPattern 关系。
    """
    db = SessionLocal()
    try:
        rules = db.query(Rule).filter(Rule.is_active == 1).all()
        reg_id_by_name = _load_regulations()
        linked = 0
        for rule in rules:
            vprops = {
                "pattern_name": rule.rule_name,
                "description": rule.description or "",
                "domain": rule.domain,
                "severity": rule.severity,
                "rule_type": rule.rule_type,
            }
            run_cypher_strict(
                """
                MERGE (v:ViolationPattern {id: $id})
                ON CREATE SET v += $props
                ON MATCH SET v += $props
                """,
                {"id": rule.id, "props": vprops},
            )
            # 领域 → 产品类型
            if rule.domain in PRODUCT_TYPES:
                type_name, _ = PRODUCT_TYPES[rule.domain]
                run_cypher_strict(
                    """
                    MERGE (p:ProductType {type_name: $tn})
                    ON CREATE SET p += {domain: $d}
                    WITH p
                    MATCH (v:ViolationPattern {id: $vid})
                    MERGE (v)-[:APPLIES_TO]->(p)
                    """,
                    {"tn": type_name, "d": rule.domain, "vid": rule.id},
                )

            # 引用法规的规则 → 建立 VIOLATES（限定同领域条款）
            refs = (rule.rule_content or {}).get("related_regulations", [])
            for ref in refs:
                core = _match_regulation_name(str(ref))
                if core is None or core not in reg_id_by_name:
                    continue
                rid = reg_id_by_name[core]
                articles = (
                    db.query(Article)
                    .filter(Article.regulation_id == rid)
                    .all()
                )
                for art in articles:
                    run_cypher_strict(
                        """
                        MATCH (a:Article {id: $aid}), (v:ViolationPattern {id: $vid})
                        MERGE (a)-[:VIOLATES {confidence: 0.9}]->(v)
                        """,
                        {"aid": art.id, "vid": rule.id},
                    )
                    linked += 1
        # 结构化关联表（rule_regulation_links）：挖掘/影响分析写入的条款级关联，
        # 精度高于 related_regulations 的"法规下全部条款"展开，优先采用
        link_rows = (
            db.query(RuleRegulationLink, Rule)
            .join(Rule, RuleRegulationLink.rule_id == Rule.id)
            .filter(Rule.is_active == 1, RuleRegulationLink.article_id.isnot(None))
            .all()
        )
        for link, _rule in link_rows:
            run_cypher_strict(
                """
                MATCH (a:Article {id: $aid}), (v:ViolationPattern {id: $vid})
                MERGE (a)-[:VIOLATES {confidence: 0.9}]->(v)
                """,
                {"aid": link.article_id, "vid": _rule.id},
            )
            linked += 1

        print(f"规则 {len(rules)} 条导入为 ViolationPattern，关联条款 {linked} 处")
        return len(rules), linked
    finally:
        db.close()


_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "banking": ["银行", "理财", "存款", "贷款", "承兑", "资管", "信用卡", "分行", "支行"],
    "fund": ["基金", "证券", "私募", "申购", "赎回", "上市公司", "信息披露", "发行股份"],
    "insurance": ["保险", "投保", "保单", "理赔", "寿险", "财险", "健康险", "保险代理"],
}


def _infer_domain(text: str) -> str | None:
    """真实罚单多无关联法规（信息公开表只给违规摘要），按文本关键词推断领域。"""
    best, best_hits = None, 0
    for domain, kws in _DOMAIN_KEYWORDS.items():
        hits = sum(1 for k in kws if k in text)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


def import_penalty_cases() -> int:
    """处罚案例 → PenaltyCase 节点（周三）。

    建立:
    - PenaltyCase -[:BASED_ON_REGULATION]-> Regulation（按案例关联法规 id 匹配）
    - PenaltyCase -[:INVOLVES_VIOLATION]-> ViolationPattern（按关联法规所属领域
      兜底关联；真实罚单多无关联法规，此时按违规文本关键词推断领域）
    """
    db = SessionLocal()
    try:
        cases = db.query(PenaltyCase).all()
        # 法规 id → 领域 映射（用于案例关联违规模式）
        reg_domains = {
            r.id: r.domain
            for r in db.query(Regulation.id, Regulation.domain).all()
        }
        for case in cases:
            cprops = {
                "case_name": case.case_name,
                "penalty_org": case.penalty_org or "",
                "penalty_result": case.penalty_result or "",
                "summary": case.violation_summary or "",
            }
            if case.penalty_date:
                cprops["penalty_date"] = (
                    case.penalty_date.isoformat()
                    if isinstance(case.penalty_date, date)
                    else str(case.penalty_date)
                )
            run_cypher_strict(
                """
                MERGE (c:PenaltyCase {id: $id})
                ON CREATE SET c += $props
                ON MATCH SET c += $props
                """,
                {"id": case.id, "props": cprops},
            )
            # BASED_ON_REGULATION：按 related_regulations 里的法规 id 关联
            reg_ids = [int(x) for x in (case.related_regulations or [])]
            for rid in reg_ids:
                run_cypher_strict(
                    """
                    MATCH (r:Regulation {id: $rid}), (c:PenaltyCase {id: $cid})
                    MERGE (c)-[:BASED_ON_REGULATION]->(r)
                    """,
                    {"rid": rid, "cid": case.id},
                )
            # INVOLVES_VIOLATION：按关联法规所属领域兜底；无关联法规时按
            # 违规文本关键词推断领域（真实罚单 related_regulations 多为空）
            domains = {reg_domains[r] for r in reg_ids if r in reg_domains}
            if not domains:
                inferred = _infer_domain(
                    f"{case.case_name} {case.violation_summary or ''}"
                )
                if inferred:
                    domains = {inferred}
            for d in domains:
                run_cypher_strict(
                    """
                    MATCH (v:ViolationPattern {domain: $d}), (c:PenaltyCase {id: $cid})
                    MERGE (c)-[:INVOLVES_VIOLATION]->(v)
                    """,
                    {"d": d, "cid": case.id},
                )
        print(f"处罚案例 {len(cases)} 条导入")
        return len(cases)
    finally:
        db.close()


def rebuild() -> None:
    """清空图谱（仅开发用）。"""
    run_cypher_strict("MATCH (n) DETACH DELETE n")
    print("图谱已清空")


def main() -> None:
    args = sys.argv[1:]
    if "--rebuild" in args:
        rebuild()
    ensure_schema()
    if "--penalty" in args:
        import_penalty_cases()
    else:
        import_regulations()
        import_rules()


if __name__ == "__main__":
    main()
