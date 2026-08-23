"""演示种子：基金销售宣传合规影响分析固定案例（公开监管数据 + 模拟业务台账）。

一条可重放的完整链路：
监管情报（规范营销物料新规）→ 影响分析（2 条规则 / 10 份存量材料 /
3 高 3 中 4 低）→ 人工确认 → 一键批量复审 → 查看批次整改。

数据约定：
- 全部带（演示）标记，--reset 可整体清除后重建；不影响真实业务数据。
- 材料文档为模拟 txt 写入 upload_dir/demo/，document_id 固定保证可重放。
- 台账为模拟业务数据；法规/罚单以公开监管口径编写，仅用于演示。

用法（仓库根目录）:
    python scripts/demo/seed_impact_demo.py          # 重建演示数据
    python scripts/demo/seed_impact_demo.py --reset  # 仅清除演示数据
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.orm import Session
from src.infrastructure.database.mysql import SessionLocal
from src.models import (
    Article,
    ImpactAssessment,
    PenaltyCase,
    ProductMaterial,
    Regulation,
    RegulationUpdate,
    Rule,
    RuleRegulationLink,
)
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEMO_MARK = "（演示）"
DEMO_REGULATION = f"证券投资基金销售宣传合规管理规定{DEMO_MARK}"
DEMO_UPDATE_TITLE = f"关于规范公募产品营销物料申报要求的补充通知{DEMO_MARK}"
DEMO_CITATION = f"《{DEMO_REGULATION}》第十二条"
DEMO_PENALTY = f"某基金销售公司宣传材料误导销售被处罚{DEMO_MARK}"
DEMO_MATERIAL_PREFIX = "演示材料-"

# 演示规则：链接到演示法规，构成"结构化关联优先"的命中路径
DEMO_RULES = [
    {
        "rule_name": f"禁止承诺保本保收益{DEMO_MARK}",
        "rule_type": "regex",
        "severity": "high",
        "description": "宣传材料不得出现保本、稳赚不赔、零风险等表述",
        "rule_content": {
            "operator": "OR",
            "conditions": [{"type": "regex", "pattern": "保本|稳赚不赔|零风险"}],
        },
    },
    {
        "rule_name": f"限制预期收益率宣传{DEMO_MARK}",
        "rule_type": "keyword",
        "severity": "medium",
        "description": "宣传材料不得使用预期收益率/年化收益率等收益承诺表述",
        "rule_content": {
            "operator": "OR",
            "conditions": [
                {
                    "type": "keyword",
                    "keywords": ["预期收益率", "年化收益率"],
                    "match_mode": "any",
                }
            ],
        },
    },
]

# 10 份模拟材料：3 高（保本表述+违规历史）3 中（收益率表述）4 低（干净）
_HIGH_TEXT = "本基金历史业绩优秀，收益稳定，保本无虞，稳赚不赔，适合稳健型投资者立即申购。"
_MEDIUM_TEXT = "本基金预期收益率可达6%，历史业绩仅供参考，投资须谨慎阅读产品资料。"
_LOW_TEXT = "本基金为指数增强型产品，风险等级中高，请仔细阅读基金合同与招募说明书。"

DEMO_MATERIALS = [
    # (序号后缀, 名称, 材料类型, 负责人, 历史状态, 文本)
    ("01", "稳健回报混合基金单页A", "宣传单页", "王敏", "violation", _HIGH_TEXT),
    ("02", "安稳盈FOF推文B", "推文", "李强", "violation", _HIGH_TEXT),
    ("03", "聚利稳选海报C", "海报", "赵磊", "violation", _HIGH_TEXT),
    ("04", "成长先锋股票基金单页D", "宣传单页", "陈静", "clean", _MEDIUM_TEXT),
    ("05", "启航混合直播话术E", "直播话术稿", "周昊", "clean", _MEDIUM_TEXT),
    ("06", "远见精选推文F", "推文", "吴倩", "clean", _MEDIUM_TEXT),
    ("07", "指数增强基金单页G", "宣传单页", "郑爽", "clean", _LOW_TEXT),
    ("08", "中证500物料H", "宣传单页", "冯磊", "clean", _LOW_TEXT),
    ("09", "红利低波海报I", "海报", "褚琴", "clean", _LOW_TEXT),
    ("10", "量化对冲推文J", "推文", "卫东", "clean", _LOW_TEXT),
]


def _demo_dir() -> Path:
    return Path(settings.upload_dir) / "demo"


def reset_demo(db: Session) -> None:
    """清除全部演示数据（按（演示）标记与固定前缀识别，不触碰真实数据）。"""
    demo_rule_ids = [
        r[0] for r in db.query(Rule.id).filter(Rule.rule_name.like(f"%{DEMO_MARK}")).all()
    ]
    demo_reg_ids = [
        r[0]
        for r in db.query(Regulation.id)
        .filter(Regulation.regulation_name.like(f"%{DEMO_MARK}"))
        .all()
    ]
    if demo_rule_ids or demo_reg_ids:
        link_q = db.query(RuleRegulationLink)
        if demo_rule_ids:
            link_q = link_q.filter(RuleRegulationLink.rule_id.in_(demo_rule_ids))
        if demo_reg_ids:
            link_q = link_q.filter(RuleRegulationLink.regulation_id.in_(demo_reg_ids))
        link_q.delete(synchronize_session=False)
    db.query(PenaltyCase).filter(PenaltyCase.case_name.like(f"%{DEMO_MARK}")).delete(
        synchronize_session=False
    )
    demo_update_ids = [
        u[0]
        for u in db.query(RegulationUpdate.id)
        .filter(RegulationUpdate.title.like(f"%{DEMO_MARK}"))
        .all()
    ]
    if demo_update_ids:
        db.query(ImpactAssessment).filter(
            ImpactAssessment.regulation_update_id.in_(demo_update_ids)
        ).delete(synchronize_session=False)
        db.query(RegulationUpdate).filter(RegulationUpdate.id.in_(demo_update_ids)).delete(
            synchronize_session=False
        )
    db.query(ProductMaterial).filter(
        ProductMaterial.name.like(f"{DEMO_MATERIAL_PREFIX}%")
    ).delete(synchronize_session=False)
    if demo_rule_ids:
        db.query(Rule).filter(Rule.id.in_(demo_rule_ids)).delete(synchronize_session=False)
    if demo_reg_ids:
        db.query(Article).filter(Article.regulation_id.in_(demo_reg_ids)).delete(
            synchronize_session=False
        )
        db.query(Regulation).filter(Regulation.id.in_(demo_reg_ids)).delete(
            synchronize_session=False
        )
    db.commit()
    if _demo_dir().exists():
        for file in _demo_dir().glob("*.txt"):
            file.unlink(missing_ok=True)
    logger.info("演示数据已清除")


def seed_demo(db: Session) -> dict:
    """重建演示数据，返回关键 id（供测试与演示脚本复用）。"""
    reset_demo(db)

    reg = Regulation(domain="fund", regulation_name=DEMO_REGULATION)
    db.add(reg)
    db.flush()
    db.add(
        Article(
            regulation_id=reg.id,
            article_no="第十二条",
            content="宣传材料不得承诺保本保收益，不得使用预期收益率等表述。",
        )
    )

    rule_ids: list[int] = []
    for spec in DEMO_RULES:
        rule = Rule(domain="fund", **spec)
        db.add(rule)
        db.flush()
        db.add(
            RuleRegulationLink(
                rule_id=rule.id, regulation_id=reg.id, citation=DEMO_CITATION
            )
        )
        rule_ids.append(rule.id)

    penalty = PenaltyCase(
        case_name=DEMO_PENALTY,
        penalty_org="中国证监会（演示口径）",
        violation_summary="销售宣传材料使用保本及收益承诺表述，误导投资者适当性判断。",
        related_regulations=[reg.id],
    )
    db.add(penalty)

    material_ids: list[int] = []
    _demo_dir().mkdir(parents=True, exist_ok=True)
    for suffix, name, mtype, owner, review_status, text in DEMO_MATERIALS:
        doc_id = f"doc_5d6f7a{suffix}"
        (_demo_dir() / f"{doc_id}.txt").write_text(text, encoding="utf-8")
        material = ProductMaterial(
            name=f"{DEMO_MATERIAL_PREFIX}{name}",
            product_type="fund",
            material_type=mtype,
            owner=owner,
            document_id=doc_id,
            status="active",
            last_review_status=review_status,
        )
        db.add(material)
        db.flush()
        material_ids.append(material.id)

    upd = RegulationUpdate(
        source="nfra",
        title=DEMO_UPDATE_TITLE,
        status="imported",
        domain="fund",
        matched_regulations=[
            {
                "regulation_id": reg.id,
                "regulation_name": reg.regulation_name,
                "article_no": "第十二条",
                "status": "effective",
            }
        ],
    )
    db.add(upd)
    db.commit()
    logger.info(
        "演示数据已重建: update=%s regulation=%s rules=%s materials=%s",
        upd.id, reg.id, rule_ids, material_ids,
    )
    return {
        "regulation_update_id": upd.id,
        "regulation_id": reg.id,
        "rule_ids": rule_ids,
        "material_ids": material_ids,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="影响分析演示数据")
    parser.add_argument("--reset", action="store_true", help="仅清除演示数据")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        if args.reset:
            reset_demo(session)
            print("演示数据已清除")
        else:
            ids = seed_demo(session)
            print(f"演示数据已重建：监管情报 #{ids['regulation_update_id']}")
            print("演示步骤：法规影响中心 → 分析影响 → 确认 → 发起批量复审 → 查看批次")
    finally:
        session.close()
