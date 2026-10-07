"""时效性告警单测（R3-2）：纯函数层测试（material_stale_reasons）.

DB 编排层（stale_materials_check 的查询部分）不做单测 mock——SQL 过滤
语义由 MySQL 恢复后的集成验证兜底；核心判定逻辑在此穷举。
"""

from src.services.impact_service import material_stale_reasons

_INACTIVE_RULES = {10: "规则已停用：禁止刚性兑付"}
_INACTIVE_REGS = {100: "法规已废止/失效：旧办法"}
_LINK = {10: 100}


def test_disabled_rule_flagged():
    reasons = material_stale_reasons(
        {10, 11}, _INACTIVE_RULES, _INACTIVE_REGS, _LINK
    )
    assert reasons == ["规则已停用：禁止刚性兑付"]


def test_repealed_regulation_via_link_flagged():
    """规则活着但关联法规废止 → 待更新（走 rule_regulation_link）。"""
    reasons = material_stale_reasons({20}, {}, _INACTIVE_REGS, {20: 100})
    assert reasons == ["法规已废止/失效：旧办法"]


def test_all_healthy_empty_reasons():
    """规则与法规全部有效 → 零待更新（10 是停用规则，healthy 集合不含它）。"""
    reasons = material_stale_reasons(
        {11, 20}, _INACTIVE_RULES, _INACTIVE_REGS, _LINK
    )
    assert reasons == []


def test_all_healthy_rules_pass():
    reasons = material_stale_reasons({11, 30}, {}, {}, {})
    assert reasons == []


def test_no_rules_no_reasons():
    assert material_stale_reasons(set(), _INACTIVE_RULES, _INACTIVE_REGS, _LINK) == []


def test_disabled_rule_takes_precedence_over_reg_reason():
    """规则停用与法规废止同时命中 → 只报规则停用（elif 顺序，原因不重复堆叠）。"""
    reasons = material_stale_reasons({10}, _INACTIVE_RULES, _INACTIVE_REGS, _LINK)
    assert reasons == ["规则已停用：禁止刚性兑付"]
    assert len(reasons) == 1


def test_multiple_reasons_sorted():
    rules = {10: "规则已停用：A", 30: "规则已停用：B"}
    reasons = material_stale_reasons({30, 10}, rules, {}, {})
    assert reasons == ["规则已停用：A", "规则已停用：B"]  # 按 rule_id 排序稳定输出
