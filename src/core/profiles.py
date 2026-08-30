"""审查策略 profile：同一引擎按使用场景切换复核强度。

- strict（对外投放）：全量人工复核——自动确认关闭、强制人工复核关卡，
  任何结论未经人工确认不得视为已定；
- standard（常规，默认）：跟随 configs/app.yaml 现有配置，行为不变；
- loose（内部预检）：草稿/培训材料的快速预检——放宽自动确认阈值
  （0.85→0.6，仅 rule/hybrid 来源）、跳过人工复核关卡，减少打扰。

profile 存在 review_tasks.profile，随任务进入 state 供 human_review
节点与报告使用；None/缺省一律按 standard 处理，向后兼容。
"""

_AUTO_CONFIRM_LOOSE_THRESHOLD = 0.6

PROFILE_LABELS = {
    "strict": "对外投放",
    "standard": "常规审查",
    "loose": "内部预检",
}
PROFILES = tuple(PROFILE_LABELS)


def normalize_profile(value) -> str | None:
    """入参归一：None/空串 → None（按 standard）；非法值抛 ValueError。"""
    if value is None or str(value).strip() == "":
        return None
    v = str(value).strip().lower()
    if v not in PROFILES:
        raise ValueError(f"未知审查策略 profile={value!r}，可选：{'/'.join(PROFILES)}")
    return v


def safe_profile(value) -> str | None:
    """容错归一：非法值回退 None（standard）不抛异常，DB 手改/历史脏数据兜底。"""
    try:
        return normalize_profile(value)
    except ValueError:
        return None


def resolve_human_review(profile: str | None, config_enabled: bool) -> bool:
    """该 profile 下是否走人工复核关卡。strict 强制开，loose 强制关。"""
    if profile == "strict":
        return True
    if profile == "loose":
        return False
    return config_enabled


def effective_auto_confirm(profile: str | None, base_cfg: dict) -> dict:
    """按 profile 得出自动确认分流配置；standard 原样跟随全局配置。"""
    if profile == "strict":
        return {"enabled": False, "threshold": base_cfg.get("threshold", 0.85)}
    if profile == "loose":
        return {"enabled": True, "threshold": _AUTO_CONFIRM_LOOSE_THRESHOLD}
    return base_cfg
