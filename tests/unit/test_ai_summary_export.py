"""AI 风险综述进导出：三个渲染器都应包含综述小节（无需数据库，本地可跑）。"""

from io import BytesIO

from src.core.report.docx import render_docx
from src.core.report.markdown import render_markdown

AI_SUMMARY = {
    "text": "本材料整体风险偏高：高风险集中于收益承诺类表述，建议优先整改后重新送审。",
    "model": "qwen-plus",
    "generated_at": "2026-09-13 15:20:00",
    "stale": False,
}

BASE_REPORT = {
    "task_id": 1,
    "document_name": "稳健回报混合基金宣传单页.pdf",
    "domain": "fund",
    "generated_at": "2026-09-11 10:26:40",
    "summary": {"total_violations": 1, "high_risk": 1, "medium_risk": 0, "low_risk": 0},
    "violations": [
        {
            "risk_level": "high",
            "source": "rule",
            "type": "禁止性",
            "rule_name": "承诺保本保收益",
            "original_text": "本金安全无忧，稳赚不赔的稳健之选",
            "confidence": 0.99,
        }
    ],
    "ai_summary": AI_SUMMARY,
}


def test_markdown_includes_ai_summary():
    md = render_markdown(BASE_REPORT)
    assert "AI 风险综述" in md
    assert "整体风险偏高" in md
    assert "qwen-plus" in md


def test_markdown_marks_stale_summary():
    report = {**BASE_REPORT, "ai_summary": {**AI_SUMMARY, "stale": True}}
    md = render_markdown(report)
    assert "（已过期，仅供参考）" in md


def test_docx_includes_ai_summary():
    docx_bytes = render_docx(BASE_REPORT)
    # python-docx 读回正文断言综述段落存在
    from docx import Document

    doc = Document(BytesIO(bytes(docx_bytes)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "AI 风险综述" in text
    assert "整体风险偏高" in text


def test_summary_endpoint_requires_authentication():
    from fastapi.testclient import TestClient
    from src.api.main import app

    client = TestClient(app)
    response = client.post("/api/v1/ai/tasks/1/summary", json={"force": True})

    assert response.status_code == 401
    assert response.json()["code"] == 1101
