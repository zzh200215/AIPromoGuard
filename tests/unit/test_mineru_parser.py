"""MinerU 解析双通道单测（R2-1）：mock 引擎，验证互校合并/路由/降级语义.

不加载真实模型（monkeypatch _engine_parse）；路由条件（mineru_enabled /
扫描件 / 降级）与 hybrid 合并行为是测试重点。
"""


import pytest
from src.parsers import mineru_parser as mp
from src.services.document_service import DocumentService

_MD = (
    "近一年年化收益率\n\n3.85%\n\n"
    "| 持有时间 | 管理费率 |\n| --- | --- |\n| 90天 | 1.20% |\n\n"
    "风险提示：过往业绩不代表未来表现。"
)


# ---------- 纯函数：表格抽取与互校 ----------

def test_extract_table_blocks():
    tables = mp.extract_table_blocks(_MD)
    assert len(tables) == 1
    assert "| 90天 | 1.20% |" in tables[0]
    assert tables[0].startswith("| 持有时间")


def test_cross_check_numbers_diff():
    diff = mp.cross_check_numbers("利率 9.85% 金额 50000", "利率 3.85%")
    assert "9.85" in diff["mineru_only"]
    assert "50000" in diff["mineru_only"]
    assert "3.85" in diff["text_only"]


def test_cross_check_numbers_all_match():
    diff = mp.cross_check_numbers("3.85% 与 50,000", "3.85 与 50000 元")
    assert diff["mineru_only"] == []
    assert diff["text_only"] == []


# ---------- hybrid 合并（mock 引擎） ----------

def test_hybrid_appends_table_block_to_text_layer(monkeypatch, tmp_path):
    monkeypatch.setattr(mp, "_engine_parse", lambda path, tier: _MD)
    text_layer = mp.ParsedDocument(
        file_name="doc.pdf",
        blocks=[
            mp.TextBlock(text="年化收益率 3.85%", page=1, paragraph=1),
            mp.TextBlock(text="风险提示：过往业绩不代表未来表现。", page=1, paragraph=2),
        ],
    )
    doc = mp.parse_pdf_hybrid(tmp_path / "doc.pdf", text_layer=text_layer)
    # 主路块原样保留（有页码），表格块补入（page=None）
    assert doc.blocks[0].page == 1
    assert doc.blocks[-1].page is None
    assert "| 90天 | 1.20% |" in doc.blocks[-1].text
    assert len(doc.blocks) == 3


def test_hybrid_dedupes_table_already_in_layer(monkeypatch, tmp_path):
    monkeypatch.setattr(mp, "_engine_parse", lambda path, tier: _MD)
    table_line = "| 持有时间 | 管理费率 |\n| --- | --- |\n| 90天 | 1.20% |"
    text_layer = mp.ParsedDocument(
        file_name="doc.pdf",
        blocks=[mp.TextBlock(text=table_line, page=1, paragraph=1)],
    )
    doc = mp.parse_pdf_hybrid(tmp_path / "doc.pdf", text_layer=text_layer)
    assert len(doc.blocks) == 1  # 表格已在主路，不重复补


def test_deep_parse_blocks_from_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(mp, "_engine_parse", lambda path, tier: _MD)
    doc = mp.parse_pdf_deep(tmp_path / "doc.pdf")
    assert len(doc.blocks) >= 3
    assert all(b.page is None for b in doc.blocks)


def test_deep_parse_empty_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(mp, "_engine_parse", lambda path, tier: "")
    with pytest.raises(ValueError):
        mp.parse_pdf_deep(tmp_path / "doc.pdf")


# ---------- 路由（document_service） ----------

@pytest.fixture
def _spy(monkeypatch):
    calls = {"hybrid": 0, "deep": 0, "factory": 0}
    import src.services.document_service as ds

    def _hybrid(*a, **k):
        calls["hybrid"] += 1
        return mp.ParsedDocument(file_name="x")

    def _deep(*a, **k):
        calls["deep"] += 1
        return mp.ParsedDocument(file_name="x")

    def _factory(path):
        calls["factory"] += 1
        return mp.ParsedDocument(file_name="x")

    monkeypatch.setattr(mp, "parse_pdf_hybrid", _hybrid)
    monkeypatch.setattr(mp, "parse_pdf_deep", _deep)
    # document_service 模块级 from-import 了 parse_document：patch 它自己的名字
    monkeypatch.setattr(ds, "parse_document", _factory)
    return calls


def _route_settings(monkeypatch, enabled, always=False):
    """项目惯例：替换模块级 settings 引用（pydantic v2 不允许 setattr 未声明方法）。"""
    from types import SimpleNamespace

    import src.services.document_service as ds

    monkeypatch.setattr(
        ds,
        "settings",
        SimpleNamespace(
            app_config=lambda section: (
                {
                    "mask_sensitive": False,
                    "mineru_enabled": enabled,
                    "mineru_always": always,
                    "mineru_tier": "standard",
                }
                if section == "parser"
                else {}
            )
        ),
    )


def test_route_disabled_goes_factory(monkeypatch, tmp_path, _spy):
    _route_settings(monkeypatch, enabled=False)
    DocumentService().parse(tmp_path / "x.pdf")
    assert _spy["factory"] == 1 and _spy["hybrid"] == 0 and _spy["deep"] == 0


def test_route_non_pdf_goes_factory(monkeypatch, tmp_path, _spy):
    _route_settings(monkeypatch, enabled=True)
    (tmp_path / "x.txt").write_text("hello", encoding="utf-8")
    DocumentService().parse(tmp_path / "x.txt")
    assert _spy["factory"] == 1


def test_route_empty_text_layer_goes_deep(monkeypatch, tmp_path, _spy):
    """扫描件（文本层空）→ MinerU 深解析。"""
    _route_settings(monkeypatch, enabled=True)
    monkeypatch.setattr(mp, "pdf_text_layer_empty", lambda path, min_chars_per_page=20: True)
    DocumentService().parse(tmp_path / "x.pdf")
    assert _spy["deep"] == 1 and _spy["factory"] == 0


def test_route_text_layer_present_no_always_goes_factory(monkeypatch, tmp_path, _spy):
    _route_settings(monkeypatch, enabled=True, always=False)
    monkeypatch.setattr(mp, "pdf_text_layer_empty", lambda path, min_chars_per_page=20: False)
    DocumentService().parse(tmp_path / "x.pdf")
    assert _spy["factory"] == 1 and _spy["hybrid"] == 0


def test_route_always_goes_hybrid(monkeypatch, tmp_path, _spy):
    _route_settings(monkeypatch, enabled=True, always=True)
    monkeypatch.setattr(mp, "pdf_text_layer_empty", lambda path, min_chars_per_page=20: False)
    DocumentService().parse(tmp_path / "x.pdf")
    assert _spy["hybrid"] == 1


def test_route_mineru_failure_degrades_to_factory(monkeypatch, tmp_path, _spy):
    """MinerU 任何失败降级原路——扫描件维持原 422 语义。"""
    _route_settings(monkeypatch, enabled=True)
    monkeypatch.setattr(mp, "pdf_text_layer_empty", lambda path, min_chars_per_page=20: True)

    def _boom(*a, **k):
        _spy["deep"] += 1  # 进入 deep 即计数（异常前），验证路由确实尝试了深解析
        raise RuntimeError("model not loaded")

    monkeypatch.setattr(mp, "parse_pdf_deep", _boom)
    DocumentService().parse(tmp_path / "x.pdf")
    assert _spy["factory"] == 1 and _spy["deep"] == 1
