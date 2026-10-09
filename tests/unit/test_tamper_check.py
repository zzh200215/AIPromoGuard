"""交叉篡改检测单测（R2-3）+ PR-6 三分支降级分流。

spike 结论落地：只比对利率/金额/期限/日期类关键数字；归一后精确相等才
判一致。PR-6 把"不一致"拆成三分支：

  1. 文字集有且相等         → 一致（无 finding）
  2. 同位置有数字但不等     → 一票 changed（high / 0.7，与旧口径一致）
  3. 文字集无此数字         → 降级 unverified（medium / 0.45，"待人工核验"）

回归红线：分支 2 的真篡改检出不许降（本文件 test_red_line_* 锁死）；
降级只影响分支 3，逻辑上与分支 2 可分离。
"""

from src.services.tamper_check import (
    TAMPER_KIND_PREFIX,
    check_tamper,
    extract_text,
    extract_text_numbers,
    is_key_number,
    norm_number,
)

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
    assert "年化收益率" in extract_text(blocks)


def test_is_key_number_filter():
    assert is_key_number("年化收益率", "3.85")
    assert is_key_number("", "50,000")  # 形态判断：≥4 位
    assert not is_key_number("", "1")  # 嵌名词单字数字不在威胁模型内


def _blocks_with(*texts: str) -> list[dict]:
    return [{"text": t, "page": 1} for t in texts]


# ---------- 分支 1：文字集有且相等 → 一致（≥3 例）----------

def test_consistent_numbers_produce_no_finding():
    vlm = [{"value": "3.85", "context": "年化收益率"},
           {"value": "50000", "context": "最低认购金额"}]
    assert check_tamper(vlm, _blocks_with("年化收益率 3.85%，最低认购金额 50,000 元")) == []


def test_consistent_with_format_variance():
    """千分位/百分号/全角格式噪声不产生误报（归一后相等即一致）。

    注：全角形态出现在 **VLM 输出侧**（模型可能回全角）；文本侧分词器对全角
    小数点的切分是已知边界（NUM_RE 见 tamper_check 模块注释），本 PR 不改
    共享正则，避免波及勾稽/巡检通道。
    """
    vlm = [{"value": "９．８５", "context": "预期年化收益率"},
           {"value": "100000", "context": "认购金额"}]
    blocks = _blocks_with("预期年化收益率 9.85%，认购金额 100,000.00 元")
    assert check_tamper(vlm, blocks) == []


def test_all_consistent_no_findings_and_no_aggregate():
    vlm = [{"value": "3.85", "context": "收益率"},
           {"value": "366", "context": "持有期限"},
           {"value": "50,000", "context": "认购金额"}]
    blocks = _blocks_with("收益率 3.85%，持有期限 366 天，认购金额 50,000 元")
    assert check_tamper(vlm, blocks) == []


# ---------- 分支 2：同位置有数字但不等 → 一票 changed（≥3 例）----------

def test_red_line_tampered_rate_still_detected():
    """核心场景（检出率红线）：图上 9.85%、文字材料同位置 3.85%——一票 changed。"""
    vlm = [{"value": "9.85", "context": "年化收益率"}]
    findings = check_tamper(vlm, _blocks_with("年化收益率 3.85%，限时抢购"))
    assert len(findings) == 1
    f = findings[0]
    assert f["issue"] == f"{TAMPER_KIND_PREFIX}：图片数字与文字材料不一致"
    assert f["severity"] == "high"  # 判定强度不降
    assert f["confidence"] == 0.7
    assert "9.85" in f["reason"] and "3.85" in f["reason"]  # 两路数字都在
    assert "图片：9.85" in f["original_text"] and "文字：3.85" in f["original_text"]
    assert "人工核对" in f["suggestion"]


def test_tampered_amount_with_thousand_separators():
    """金额篡改：图上 100,000、文字 50,000 —— 同位置不等仍判 changed。"""
    vlm = [{"value": "100,000", "context": "最低认购金额"}]
    findings = check_tamper(vlm, _blocks_with("最低认购金额 50,000 元起"))
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert "50,000" in findings[0]["reason"]


def test_tampered_date_detected_at_same_position():
    """日期篡改：图上 2026 年、文字材料同位置 2025 年。"""
    vlm = [{"value": "2026", "context": "认购截止日期"}]
    findings = check_tamper(vlm, _blocks_with("认购截止日期 2025年12月31日"))
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert "2025" in findings[0]["reason"]


def test_anchor_nearest_number_wins():
    """锚点邻域有多个数字时，报告距离最近的一个作为文字侧现值。"""
    vlm = [{"value": "9.85", "context": "年化收益率"}]
    blocks = _blocks_with("产品期限 90 天，年化收益率 3.85%")
    findings = check_tamper(vlm, blocks)
    assert len(findings) == 1
    assert "文字：3.85" in findings[0]["original_text"]


# ---------- 分支 3：文字集无此数字 → 降级 unverified（≥3 例）----------

def test_unverified_when_context_absent_from_text():
    """锚点无处可寻（文字材料根本没有该标签）→ 待人工核验，不再冒充 changed。"""
    vlm = [{"value": "9.85", "context": "年化收益率"}]
    findings = check_tamper(vlm, _blocks_with("材料数字 3.85%"))
    assert len(findings) == 1
    f = findings[0]
    assert f["issue"] == f"{TAMPER_KIND_PREFIX}：图片数字未在文字材料中读到（待人工核验）"
    assert f["severity"] == "medium"
    assert f["confidence"] == 0.45
    assert "图片：9.85" in f["original_text"] and "文字：未读到" in f["original_text"]


def test_unverified_when_anchor_found_but_no_numbers_near():
    """锚点命中但邻域没有数字（OCR 把小字数字整段漏读）→ 待人工核验。"""
    vlm = [{"value": "9.85", "context": "预期年化收益率"}]
    blocks = _blocks_with("预期年化收益率：见产品说明书")
    findings = check_tamper(vlm, blocks)
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert "待人工核验" in findings[0]["issue"]


def test_unverified_when_no_context_at_all():
    """VLM 未给 context（只有数字）→ 无法定位对应位置 → 待人工核验。"""
    vlm = [{"value": "9.85", "context": ""}]
    findings = check_tamper(vlm, _blocks_with("材料数字 3.85%"))
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert "文字：未读到" in findings[0]["original_text"]


def test_unverified_mixed_with_consistent_and_changed():
    """混合场景：一致 / changed / unverified 三类共存，各自判定强度正确。"""
    vlm = [
        {"value": "3.85", "context": "年化收益率"},   # 一致
        {"value": "1000", "context": "最低认购金额"},  # 同位置 50,000 → changed
        {"value": "8.88", "context": "管理费用"},      # 文字层没有该标签 → unverified
    ]
    blocks = _blocks_with("年化收益率 3.85%，最低认购金额 50,000 元")
    findings = check_tamper(vlm, blocks)
    assert len(findings) == 2
    by_issue = {f["issue"]: f for f in findings}
    changed = [f for f in findings if f["severity"] == "high"]
    unverified = [f for f in findings if f["severity"] == "medium"]
    assert len(changed) == 1 and "1000" in changed[0]["reason"]
    assert len(unverified) == 1 and "8.88" in unverified[0]["reason"]
    assert len(by_issue) == 2


# ---------- 聚合护栏：OCR 系统性漏读不逐条轰炸 ----------

def test_aggregate_when_majority_unverified():
    """unverified >50% 且 ≥3 条 → 合并为一条整档核对条目。"""
    vlm = [{"value": f"1.1{i}", "context": "收益率"} for i in range(5)]
    findings = check_tamper(vlm, _blocks_with("本材料无相关数字"))
    assert len(findings) == 1
    f = findings[0]
    assert f["issue"] == f"{TAMPER_KIND_PREFIX}：文字层未读到多数图片数字（待整档核对）"
    assert "整档人工核对" in f["suggestion"]
    assert "5 个" in f["reason"]  # key_total 全未读到


def test_no_aggregate_when_at_threshold_but_few():
    """低于最小条数（2 条，纵然 100%）不聚合——小题不做整档结论。"""
    vlm = [{"value": "9.85", "context": "收益率"},
           {"value": "3.85", "context": "收益率"}]
    findings = check_tamper(vlm, _blocks_with("本材料无相关数字"))
    assert len(findings) == 2
    assert all("待人工核验" in f["issue"] for f in findings)


def test_no_aggregate_when_ratio_at_half():
    """恰好 50%（4 条中 2 条 unverified）不聚合——阈值是"大于 50%"。"""
    vlm = [
        {"value": "3.85", "context": "年化收益率"},      # 一致
        {"value": "50000", "context": "最低认购金额"},    # 一致
        {"value": "9.85", "context": "某标签"},          # unverified（锚点不在）
        {"value": "8.88", "context": "另标签"},          # unverified
    ]
    blocks = _blocks_with("年化收益率 3.85%，最低认购金额 50,000 元")
    findings = check_tamper(vlm, blocks)
    assert len(findings) == 2  # 逐条保留，未聚合
    assert all("待人工核验" in f["issue"] for f in findings)


def test_aggregate_keeps_changed_items_individual():
    """聚合只合并 unverified；changed 条目保持逐条（真篡改不能被稀释）。"""
    vlm = [{"value": "1000", "context": "最低认购金额"}]  # 同位置 50,000 → changed
    vlm += [{"value": f"7.7{i}", "context": f"标签{i}"} for i in range(4)]
    blocks = _blocks_with("最低认购金额 50,000 元")
    findings = check_tamper(vlm, blocks)
    assert len(findings) == 2
    kinds = sorted(f["severity"] for f in findings)
    assert kinds == ["high", "medium"]
    assert any("整档核对" in f["issue"] for f in findings)


# ---------- 上游门：ocr_missing 预筛（PR-6 两阶段流水线）----------

def test_ocr_missing_gate_skips_contradictory_number():
    """上游说图片 OCR 读到过该数字（不在 ocr_missing）→ 不做不一致判定。"""
    vlm = [{"value": "9.85", "context": "年化收益率"}]
    blocks = _blocks_with("年化收益率 3.85%")
    # 不带门：判定 changed
    assert len(check_tamper(vlm, blocks)) == 1
    # 带门且该数字不在 missing 集（OCR 声称读到过）→ 跳过
    assert check_tamper(vlm, blocks, ocr_missing=[]) == []
    # 带门且该数字在 missing 集 → 正常判定
    gated = check_tamper(vlm, blocks, ocr_missing=[{"value": "9.85", "context": "年化收益率"}])
    assert len(gated) == 1


# ---------- 比对口径：必须用未脱敏文本（PR-6 真机验证发现）----------

def test_masked_text_causes_false_tamper_so_pipeline_uses_raw():
    """脱敏文本会把带单位金额抹成 '50,***元' → 用脱敏文本比对必报假篡改。

    这是 PR-6 真机验证抓到的真实误报（海报"认购金额50,000元起"被脱敏成
    "认购金额50,***元起"，残留数字 "50" 被当成同位置现值）。故 review_service
    的篡改比对走后端未脱敏解析（`_raw_blocks_for_tamper`，与巡检基线 10-07
    同类修复）——本测试锁住"原文口径零误报"的对称性。
    """
    vlm = [{"value": "50,000", "context": "认购金额"}]
    masked = _blocks_with("认购金额50,***元起")
    raw = _blocks_with("认购金额50,000元起")
    assert len(check_tamper(vlm, masked)) == 1  # 脱敏口径：假篡改（管线不得使用）
    assert check_tamper(vlm, raw) == []  # 原文口径：一致，零误报


def test_raw_blocks_helper_parses_unmasked(monkeypatch):
    """接线断言：篡改比对取的是 mask=False 的解析（口径与图片原文一致）。"""
    from src.services import review_service

    calls: dict = {}

    class _FakeDoc:
        blocks = [
            type(
                "B",
                (),
                {"text": "认购金额50,000元起", "page": 1, "paragraph": 1, "heading": None},
            )(),
        ]
        text = "认购金额50,000元起"

    def _fake_parse(path, *, mask=True):
        calls["path"] = path
        calls["mask"] = mask
        return _FakeDoc()

    monkeypatch.setattr(review_service.document_service, "parse", _fake_parse)
    blocks, text = review_service._raw_blocks_for_tamper("poster.png")
    assert calls["mask"] is False
    assert calls["path"] == "poster.png"
    assert blocks and blocks[0]["text"] == "认购金额50,000元起"
    assert text == "认购金额50,000元起"


# ---------- 边界与降级 ----------

def test_empty_inputs_degrade():
    assert check_tamper([], _blocks_with("3.85")) == []
    assert check_tamper([{"value": "3.85", "context": "收益率"}], []) == []


def test_malformed_items_skipped():
    vlm = [None, "not-a-dict", {"value": "", "context": "收益率"}]
    assert check_tamper(vlm, _blocks_with("3.85")) == []


def test_non_key_number_ignored():
    vlm = [{"value": "1", "context": ""}]  # 无关键词 context + 单字
    assert check_tamper(vlm, _blocks_with("3.85%")) == []
