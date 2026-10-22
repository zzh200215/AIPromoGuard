"""监管动态追踪 service 测试：源解析、去重、确认/忽略/手动录入、LLM 降级。

纯解析与 prompt 测试不依赖 DB；涉及落库的用例依赖真实 DB（skipif）。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from src.core.llm.prompts.monitor import build_tag_messages, parse_tag_response
from src.infrastructure.database.mysql import SessionLocal
from src.models import Regulation, RegulationUpdate
from src.services import regulation_monitor as rm
from src.utils.errors import AppError, ErrorCode

_PBC_HTML = (
    "<ul>"
    # 栏目导航自链接：2026-10-19 曾把"部门规章"当文档标题入库（#62），必须跳过
    '<li><a href="/tiaofasi/144941/144957/index.html">部门规章</a></li>'
    '<li><a href="/tiaofasi/144941/144957/2026012916432593034/index.html">'
    "中国人民银行令〔2026〕第3号 管理办法</a></li>"
    '<li><a href="/tiaofasi/144941/144957/2026012314163359926/index.html">'
    "中国人民银行令〔2025〕第13号 保护通知</a></li>"
    '<li><a href="/tiaofasi/144941/144957/5863367/index.html">'
    "中国人民银行令〔2025〕第8号 审计指引</a></li>"
    "</ul>"
).encode()

_NFRA_JSON = (
    '{"rptCode":200,"msg":"成功","data":['
    '{"docId":1266349,"docTitle":"金融监管总局\\n关于健全金融机构治理的实施意见",'
    '"publishDate":"2026-07-31 16:00:00","itemId":928},'
    '{"docId":1264238,"docTitle":"关于严重失信主体名单管理的规定（试行）",'
    '"publishDate":"2026-07-10 17:53:00","itemId":928}'
    "]}"
).encode()


def _db_ready() -> bool:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


# ---------- 源解析（纯逻辑） ----------

def test_parse_pbc():
    items = rm._parse_pbc(_PBC_HTML)
    assert len(items) == 3
    assert items[0].source == "pbc"
    assert items[0].title.startswith("中国人民银行令〔2026〕第3号")
    assert items[0].doc_no == "〔2026〕第3号"
    expected = "http://www.pbc.gov.cn/tiaofasi/144941/144957/2026012916432593034/index.html"
    assert items[0].url == expected
    assert items[1].doc_no == "〔2025〕第13号"
    # 栏目导航（"部门规章"自链接）不应进入结果
    assert all(i.title != "部门规章" for i in items)


def test_parse_nfra():
    items = rm._parse_nfra(_NFRA_JSON)
    assert len(items) == 2
    it = items[0]
    assert it.source == "nfra"
    assert "关于健全金融机构治理的实施意见" in it.title  # 换行已清理
    assert "\n" not in it.title
    assert it.publish_date == "2026-07-31"
    expected = (
        "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html"
        "?docId=1266349&itemId=928"
    )
    assert it.url == expected
    assert items[1].doc_no is None  # 标题无文号


def test_parse_nfra_invalid_json_returns_empty():
    assert rm._parse_nfra(b"<html>not json</html>") == []


_CSCR_HTML = (
    "<ul>"
    '<li><a href="/csrc/c106256/c3217074/content.shtml">'
    "中国证监会派出机构监管职责规定（2015年10月29日证监会令第118号公布根据2022年5月31日修订）</a></li>"
    '<li><a href="/csrc/c106256/c1942800/content.shtml">'
    "证券基金经营机构董事、监事、高级管理人员及从业人员监督管理办法"
    "（2022年2月18日证监会令第195号公布自2022年施行）</a></li>"
    "</ul>"
).encode()


def test_parse_csrc():
    items = rm._parse_csrc(_CSCR_HTML)
    assert len(items) == 2
    it = items[0]
    assert it.source == "csrc"
    assert it.title == "中国证监会派出机构监管职责规定"
    assert it.doc_no == "证监会令第118号"
    assert it.publish_date == "2015-10-29"
    assert it.url.startswith("http://www.csrc.gov.cn/csrc/c106256/")
    assert items[1].title == "证券基金经营机构董事、监事、高级管理人员及从业人员监督管理办法"
    assert items[1].doc_no == "证监会令第195号"
    assert items[1].publish_date == "2022-02-18"
    # 半角括号的标题（如"上市公司信息披露管理办法(2007年...）只提取法规名
    half = rm._parse_csrc(
        '<a href="/csrc/c106256/c1/content.shtml">'
        "上市公司信息披露管理办法(2007年1月30日证监会令第40号公布)</a>".encode()
    )
    assert half[0].title == "上市公司信息披露管理办法"
    # 19xx 年份的旧规章（如"证券交易所管理办法（1997年...））
    old = rm._parse_csrc(
        '<a href="/csrc/c106256/c2/content.shtml">'
        "证券交易所管理办法（1997年11月30日国务院批准 "
        "2001年12月12日证监会令第4号重新公布）</a>".encode()
    )
    assert old[0].title == "证券交易所管理办法"
    assert old[0].publish_date == "1997-11-30"


def test_parse_csrc_ignores_other_columns():
    # 非 c106256 栏目链接 / 无 a 标签内容被忽略
    assert rm._parse_csrc("<html>中国证监会2025年政府信息公开工作年度报告</html>".encode()) == []
    assert rm._parse_csrc('<a href="/csrc/c100028/c1/content.shtml">别的栏目</a>'.encode()) == []


def test_extract_doc_no():
    assert rm._extract_doc_no("中国人民银行令〔2026〕第3号 管理办法") == "〔2026〕第3号"
    assert rm._extract_doc_no("银保监规〔2023〕1号 通知") == "〔2023〕1号"
    assert rm._extract_doc_no("无文号标题") is None


def test_parse_date():
    assert str(rm._parse_date("2026-07-31")) == "2026-07-31"
    assert rm._parse_date("") is None
    assert rm._parse_date(None) is None
    assert rm._parse_date("bad-date") is None


# ---------- prompt 打标解析 ----------

def test_build_tag_messages():
    msgs = build_tag_messages([{"title": "测试法规", "doc_no": "〔2026〕第1号"}])
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "测试法规" in msgs[1]["content"]


def test_parse_tag_response():
    content = (
        '[{"index": 0, "is_finance": 1, "domain": "fund", '
        '"doc_type": "部门规章", "summary": "约束基金销售"}]'
    )
    tags = parse_tag_response(content)
    assert tags[0]["domain"] == "fund"
    assert tags[0]["is_finance"] == 1
    assert tags[0]["summary"] == "约束基金销售"
    assert parse_tag_response("not json") == {}
    assert parse_tag_response("```json\n[]\n```") == {}


# ---------- DB 集成：去重 / 确认 / 忽略 / 手动 / LLM 降级 ----------

@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_fetch_sources_dedup_and_in_db(monkeypatch):
    db = SessionLocal()
    try:
        dup_title = "中国人民银行令〔2026〕第3号 管理办法"
        in_db_title = "中国人民银行令〔2025〕第13号 保护通知"
        new_title = "中国人民银行令〔2025〕第8号 审计指引"
        # 预置：一条已抓取的重复记录 + 一条已在库法规
        upd = RegulationUpdate(source="pbc", title=dup_title, status="pending", match_type="fetch")
        db.add(upd)
        db.add(Regulation(domain="banking", regulation_name=in_db_title, status="effective"))
        db.commit()

        monkeypatch.setattr(rm, "_fetch", lambda url, timeout: _PBC_HTML)

        # dry-run：统计不落库
        res = rm.fetch_sources(db, dry_run=True)
        stats = res["sources"]["pbc"]
        assert stats["fetched"] == 3
        assert stats["new"] == 1
        assert stats["duplicate"] == 1
        assert stats["in_db"] == 1
        # 无错误源
        assert not res["errors"]

        # 真实抓取：插入 new 条
        res2 = rm.fetch_sources(db, dry_run=False)
        assert res2["sources"]["pbc"]["new"] == 1
        row = (
            db.query(RegulationUpdate)
            .filter(RegulationUpdate.source == "pbc", RegulationUpdate.title == new_title)
            .first()
        )
        assert row is not None
        assert row.status == "pending"
        assert row.match_type == "fetch"
        # 二次抓取同一批 → 全部 duplicate
        res3 = rm.fetch_sources(db, dry_run=False)
        assert res3["sources"]["pbc"]["new"] == 0
    finally:
        db.query(RegulationUpdate).filter(
            RegulationUpdate.title.in_([dup_title, new_title])
        ).delete()
        db.query(Regulation).filter(
            Regulation.regulation_name.in_([in_db_title])
        ).delete()
        db.commit()
        db.close()


_DUP_PBC_HTML = (
    "<ul>"
    '<li><a href="/tiaofasi/144941/144957/a1/index.html">'
    "中国人民银行令〔2026〕第1号 测试办法</a></li>"
    '<li><a href="/tiaofasi/144941/144957/a2/index.html">'
    "中国人民银行令〔2026〕第1号 测试办法</a></li>"
    "</ul>"
).encode()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_fetch_sources_dedups_within_batch(monkeypatch):
    """同一批内标题重复（pbc 列表页重复条目）只入库一次，第二次计 duplicate。"""
    dup_title = "中国人民银行令〔2026〕第1号 测试办法"
    db = SessionLocal()
    try:
        monkeypatch.setattr(rm, "_fetch", lambda url, timeout: _DUP_PBC_HTML)
        res = rm.fetch_sources(db, dry_run=True)
        stats = res["sources"]["pbc"]
        assert stats["fetched"] == 2
        assert stats["new"] == 1
        assert stats["duplicate"] == 1
        # 真实抓取：重复标题只插入一条
        rm.fetch_sources(db, dry_run=False)
        count = db.query(RegulationUpdate).filter(RegulationUpdate.title == dup_title).count()
        assert count == 1
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == dup_title).delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_confirm_update_creates_regulation():
    db = SessionLocal()
    try:
        upd = RegulationUpdate(
            source="pbc",
            title="监管测试确认法规",
            status="pending",
            match_type="fetch",
        )
        db.add(upd)
        db.commit()
        db.refresh(upd)

        reg = rm.confirm_update(db, upd.id)
        assert reg.regulation_name == "监管测试确认法规"
        assert reg.domain == "other"  # 无 LLM 判定时兜底
        db.refresh(upd)
        assert upd.status == "imported"
        assert upd.match_type == "confirm"

        # 已入库状态不可再次确认
        with pytest.raises(AppError) as ei:
            rm.confirm_update(db, upd.id)
        assert ei.value.code == ErrorCode.UPDATE_NOT_PENDING
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == "监管测试确认法规").delete()
        db.query(Regulation).filter(Regulation.regulation_name == "监管测试确认法规").delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_confirm_update_skips_existing_regulation():
    db = SessionLocal()
    try:
        existing = Regulation(
            domain="fund",
            regulation_name="监管测试已存在法规",
            status="effective",
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
        upd = RegulationUpdate(
            source="pbc",
            title="监管测试已存在法规",
            status="pending",
            match_type="fetch",
        )
        db.add(upd)
        db.commit()
        db.refresh(upd)

        reg = rm.confirm_update(db, upd.id)
        assert reg.id == existing.id  # 返回已有法规，不新建
        count = (
            db.query(Regulation)
            .filter(Regulation.regulation_name == "监管测试已存在法规")
            .count()
        )
        assert count == 1
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == "监管测试已存在法规").delete()
        db.query(Regulation).filter(Regulation.regulation_name == "监管测试已存在法规").delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_ignore_update():
    db = SessionLocal()
    try:
        upd = RegulationUpdate(
            source="nfra",
            title="监管测试忽略法规",
            status="pending",
            match_type="fetch",
        )
        db.add(upd)
        db.commit()
        db.refresh(upd)
        rm.ignore_update(db, upd.id)
        db.refresh(upd)
        assert upd.status == "ignored"

        with pytest.raises(AppError):
            rm.ignore_update(db, upd.id)
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == "监管测试忽略法规").delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_create_manual_and_duplicate():
    db = SessionLocal()
    try:
        upd = rm.create_manual(db, "pbc", "监管测试手动录入法规")
        assert upd.status == "pending"
        assert upd.match_type == "manual"
        with pytest.raises(AppError):
            rm.create_manual(db, "pbc", "监管测试手动录入法规")
        with pytest.raises(AppError):
            rm.create_manual(db, "bad_source", "非法来源")
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == "监管测试手动录入法规").delete()
        db.commit()
        db.close()


@pytest.mark.skipif(not _db_ready(), reason="数据库不可用")
def test_llm_tag_titles_degrades_without_key(monkeypatch):
    """未配置 DASHSCOPE_API_KEY 时打标静默跳过，不抛异常。"""
    db = SessionLocal()
    try:
        upd = RegulationUpdate(
            source="pbc",
            title="监管测试无key法规",
            status="pending",
            match_type="fetch",
        )
        db.add(upd)
        db.commit()
        monkeypatch.setattr(rm, "get_llm", lambda: None)
        item = rm.RegulationItem(source="pbc", title="监管测试无key法规", url="")
        rm._llm_tag_titles(db, [item])
        db.refresh(upd)
        assert upd.domain is None
        assert upd.llm_summary is None
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == "监管测试无key法规").delete()
        db.commit()
        db.close()


def test_integrity_error_unique_source_title():
    """UNIQUE(source, title) 约束：同源同标题仅允许一条。"""
    if not _db_ready():
        pytest.skip("数据库不可用")
    db = SessionLocal()
    try:
        db.add(RegulationUpdate(source="pbc", title="唯一性测试法规", status="pending"))
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(RegulationUpdate(source="pbc", title="唯一性测试法规", status="pending"))
            db.commit()
        db.rollback()
    finally:
        db.query(RegulationUpdate).filter(RegulationUpdate.title == "唯一性测试法规").delete()
        db.commit()
        db.close()
