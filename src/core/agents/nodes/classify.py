"""DocClassifier：文档领域识别。

MVP 用关键词打分（保险/基金/银行理财），无外部依赖、零延迟；
W19 起领域清单与关键词表由 configs/app.yaml `domains` 段驱动，
新增领域只需加配置 + 导入法规/规则数据，无需改逻辑代码。
后续可替换为 LLM 分类，接口不变（输入/输出均为 ReviewState 字段）。
"""

from src.core.agents.state import ReviewState
from src.utils.config import settings

# 内置默认关键词表（app.yaml 无 domains 配置时的兜底，与配置保持一致）
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "insurance": [
        "保险", "保额", "保费", "理赔", "保单", "寿险", "重疾", "投保", "保险责任", "被保险人",
    ],
    "fund": [
        "基金", "申购", "赎回", "净值", "基金经理", "份额", "基金合同", "招募说明书", "托管人",
    ],
    "banking": [
        "理财", "银行", "存款", "年化", "资管", "预期收益", "收益率", "理财产品", "净值型",
    ],
}


def _load_domain_keywords() -> dict[str, list[str]]:
    """从 app.yaml domains 读取领域关键词表；配置缺失/为空时回退内置默认。"""
    cfg = settings.app_config("domains") or {}
    if not cfg:
        return _DOMAIN_KEYWORDS
    return {
        domain: item["keywords"]
        for domain, item in cfg.items()
        if item.get("keywords")
    }


def _detect_domain(text: str) -> str | None:
    keywords = _load_domain_keywords()
    best: str | None = None
    best_score = 0
    for domain, domain_keywords in keywords.items():
        score = sum(text.count(kw) for kw in domain_keywords)
        if score > best_score:
            best, best_score = domain, score
    return best


# 轻量通道的风险信号词：出现任一即不得进轻量通道。这不是检测规则（不判定违规），
# 只是路由护栏——语义违规必然承载风险性语言（保义改写的"本金毫发无损"含"本金"），
# 纯口号（"让金融更美好"）零信号词才允许只走规则引擎，变体集召回因此不受影响。
_DEFAULT_RISK_KEYWORDS = [
    "保本", "保息", "稳赚", "承诺", "收益", "本金", "杠杆", "无风险", "担保",
    "首付贷", "年化", "净值", "返现", "补贴", "内部测算",
]


def _scan_intensity(text: str, blocks: list) -> str:
    """执行强度分级（第 4 批）：light / standard / deep，确定性打分零 LLM。

    - light：短文本且零风险信号词 → 只走规则引擎（省配额；语义风险是零信号词
      表述的定义域之外）；
    - deep：workflow.deep_scan 开启且文档规模越阈 → 深查通道（多工具 ReAct，
      见 src/core/llm/deep_tools.py）；
    - standard：其余（现状行为）。
    """
    workflow = settings.app_config("workflow") or {}
    if not workflow.get("scan_intensity", True):
        return "standard"
    total_chars = sum(len(b.get("text") or "") for b in blocks) or len(text)
    if total_chars <= int(workflow.get("light_max_chars", 120)):
        risk_words = workflow.get("light_risk_keywords") or _DEFAULT_RISK_KEYWORDS
        if not any(w in text for w in risk_words):
            return "light"
    if workflow.get("deep_scan", False):
        if (
            total_chars >= int(workflow.get("deep_min_chars", 3000))
            or len(blocks) >= int(workflow.get("deep_min_blocks", 40))
        ):
            return "deep"
    return "standard"


def classify(state: ReviewState) -> dict:
    text = state.get("text", "")
    blocks = state.get("blocks") or []
    return {
        "domain": _detect_domain(text),
        "scan_intensity": _scan_intensity(text, blocks),
    }
