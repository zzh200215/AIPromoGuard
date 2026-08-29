"""LLM-as-a-Judge 评估（P4）：审查结论语义判分 + 检索质量指标 + 引用幻觉检查。

背景：evaluate.py 的 span 重叠口径适合规则引擎（字面命中），但 full 引擎的
LLM findings 会改写/概括原文，span 匹配系统性低估真实效果；变体集又刻意
绕开规则触发词，其 full 引擎效果目前只有人工口径。本脚本用 LLM 复核员做
语义级判分，并给出 RAGAS 式检索质量指标：

- judge_finding：逐条结论判 true_violation / false_positive / wrong_basis
- judge_context：召回条款与文档的主题相关性 + 文档涉及但未召回的监管主题
- 引用幻觉检查（确定性、零 LLM）：结论引用的法规是否出现在召回上下文中

定位：本地评估工具（需 DASHSCOPE_API_KEY），observe-only，不进 CI 门禁；
单测全离线（mock LLM 与扫描管线）。

用法（仓库根目录）:
    python scripts/evaluate/judge.py --limit 10 --out judge_report.json
    python scripts/evaluate/judge.py --engine rule      # 复核规则引擎输出
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.agents.nodes.regulation_match import regulation_match  # noqa: E402
from src.core.llm.client import get_llm, merge_usage  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

_EVALUATE_PATH = Path(__file__).resolve().parent / "evaluate.py"

_FINDING_SYSTEM = (
    "你是金融合规复核员。给定营销文档片段与合规审查系统给出的一条违规结论，"
    "判断该结论是否成立：\n"
    "- true_violation：原文确有此类违规表述，结论成立\n"
    "- false_positive：原文表述合规、属正常风险披露或依据不足，属于误报\n"
    "- wrong_basis：问题确实存在，但引用的法规依据明显错误或违规类型判定不当\n"
    "举证责任在审查系统：拿不准时判 false_positive。\n"
    '只输出 JSON：{"verdict": "true_violation|false_positive|wrong_basis", '
    '"reason": "一句话依据"}'
)

_CONTEXT_SYSTEM = (
    "你是法规检索质量评估员。给定营销文档片段与检索系统召回的法规条款列表"
    "（带序号），逐条判断该条款与文档的监管主题是否相关，"
    "并指出文档涉及但召回条款未覆盖的监管主题（没有则空数组）。\n"
    '只输出 JSON：{"relevant": [相关条款序号], "irrelevant": [无关条款序号], '
    '"missing_topics": ["主题1"]}。'
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
_MAX_FINDINGS_PER_CASE = 6  # 单案例判定的结论数上限（控成本，超出部分计数不判）
_CITE_NAME_RE = re.compile(r"《([^》]{4,40})》")


def _load_evaluate():
    """复用 evaluate.py 的扫描管线与 span 匹配（不改动该文件）。"""
    spec = importlib.util.spec_from_file_location("evaluate_for_judge", _EVALUATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_json_object(content: str) -> dict | None:
    """宽容提取 LLM 输出中的首个 JSON 对象（剥代码围栏 / 前后杂质）。"""
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _ask_json(llm, messages: list[dict]) -> tuple[dict | None, dict | None]:
    """带一次自纠错重试的结构化提问。返回 (data, usage)。"""
    usage = None
    for attempt in range(2):
        try:
            result = llm.complete(messages)
        except Exception:
            logger.exception("Judge LLM 调用失败")
            return None, usage
        usage = merge_usage(usage, result.usage)
        data = _parse_json_object(result.content)
        if data is not None:
            return data, usage
        if attempt == 0:
            messages = messages + [
                {"role": "assistant", "content": result.content},
                {
                    "role": "user",
                    "content": "上面的输出不是合法 JSON。只输出一个 JSON 对象，不要任何其他内容。",
                },
            ]
    return None, usage


def judge_finding(llm, case_text: str, finding: dict) -> tuple[dict | None, dict | None]:
    """单条违规结论判分。返回 ({"verdict","reason"}, usage)。"""
    user = (
        f"营销文档片段：\n{case_text[:800]}\n\n"
        "系统结论：\n"
        f"- 违规类型: {finding.get('type', '')}\n"
        f"- 问题: {finding.get('issue', '')}\n"
        f"- 原文片段: {finding.get('original_text', '')}\n"
        f"- 法规依据: {finding.get('regulation', '')}\n"
        f"- 违规理由: {finding.get('reason', '')}\n"
        f"- 严重度: {finding.get('severity', '')}"
    )
    data, usage = _ask_json(
        llm,
        [
            {"role": "system", "content": _FINDING_SYSTEM},
            {"role": "user", "content": user},
        ],
    )
    if not data or data.get("verdict") not in ("true_violation", "false_positive", "wrong_basis"):
        return None, usage
    return {"verdict": data["verdict"], "reason": str(data.get("reason") or "")}, usage


def citation_supported(finding: dict, articles: list[dict]) -> bool | None:
    """结论引用的法规是否出现在召回上下文（确定性检查，零 LLM）。

    结论未引用法规（regulation 为空 / 无可匹配名）→ None（不参与统计）；
    有《书名号》名时按名匹配；否则退化为子串匹配——召回法规名出现在引用
    文本中即支撑；引用文本里找不到任何召回法规名（含"根据监管规定"式泛引）
    记为不可支撑。
    """
    citation = (finding.get("regulation") or "").strip()
    if not citation:
        return None
    recalled = {str(a.get("regulation_name") or "").strip("《》") for a in articles}
    recalled.discard("")
    if not recalled:
        return None
    names = _CITE_NAME_RE.findall(citation)
    if names:
        return any(name in recalled for name in names)
    if len(citation) < 6:
        return None
    return any(name in citation for name in recalled)


def judge_context(llm, case_text: str, articles: list[dict]) -> tuple[dict | None, dict | None]:
    """召回条款相关性 + 缺失监管主题（RAGAS 式，单次调用判全部条款）。

    返回 ({"context_precision", "missing_topics"}, usage)；无条款时 precision=None。
    """
    if not articles:
        return {"context_precision": None, "missing_topics": []}, None
    lines = [
        f"{i}. 《{a.get('regulation_name', '')}》{a.get('article_no', '')}:"
        f" {(a.get('content') or '')[:50]}"
        for i, a in enumerate(articles)
    ]
    data, usage = _ask_json(
        llm,
        [
            {"role": "system", "content": _CONTEXT_SYSTEM},
            {
                "role": "user",
                "content": f"营销文档片段：\n{case_text[:600]}\n\n召回条款：\n" + "\n".join(lines),
            },
        ],
    )
    if not data:
        return None, usage
    relevant = data.get("relevant") or []
    irrelevant = data.get("irrelevant") or []
    judged = len(relevant) + len(irrelevant)
    precision = round(len(relevant) / judged, 3) if judged else None
    missing = [str(t) for t in (data.get("missing_topics") or [])]
    return {"context_precision": precision, "missing_topics": missing}, usage


def judge_case(llm, ev, case: dict, engine: str) -> dict:
    """单案例完整判分：结论判分 + span 口径对照 + 检索质量 + 引用幻觉。"""
    text = case["text"]
    findings = ev._scan_full(case) if engine == "full" else ev._scan_rule_engine(case)
    articles = regulation_match({"text": text, "domain": case.get("domain")})["matched_articles"]

    usage = None
    verdicts = []
    truncated = 0
    for finding in findings:
        if len(verdicts) >= _MAX_FINDINGS_PER_CASE:
            truncated += 1
            break
        verdict, u = judge_finding(llm, text, finding)
        usage = merge_usage(usage, u)
        if verdict is not None:
            verdicts.append(verdict)

    counts = {v: sum(1 for x in verdicts if x["verdict"] == v) for v in
              ("true_violation", "false_positive", "wrong_basis")}
    judge_precision = (
        round(counts["true_violation"] / len(verdicts), 3) if verdicts else None
    )

    # 与 span 口径对照（规则引擎字面命中的既有指标，供两种口径并读）
    gt = case.get("ground_truth", [])
    span_hits = sum(
        1
        for g in gt
        if any(ev._overlaps(f.get("original_text") or "", g.get("text", "")) for f in findings)
    )
    span_recall = round(span_hits / len(gt), 3) if gt else None

    citations = [citation_supported(f, articles) for f in findings]
    checked = [c for c in citations if c is not None]
    citation_support = round(sum(checked) / len(checked), 3) if checked else None

    context, u = judge_context(llm, text, articles)
    usage = merge_usage(usage, u)

    return {
        "id": case["id"],
        "domain": case.get("domain"),
        "findings_total": len(findings),
        "findings_judged": len(verdicts),
        "findings_truncated": truncated,
        **counts,
        "judge_precision": judge_precision,
        "span_recall": span_recall,
        "citation_support": citation_support,
        "context_precision": (context or {}).get("context_precision"),
        "missing_topics": (context or {}).get("missing_topics", []),
        "usage": usage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-as-a-Judge 评估（本地工具，observe-only）")
    parser.add_argument("--engine", choices=["full", "rule"], default="full")
    default_cases = str(Path(__file__).resolve().parent / "variant_cases.json")
    parser.add_argument("--cases", default=default_cases)
    parser.add_argument("--limit", type=int, default=0, help="只评估前 N 例（0=全部）")
    parser.add_argument("--domain", default=None, help="只评估指定领域")
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径（缺省只打印）")
    args = parser.parse_args()

    llm = get_llm()
    if llm is None:
        print("未配置 DASHSCOPE_API_KEY，Judge 评估需要 LLM（CI 不运行本脚本）")
        return 2

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8")).get("cases", [])
    if args.domain:
        cases = [c for c in cases if c.get("domain") == args.domain]
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("没有可评估的案例")
        return 2

    ev = _load_evaluate()
    results = []
    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case['id']} ...", flush=True)
        try:
            results.append(judge_case(llm, ev, case, args.engine))
        except Exception:
            logger.exception("案例 %s 判分失败，跳过", case.get("id"))

    # 汇总（逐指标对非空值求均值）
    def _mean(key):
        vals = [r[key] for r in results if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    summary = {
        "engine": args.engine,
        "cases": len(results),
        "judge_precision": _mean("judge_precision"),
        "span_recall": _mean("span_recall"),
        "citation_support": _mean("citation_support"),
        "context_precision": _mean("context_precision"),
        "verdicts": {
            v: sum(r.get(v, 0) for r in results)
            for v in ("true_violation", "false_positive", "wrong_basis")
        },
        "usage": merge_usage(*[r.get("usage") for r in results]),
    }
    print(
        f"\n== Judge 汇总（{args.engine}，{len(results)} 例）==\n"
        f"结论判分精度 {summary['judge_precision']}（true {summary['verdicts']['true_violation']}"
        f" / false_positive {summary['verdicts']['false_positive']}"
        f" / wrong_basis {summary['verdicts']['wrong_basis']}）\n"
        f"span 口径召回 {summary['span_recall']}（对照既有口径）\n"
        f"引用可支撑率 {summary['citation_support']}  检索相关性 {summary['context_precision']}\n"
        f"token: {summary['usage']}"
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps({"summary": summary, "cases": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"明细已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
