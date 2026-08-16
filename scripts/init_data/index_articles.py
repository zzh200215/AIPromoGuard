"""将法规条款向量化并写入 ChromaDB，供语义召回使用。

幂等: 默认只索引未向量化的条款（vector_id 为空）；--rebuild 全量重建（先清空再重写）。

用法:
    python scripts/init_data/index_articles.py [--rebuild]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.infrastructure.database.mysql import SessionLocal
from src.infrastructure.embedding import get_embedder
from src.infrastructure.vectorstore import get_vector_store
from src.models import Article, Regulation
from src.utils.config import settings

_BATCH = 16

COLLECTION = (
    settings.app_config("vectorstore").get("collection_prefix", "legal_") + "articles"
)


def main() -> None:
    rebuild = "--rebuild" in sys.argv
    embedder = get_embedder()
    store = get_vector_store()

    db = SessionLocal()
    try:
        query = db.query(Article, Regulation).join(
            Regulation, Article.regulation_id == Regulation.id
        )
        if not rebuild:
            query = query.filter(Article.vector_id.is_(None))
        rows = query.all()

        if rebuild:
            # 整集合清空：按当前表 id 删无法覆盖已不在表中的历史向量
            removed = store.delete_all(COLLECTION)
            print(f"清空旧向量 {removed} 条")

        texts = [a.content for a, _ in rows]
        docs = [
            {
                "article_id": a.id,
                "regulation_id": r.id,
                "regulation_name": r.regulation_name,
                "article_no": a.article_no or "",
                "chapter_no": a.chapter_no or "",
                "domain": r.domain,
                "status": r.status,
            }
            for a, r in rows
        ]

        added = 0
        for i in range(0, len(texts), _BATCH):
            batch = texts[i : i + _BATCH]
            metas = docs[i : i + _BATCH]
            vectors = embedder.embed(batch)
            store.add(
                COLLECTION,
                ids=[str(m["article_id"]) for m in metas],
                embeddings=vectors,
                documents=batch,
                metadatas=metas,
            )
            for m in metas:
                db.get(Article, m["article_id"]).vector_id = str(m["article_id"])
            db.commit()
            added += len(batch)
            print(f"  已索引 {added}/{len(texts)}")

        total = store.count(COLLECTION)
        print(f"完成: 索引条款 {added} 条 -> '{COLLECTION}'（共 {total} 条）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
