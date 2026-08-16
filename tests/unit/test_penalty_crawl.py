"""真实处罚数据爬虫的解析逻辑单测（离线：合成 HTML，不打网络）。

覆盖 scripts/crawl/fetch_penalty_cases.py 的：
- NFRA 信息公开表解析（表头列序定位、文号列误中的兜底）
- CSRC 决定书解析（文号/当事人/违法事实/我会决定/挂件日期）
- 相关性优先截断
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_EVAL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "crawl" / "fetch_penalty_cases.py"
_spec = importlib.util.spec_from_file_location("fetch_penalty_cases", _EVAL_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _resp(text: str = "", payload: dict | None = None):
    return SimpleNamespace(
        text=text,
        encoding=None,
        charset_encoding="utf-8",
        json=lambda: payload or {},
        raise_for_status=lambda: None,
    )


def _nfra_doc(table_html: str, doc_id: int = 1, publish: str = "2026-08-10 10:00:00"):
    return _resp(
        payload={
            "data": {
                "rows": [
                    {
                        "docId": doc_id,
                        "docTitle": "某监管局行政处罚信息公开表",
                        "publishDate": publish,
                    }
                ]
            }
        }
    ), _resp(payload={"data": {"docClob": table_html}})


NFRA_TABLE = """
<table>
<tr><td>序号</td><td>当事人名称</td><td>主要违法违规行为（案由）</td>
    <td>行政处罚决定书文号</td><td>行政处罚内容</td><td>作出决定机关</td></tr>
<tr><td>1</td><td>某财产保险公司</td><td>编制虚假宣传资料误导投保人</td>
    <td>金罚决字〔2026〕10号</td><td>警告并罚款30万元</td><td>某金融监管局</td></tr>
<tr><td>2</td><td>某银行分行</td><td></td><td>x号</td><td>罚款</td><td>某金融监管局</td></tr>
</table>
"""

# 处罚内容列只有文号的表：兜底应从同其他列找到真正处罚内容
NFRA_TABLE_DOCNO_ONLY = """
<table>
<tr><td>序号</td><td>当事人名称</td><td>主要违法违规行为</td>
    <td>行政处罚内容</td><td>作出决定机关</td></tr>
<tr><td>1</td><td>某人寿支公司</td><td>委托无资质人员销售保险</td>
    <td>鲁金罚决字〔2026〕66号；对当事人警告并罚款2万元</td><td>某监管局</td></tr>
</table>
"""


def test_fetch_nfra_parses_rows(monkeypatch):
    list_resp, detail_resp = _nfra_doc(NFRA_TABLE)
    monkeypatch.setattr(
        mod, "_get", lambda url: list_resp if "SelectDocByItemIdAndChild" in url else detail_resp
    )
    cases = mod.fetch_nfra(1)
    assert len(cases) == 1  # 空违规行为的行被跳过
    c = cases[0]
    assert c["case_name"] == "某金融监管局对某财产保险公司行政处罚案"
    assert c["penalty_org"] == "某金融监管局"
    assert c["penalty_date"] == "2026-08-10"
    assert c["penalty_result"] == "警告并罚款30万元"
    assert "误导" in c["violation_summary"]
    assert c["source"] == "nfra"
    assert "nfra.gov.cn" in c["source_url"]


def test_fetch_nfra_header_with_docno_column(monkeypatch):
    """表头含"行政处罚决定书文号"列时不得误选为处罚内容列。"""
    list_resp, detail_resp = _nfra_doc(NFRA_TABLE)
    monkeypatch.setattr(
        mod, "_get", lambda url: list_resp if "SelectDocByItemIdAndChild" in url else detail_resp
    )
    cases = mod.fetch_nfra(1)
    assert cases[0]["penalty_result"] == "警告并罚款30万元"


CSRC_DECISION = (
    "索 引 号 bm56/2026 索引 中国证券监督管理委员会行政处罚决定书 "
    "〔2026〕33号 当事人:张某,男。 经查明,张某存在以下违法事实: "
    "张某在报告期内控制使用他人证券账户进行交易,账户组交易行为明显异常且无正当理由,"
    "涉案金额巨大,扰乱证券市场正常交易秩序。上述违法事实,有交易流水等证据证明。 "
    "我会决定:没收张某违法所得100万元,并处以300万元罚款。 "
    "当事人如果不服本处罚决定,可申请行政复议。"
)

_CSRC_HREF = "/csrc/c101928/c7650681/content.shtml"
CSRC_HOME = (
    "<html><body><ul>"
    f'<li><a href="{_CSRC_HREF}">中国证券监督管理委员会行政处罚决定书</a> 07-31</li>'
    f'<li><a href="{_CSRC_HREF}">重复链接应去重</a> 07-31</li>'
    "</ul></body></html>"
)


def test_fetch_csrc_parses_decision(monkeypatch):
    def fake_get(url):
        if url == mod.CSRC_HOME:
            return _resp(CSRC_HOME)
        return _resp(f'<div class="content">{CSRC_DECISION}</div>')

    monkeypatch.setattr(mod, "_get", fake_get)
    cases = mod.fetch_csrc(3)
    assert len(cases) == 1  # 重复链接去重
    c = cases[0]
    assert c["case_name"] == "中国证监会对张某行政处罚案（〔2026〕33号）"
    assert c["penalty_org"] == "中国证券监督管理委员会"
    assert c["penalty_date"] == "2026-07-31"  # 挂件 MM-DD + 文号年份
    assert "没收" in c["penalty_result"] and "300万元" in c["penalty_result"]
    assert "证券账户" in c["violation_summary"] and "违法所得" not in c["violation_summary"]
    assert c["source"] == "csrc"


def test_prioritize_and_cap_relevant_first():
    cases = [
        {"case_name": "a", "violation_summary": "贷款分类不准确"},
        {"case_name": "b", "violation_summary": "保险销售误导"},
        {"case_name": "c", "violation_summary": "宣传预期收益率"},
    ]
    kept = mod._prioritize_and_cap(cases, 2)
    assert [k["case_name"] for k in kept] == ["b", "c"]


def test_penalty_regex_covers_common_sanctions():
    for word in ["罚款", "警告", "禁止", "没收", "责令", "取消", "终身"]:
        assert mod._PENALTY_RE.search(f"对当事人{word}")
