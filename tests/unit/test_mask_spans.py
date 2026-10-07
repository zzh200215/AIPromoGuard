"""方案 A 测试：脱敏时采集命中元数据 → 检测层消费（修复 PII 检测失效）。

背景：解析阶段（PRD §13.2）先脱敏，`scan_pii` 的正则只认原始格式，
导致 PII 检测在真实管线中永不命中（脱敏后是 138****5678）。
方案 A 让脱敏与检测共用一遍扫描：脱敏时记录 kind（PII 不带原文，金额带值）。
"""

from src.core.rule_engine.pii_scan import scan_pii_from_spans
from src.utils.masking import mask_sensitive, mask_sensitive_with_spans


class TestMaskWithSpans:
    def test_phone_collected_without_value(self):
        masked, spans = mask_sensitive_with_spans("联系电话 13812345678 咨询")
        assert masked == "联系电话 138****5678 咨询"
        assert spans == [{"kind": "phone", "value": None}]

    def test_id_card_collected(self):
        masked, spans = mask_sensitive_with_spans("身份证：110101199003070011")
        assert "****" in masked
        assert {"kind": "id_card", "value": None} in spans

    def test_amount_collected_with_value(self):
        """金额带原值（勾稽/数字比对需要值；金额是宣传数字非客户隐私）。"""
        masked, spans = mask_sensitive_with_spans("起购金额 50000元，上限 5万元")
        assert "50000" not in masked
        amounts = [s for s in spans if s["kind"] == "amount"]
        assert [a["value"] for a in amounts] == ["50000", "5"]

    def test_multiple_kinds_in_one_text(self):
        text = "张先生 13812345678，卡号 6222020200112230，起投 1000元"
        masked, spans = mask_sensitive_with_spans(text)
        kinds = sorted(s["kind"] for s in spans)
        assert kinds == ["amount", "bank_card", "phone"]
        assert "13812345678" not in masked
        assert "6222020200112230" not in masked

    def test_clean_text_yields_no_spans(self):
        text = "本基金历史业绩不代表未来表现"
        masked, spans = mask_sensitive_with_spans(text)
        assert masked == text
        assert spans == []

    def test_plain_mask_sensitive_unchanged(self):
        """向后兼容：原 mask_sensitive 行为不变。"""
        assert mask_sensitive("电话 13812345678") == "电话 138****5678"
        assert mask_sensitive("金额 50000元") == "金额 ***元"


class TestScanPiiFromSpans:
    def test_phone_hit_aggregated_with_count(self):
        spans = [{"kind": "phone", "value": None}, {"kind": "phone", "value": None}]
        hits = scan_pii_from_spans(spans)
        assert len(hits) == 1
        hit = hits[0]
        assert hit.rule_name == "敏感信息：手机号"
        assert hit.severity == "high"
        assert hit.confidence == 1.0
        assert "× 2" in hit.matched_text
        assert "138" not in hit.matched_text  # 不含任何原文数字

    def test_id_card_and_bank_card_separate_hits(self):
        spans = [{"kind": "id_card", "value": None}, {"kind": "bank_card", "value": None}]
        hits = scan_pii_from_spans(spans)
        assert {h.rule_name for h in hits} == {"敏感信息：身份证号", "敏感信息：银行卡号"}

    def test_amount_spans_do_not_produce_pii_hits(self):
        """金额不是 PII 命中（它是材料宣传数字，由勾稽/数字比对消费）。"""
        spans = [{"kind": "amount", "value": "50000"}]
        assert scan_pii_from_spans(spans) == []

    def test_empty_spans(self):
        assert scan_pii_from_spans([]) == []

    def test_unknown_kind_ignored(self):
        spans = [{"kind": "unknown_future_kind", "value": None}]
        assert scan_pii_from_spans(spans) == []


class TestTableRowAmountExemption:
    """表格行豁免金额脱敏（2026-10-07）：勾稽需原值；PII 在表格内仍脱敏。"""

    def test_table_row_amount_kept(self):
        text = "| 认购金额 | 预期收益 |\n| --- | --- |\n| 50000元 | 2100元 |"
        masked, spans = mask_sensitive_with_spans(text)
        assert "50000元" in masked and "2100元" in masked
        assert "***元" not in masked
        assert spans == []  # 未脱敏即无 amount span（amount 本就无消费方）

    def test_prose_amount_still_masked(self):
        masked, spans = mask_sensitive_with_spans("认购金额 50000元。")
        assert masked == "认购金额 ***元。"
        assert [s["kind"] for s in spans] == ["amount"]

    def test_table_row_pii_still_masked_amount_kept(self):
        text = "| 联系电话 | 金额 |\n| 13812345678 | 50000元 |"
        masked, spans = mask_sensitive_with_spans(text)
        assert "138****5678" in masked
        assert "50000元" in masked
        assert [s["kind"] for s in spans] == ["phone"]

    def test_plain_mask_sensitive_same_behavior(self):
        """mask_sensitive 与 with_spans 行为一致（同一行级实现）。"""
        assert mask_sensitive("| 50000元 | 2100元 |") == "| 50000元 | 2100元 |"
        assert mask_sensitive("本金 50000元。") == "本金 ***元。"
