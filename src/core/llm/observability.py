"""LLM 可观测性埋点（Langfuse，可选启用）。

设计原则与项目整体降级哲学一致：
- 可选依赖：未安装 langfuse 或未配置 Key 时全链路 no-op，不抛错、不打扰业务；
- 异常安全：任何埋点异常只记 debug 日志，绝不影响主流程；
- 零侵入：调用方只依赖本模块的 Observer 接口，测试可注入 fake client。

启用方式（.env）：
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_HOST=https://cloud.langfuse.com   # 自托管填自己的地址
"""

from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class _NoopSpan:
    """未启用时的空 span：支持 end()/update()，调用无副作用。"""

    def update(self, *args: Any, **kwargs: Any) -> None:  # noqa: D102
        pass

    def end(self, *args: Any, **kwargs: Any) -> None:  # noqa: D102
        pass


class LLMObserver:
    """Langfuse 埋点封装。所有公开方法异常安全，未启用时为 no-op。

    记录两类事件：
    - generation：每次 LLM API 调用（input/output/model/usage），来自 client.py；
    - node span：LangGraph 每个节点的执行耗时/状态，来自 graph._wrap。
    """

    def __init__(self, client: Any = None) -> None:
        # client 参数仅供测试注入 fake；生产路径走 _ensure_init 惰性初始化
        self._client = client
        self._init_attempted = client is not None

    @property
    def enabled(self) -> bool:
        self._ensure_init()
        return self._client is not None

    def _ensure_init(self) -> None:
        if self._init_attempted:
            return
        self._init_attempted = True
        # 延迟导入 settings，避免观测模块影响配置加载顺序
        from src.utils.config import settings

        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            return  # 未配置：保持 no-op（默认状态）
        try:
            from langfuse import get_client  # Langfuse SDK v3+

            self._client = get_client()
            logger.info("Langfuse 埋点已启用")
        except Exception as exc:  # ImportError 或初始化失败均降级
            logger.info("Langfuse 不可用，LLM 埋点保持关闭: %s", exc)

    def _start_span(self, name: str, **kwargs: Any) -> Any:
        if self._client is None:
            return _NoopSpan()
        try:
            return self._client.start_span(name=name, **kwargs)
        except TypeError:
            # SDK 版本签名差异：退化为仅传 name
            try:
                return self._client.start_span(name=name)
            except Exception as exc:
                logger.debug("Langfuse span 创建失败: %s", exc)
                return _NoopSpan()
        except Exception as exc:
            logger.debug("Langfuse span 创建失败: %s", exc)
            return _NoopSpan()

    def record_generation(
        self,
        name: str,
        model: str,
        input: Any,
        output: Any,
        usage: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        """记录一次 LLM 调用。usage 为 OpenAI 风格 token 计数 dict。"""
        if self._client is None:
            return
        span = self._start_span(name, input=input, metadata={**(metadata or {}), "model": model})
        try:
            lf_usage = {
                "input": (usage or {}).get("prompt_tokens", 0),
                "output": (usage or {}).get("completion_tokens", 0),
                "total": (usage or {}).get("total_tokens", 0),
                "unit": "TOKENS",
            }
            span.update(model=model, usage=lf_usage)
            span.end(output=output)
        except Exception as exc:
            logger.debug("Langfuse generation 记录失败: %s", exc)

    def record_node(
        self, name: str, cost_ms: int, status: str = "completed", task_id: Any = None
    ) -> None:
        """记录 LangGraph 节点执行（耗时/状态），供调用链还原。"""
        if self._client is None:
            return
        try:
            span = self._start_span(
                f"node:{name}",
                metadata={"cost_ms": cost_ms, "status": status, "task_id": task_id},
            )
            span.end()
        except Exception as exc:
            logger.debug("Langfuse node 记录失败: %s", exc)


_observer: LLMObserver | None = None


def get_llm_observer() -> LLMObserver:
    """进程级单例。测试可直接实例化 LLMObserver(client=fake) 替代。"""
    global _observer
    if _observer is None:
        _observer = LLMObserver()
    return _observer
