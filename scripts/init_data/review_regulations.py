"""法规草稿人工确认 CLI（数据飞轮第二步：抓取草稿 → 人工把关 → 正式知识库）。

逐条预览 pending/regulations/ 下的抓取草稿（来源 / 文号 / 条款数 / 抽样内容 /
校验问题），确认采纳后剥掉 _meta 元数据合并进 regulations_crawled.json
（import_regulations.py 只接受 ORM 已知字段，_meta 必须在入库前剥掉），
丢弃则删除草稿文件。重复执行安全：已存在的同名法规会提示跳过。

为什么需要人工关卡：爬虫的确定性切分 + LLM 兜底切分都不可能 100% 可靠，
LLM 还可能漏切/并切条款；合规知识库的准确性优先于覆盖率，所以抓取产物
一律先落 pending 草稿区，人看过再入库（与规则挖掘 draft→active 同一设计哲学）。

用法（仓库根目录）:
    python scripts/init_data/review_regulations.py               # 逐条交互审核
    python scripts/init_data/review_regulations.py --list        # 只列出草稿概况
    python scripts/init_data/review_regulations.py --adopt-all   # 全部采纳（谨慎）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parents[2]
PENDING_DIR = _ROOT / "scripts" / "init_data" / "pending" / "regulations"
CRAWLED_JSON = _ROOT / "scripts" / "init_data" / "regulations_crawled.json"

# 已有知识库的法规名 + 文号（含 regulations.json / regulations_core_extra.json /
# regulations_crawled.json），用于采纳时查重：防止爬虫重复/改版同名法规造成双份
_EXISTING_NAMES: set[str] | None = None


def _load_existing_names() -> set[str]:
    global _EXISTING_NAMES
    if _EXISTING_NAMES is not None:
        return _EXISTING_NAMES
    names: set[str] = set()
    for f in ("regulations.json", "regulations_core_extra.json", "regulations_crawled.json"):
        path = Path(__file__).resolve().parent / f
        if not path.exists():
            continue
        try:
            for reg in json.loads(path.read_text(encoding="utf-8")):
                names.add(reg.get("regulation_name") or "")
        except (json.JSONDecodeError, OSError):
            continue
    _EXISTING_NAMES = names
    return names


def _norm(title: str) -> str:
    return re.sub(r"[《》\s（）()【】]", "", title or "")


def load_drafts() -> list[Path]:
    if not PENDING_DIR.exists():
        return []
    return sorted(PENDING_DIR.glob("*.json"))


def show(reg: dict) -> None:
    meta = reg.get("_meta") or {}
    print("=" * 70)
    print(f"法规名   : {reg.get('regulation_name')}")
    print(f"文号     : {reg.get('regulation_no')}")
    print(f"领域/状态: {reg.get('domain')} / {reg.get('status')}")
    print(f"发布机关 : {reg.get('issuer') or '(未识别)'}  日期: {reg.get('publish_date')}")
    print(
        f"来源     : {meta.get('source')} | {meta.get('extraction')} 切分"
        f" | {meta.get('source_url')}"
    )
    print(f"条款数   : {len(reg.get('articles') or [])}")
    problems = meta.get("problems") or []
    if problems:
        print(f"! 校验问题: {'; '.join(problems)}")
    articles = reg.get("articles") or []
    for label, a in [("首条", articles[0]), ("末条", articles[-1])]:
        chapter = f" [{a['chapter_no']}]" if a.get("chapter_no") else ""
        print(f"  {label}: {a['article_no']}{chapter} {a['content'][:80]}")
    # 抽中间一条看拼接质量
    if len(articles) > 4:
        mid = articles[len(articles) // 2]
        print(f"  中条: {mid['article_no']} {mid['content'][:80]}")


def adopt(reg: dict, draft: Path) -> None:
    name = reg.get("regulation_name") or ""
    no = reg.get("regulation_no") or ""
    existing = _load_existing_names()
    if name in existing or _norm(name) in {_norm(n) for n in existing}:
        print(f"  已存在同名法规，跳过（如需扩充请手工合并）: {name}")
        draft.unlink()
        return
    records = []
    if CRAWLED_JSON.exists():
        try:
            records = json.loads(CRAWLED_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            records = []
    if any(r.get("regulation_no") == no for r in records):
        print(f"  文号已存在（{no}），跳过")
        draft.unlink()
        return
    clean = {k: v for k, v in reg.items() if k != "_meta"}
    records.append(clean)
    CRAWLED_JSON.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    draft.unlink()
    print(f"  ✓ 已采纳 → regulations_crawled.json（当前 {len(records)} 部），草稿已删除")


def main() -> None:
    parser = argparse.ArgumentParser(description="法规草稿人工确认")
    parser.add_argument("--list", action="store_true", help="只列出草稿概况")
    parser.add_argument("--adopt-all", action="store_true", help="跳过交互全部采纳（谨慎）")
    args = parser.parse_args()

    drafts = load_drafts()
    if not drafts:
        print(f"无待审草稿（{PENDING_DIR}）")
        return

    if args.list:
        for draft in drafts:
            reg = json.loads(draft.read_text(encoding="utf-8"))
            meta = reg.get("_meta") or {}
            problems = meta.get("problems") or []
            flag = " ! " + "; ".join(problems) if problems else ""
            print(
                f"{len(reg.get('articles') or []):>4} 条 | {reg.get('regulation_name')[:32]:<34}"
                f" | {meta.get('source')}-{meta.get('extraction')}{flag}"
            )
        return

    adopted = dropped = 0
    for draft in drafts:
        reg = json.loads(draft.read_text(encoding="utf-8"))
        show(reg)
        if args.adopt_all:
            choice = "y"
        else:
            try:
                choice = input("采纳 [y]/丢弃 [n]/跳过 [s]: ").strip().lower()
            except EOFError:
                choice = "s"
        if choice == "y":
            adopt(reg, draft)
            adopted += 1
        elif choice == "n":
            draft.unlink()
            dropped += 1
            print("  ✗ 已丢弃")
        else:
            print("  - 保留草稿，下次再审")
    print(f"\n结束: 采纳 {adopted}, 丢弃 {dropped}")
    if adopted:
        print("下一步: python scripts/init_data/import_regulations.py --json "
              "scripts/init_data/regulations_crawled.json")


if __name__ == "__main__":
    main()
