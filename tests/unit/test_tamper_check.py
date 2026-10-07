"""交叉篡改检测单测（R2-3）：关键数字过滤/归一容错/不一致判定的正负样本。

spike 结论落地：只比对利率/金额/期限/日期类关键数字；归一后精确相等才
判一致；不一致一律产出"疑似"finding（人工核验，不自动确认）。
"""

from src.services.tamper_check import check_tamper, extract_text_numbers, norm_number

# ---------- 归一化 ----------

def test_norm_thousands_and_percent():
    assert norm_number("3,850.00") == "3850"
    assert norm_number("9.85%") == "9.85"
    assert norm_number("３．８５") == "3.85"  # 全角
    assert norm_number("0.90") == "0.9"  # 尾零归一


# ---------- 文本数字提取 ----------

def test_extract_text_numbers_from_blocks():
    blocks = [
        {"text": "年化收益率 3.85%，最低认购 50,000 元"},
        {"text": "持有期限 366 天"},
    ]
    nums = extract_text_numbers(blocks)
    assert "3.85" in nums and "50000" in nums and "366" in nums


# ---------- check_tamper 正负样本 ----------

def _blocks_with(*nums: str) -> list[dict]:
    return [{"text": f"材料数字 {' '.join(nums)}", "page": 1}]


def test_consistent_numbers_produce_no_finding():
    vlm = [{"value": "3.85", "context": "年化收益率"},
           {"value": "50000", "context": "最低认购金额"}]
    findings = check_tamper(vlm, _blocks_with("3.85%", "50,000"))
    assert findings == []


def test_tampered_rate_detected():
    """核心场景：图上 9.85%、文字材料只有 3.85%——P 图篡改。"""
    vlm = [{"value": "9.85", "context": "年化收益率"}]
    findings = check_tamper(vlm, _blocks_with("3.85%"))
    assert len(findings) == 1
    f = findings[0]
    assert f["issue"] == "疑似篡改：图片数字与文字材料不一致"
    assert f["severity"] == "high"
    assert f["confidence"] == 0.7
    assert "9.85" in f["reason"]
    assert "人工核对" in f["suggestion"]


def test_non_key_number_ignored():
    """嵌名词单字数字不在威胁模型内（spike 结论），不参与比对。"""
    vlm = [{"value": "1", "context": ""}]  # 无关键词 context + 单字
    assert check_tamper(vlm, _blocks_with("3.85%")) == []


def test_date_number_detected_when_missing():
    vlm = [{"value": "2026", "context": "认购截止日期"}]
    findings = check_tamper(vlm, _blocks_with("2025年12月31日"))
    assert len(findings) == 1


def test_empty_inputs_degrade():
    assert check_tamper([], _blocks_with("3.85")) == []
    assert check_tamper([{"value": "3.85", "context": "收益率"}], []) == []


def test_malformed_items_skipped():
    vlm = [None, "not-a-dict", {"value": "", "context": "收益率"}]
    assert check_tamper(vlm, _blocks_with("3.85")) == []


def test_mixed_consistent_and_tampered():
    vlm = [
        {"value": "3.85", "context": "年化收益率"},       # 一致
        {"value": "1000", "context": "最低认购金额"},      # 图上 1000，文中 50000
    ]
    findings = check_tamper(vlm, _blocks_with("3.85%", "50,000"))
    assert len(findings) == 1
    assert "1000" in findings[0]["reason"]
