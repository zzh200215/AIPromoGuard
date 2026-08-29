"""法规草稿确认 CLI 的采纳逻辑单测（离线：tmp 目录，不碰真实数据）。

覆盖 scripts/init_data/review_regulations.py 的：
- 采纳：剥 _meta 元数据（import 端 ORM 构造器不接受额外字段）、追加合并
- 查重：同名法规 / 同文号跳过
"""

import importlib.util
import json
from pathlib import Path

_EVAL_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "init_data" / "review_regulations.py"
)
_spec = importlib.util.spec_from_file_location("review_regulations", _EVAL_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _draft(tmp_path: Path, name: str = "测试办法", no: str = "银保监发〔2026〕1号") -> Path:
    reg = {
        "_meta": {"source": "govcn", "source_url": "https://example.gov.cn/x", "problems": []},
        "domain": "banking",
        "regulation_name": name,
        "regulation_no": no,
        "issuer": "测试机关",
        "publish_date": "2026-01-01",
        "effective_date": "2026-01-01",
        "status": "effective",
        "articles": [{"chapter_no": "", "article_no": "第一条", "content": "第一条 测试条款。"}],
    }
    p = tmp_path / f"draft-{name}.json"
    p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    return p


def test_adopt_strips_meta_and_appends(tmp_path, monkeypatch):
    crawled = tmp_path / "crawled.json"
    draft = _draft(tmp_path)
    monkeypatch.setattr(mod, "CRAWLED_JSON", crawled)
    monkeypatch.setattr(mod, "_load_existing_names", lambda: set())

    reg = json.loads(draft.read_text(encoding="utf-8"))
    mod.adopt(reg, draft)

    records = json.loads(crawled.read_text(encoding="utf-8"))
    assert len(records) == 1
    assert "_meta" not in records[0]  # ORM 构造器不接受额外字段，必须剥掉
    assert records[0]["regulation_name"] == "测试办法"
    assert not draft.exists()  # 草稿采纳后删除


def test_adopt_skips_existing_name(tmp_path, monkeypatch):
    crawled = tmp_path / "crawled.json"
    draft = _draft(tmp_path, name="已存在的法规")
    monkeypatch.setattr(mod, "CRAWLED_JSON", crawled)
    monkeypatch.setattr(mod, "_load_existing_names", lambda: {"已存在的法规"})

    reg = json.loads(draft.read_text(encoding="utf-8"))
    mod.adopt(reg, draft)

    assert not crawled.exists()  # 未追加
    assert not draft.exists()  # 草稿删除（视为已处理）


def test_adopt_skips_duplicate_regulation_no(tmp_path, monkeypatch):
    crawled = tmp_path / "crawled.json"
    crawled.write_text(
        json.dumps([{"regulation_name": "别的法规", "regulation_no": "银保监发〔2026〕1号"}],
                   ensure_ascii=False),
        encoding="utf-8",
    )
    draft = _draft(tmp_path, name="新法规", no="银保监发〔2026〕1号")
    monkeypatch.setattr(mod, "CRAWLED_JSON", crawled)
    monkeypatch.setattr(mod, "_load_existing_names", lambda: set())

    reg = json.loads(draft.read_text(encoding="utf-8"))
    mod.adopt(reg, draft)

    records = json.loads(crawled.read_text(encoding="utf-8"))
    assert len(records) == 1  # 同文号不重复导入（幂等键）
    assert not draft.exists()
