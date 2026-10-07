"""内置 PII 检测单测（R1-1）：20 案例正负样本，验收召回 100% / 误报 0%.

正样本覆盖：合法校验位身份证（数字/X 结尾）、手机号、Luhn 合法银行卡、
邮箱、微信号（带标签）、混合块。
负样本覆盖：座机/400 电话、金额、百分比、日期、订单号、校验位失败的
身份证、Luhn 失败的 18 位数字、无标签微信号——全零误报是验收底线。
"""

from src.core.rule_engine.pii_scan import _id_card_valid, _luhn_valid, scan_pii
from src.parsers.base import TextBlock


def _scan_one(text: str) -> list:
    return scan_pii([TextBlock(text=text, page=1, paragraph=1)])


def _kinds(text: str) -> set[str]:
    return {h.rule_name for h in _scan_one(text)}


# ---------- 校验器自检（算法正确性锚点） ----------

def test_id_card_validator_accepts_known_valid():
    # 常见公开测试号，GB 11643 校验位为 X
    assert _id_card_valid("11010519491231002X")
    assert _id_card_valid("11010519491231002x")  # 小写 x 兼容


def test_id_card_validator_rejects_bad_check_digit():
    assert not _id_card_valid("110105194912310021")  # 校验位应为 X
    assert not _id_card_valid("11010519491231002A")  # 非法字符


def test_luhn_validator():
    # 6222020200112230：前缀 622202020011223 的 Luhn 校验位为 0（程序生成验证）
    assert _luhn_valid("6222020200112230")
    assert not _luhn_valid("6222020200112234")


# ---------- 正样本（召回） ----------

def test_valid_id_card_detected():
    hits = _scan_one("客户经理张某，身份证号 11010519491231002X，请勿外传")
    kinds = _kinds("客户经理张某，身份证号 11010519491231002X，请勿外传")
    assert "敏感信息：身份证号" in kinds
    assert hits[0].severity == "high"
    assert hits[0].confidence == 1.0
    assert hits[0].rule_id is None  # BigInteger 列安全（内置规则无 DB 行）


def test_valid_id_card_digit_ending_detected():
    # 11010119900307001 的 GB11643 校验位为 1
    assert "敏感信息：身份证号" in _kinds("身份证：110101199003070011")


def test_phone_detected():
    assert "敏感信息：手机号" in _kinds("详情咨询 13812345678")


def test_phone_other_prefix_detected():
    assert "敏感信息：手机号" in _kinds("联系电话 15912345678")


def test_luhn_valid_bank_card_detected():
    assert "敏感信息：银行卡号" in _kinds("还款卡号 6222020200112230")


def test_email_detected():
    assert "敏感信息：电子邮箱" in _kinds("投递至 service@example.com")


def test_wechat_with_label_detected():
    kinds = _kinds("添加 微信号：ABC_12345 领取资料")
    assert "敏感信息：微信号" in kinds


def test_mixed_block_all_detected():
    text = "联系人 13912345678，邮箱 a.b@test.cn"
    hits = _scan_one(text)
    names = {h.rule_name for h in hits}
    assert "敏感信息：手机号" in names
    assert "敏感信息：电子邮箱" in names


def test_hit_location_fields():
    hits = _scan_one("咨询 13812345678")
    assert hits[0].page == 1
    assert hits[0].paragraph == 1
    assert hits[0].matched_text == "13812345678"
    assert hits[0].char_start == 3
    assert hits[0].char_end == 14


def test_related_regulations_present():
    hits = _scan_one("13812345678")
    assert hits[0].related_regulations == ["《中华人民共和国个人信息保护法》"]


# ---------- 负样本（零误报） ----------

def test_landline_not_flagged():
    hits = _scan_one("客服热线 010-88886666")
    assert hits == []


def test_400_number_not_flagged():
    hits = _scan_one("全国服务热线 400-810-1818")
    assert hits == []


def test_amount_not_flagged():
    hits = _scan_one("认购金额 100,000 元，年化收益率 3.85%")
    assert hits == []


def test_product_code_not_flagged():
    # 字母开头 + 13 位数字：不是银行卡（Luhn 前缀不符也不是纯数字段）
    hits = _scan_one("产品登记编码 C1234567890123")
    assert hits == []


def test_date_number_not_flagged():
    hits = _scan_one("认购期 2026年10月8日 起")
    assert hits == []


def test_luhn_invalid_long_number_not_flagged():
    # 18 位但 Luhn 失败、也非合法身份证
    hits = _scan_one("单号 6222020200112234 至 6222020200112299")
    assert hits == []


def test_bad_checkdigit_id_not_flagged():
    hits = _scan_one("编号 110105194912310021")
    assert hits == []


def test_unlabeled_wechat_style_not_flagged():
    # 无"微信号"标签的字母数字串不报（误报不可控，需显式标签）
    hits = _scan_one("搜索 weixin_888 即可")
    assert hits == []


def test_order_number_not_flagged():
    hits = _scan_one("订单号 ORD202603880015 已受理")
    assert hits == []


def test_verification_code_not_flagged():
    hits = _scan_one("短信验证码 123456，5 分钟内有效")
    assert hits == []


def test_clean_marketing_text_zero_hits():
    text = (
        "XX稳健理财1号（第3期）近一年年化收益率 3.85%，业绩比较基准 "
        "3.50%-4.50%，最低认购 50,000 元，持有期限 366 天。"
        "风险提示：本产品为非保本浮动收益产品，过往业绩不代表未来表现。"
    )
    assert _scan_one(text) == []


# ---------- 边界：长数字串中间不截出假手机号 ----------

def test_no_phone_inside_long_number():
    # 20 位数字串内含 "13812345678" 片段，边界断言应阻止截出
    hits = _scan_one("流水号 99138123456789999999（20 位）")
    assert all(h.rule_name != "敏感信息：手机号" for h in hits)
