"""敏感信息脱敏单元测试（PRD §13.2）。"""

from src.utils.masking import mask_sensitive


def test_mask_id_card():
    assert mask_sensitive("身份证号110101199001011234。") == "身份证号110****1234。"


def test_mask_phone():
    assert mask_sensitive("联系电话13812345678。") == "联系电话138****5678。"


def test_mask_bank_card():
    # 16 位银行卡：不匹配身份证（18 位），走银行卡规则保留后 4
    assert mask_sensitive("卡号6222020200112233。") == "卡号****2233。"


def test_mask_amount():
    assert mask_sensitive("认购金额100万元。") == "认购金额***万元。"
    assert mask_sensitive("本金1.5亿元。") == "本金***亿元。"


def test_masking_leaves_percentages():
    # 百分比不匹配"元"单位，保留原样
    assert mask_sensitive("预期年化收益率5.8%") == "预期年化收益率5.8%"


def test_masking_does_not_break_normal_text():
    assert mask_sensitive("本产品为净值型理财产品") == "本产品为净值型理财产品"
