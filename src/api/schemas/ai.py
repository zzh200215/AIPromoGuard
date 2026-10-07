"""AI Copilot 请求模型。"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """审查问答入参：一句话提问，防止超长上下文滥用。"""

    question: str = Field(..., min_length=1, max_length=500)


class SummaryRequest(BaseModel):
    """风险综述入参：force=True 强制重新生成（忽略未过期缓存）。"""

    force: bool = False
