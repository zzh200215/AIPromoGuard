"""数据备份脚本（W20，PRD §4.3 数据备份 / 灾难恢复）。

备份内容（四件套，缺一即"不完整"）：
- MySQL：mysqldump 导出全部业务表为 SQL（通过 docker exec）
- ChromaDB：拷贝 data/chroma 持久化目录
- Neo4j：通过客户端导出图谱节点/关系为 JSON
- 上传目录：拷贝 data/uploads（材料原文；2026-10-19 补入）

每次备份写 manifest.json（组件 / 字节数 / 错误），并据完整性返回退出码：
  0=四件齐全  2=部分缺失（如 12:30 时 Docker 未启动导致 mysqldump 失败）  1=全部失败
2026-10-19 教训：此前"缺件"仍返回 0，10-17/18/19 三次备份只剩 chroma 却无人知情。

用法:
    python scripts/backup/backup.py [--out 备份目录] [--keep 保留份数]
默认输出到 data/backups/<时间戳>/（data/ 已 .gitignore，不随代码提交）。
--keep N：本次备份至少成功一项后，只保留最近 N 份备份目录（默认 0=不清理）。
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


_MIN_MYSQL_DUMP_BYTES = 100_000  # 小于 100KB 视为异常（正常全量 dump 数 MB）


def _backup_mysql(out: Path) -> dict:
    """通过 docker exec mysqldump 导出 MySQL。返回 {ok, bytes, error}。"""
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
            return {"ok": False, "bytes": 0, "error": proc.stderr.strip()[:300] or "returncode!=0"}
        size = len(proc.stdout)
        if size < _MIN_MYSQL_DUMP_BYTES:
            logger.warning("mysqldump 输出异常小（%d 字节），判定失败", size)
            return {"ok": False, "bytes": size, "error": f"dump too small: {size}B"}
        sql_path = out / "mysql.sql"
        sql_path.write_text(proc.stdout, encoding="utf-8")
        logger.info("MySQL 已备份: %s（%d 字节）", sql_path.name, size)
        return {"ok": True, "bytes": size, "error": None}
    except FileNotFoundError:
        logger.warning("未找到 docker CLI，跳过 MySQL 备份")
        return {"ok": False, "bytes": 0, "error": "docker CLI not found"}
    except subprocess.TimeoutExpired:
        logger.warning("mysqldump 超时，跳过")
        return {"ok": False, "bytes": 0, "error": "timeout"}


def _dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _backup_chroma(out: Path) -> dict:
    """拷贝 ChromaDB 持久化目录。"""
    src = Path(settings.chroma_persist_dir)
    if not src.exists():
        logger.warning("Chroma 目录不存在，跳过: %s", src)
        return {"ok": False, "bytes": 0, "error": "dir missing"}
    # Chroma 底层是 SQLite：运行中拷贝可能拿到写一半的文件导致备份损坏。
    # 此处无法代停服务，至少把风险说清楚（与 index_cases.py 的停写要求一致）。
    logger.warning("注意: 建议backup前停止 api/worker 对 Chroma 的写入，运行中拷贝有损坏风险")
    shutil.copytree(src, out / "chroma", dirs_exist_ok=True)
    logger.info("Chroma 已备份: %s", src)
    return {"ok": True, "bytes": _dir_bytes(out / "chroma"), "error": None}


def _backup_uploads(out: Path) -> dict:
    """拷贝上传目录（材料原文）——恢复审查线索需要文件本身，不止数据库行。"""
    src = Path(settings.upload_dir)
    if not src.exists():
        logger.warning("上传目录不存在，跳过: %s", src)
        return {"ok": False, "bytes": 0, "error": "dir missing"}
    shutil.copytree(src, out / "uploads", dirs_exist_ok=True)
    logger.info("上传目录已备份: %s", src)
    return {"ok": True, "bytes": _dir_bytes(out / "uploads"), "error": None}


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
        return {"ok": True, "bytes": (out / "neo4j.json").stat().st_size, "error": None}
    except Exception as exc:
        logger.warning("Neo4j 备份失败: %s", exc)
        return {"ok": False, "bytes": 0, "error": str(exc)[:300]}


def _parse_args(argv: list[str]) -> tuple[Path, int]:
    """解析 --out 备份目录与 --keep 保留份数（0=不清理，默认）。"""
    out = Path("data/backups")
    keep = 0
    i = 0
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--keep" and i + 1 < len(argv):
            keep = int(argv[i + 1])
            i += 2
        else:
            i += 1  # 未知参数忽略（保持旧版宽容行为）
    return out, keep


_BACKUP_DIR_RE = re.compile(r"\d{8}_\d{6}")


def _prune_old(base: Path, keep: int) -> list[str]:
    """只保留最近 keep 个备份目录（按时间戳目录名排序），返回被清理的目录名。

    仅匹配时间戳命名的目录（防误删人为放进备份目录的其他内容）；
    只在本次备份至少成功一项后才调用（见 main）。
    """
    if keep <= 0 or not base.exists():
        return []
    dirs = sorted(
        d for d in base.iterdir() if d.is_dir() and _BACKUP_DIR_RE.fullmatch(d.name)
    )
    stale = dirs[:-keep] if len(dirs) > keep else []
    removed = []
    for d in stale:
        shutil.rmtree(d)
        removed.append(d.name)
        logger.info("已清理过期备份: %s", d.name)
    return removed


def main() -> None:
    base, keep = _parse_args(sys.argv[1:])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base / timestamp
    out.mkdir(parents=True, exist_ok=True)

    results = {
        "mysql": _backup_mysql(out),
        "chroma": _backup_chroma(out),
        "neo4j": _backup_neo4j(out),
        "uploads": _backup_uploads(out),
    }
    ok = [k for k, v in results.items() if v["ok"]]
    failed = [k for k, v in results.items() if not v["ok"]]
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "database": settings.mysql_database,
        "components": results,
        "complete": not failed,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"备份完成: {out}（{'完整' if not failed else '不完整'}）")
    print(f"  成功: {', '.join(ok) if ok else '无'}")
    if failed:
        detail = "; ".join(f"{k}={results[k]['error']}" for k in failed)
        print(f"  缺失: {detail}")
    # 保留策略：本次至少成功一项才清理（全失败的当天不删历史备份）
    if keep > 0 and ok:
        removed = _prune_old(base, keep)
        if removed:
            print(f"  已清理过期备份 {len(removed)} 个（保留最近 {keep}）: {', '.join(removed)}")
    if not ok:
        sys.exit(1)
    if failed:
        sys.exit(2)  # 部分缺失：让定时任务/摘要能看见"不完整"，而不是静默通过


if __name__ == "__main__":
    main()
