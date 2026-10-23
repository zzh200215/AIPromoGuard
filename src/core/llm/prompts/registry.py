"""Prompt 注册表加载器：configs/prompts/registry.yaml 是全部系统 prompt 的唯一事实源。

设计约束：
- 响亮失败：注册表文件缺失 / prompt 名不存在 / 结构不合法直接抛 PromptRegistryError，
  不做任何静默回退——prompt 是 LLM 引擎行为的最大杠杆，静默降级比失败更危险
  （与 VECTOR_STORE_TYPE 非法值响亮报错同一哲学）。
- 版本可溯：prompt_versions() 供 stage_log / 报告记录本次审查实际使用的 prompt 版本，
  prompt 变更的影响可通过版本号回溯定位。
- 模块级缓存：进程内只解析一次；测试可用 load_registry(force=True) 重载。
"""

from dataclasses import dataclass
from typing import Any

import yaml

from src.utils.config import PROJECT_ROOT

REGISTRY_PATH = PROJECT_ROOT / "configs" / "prompts" / "registry.yaml"


class PromptRegistryError(RuntimeError):
    """注册表缺失 / 结构不合法 / prompt 名不存在。"""


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: int
    description: str
    template: str
    changelog: tuple[dict[str, Any], ...]


def _validate(name: str, raw: Any) -> PromptSpec:
    if not isinstance(raw, dict):
        raise PromptRegistryError(f"prompt '{name}' 结构不合法：应为 mapping")
    version = raw.get("version")
    template = raw.get("template")
    if not isinstance(version, int) or version < 1:
        raise PromptRegistryError(f"prompt '{name}' version 必须为 >=1 的整数")
    if not isinstance(template, str) or not template.strip():
        raise PromptRegistryError(f"prompt '{name}' template 不能为空")
    changelog = raw.get("changelog") or []
    versions_in_log = [c.get("version") for c in changelog if isinstance(c, dict)]
    if len(changelog) != version or max(versions_in_log, default=0) != version:
        raise PromptRegistryError(
            f"prompt '{name}' changelog 条数（{len(changelog)}）必须等于 version（{version}），"
            "每个版本一条记录，不允许跳版本或无记录变更"
        )
    return PromptSpec(
        name=name,
        version=version,
        description=str(raw.get("description", "")),
        template=template,
        changelog=tuple(changelog),
    )


def load_registry(force: bool = False) -> dict[str, PromptSpec]:
    """解析并缓存注册表。文件级缓存（而非 lru_cache）便于测试强制重载。"""
    cached: dict[str, PromptSpec] | None = getattr(load_registry, "_cache", None)
    if cached is not None and not force:
        return cached

    if not REGISTRY_PATH.is_file():
        raise PromptRegistryError(f"prompt 注册表不存在：{REGISTRY_PATH}（勿删除，勿改名）")
    try:
        data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PromptRegistryError(f"prompt 注册表 YAML 解析失败：{exc}") from exc

    prompts = (data or {}).get("prompts")
    if not isinstance(prompts, dict) or not prompts:
        raise PromptRegistryError("prompt 注册表缺少非空 prompts 段")

    specs = {name: _validate(name, raw) for name, raw in prompts.items()}
    load_registry._cache = specs  # type: ignore[attr-defined]
    return specs


def get_prompt(name: str) -> PromptSpec:
    specs = load_registry()
    if name not in specs:
        raise PromptRegistryError(
            f"prompt '{name}' 不在注册表中，可用：{sorted(specs)}"
        )
    return specs[name]


def prompt_versions() -> dict[str, int]:
    """全部 prompt 的当前版本号（用于审查产物审计落痕）。"""
    return {name: spec.version for name, spec in load_registry().items()}
