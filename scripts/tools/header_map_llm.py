"""表头语义映射的 LLM 辅助草稿工具（R2-2 第二层，离线运行）。

## 为什么是离线工具而不是审查时的在线调用

`consistency.py` 的模板层（`map_fields`）匹配不上表头时**静默跳过**——这是
"零误报优先"的有意设计。方案对第二层的口径是：*"映射结果仅生成勾稽规则
草稿，走人工确认后模板才固化"*（R2-2 设计口径）。因此本工具：

- **不在审查管线里跑**（零运行时 LLM 成本、零误报风险）；
- 扫描既有文档取材，把模板未命中的表头交给 LLM 判定列语义；
- 产出**草稿文件**，人工确认后把新模式手工并入 `FIELD_PATTERNS`。

## 用法

    # 零成本预览：只列出未命中表头，不调 LLM
    python scripts/tools/header_map_llm.py --dry-run

    # 指定来源目录/文件
    python scripts/tools/header_map_llm.py --source data/uploads

    # 真实调用 LLM 产出草稿
    python scripts/tools/header_map_llm.py --output data/header_map_drafts.json

## 输出草稿格式

    {
      "generated_at": "...",
      "scanned_files": 42,
      "drafts": [
        {
          "header": ["产品名称", "业绩基准(年化)", "测算收益", "到期金额"],
          "llm_mapping": {"rate": 1, "profit": 2, "total": 3},
          "suggested_patterns": {
            "rate": ["业绩基准"], "profit": ["测算收益"], "total": ["到期金额"]
          },
          "confidence": 0.8,
          "note": "人工确认后把 suggested_patterns 并入 consistency.FIELD_PATTERNS"
        }
      ]
    }
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.rule_engine.consistency import FIELD_PATTERNS, map_fields
from src.utils.logger import get_logger

logger = get_logger(__name__)

# LLM 只判这五个字段（与 FIELD_PATTERNS 同口径），其余一律 other
VALID_FIELDS = tuple(FIELD_PATTERNS.keys())

_SYSTEM_PROMPT = """你是金融营销材料表格的结构标注助手。
用户给出一个 markdown 表格的表头（列名列表），你要判断每一列承载哪种语义。
可选语义（严格从中选）：
- principal: 本金/认购金额/起投金额类
- rate: 收益率/年化/业绩比较基准/演示利率类
- profit: 收益金额/测算收益/到期收益类
- total: 期末合计/到期本息/期末金额类
- days: 期限/天数/持有期类
- other: 以上都不是（产品名、编号、备注等）

只输出 JSON，不要任何解释文字。格式：
{"mapping": {"<列名>": "<语义>", ...}, "confidence": 0~1 的小数}

confidence 表示你对整体判断的把握：表头语义清晰且无歧义时给 0.8+；
存在歧义或列名指向不明时给 0.5 以下。"""


def extract_headers_from_text(text: str) -> list[list[str]]:
    """从文档全文提取全部 markdown 表格的表头（去重由调用方处理）。"""
    from src.core.rule_engine.consistency import _MD_SEP_ROW, _cells

    headers: list[list[str]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        # 表头行的判据：下一行是分隔行（|---|）
        if i + 1 < len(lines) and _MD_SEP_ROW.match(lines[i + 1]):
            cells = _cells(stripped)
            if len(cells) >= 2:
                headers.append(cells)
    return headers


def collect_unmapped_headers(source: Path) -> tuple[list[list[str]], int]:
    """扫描来源目录/文件，返回 (模板未命中的表头去重列表, 扫描文件数)。"""
    patterns = ["*.txt", "*.md"] if source.is_dir() else []
    files = (
        [p for pat in patterns for p in glob.glob(str(source / pat))]
        if source.is_dir()
        else [str(source)]
    )
    seen: set[tuple[str, ...]] = set()
    unmapped: list[list[str]] = []
    for f in files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for header in extract_headers_from_text(text):
            key = tuple(header)
            if key in seen:
                continue
            seen.add(key)
            if map_fields(header) is None:  # 模板层未命中 → 候选
                unmapped.append(header)
    return unmapped, len(files)


def _clean_json(raw: str) -> str:
    """剥掉 LLM 常见的 ```json 围栏。"""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
    return s.strip()


def core_term(col: str) -> str:
    """列名 → 建议模式的核心词（剥括号后缀与单位符号，让模式更通用）。

    "投入金额(元)" → "投入金额"（否则换个表写"投入金额(万元)"就匹配不上）；
    括号内本身是语义的（如"年化(单利)"）会一并剥掉——这是有意的保守取舍，
    人工确认阶段可以按需补回。
    """
    s = re.sub(r"[（(].*?[)）]", "", col).strip()
    s = re.sub(r"[/／%％]", "", s).strip()
    return s or col.strip()


def llm_map_header(header: list[str], llm) -> dict | None:
    """调 LLM 判定表头列语义；解析失败返回 None（调用方跳过该样本）。"""
    user = "表头（按列顺序）：\n" + json.dumps(header, ensure_ascii=False)
    try:
        completion = llm.complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
        )
    except Exception:
        logger.exception("LLM 调用失败，跳过该表头")
        return None

    raw = getattr(completion, "content", None) or str(completion)
    try:
        data = json.loads(_clean_json(raw))
    except json.JSONDecodeError:
        logger.warning("LLM 输出非 JSON，跳过：%s", raw[:80])
        return None

    mapping_raw = data.get("mapping") or {}
    # 只保留合法字段 + 拒绝 other
    mapping: dict[str, int] = {}
    for col_idx, col_name in enumerate(header):
        field = str(mapping_raw.get(col_name, "")).strip().lower()
        if field in VALID_FIELDS and field not in mapping:
            mapping[field] = col_idx
    if len(mapping) < 2:  # 与模板层同门槛：少于 2 个字段不足以做勾稽
        return None

    patterns: dict[str, list[str]] = {}
    for field, idx in mapping.items():
        term = core_term(header[idx])
        if term:
            patterns[field] = [term]

    return {
        "header": header,
        "llm_mapping": mapping,
        "suggested_patterns": patterns,
        "confidence": float(data.get("confidence") or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R2-2 表头语义映射 LLM 辅助草稿工具")
    parser.add_argument("--source", default="data/uploads", help="扫描来源（目录或单个文件）")
    parser.add_argument("--output", default="data/header_map_drafts.json", help="草稿输出路径")
    parser.add_argument("--dry-run", action="store_true", help="只列出未命中表头，不调 LLM")
    parser.add_argument("--limit", type=int, default=20, help="最多处理多少个未命中表头")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"[x] 来源不存在：{source}")
        return 2

    unmapped, scanned = collect_unmapped_headers(source)
    print(f"扫描 {scanned} 个文件，模板未命中的表头 {len(unmapped)} 个（去重后）")
    for h in unmapped[: args.limit]:
        print("  未命中:", " | ".join(h))

    if args.dry_run:
        print("\n[dry-run] 未调用 LLM。去掉 --dry-run 生成草稿。")
        return 0

    if not unmapped:
        print("没有未命中样本，无需生成草稿（模板库覆盖良好）。")
        return 0

    from src.core.llm.client import get_llm

    llm = get_llm()
    drafts: list[dict] = []
    for header in unmapped[: args.limit]:
        draft = llm_map_header(header, llm)
        if draft:
            draft["note"] = "人工确认后把 suggested_patterns 并入 consistency.FIELD_PATTERNS"
            drafts.append(draft)
            print(f"  ✓ {draft['llm_mapping']}  conf={draft['confidence']:.2f}")
        else:
            print(f"  - 跳过（LLM 判定不足 2 字段或解析失败）：{' | '.join(header)}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scanned_files": scanned,
        "unmapped_total": len(unmapped),
        "drafts": drafts,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n草稿已写入 {out}（{len(drafts)} 条，全部待人工确认）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
