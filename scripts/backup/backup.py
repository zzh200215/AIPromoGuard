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
                "docker", "exec",
                # 密码经环境变量传入：-p 写在 argv 会暴露在进程列表/docker inspect 中
                "-e", f"MYSQL_PWD={settings.mysql_password}",
                "fcr-mysql", "mysqldump",
                "-uroot",
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
    # Chroma 底层是 SQLite：运行中拷贝可能拿到写一半的文件导致备份损坏。
    # 此处无法代停服务，至少把风险说清楚（与 index_cases.py 的停写要求一致）。
    logger.warning("注意: 建议backup前停止 api/worker 对 Chroma 的写入，运行中拷贝有损坏风险")
    shutil.copytree(src, out / "chroma", dirs_exist_ok=True)
    logger.info("Chroma 已备份: %s", src)
    return True


def _backup_neo4j(out: Path) -> bool:
    """通过 neo4j_client 导出图谱节点/关系为 JSON。

    用 strict 版查询：普通 run_cypher 在服务不可用时降级返回空列表，
    会写出空 neo4j.json 且被记为"成功"——恢复时数据全丢而无人知情。
    """
    try:
        from src.infrastructure.database.neo4j_client import run_cypher_strict

        nodes = run_cypher_strict(
            "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props"
        )
        rels = run_cypher_strict(
            "MATCH ()-[r]->() RETURN type(r) AS type, "
            "startNode(r).id AS source, endNode(r).id AS target, properties(r) AS props"
        )
        (out / "neo4j.json").write_text(
            json.dumps({"nodes": nodes, "relationships": rels}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Neo4j 图谱已备份: %d 节点 %d 关系", len(nodes), len(rels))
        return True
    except Exception as exc:
        logger.warning("Neo4j 备份失败: %s", exc)
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
