"""混合检索延迟基线：regulation_match 语义 + 关键词 RRF 混合检索 p50/p95。

口径：
- 固定查询集（16 条金融合规域中文查询）× 固定重复轮数（默认 5）→ 样本 80；
  另有 3 次 warmup 剔除模型加载/连接建立的冷启动开销。
- 每样本主指标 = `search_hybrid(db, query, None, top_k=5)` 单次墙钟耗时
  （含查询 embedding + 语义召回 + 关键词路 + RRF 融合 + 法规元数据 enrich；
  rerank 按当前配置关闭）。
- 纯本地组件（fastembed ONNX + Chroma + MySQL），与 LLM 无关——
  同机同环境两次运行偏差应 <5%（验收②口径）。

用法（项目根执行）：
    python scripts/bench/bench_retrieval_latency.py
    python scripts/bench/bench_retrieval_latency.py --repeats 5 --json data/bench/retrieval.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from _common import pct_stats  # noqa: E402
from src.infrastructure.database.mysql import SessionLocal  # noqa: E402
from src.infrastructure.embedding import get_embedder  # noqa: E402
from src.services.regulation_service import search_hybrid  # noqa: E402

# 固定查询集：覆盖不同域（基金/银行/保险/信贷）与表述形态（短词/长句/数字）
QUERIES: list[str] = [
    "保本保收益",
    "承诺最低收益 无风险",
    "预期收益率 年化 12%",
    "风险提示 提示不到位",
    "投资者适当性管理 风险承受能力评估",
    "基金宣传推介材料 不得登载预期收益率",
    "银行理财产品 销售 不得承诺保本",
    "保险产品 分红 不确定利益 演示",
    "私募基金 合格投资者 募集",
    "贷款 催收 暴力催收",
    "信用卡 分期 手续费披露",
    "信息披露 重大事项 及时披露",
    "客户信息保护 个人金融信息",
    "反洗钱 客户身份识别",
    "销售误导 夸大保障范围",
    "代销 第三方机构 资质审查",
]

WARMUP = 3


def main() -> int:
    ap = argparse.ArgumentParser(description="混合检索延迟基线")
    ap.add_argument("--repeats", type=int, default=5, help="每条查询重复轮数（默认 5）")
    ap.add_argument("--top-k", type=int, default=5, help="检索返回条数（默认 5）")
    ap.add_argument("--json", dest="json_path", default=None, help="结果写入 JSON 文件路径")
    args = ap.parse_args()

    embedder = get_embedder()
    db = SessionLocal()
    hybrid_ms: list[float] = []
    embed_ms: list[float] = []
    try:
        # warmup：模型加载 + Chroma/DB 连接建立不计入统计
        for q in QUERIES[:WARMUP]:
            search_hybrid(db, q, None, args.top_k)

        for _ in range(args.repeats):
            for q in QUERIES:
                t0 = time.perf_counter()
                embedder.embed([q])
                t_embed = (time.perf_counter() - t0) * 1000

                t1 = time.perf_counter()
                hits = search_hybrid(db, q, None, args.top_k)
                t_hybrid = (time.perf_counter() - t1) * 1000

                assert hits is not None  # 检索路不得异常（空结果合法，异常会抛）
                hybrid_ms.append(t_hybrid)
                embed_ms.append(t_embed)
    finally:
        db.close()

    stats_hybrid = pct_stats(hybrid_ms)
    stats_embed = pct_stats(embed_ms)  # embedding 单测仅作组件分解参考

    print(f"混合检索（search_hybrid, top_k={args.top_k}，rerank 关闭）：")
    print(
        f"  p50 = {stats_hybrid['p50_ms']} ms | p95 = {stats_hybrid['p95_ms']} ms | "
        f"mean = {stats_hybrid['mean_ms']} ms | max = {stats_hybrid['max_ms']} ms "
        f"(n={stats_hybrid['n']})"
    )
    print(f"  组件参考：查询 embedding 单测 p50 = {stats_embed['p50_ms']} ms")
    print(f"  查询集 = {len(QUERIES)} 条 × {args.repeats} 轮 + {WARMUP} warmup")

    if args.json_path:
        out = {
            "bench": "retrieval_latency",
            "queries": len(QUERIES),
            "repeats": args.repeats,
            "top_k": args.top_k,
            "warmup": WARMUP,
            "hybrid": stats_hybrid,
            "embed_reference": stats_embed,
        }
        p = Path(args.json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  已写入 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
