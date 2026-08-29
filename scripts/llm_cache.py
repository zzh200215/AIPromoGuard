"""LLM 缓存管理 CLI（P5）：统计 / 清理过期 / 全量清空。

用法（仓库根目录）:
    python scripts/llm_cache.py --stats           # 条目数 / 有效条目 / 累计命中
    python scripts/llm_cache.py --clear-expired   # 删除 TTL 到期条目
    python scripts/llm_cache.py --clear           # 全量清空（提示词/模型升级后）
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.infrastructure.database.mysql import Base, engine  # noqa: E402
from src.models import LlmCache  # noqa: E402,F401  (注册表模型，确保 create_all 覆盖)
from src.services import llm_cache as lc  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM 缓存管理")
    parser.add_argument("--stats", action="store_true", help="查看缓存统计")
    parser.add_argument("--clear-expired", action="store_true", help="删除过期条目")
    parser.add_argument("--clear", action="store_true", help="清空全部缓存")
    args = parser.parse_args()

    if not (args.stats or args.clear_expired or args.clear):
        parser.print_help()
        return 2

    # 表不存在时自动建表（幂等），避免首次使用报错
    Base.metadata.create_all(bind=engine, tables=[LlmCache.__table__])

    if args.stats:
        print(lc.cache_stats())
    if args.clear_expired:
        print(f"已删除过期条目 {lc.clear_expired()} 条")
    if args.clear:
        print(f"已清空缓存 {lc.clear_all()} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
