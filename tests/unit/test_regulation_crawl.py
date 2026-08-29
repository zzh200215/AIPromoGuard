"""法规抓取管道的切分/校验逻辑单测（离线：不打网络、不调 LLM）。

覆盖 scripts/crawl/fetch_regulations.py 的：
- 中文数字解析与标题模糊匹配
- 条款确定性切分（目录行过滤 / 多行拼接 / 章-节归并 / 顿号模式）
- 条号连续性与 schema 校验
- 防错标派生与文号兜底提取
- LLM 兜底触发条件（确定性切分质量不足时）
"""

import importlib.util
from pathlib import Path

_EVAL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "crawl" / "fetch_regulations.py"
_spec = importlib.util.spec_from_file_location("fetch_regulations", _EVAL_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_cn_to_int():
    assert mod.cn_to_int("一") == 1
    assert mod.cn_to_int("十二") == 12
    assert mod.cn_to_int("二十三") == 23
    assert mod.cn_to_int("一百零五") == 105
    assert mod.cn_to_int("36") == 36
    assert mod.cn_to_int("第 hundred") is None
    assert mod.cn_to_int("") is None


def test_title_score_matching():
    assert mod.title_score("存款保险条例", "存款保险条例") == 1.0
    # 带发文机关前缀的标题 → 包含关系高分
    full = "中国银保监会关于印发《互联网保险业务监管办法》的通知"
    assert mod.title_score("互联网保险业务监管办法", full) >= 0.9
    # 完全不同的标题低分（宁缺毋滥）
    assert mod.title_score("互联网保险业务监管办法", "保险代理人监管规定") < 0.5


def test_extract_articles_skips_toc_and_merges_lines():
    text = (
        "目 录\n"
        "第一条\n"
        "第二条\n"
        "第一章 总则\n"
        "第一条 为了规范理财业务活动，保护投资者合法权益，\n"
        "特制定本办法。\n"
        "第二条 本办法所称理财业务是指商业银行接受\n"
        "投资者委托的投资活动。\n"
    )
    articles = mod.extract_articles(text)
    assert [a["article_no"] for a in articles] == ["第一条", "第二条"]
    # 多行拼接为连贯正文，且目录行没有变成条款
    assert articles[0]["content"].endswith("特制定本办法。")
    assert "目 录" not in articles[0]["content"]


def test_extract_articles_merges_section_into_chapter():
    text = (
        "第二章 销售管理\n"
        "第二节 销售规范\n"
        "第七条 商业银行销售理财产品应当加强投资者适当性管理。\n"
    )
    articles = mod.extract_articles(text)
    assert articles[0]["chapter_no"] == "第二章 销售管理 第二节 销售规范"


def test_extract_articles_dunhao_mode():
    # 指导意见类无"第X条"结构：一、二、三 → 第X条（与现有库表示约定一致）
    text = (
        "一、资产管理业务是指金融机构接受投资者委托进行的投资活动。\n"
        "二、金融机构开展资产管理业务时不得承诺保本保收益。\n"
    )
    articles = mod.extract_articles(text)
    assert [a["article_no"] for a in articles] == ["第一条", "第二条"]
    assert articles[1]["content"].startswith("二、")


def test_numbering_quality_detects_broken_sequence():
    good = [{"article_no": f"第{n}条"} for n in ["一", "二", "三", "四", "五"]]
    assert mod.numbering_quality(good) == 1.0
    broken = good + [{"article_no": "第三条"}]  # 重复条号
    assert mod.numbering_quality(broken) == 0.0
    assert mod.numbering_quality([]) == 0.0


def _reg(articles: list[dict], **overrides) -> dict:
    base = {
        "domain": "banking",
        "regulation_name": "测试办法",
        "regulation_no": "银保监发〔2026〕1号",
        "issuer": "测试机关",
        "publish_date": "2026-01-01",
        "effective_date": "2026-01-01",
        "status": "effective",
        "articles": articles,
    }
    base.update(overrides)
    return base


def test_validate_regulation():
    arts = [
        {"chapter_no": "", "article_no": f"第{n}条", "content": f"第{n}条 " + "内容" * 10}
        for n in ["一", "二", "三", "四", "五", "六"]
    ]
    assert mod.validate_regulation(_reg(arts)) == []
    problems = mod.validate_regulation(_reg(arts[:2]))
    assert any("条款过少" in p for p in problems)
    problems = mod.validate_regulation(_reg(arts, domain="crypto"))
    assert any("domain" in p for p in problems)
    problems = mod.validate_regulation(_reg(arts, regulation_no=""))
    assert any("regulation_no" in p for p in problems)


def test_derive_name_prevents_mislabel():
    # 《》内书名优先
    assert mod._derive_name("中国银保监会关于印发《XX办法》的通知") == "XX办法"
    # 无书名时从"关于"起（去掉发文机关前缀），避免把通知标题当法规名
    assert (
        mod._derive_name("中国银保监会关于规范互联网保险销售行为可回溯管理的通知")
        == "关于规范互联网保险销售行为可回溯管理的通知"
    )
    assert mod._derive_name("存款保险条例") is None


def test_extract_doc_no_variants():
    # 带年份的令号（可跨行）
    assert mod._extract_doc_no("中国银行保险监督管理委员会令\n2018年第2号 公布", "") == (
        "中国银行保险监督管理委员会令2018年第2号"
    )
    # 不带年份的令号（2014 年前的条例）
    assert mod._extract_doc_no("中华人民共和国国务院令第660号", "") == (
        "中华人民共和国国务院令第660号"
    )
    # 通知文号（标题兜底路径）
    assert mod._extract_doc_no("", "银保监规〔2022〕13号") == "银保监规〔2022〕13号"
    assert mod._extract_doc_no("无文号文本", "无文号标题") is None


def test_text_to_articles_falls_back_to_llm():
    class FakeLLM:
        def __init__(self, payload: str):
            self.payload = payload
            self.calls = 0

        def chat(self, messages):
            self.calls += 1
            return self.payload

    # 正文无条锚点且无顿号结构 → 确定性切分不足 → LLM 兜底
    messy = "这是在没有条款结构的文件里的一段话。" * 10
    llm_payload = (
        '[{"article_no": "第一条", "chapter_no": "", "content": "第一条 完整条款内容足够长了啊。"},'
        '{"article_no": "第二条", "chapter_no": "", "content": "第二条 另一个完整条款内容够长。"},'
        '{"article_no": "第三条", "chapter_no": "", "content": "第三条 再一个完整条款内容够长。"},'
        '{"article_no": "第四条", "chapter_no": "", "content": "第四条 还有完整条款内容够长。"},'
        '{"article_no": "第五条", "chapter_no": "", "content": "第五条 最后完整条款内容够长。"}]'
    )
    llm = FakeLLM(llm_payload)
    articles, method = mod.text_to_articles(messy, llm)
    assert method == "llm" and llm.calls == 1
    assert len(articles) == 5

    # 确定性切分质量好时不调 LLM
    clean = (
        "第一章 总则\n第一条 内容足够长的条款文本。\n第二条 内容足够长的条款文本。\n"
        "第三条 内容足够长的条款文本。\n第四条 内容足够长的条款文本。\n"
        "第五条 内容足够长的条款文本。\n"
    )
    llm2 = FakeLLM(llm_payload)
    articles2, method2 = mod.text_to_articles(clean, llm2)
    assert method2 == "deterministic" and llm2.calls == 0
    assert len(articles2) == 5


def test_squeeze_cjk_removes_render_artifacts():
    assert mod._squeeze_cjk("记录 和 保存") == "记录和保存"
    # 英文/数字上下文的空格保留
    assert mod._squeeze_cjk("T+0 赎回 20 日") == "T+0 赎回 20 日"
