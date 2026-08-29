"""LLM-as-a-Judge 评估脚本的纯逻辑单测（离线：FakeLLM + 桩扫描管线，不连库/不调真 LLM）。

覆盖：
- JSON 宽容解析 / 结论判分解析 / 引用可支撑性判定（确定性幻觉检查）
- 单案例判分聚合（judge_precision / span 口径对照 / 检索相关性 / 结论数上限）
- main() 端到端（tmp 案例文件 → 汇总输出 → 明细落盘）与未配 key 的退出码
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

_JUDGE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "evaluate" / "judge.py"
_spec = importlib.util.spec_from_file_location("judge", _JUDGE_PATH)
judge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(judge)


def _llm_result(payload):
    return SimpleNamespace(content=payload, usage={"total_tokens": 10})


class FakeLLM:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return self.results.pop(0)


def _finding(reg="《互联网保险业务监管办法》第十二条"):
    return {
        "type": "禁止性",
        "issue": "承诺保本保收益",
        "original_text": "本产品保本保收益",
        "regulation": reg,
        "reason": "违反禁止刚性兑付规定",
        "severity": "high",
    }


def _article(name="互联网保险业务监管办法", aid=1):
    return {
        "article_id": aid,
        "regulation_name": name,
        "article_no": "第十二条",
        "content": "不得保本保收益",
        "status": "effective",
        "score": 0.8,
    }


# ---------- 解析 ----------


def test_parse_json_object_variants():
    payload = '{"verdict": "true_violation", "reason": "确有承诺"}'
    assert judge._parse_json_object(payload)["verdict"] == "true_violation"
    assert judge._parse_json_object("```json\n" + payload + "\n```")["verdict"] == "true_violation"
    assert judge._parse_json_object("结论：" + payload)["reason"] == "确有承诺"
    assert judge._parse_json_object("不是 JSON") is None
    assert judge._parse_json_object("") is None


def test_judge_finding_parses_and_rejects_bad_verdict():
    llm = FakeLLM([_llm_result('{"verdict": "true_violation", "reason": "确有承诺"}')])
    verdict, usage = judge.judge_finding(llm, "本产品保本保收益", _finding())
    assert verdict == {"verdict": "true_violation", "reason": "确有承诺"}
    assert usage["total_tokens"] == 10

    llm = FakeLLM([_llm_result('{"verdict": "不知道", "reason": "x"}')])
    assert judge.judge_finding(llm, "text", _finding())[0] is None


# ---------- 引用可支撑性（确定性幻觉检查） ----------


def test_citation_supported():
    articles = [_article("互联网保险业务监管办法")]
    assert judge.citation_supported(_finding(), articles) is True
    assert judge.citation_supported(_finding("《不存在的办法》第五条"), articles) is False
    assert judge.citation_supported(_finding(""), articles) is None  # 未引用法规不参与统计
    assert judge.citation_supported(_finding("第X条"), articles) is None  # 过短引用不判
    # 无书名号时退化为子串匹配：引用文本中找不到任何召回法规名 → 不可支撑（含泛引）
    assert judge.citation_supported(_finding("根据某办法第X条"), articles) is False
    # 无书名号但召回法规名出现在引用文本中 → 支撑
    assert (
        judge.citation_supported(_finding("根据互联网保险业务监管办法第二十六条"), articles)
        is True
    )


# ---------- 检索质量 ----------


def test_judge_context_precision_and_missing_topics():
    llm = FakeLLM(
        [_llm_result('{"relevant": [0], "irrelevant": [1], "missing_topics": ["销售适当性"]}]')]
    )
    out, usage = judge.judge_context(llm, "文本", [_article(), _article("无关法规", aid=2)])
    assert out == {"context_precision": 0.5, "missing_topics": ["销售适当性"]}
    assert usage["total_tokens"] == 10


def test_judge_context_empty_articles_skips_llm():
    llm = FakeLLM([])
    out, usage = judge.judge_context(llm, "文本", [])
    assert out == {"context_precision": None, "missing_topics": []}
    assert usage is None and llm.calls == 0


# ---------- 单案例判分聚合 ----------


class _StubEvaluate:
    @staticmethod
    def _scan_full(case):
        return [_finding(), _finding("《不存在的办法》第五条")]

    @staticmethod
    def _scan_rule_engine(case):
        return [_finding()]

    @staticmethod
    def _overlaps(a, b):
        return bool(a) and bool(b) and (a in b or b in a)


def _patch_stubs(monkeypatch, llm):
    monkeypatch.setattr(judge, "_load_evaluate", lambda: _StubEvaluate)
    monkeypatch.setattr(
        judge, "regulation_match", lambda state: {"matched_articles": [_article()]}
    )
    return llm


def test_judge_case_aggregates(monkeypatch):
    llm = _patch_stubs(
        monkeypatch,
        FakeLLM(
            [
                _llm_result('{"verdict": "true_violation", "reason": "成立"}'),
                _llm_result('{"verdict": "false_positive", "reason": "误报"}'),
                _llm_result('{"relevant": [0], "irrelevant": [], "missing_topics": []}'),
            ]
        ),
    )
    case = {
        "id": "c1",
        "domain": "insurance",
        "text": "本产品保本保收益",
        "ground_truth": [{"text": "保本保收益"}],
    }
    out = judge.judge_case(llm, _StubEvaluate, case, "full")

    assert out["judge_precision"] == 0.5  # 1 true / 2 judged
    assert out["true_violation"] == 1 and out["false_positive"] == 1
    assert out["span_recall"] == 1.0  # gt 片段被检出原文覆盖
    assert out["citation_support"] == 0.5  # 一条引用可支撑、一条幻觉
    assert out["context_precision"] == 1.0
    assert out["usage"]["total_tokens"] == 30


def test_judge_case_caps_findings(monkeypatch):
    _patch_stubs(monkeypatch, FakeLLM([]))
    case = {"id": "c2", "text": "文本", "ground_truth": []}
    ev = SimpleNamespace(
        _scan_full=lambda case: [_finding()] * 8,
        _scan_rule_engine=lambda case: [],
        _overlaps=lambda a, b: False,
    )
    verdict = '{"verdict": "true_violation", "reason": "ok"}'
    llm = FakeLLM([_llm_result(verdict)] * judge._MAX_FINDINGS_PER_CASE)
    out = judge.judge_case(llm, ev, case, "full")
    assert out["findings_total"] == 8
    assert out["findings_judged"] == judge._MAX_FINDINGS_PER_CASE
    assert out["findings_truncated"] == 1


# ---------- main() 端到端 ----------


def test_main_runs_and_writes_report(monkeypatch, tmp_path, capsys):
    cases = {
        "cases": [
            {"id": "c1", "domain": "insurance", "text": "本产品保本保收益", "ground_truth": []},
            {"id": "c2", "domain": "fund", "text": "预期收益翻倍", "ground_truth": []},
        ]
    }
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "judge_report.json"

    _patch_stubs(monkeypatch, None)
    llm = FakeLLM(
        [
            _llm_result('{"verdict": "true_violation", "reason": "ok"}'),
            _llm_result('{"verdict": "false_positive", "reason": "ok"}'),
            _llm_result('{"relevant": [0], "irrelevant": [], "missing_topics": []}'),
        ]
        * 2
    )
    monkeypatch.setattr(judge, "get_llm", lambda: llm)
    monkeypatch.setattr(
        "sys.argv", ["judge.py", "--cases", str(cases_path), "--out", str(out_path)]
    )

    assert judge.main() == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["summary"]["cases"] == 2
    assert report["summary"]["engine"] == "full"
    assert len(report["cases"]) == 2
    assert "Judge 汇总" in capsys.readouterr().out


def test_main_without_llm_key_exits_2(monkeypatch):
    monkeypatch.setattr(judge, "get_llm", lambda: None)
    monkeypatch.setattr("sys.argv", ["judge.py"])
    assert judge.main() == 2
