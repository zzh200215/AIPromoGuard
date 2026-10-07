"""Word 报告渲染测试（src/core/report/docx.py）：纯逻辑，无需 DB。

docx 本质是 zip（PK 魔数），读回验证段落与表格内容。
"""

import io

from docx import Document
from src.core.report.docx import render_docx

_REPORT = {
    "task_id": 1,
    "document_name": "稳健回报混合基金宣传单页.pdf",
    "domain": "fund",
    "generated_at": "2026-09-12T15:00:00",
    "summary": {"total_violations": 2, "high_risk": 1, "medium_risk": 1, "low_risk": 0},
    "violations": [
        {
            "risk_level": "high", "source": "rule", "human_status": "confirmed",
            "human_confirmed_by": 2, "original_text": "本金安全无忧，稳赚不赔的稳健之选",
            "page": 1, "paragraph": 2, "rule_name": "承诺保本保收益",
            "suggestion": "删除保本承诺", "confidence": 0.99, "related_cases": [],
        },
        {
            "risk_level": "medium", "source": "llm", "human_status": "false_positive",
            "human_confirmed_by": 2, "original_text": "历史年化收益均超 8%，未来可期",
            "page": 1, "paragraph": 3, "description": "以历史业绩暗示未来收益",
            "evidence_supported": False, "suggestion": "补充声明",
        },
    ],
    "human_review": {
        "pending_confirm": 0, "confirmed": 1, "false_positive": 1, "auto_confirmed": 0,
        "manual_reviewed": 2, "final_total": 1, "final_high": 1, "final_medium": 0,
        "final_low": 0, "last_confirmed_at": "2026-09-12T14:00:00",
    },
    "regulations": [
        {"id": 2, "regulation_name": "公开募集证券投资基金销售机构监督管理办法",
         "regulation_no": "证监会令第196号"},
    ],
    "pending_verification": [
        {"risk_level": "medium", "original_text": "适合所有投资者配置",
         "page": 2, "paragraph": 4, "reasons": ["适当性匹配需人工判断"]},
    ],
}


def _render():
    data = render_docx(_REPORT)
    assert data[:2] == b"PK" and len(data) > 4000
    return Document(io.BytesIO(data))


def test_docx_contains_human_review_and_regulations():
    doc = _render()
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "金融产品合规审查报告" in text
    assert "剔除误报后，最终确认违规 1 处" in text
    # 结构化法规引用带文号
    assert "《公开募集证券投资基金销售机构监督管理办法》（证监会令第196号）" in text
    assert "待人工核验清单" in text


def test_docx_violation_table_has_human_column():
    doc = _render()
    table = doc.tables[0]
    assert len(table.rows) == 3  # 表头 + 2 条违规
    assert table.rows[0].cells[1].text == "人工"
    assert table.rows[1].cells[1].text == "已确认"
    assert table.rows[2].cells[1].text == "误报剔除"


def test_docx_auto_confirmed_labeled():
    _render()
    data = render_docx({**_REPORT, "human_review": None, "regulations": None})
    doc2 = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc2.paragraphs)
    # 无 human_review 数据时不得出现人工复核段
    assert "剔除误报后" not in text
    assert "金融产品合规审查报告" in text
