"""数据备份脚本（W20，PRD §4.3 数据备份 / 灾难恢复）。

备份内容：
- MySQL：mysqldump 导出全部业务表为 SQL（通过 docker exec）
- ChromaDB：拷贝 data/chroma 持久化目录
- Neo4j：通过客户端导出图谱节点/关系为 JSON

用法:
    python scripts/backup/backup.py [--out 备份目录]
默认输出到 data/backups/<时间戳>/（data/ 已 .gitignore，不随代码提交）。
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _backup_mysql(out: Path) -> bool:
    """通过 docker exec mysqldump 导出 MySQL。返回是否成功。"""
    try:
        proc = subprocess.run(
            [
                "docker", "exec", "fcr-mysql", "mysqldump",
                "-uroot", f"-p{settings.mysql_password}",
                "--single-transaction", settings.mysql_database,
            ],
            capture_output=True,
            encoding="utf-8",  # Windows 默认 GBK，必须显式 utf-8（dump 含中文）
            errors="replace",
            timeout=120,
        )
        if proc.returncode != 0:
            logger.warning("mysqldump 失败: %s", proc.stderr.strip()[:300])
            return False
        sql_path = out / "mysql.sql"
        sql_path.write_text(proc.stdout, encoding="utf-8")
        logger.info("MySQL 已备份: %s（%d 字节）", sql_path.name, len(proc.stdout))
        return True
    except FileNotFoundError:
        logger.warning("未找到 docker CLI，跳过 MySQL 备份")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("mysqldump 超时，跳过")
        return False


def _backup_chroma(out: Path) -> bool:
    """拷贝 ChromaDB 持久化目录。"""
    src = Path(settings.chroma_persist_dir)
    if not src.exists():
        logger.warning("Chroma 目录不存在，跳过: %s", src)
        return False
    shutil.copytree(src, out / "chroma", dirs_exist_ok=True)
    logger.info("Chroma 已备份: %s", src)
    return True


def _backup_neo4j(out: Path) -> bool:
    """通过 neo4j_client 导出图谱节点/关系为 JSON。"""
    try:
        from src.infrastructure.database.neo4j_client import run_cypher

        nodes = run_cypher(
            "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props"
        )
        rels = run_cypher(
            "MATCH ()-[r]->() RETURN type(r) AS type, "
            "startNode(r).id AS source, endNode(r).id AS target, properties(r) AS props"
        )
        (out / "neo4j.json").write_text(
            json.dumps({"nodes": nodes, "relationships": rels}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Neo4j 图谱已备份: %d 节点 %d 关系", len(nodes), len(rels))
        return True
    except Exception:
        logger.warning("Neo4j 备份失败（图谱未启用时正常）")
        return False


def main() -> None:
    args = sys.argv[1:]
    base = Path(args[args.index("--out") + 1]) if "--out" in args else Path("data/backups")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base / timestamp
    out.mkdir(parents=True, exist_ok=True)

    results = {
        "mysql": _backup_mysql(out),
        "chroma": _backup_chroma(out),
        "neo4j": _backup_neo4j(out),
    }
    ok = [k for k, v in results.items() if v]
    skipped = [k for k, v in results.items() if not v]
    print(f"备份完成: {out}")
    print(f"  成功: {', '.join(ok) if ok else '无'}")
    print(f"  跳过/失败: {', '.join(skipped) if skipped else '无'}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
