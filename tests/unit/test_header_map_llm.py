"""R2-2 表头映射 LLM 辅助工具的纯逻辑测试（不调真实 LLM）。

工具定位：离线草稿生成——扫描文档 → 找模板未命中表头 → LLM 判语义 →
产出待人工确认的草稿（见 scripts/tools/header_map_llm.py 头部说明）。
"""

import importlib.util
import json
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[2] / "scripts" / "tools" / "header_map_llm.py"
_spec = importlib.util.spec_from_file_location("header_map_llm", _TOOL)
hml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hml)


class _FakeLLM:
    """桩：返回预设 content（模仿项目 llm.complete 的返回结构）。"""

    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    def complete(self, messages, temperature=0.1):  # noqa: ARG002
        self.calls += 1

        class _R:
            pass

        r = _R()
        r.content = self._content
        return r


class TestExtractHeaders:
    def test_extracts_only_real_table_headers(self):
        text = (
            "前文\n"
            "| 投入金额 | 基准年化 | 参考收益 |\n"
            "| --- | --- | --- |\n"
            "| 50000 | 4.2 | 2100 |\n"
            "中间文字 | 不是表格\n"
            "| 单列 |\n"
        )
        headers = hml.extract_headers_from_text(text)
        assert headers == [["投入金额", "基准年化", "参考收益"]]

    def test_no_table_returns_empty(self):
        assert hml.extract_headers_from_text("纯文本没有表格") == []

    def test_multiple_tables(self):
        text = (
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
            "| C | D |\n| --- | --- |\n| 3 | 4 |\n"
        )
        assert hml.extract_headers_from_text(text) == [["A", "B"], ["C", "D"]]


class TestCollectUnmapped:
    def test_only_unmapped_headers_collected(self, tmp_path):
        # 命中模板的表头（"期初本金"在 FIELD_PATTERNS.principal 中）
        mapped = tmp_path / "mapped.txt"
        mapped.write_text(
            "| 期初本金 | 预期年化收益率 | 持有期收益 | 期末金额 |\n"
            "| --- | --- | --- | --- |\n| 1 | 2 | 3 | 4 |\n",
            encoding="utf-8",
        )
        # 异构表头：模板不含这些词
        unmapped = tmp_path / "unmapped.txt"
        unmapped.write_text(
            "| 投入金额(元) | 基准年化(%) | 参考收益(元) | 结算金额(元) |\n"
            "| --- | --- | --- | --- |\n| 1 | 2 | 3 | 4 |\n",
            encoding="utf-8",
        )
        headers, scanned = hml.collect_unmapped_headers(tmp_path)
        assert scanned == 2
        assert len(headers) == 1
        assert headers[0][0] == "投入金额(元)"

    def test_duplicate_headers_deduped(self, tmp_path):
        for name in ("a.txt", "b.txt"):
            (tmp_path / name).write_text(
                "| 投入金额(元) | 基准年化(%) |\n| --- | --- |\n| 1 | 2 |\n",
                encoding="utf-8",
            )
        headers, scanned = hml.collect_unmapped_headers(tmp_path)
        assert scanned == 2
        assert len(headers) == 1


class TestCoreTerm:
    def test_strips_unit_parentheses(self):
        assert hml.core_term("投入金额(元)") == "投入金额"
        assert hml.core_term("基准年化(%)") == "基准年化"
        assert hml.core_term("到账金额（万元）") == "到账金额"

    def test_strips_slash_and_percent(self):
        assert hml.core_term("年化/基准") == "年化基准"

    def test_falls_back_to_raw_when_empty(self):
        assert hml.core_term("(元)") == "(元)"


class TestCleanJson:
    def test_strips_json_fence(self):
        raw = '```json\n{"mapping": {}}\n```'
        assert json.loads(hml._clean_json(raw)) == {"mapping": {}}

    def test_plain_json_passthrough(self):
        raw = '{"mapping": {"a": "rate"}}'
        assert json.loads(hml._clean_json(raw))["mapping"]["a"] == "rate"


class TestLlmMapHeader:
    HEADER = ["投入金额(元)", "基准年化(%)", "参考收益(元)", "结算金额(元)"]

    def test_valid_mapping_produces_draft(self):
        llm = _FakeLLM(
            json.dumps(
                {
                    "mapping": {
                        "投入金额(元)": "principal",
                        "基准年化(%)": "rate",
                        "参考收益(元)": "profit",
                        "结算金额(元)": "total",
                    },
                    "confidence": 0.9,
                }
            )
        )
        draft = hml.llm_map_header(self.HEADER, llm)
        assert draft is not None
        assert draft["llm_mapping"] == {"principal": 0, "rate": 1, "profit": 2, "total": 3}
        # 建议模式已剥单位后缀
        assert draft["suggested_patterns"]["principal"] == ["投入金额"]
        assert draft["confidence"] == 0.9

    def test_insufficient_fields_returns_none(self):
        """少于 2 个字段 → 与模板层同门槛拒绝（非勾稽表不该产出草稿）。"""
        llm = _FakeLLM(
            json.dumps({"mapping": {"投入金额(元)": "principal"}, "confidence": 0.9})
        )
        assert hml.llm_map_header(self.HEADER, llm) is None

    def test_other_and_unknown_fields_rejected(self):
        llm = _FakeLLM(
            json.dumps(
                {
                    "mapping": {
                        "投入金额(元)": "other",
                        "基准年化(%)": "完全不存在的字段",
                        "参考收益(元)": "profit",
                        "结算金额(元)": "total",
                    },
                    "confidence": 0.5,
                }
            )
        )
        draft = hml.llm_map_header(self.HEADER, llm)
        assert draft is not None
        # other 与未知字段都被拒绝，只剩有效两列
        assert draft["llm_mapping"] == {"profit": 2, "total": 3}

    def test_non_json_output_returns_none(self):
        llm = _FakeLLM("抱歉，我无法判断这个表格。")
        assert hml.llm_map_header(self.HEADER, llm) is None

    def test_llm_exception_returns_none(self):
        class BoomLLM:
            def complete(self, messages, temperature=0.1):  # noqa: ARG002
                raise RuntimeError("network down")

        assert hml.llm_map_header(self.HEADER, BoomLLM()) is None
