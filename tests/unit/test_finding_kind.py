"""F1-2 维度身份前缀契约：results.py 的 finding_kind 派生依赖三个检测器的
文案前缀 + review_service 的 [rule_name] 注入。前缀漂移会静默破坏前端维度
标签——本测试是防漂移的锁。"""

from src.core.rule_engine.consistency import CONSISTENCY_KIND_PREFIX, _consistency_hit
from src.core.rule_engine.pii_scan import _NAME, PII_KIND_PREFIX
from src.services.review_service import _persist_results
from src.services.tamper_check import TAMPER_KIND_PREFIX, check_tamper


def test_pii_names_all_start_with_prefix():
    for name in _NAME.values():
        assert name.startswith(PII_KIND_PREFIX), f"PII rule_name 前缀漂移: {name}"


def test_consistency_rule_name_starts_with_prefix():
    hit = _consistency_hit("测试明细", "测试证据")
    assert hit.rule_name.startswith(CONSISTENCY_KIND_PREFIX)


def test_tamper_issue_starts_with_prefix():
    findings = check_tamper(
        [{"value": "9.85", "context": "年化收益率"}],
        [{"text": "年化收益率 3.85%"}],
        page=1,
    )
    assert findings, "构造的篡改样本应命中"
    assert findings[0]["issue"].startswith(TAMPER_KIND_PREFIX)


def test_prefixes_are_distinct():
    prefixes = {PII_KIND_PREFIX, CONSISTENCY_KIND_PREFIX, TAMPER_KIND_PREFIX}
    assert len(prefixes) == 3


class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def delete(self):
        return 0


class _FakeDB:
    """只承载 _persist_results 的最小接口：记录 add 进来的 ReviewResult。"""

    def __init__(self):
        self.items = []

    def query(self, *a, **k):
        return _FakeQuery()

    def add(self, obj):
        self.items.append(obj)


def test_persist_injects_builtin_rule_name_into_description():
    """内置命中落库后 description 头部带 [rule_name]；普通 LLM 命中不受影响。"""
    findings = [
        {
            "violation_type": "rule",
            "rule_id": None,
            "rule_name": "敏感信息：手机号",
            "description": "材料包含疑似真实客户手机号",
            "original_text": "13812345678",
            "confidence": 1.0,
            "risk_level": "high",
        },
        {
            "violation_type": "llm",
            "rule_id": None,
            "rule_name": "LLM 生成的标题",
            "description": "LLM 判定依据",
            "original_text": "x",
            "confidence": 0.6,
            "risk_level": "medium",
        },
    ]
    db = _FakeDB()
    _persist_results(db, 1, findings)
    assert db.items[0].description.startswith("[敏感信息：手机号]")
    assert not db.items[1].description.startswith("["), "普通 LLM 命中不应被注入前缀"


def test_persist_no_double_prefix_on_rerun_shape():
    """已带前缀的 description（重算回放等场景）不重复注入。"""
    findings = [
        {
            "violation_type": "rule",
            "rule_id": None,
            "rule_name": "敏感信息：手机号",
            "description": "[敏感信息：手机号] 材料包含疑似真实客户手机号",
            "original_text": "13812345678",
            "confidence": 1.0,
            "risk_level": "high",
        },
    ]
    db = _FakeDB()
    _persist_results(db, 1, findings)
    assert db.items[0].description.count("[敏感信息：手机号]") == 1
