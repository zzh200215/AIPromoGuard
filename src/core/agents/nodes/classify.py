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


def classify(state: ReviewState) -> dict:
    domain = _detect_domain(state.get("text", ""))
    return {"domain": domain}
