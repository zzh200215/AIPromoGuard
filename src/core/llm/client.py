"""QWEN LLM 客户端：走 DashScope OpenAI 兼容接口。

能力（按接入时间演进）：
- 未配置 DASHSCOPE_API_KEY 时 get_llm() 返回 None（由调用方决定降级）；
- 调用失败按 fallback_models 依次降级（configs/app.yaml llm.fallback_models），
  全部失败抛异常，由上层节点捕获做优雅降级；
- chat_json/achat_json：结构化输出（response_format=json_object），解析失败
  自动带上错误反馈重试一次（self-repair），仍失败降级为空结果；
- acomplete：AsyncOpenAI 异步版本，供 llm_scan 并发审查多个文档块；
- token 用量从 resp.usage 采集并随结果返回（成本观测，见 stage_log.llm_usage）；
- 每次调用经 Langfuse 埋点（未配置时 no-op，见 observability.py）。
"""

import asyncio
import json
import re
from dataclasses import dataclass

from openai import AsyncOpenAI, OpenAI

from src.core.llm.observability import get_llm_observer
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_REPAIR_INSTRUCTION = (
    "上面的输出不是合法的 JSON。请重新输出，只输出形如 "
    '{"findings": [...]} 的 JSON 对象，不要包含任何解释、Markdown 代码块或其他文字。'
)


@dataclass
class CompletionResult:
    """单次补全结果：内容 + 实际使用的模型 + token 用量。"""

    content: str
    model: str
    usage: dict

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("total_tokens") or 0)


def extract_findings(content: str) -> list | None:
    """从模型输出提取结果列表，兼容三种形态。

    json_object 模式约定输出 {"findings": [...]}，但模型偶尔会给裸数组、
    或包一层 violations/items 键；也兼容遗留的 markdown 代码围栏。
    解析失败返回 None（调用方决定是否触发纠错重试）。
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("findings", "violations", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return None


def merge_usage(*usages: dict | None) -> dict:
    """累加多段调用的 token 用量（纠错重试也计成本）。"""
    merged = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
    for u in usages:
        if not u:
            continue
        merged["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
        merged["completion_tokens"] += int(u.get("completion_tokens") or 0)
        merged["total_tokens"] += int(u.get("total_tokens") or 0)
        merged["calls"] += 1
    return merged


class QwenClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        self._aclient: AsyncOpenAI | None = None
        self._aclient_loop = None  # _aclient 绑定的 event loop（见 _async_client）
        self.model = settings.llm_model
        self._observer = get_llm_observer()

    def _async_client(self) -> AsyncOpenAI:
        """按事件循环惰性创建 AsyncOpenAI。

        httpx 连接池绑定创建时的 event loop，而 llm_scan 每次审查走一次
        asyncio.run()（新 loop）。loop 变化后复用旧客户端会报
        "Event loop is closed"，因此检测到 loop 更替即重建客户端。
        """
        loop = asyncio.get_running_loop()
        if self._aclient is None or self._aclient_loop is not loop:
            self._aclient = AsyncOpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout,
            )
            self._aclient_loop = loop
        return self._aclient

    # ---------- 基础调用 ----------

    def _models(self) -> list[str]:
        return [self.model] + list(
            settings.app_config("llm").get("fallback_models", [])
        )

    @staticmethod
    def _usage(resp) -> dict:
        u = getattr(resp, "usage", None)
        return {
            "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
            "total_tokens": getattr(u, "total_tokens", 0) or 0,
        }

    def _create(
        self, client, model: str, messages: list[dict], temperature: float, json_mode: bool
    ):
        kwargs: dict = {"model": model, "messages": messages, "temperature": temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)

    def _finish(self, resp, model: str, messages: list[dict], json_mode: bool) -> CompletionResult:
        content = resp.choices[0].message.content or ""
        usage = self._usage(resp)
        self._observer.record_generation(
            name=f"chat:{model}" + (":json" if json_mode else ""),
            model=model,
            input=messages,
            output=content,
            usage=usage,
        )
        return CompletionResult(content=content, model=model, usage=usage)

    def complete(
        self, messages: list[dict], temperature: float | None = None, json_mode: bool = False
    ) -> CompletionResult:
        """同步单次调用（含模型级 fallback 降级链）。"""
        temp = settings.llm_temperature if temperature is None else temperature
        last_error: Exception | None = None
        for model in self._models():
            try:
                resp = self._create(self._client, model, messages, temp, json_mode)
                return self._finish(resp, model, messages, json_mode)
            except Exception as exc:
                # response_format 不被模型/网关支持时，去掉该参数重试一次
                if json_mode and "response_format" in str(exc):
                    try:
                        resp = self._create(self._client, model, messages, temp, False)
                        return self._finish(resp, model, messages, False)
                    except Exception as exc2:
                        last_error = exc2
                        logger.warning("LLM 模型 %s 调用失败，尝试降级: %s", model, exc2)
                        continue
                last_error = exc
                logger.warning("LLM 模型 %s 调用失败，尝试降级: %s", model, exc)
        raise last_error  # type: ignore[misc]

    async def acomplete(
        self, messages: list[dict], temperature: float | None = None, json_mode: bool = False
    ) -> CompletionResult:
        """异步单次调用（AsyncOpenAI），语义与 complete 一致。"""
        temp = settings.llm_temperature if temperature is None else temperature
        last_error: Exception | None = None
        aclient = self._async_client()
        for model in self._models():
            try:
                resp = await self._create(aclient, model, messages, temp, json_mode)
                return self._finish(resp, model, messages, json_mode)
            except Exception as exc:
                if json_mode and "response_format" in str(exc):
                    try:
                        resp = await self._create(aclient, model, messages, temp, False)
                        return self._finish(resp, model, messages, False)
                    except Exception as exc2:
                        last_error = exc2
                        logger.warning("LLM 模型 %s 调用失败，尝试降级: %s", model, exc2)
                        continue
                last_error = exc
                logger.warning("LLM 模型 %s 调用失败，尝试降级: %s", model, exc)
        raise last_error  # type: ignore[misc]

    # ---------- 结构化输出 ----------

    @staticmethod
    def _json_repair_messages(messages: list[dict], bad_output: str) -> list[dict]:
        return messages + [
            {"role": "assistant", "content": bad_output},
            {"role": "user", "content": _REPAIR_INSTRUCTION},
        ]

    async def achat_json(
        self, messages: list[dict], temperature: float | None = None
    ) -> tuple[list, dict]:
        """异步结构化输出：返回 (findings 列表, 累计 usage)。

        json_object 模式 + 解析失败自纠错重试一次；重试仍失败返回 ([], usage)。
        """
        result = await self.acomplete(messages, temperature, json_mode=True)
        data = extract_findings(result.content)
        if data is not None:
            return data, result.usage
        try:
            repaired = await self.acomplete(
                self._json_repair_messages(messages, result.content), temperature, json_mode=True
            )
            data = extract_findings(repaired.content)
            usage = merge_usage(result.usage, repaired.usage)
            if data is not None:
                return data, usage
            logger.warning("LLM 结构化输出纠错重试仍解析失败: %.100s", repaired.content)
            return [], usage
        except Exception as exc:
            logger.warning("LLM 结构化输出纠错重试调用失败: %s", exc)
            return [], result.usage

    # ---------- 兼容入口 ----------

    def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        """同步纯文本入口（regulation_monitor 打标等沿用）。"""
        return self.complete(messages, temperature).content


def get_llm() -> QwenClient | None:
    """未配置 key 时返回 None，上游节点据此跳过 LLM 调用。"""
    if not settings.dashscope_api_key:
        return None
    return QwenClient()
