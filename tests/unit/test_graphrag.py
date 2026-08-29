"""GraphRAG 条款级多跳召回的纯逻辑单测（离线：mock Neo4j / MySQL，不连库）。

覆盖：
- graph_service.related_articles_for_text：多跳 Cypher 结果整形 / 去重 / 截断 / 空降级
- regulation_service.fuse_graph_route：图谱第三路 RRF 融合与生效优先排序
- regulation_match 节点：图谱路并入、失败降级、配置开关
- import_graph.import_rules：有条款级精确关联的规则跳过法规级粗展开
"""

from types import SimpleNamespace

import src.core.agents.nodes.regulation_match as rm_node
import src.services.graph_service as gs
from src.services import graph_service, regulation_service


def _article(aid, no="第二条", reg="互联网保险业务监管办法", content="保险公司不得保本保收益。"):
    return {
        "article_id": aid,
        "article_no": no,
        "content": content,
        "regulation_id": 5,
        "regulation_name": reg,
        "status": "effective",
    }


# ---------- graph_service.related_articles_for_text ----------


def test_related_articles_shapes_dedupes_and_orders(monkeypatch):
    """引擎命中优先：多跳结果按置信度降序展开、同条款去重、空 map 过滤、带溯源字段。"""
    monkeypatch.setattr(
        gs, "_fired_pattern_ids", lambda *a, **k: [(0.95, 1), (0.8, 2)]
    )
    captured = {}

    def fake_cypher(query, params):
        captured["ids"] = params["ids"]
        assert "VIOLATES" in query and "HAS_ARTICLE" in query
        return [
            {
                "pattern_id": 1,
                "pattern_name": "保本保收益",
                "articles": [
                    _article(10),
                    {"article_id": None, "article_no": None, "content": None,
                     "regulation_id": None, "regulation_name": None, "status": None},
                    _article(11, no="第三条"),
                ],
            },
            {
                "pattern_id": 2,
                "pattern_name": "稳赚不赔承诺",
                "articles": [_article(10), _article(12, no="第一条")],
            },
        ]

    monkeypatch.setattr(gs, "run_cypher", fake_cypher)
    out = graph_service.related_articles_for_text("本产品保本保收益，稳赚不赔", "fund", top_k=5)

    assert captured["ids"] == [1, 2]
    assert [a["article_id"] for a in out] == [10, 11, 12]  # 置信度高的模式 1 先展开，跨模式去重
    assert all(a["source"] == "graph" for a in out)
    assert out[0]["matched_pattern"] == "保本保收益"
    assert out[2]["matched_pattern"] == "稳赚不赔承诺"
    assert out[0]["regulation_name"] == "互联网保险业务监管办法"
    assert out[0]["status"] == "effective"


def test_related_articles_caps_articles_per_pattern(monkeypatch):
    """单模式展开条款数不超过 _GRAPH_MAX_ARTICLES（防粗关联稀释精度）。"""
    monkeypatch.setattr(gs, "_fired_pattern_ids", lambda *a, **k: [(0.9, 1)])
    monkeypatch.setattr(
        gs,
        "run_cypher",
        lambda q, p: [
            {
                "pattern_id": 1,
                "pattern_name": "保本保收益",
                "articles": [_article(i, no=f"第{i}条") for i in range(8)],
            }
        ],
    )
    out = graph_service.related_articles_for_text("本产品保本保收益的宣传表述", None, top_k=10)
    assert len(out) == gs._GRAPH_MAX_ARTICLES


def test_related_articles_falls_back_to_containment(monkeypatch):
    """引擎零命中 → 退化为模式短语覆盖度匹配。"""
    captured = {}
    monkeypatch.setattr(gs, "_fired_pattern_ids", lambda *a, **k: [])
    monkeypatch.setattr(
        gs, "_load_patterns", lambda domain=None: [{"id": 9, "pattern_name": "承诺高额返利"}]
    )

    def fake_cypher(query, params):
        captured["ids"] = params["ids"]
        return [
            {
                "pattern_id": 9,
                "pattern_name": "承诺高额返利",
                "articles": [_article(30)],
            }
        ]

    monkeypatch.setattr(gs, "run_cypher", fake_cypher)
    out = graph_service.related_articles_for_text("申购即享高额返利红包", None, top_k=5)
    assert captured["ids"] == [9]
    assert out[0]["matched_pattern"] == "承诺高额返利"


def test_related_articles_no_pattern_match_returns_empty(monkeypatch):
    """引擎与覆盖度双路都无候选 → 不查库直接返回空。"""
    called = {"n": 0}

    def fail_cypher(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(gs, "_fired_pattern_ids", lambda *a, **k: [])
    monkeypatch.setattr(
        gs, "_load_patterns", lambda domain=None: [{"id": 1, "pattern_name": "承诺高额返利"}]
    )
    monkeypatch.setattr(gs, "run_cypher", fail_cypher)
    # 文本与模式无措辞重叠 → 覆盖度低于阈值，不发起多跳查询
    assert graph_service.related_articles_for_text("今日天气不错适合散步", None) == []
    assert called["n"] == 0


def test_related_articles_graph_unavailable_returns_empty(monkeypatch):
    """Neo4j 不在线（run_cypher 返回空）→ 优雅降级空列表。"""
    monkeypatch.setattr(gs, "_fired_pattern_ids", lambda *a, **k: [(0.9, 1)])
    monkeypatch.setattr(gs, "run_cypher", lambda q, p: [])
    assert graph_service.related_articles_for_text("本产品保本保收益", None) == []


def test_related_articles_respects_top_k(monkeypatch):
    monkeypatch.setattr(gs, "_fired_pattern_ids", lambda *a, **k: [(0.9, 1)])
    monkeypatch.setattr(
        gs,
        "run_cypher",
        lambda q, p: [
            {
                "pattern_id": 1,
                "pattern_name": "保本保收益",
                "articles": [_article(i, no=f"第{i}条") for i in range(5)],
            }
        ],
    )
    out = graph_service.related_articles_for_text("本产品保本保收益的宣传表述", None, top_k=2)
    assert len(out) == 2


def test_fired_pattern_ids_sorts_dedupes_and_filters(monkeypatch):
    """引擎实扫：置信度降序、同规则去重、低于全局阈值过滤。"""
    import src.core.rule_engine as re_mod

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [SimpleNamespace(id=1)]

    monkeypatch.setattr(
        gs, "SessionLocal", lambda: SimpleNamespace(query=lambda *a: _Q(), close=lambda: None)
    )
    hits = [
        SimpleNamespace(rule_id=3, confidence=0.9),
        SimpleNamespace(rule_id=7, confidence=0.95),
        SimpleNamespace(rule_id=3, confidence=0.99),  # 同规则重复命中，保留最高分
        SimpleNamespace(rule_id=8, confidence=0.4),  # 低于 min_confidence 0.5 被滤
    ]
    monkeypatch.setattr(re_mod.rule_scanner, "scan", lambda blocks, rules, domain=None: hits)
    out = gs._fired_pattern_ids("本产品保本保收益", "banking")
    assert out == [(0.99, 3), (0.95, 7)]


# ---------- regulation_service.fuse_graph_route ----------


def _item(aid, rank_score, status="effective", **extra):
    return {
        "article_id": aid,
        "regulation_name": f"法规{aid}",
        "article_no": "第二条",
        "content": "内容",
        "status": status,
        "score": rank_score,
        **extra,
    }


def test_fuse_graph_route_boosts_overlap_and_keeps_graph_only():
    hybrid = [_item(10, 0.9), _item(20, 0.8)]
    graph = [_item(10, 0.7, source="graph"), _item(99, 0.6, source="graph")]
    out = regulation_service.fuse_graph_route(hybrid, graph, top_k=5)

    assert [a["article_id"] for a in out] == [10, 20, 99]  # 双路命中的 10 叠加居首
    assert out[0]["rrf_score"] > out[1]["rrf_score"]
    assert out[2]["source"] == "graph"


def test_fuse_graph_route_effective_first():
    hybrid = [_item(10, 0.9)]
    graph = [_item(99, 0.8, source="graph", status="expired")]
    out = regulation_service.fuse_graph_route(hybrid, graph, top_k=5)
    assert [a["article_id"] for a in out] == [10, 99]


def test_fuse_graph_route_empty_graph_returns_hybrid():
    hybrid = [_item(10, 0.9), _item(20, 0.8)]
    out = regulation_service.fuse_graph_route(hybrid, [], top_k=1)
    assert [a["article_id"] for a in out] == [10]


def test_fuse_graph_route_hybrid_empty_graph_fills():
    graph = [_item(99, 0.6, source="graph")]
    out = regulation_service.fuse_graph_route([], graph, top_k=5)
    assert [a["article_id"] for a in out] == [99]


# ---------- regulation_match 节点 ----------


class _FakeDB:
    def close(self):
        pass


def _patch_hybrid(monkeypatch, articles):
    monkeypatch.setattr(rm_node, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(regulation_service, "search_hybrid", lambda *a, **k: list(articles))


def test_regulation_match_merges_graph_route(monkeypatch):
    hybrid = [_item(10, 0.9)]
    graph = [_item(99, 0.8, source="graph", matched_pattern="承诺保本")]
    _patch_hybrid(monkeypatch, hybrid)
    monkeypatch.setattr(graph_service, "related_articles_for_text", lambda *a, **k: graph)

    state = rm_node.regulation_match({"text": "本产品保本保收益", "domain": "banking"})
    ids = [a["article_id"] for a in state["matched_articles"]]
    assert 99 in ids  # 仅图谱召回的条款进入 LLM 审查上下文
    assert state["matched_articles"][0]["article_id"] == 10  # 双路增强仍居首


def test_regulation_match_graph_failure_degrades(monkeypatch):
    hybrid = [_item(10, 0.9)]
    _patch_hybrid(monkeypatch, hybrid)

    def boom(*a, **k):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(graph_service, "related_articles_for_text", boom)
    state = rm_node.regulation_match({"text": "文本", "domain": None})
    assert [a["article_id"] for a in state["matched_articles"]] == [10]


def test_regulation_match_graph_recall_disabled(monkeypatch):
    hybrid = [_item(10, 0.9)]
    _patch_hybrid(monkeypatch, hybrid)
    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(graph_service, "related_articles_for_text", spy)
    # settings 是 pydantic 实例（禁设非字段属性），替换节点模块引用
    monkeypatch.setattr(
        rm_node,
        "settings",
        SimpleNamespace(app_config=lambda key: {"graph_recall": False, "regulation_top_k": 5}),
    )
    rm_node.regulation_match({"text": "文本", "domain": None})
    assert called["n"] == 0


# ---------- import_graph：条款级精确关联优先 ----------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def join(self, *a, **k):
        return self

    def distinct(self):
        return self

    def all(self):
        return self._rows


class _ImportDB:
    """按 query() 首参区分的四类查询桩。"""

    def __init__(self, rules, reg_rows, articles, link_pairs, precise_ids):
        self._map = {
            "rules": rules,
            "regs": reg_rows,
            "articles": articles,
            "links": link_pairs,
            "precise": precise_ids,
        }

    def query(self, *args):
        import src.models as m

        # 一律用 is 身份比较：元组 == 会触发 ORM 属性的 __eq__ 构造 SQL 表达式
        if len(args) == 1 and args[0] is m.Rule:
            return _FakeQuery(self._map["rules"])
        if (
            len(args) == 2
            and args[0] is m.Regulation.id
            and args[1] is m.Regulation.regulation_name
        ):
            return _FakeQuery(self._map["regs"])
        if len(args) == 1 and args[0] is m.Article:
            return _FakeQuery(self._map["articles"])
        if len(args) == 2 and args[0] is m.RuleRegulationLink and args[1] is m.Rule:
            return _FakeQuery(self._map["links"])
        if len(args) == 1 and args[0] is m.RuleRegulationLink.rule_id:
            return _FakeQuery(self._map["precise"])
        raise AssertionError(f"未预期的查询: {args}")

    def close(self):
        pass


def _rule(rid, with_ref=True):
    return SimpleNamespace(
        id=rid,
        rule_name=f"规则{rid}",
        description="",
        domain="insurance",
        severity="high",
        rule_type="keyword",
        rule_content=(
            {"related_regulations": ["《互联网保险业务监管办法》第二条"]} if with_ref else {}
        ),
        is_active=1,
    )


def test_import_rules_skips_coarse_expansion_for_precise_links(monkeypatch):
    import scripts.init_data.import_graph as ig

    rule_precise = _rule(1)
    rule_coarse = _rule(2)
    db = _ImportDB(
        rules=[rule_precise, rule_coarse],
        reg_rows=[SimpleNamespace(id=5, regulation_name="互联网保险业务监管办法")],
        articles=[SimpleNamespace(id=101), SimpleNamespace(id=102)],
        link_pairs=[(SimpleNamespace(rule_id=1, article_id=101), rule_precise)],
        precise_ids=[(1,)],
    )
    edges = []

    def fake_strict(query, params=None):
        if "VIOLATES" in query:
            edges.append((params["aid"], params["vid"]))

    monkeypatch.setattr(ig, "SessionLocal", lambda: db)
    monkeypatch.setattr(ig, "run_cypher_strict", fake_strict)

    n_rules, linked = ig.import_rules()

    assert (n_rules, linked) == (2, 3)
    # 规则 1 有条款级精确关联 → 只连精确条款 101，不做"该法规全部条款"粗展开
    assert (101, 1) in edges
    assert (102, 1) not in edges
    # 规则 2 无精确关联 → related_regulations 粗展开兜底（两条都连）
    assert (101, 2) in edges and (102, 2) in edges
