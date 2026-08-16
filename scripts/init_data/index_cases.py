"""将处罚案例向量化并写入 ChromaDB，供相似案例语义召回（W10 增强）。

幂等: 按 case_id 覆盖写（vector_id = str(case.id)），--rebuild 先清空再重写。
注意: 写 Chroma 前先停 api 容器（`docker compose stop api`），避免多进程并发写坏 SQLite。

用法:
    python scripts/init_data/index_cases.py [--rebuild]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.infrastructure.embedding import get_embedder
from src.infrastructure.vectorstore import get_vector_store
from src.models import PenaltyCase, Regulation
from src.utils.config import settings

_BATCH = 16

COLLECTION = (
    settings.app_config("vectorstore").get("collection_prefix", "legal_") + "penalty_cases"
)


def main() -> None:
    rebuild = "--rebuild" in sys.argv
    embedder = get_embedder()
    store = get_vector_store()

    db = SessionLocal()
    try:
        reg_id_by_domain = {
            r.id: r.domain for r in db.query(Regulation.id, Regulation.domain).all()
        }
        cases = db.query(PenaltyCase).all()

        if rebuild:
            # 整集合清空：按当前表 id 删无法覆盖已不在表中的历史向量
            # （数据源整体替换后 id 重排，旧向量会变幽灵）
            removed = store.delete_all(COLLECTION)
            print(f"清空旧向量 {removed} 条")

        texts = []
        docs = []
        for c in cases:
            # 案例文本：案例名 + 违规摘要（语义召回的内容载体）
            summary = (c.violation_summary or "").strip()
            text = f"{c.case_name}。{summary}".strip()
            # 领域：取首个关联法规的领域（用于领域过滤）
            domain = next(
                (
                    reg_id_by_domain[r]
                    for r in (c.related_regulations or [])
                    if r in reg_id_by_domain
                ),
                None,
            )
            texts.append(text)
            docs.append(
                {
                    "case_id": c.id,
                    "case_name": c.case_name,
                    "penalty_org": c.penalty_org or "",
                    "penalty_date": c.penalty_date.isoformat() if c.penalty_date else "",
                    "penalty_result": c.penalty_result or "",
                    "domain": domain or "unknown",
                }
            )

        added = 0
        for i in range(0, len(texts), _BATCH):
            batch = texts[i : i + _BATCH]
            metas = docs[i : i + _BATCH]
            vectors = embedder.embed(batch)
            store.add(
                COLLECTION,
                ids=[str(m["case_id"]) for m in metas],
                embeddings=vectors,
                documents=batch,
                metadatas=metas,
            )
            added += len(batch)
            print(f"  已索引 {added}/{len(texts)}")

        total = store.count(COLLECTION)
        print(f"完成: 索引案例 {added} 条 -> '{COLLECTION}'（共 {total} 条）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
