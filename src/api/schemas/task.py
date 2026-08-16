from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    document_id: str = Field(..., description="上传文档接口返回的 document_id")
    task_name: str | None = None
    document_type: str | None = Field(
        None, description="说明书/协议/宣传材料"
    )
    domain: str | None = Field(None, description="banking/fund/insurance")
    base_document_id: str | None = Field(
        None, description="对比审查旧版文档 document_id（提供时进入对比模式）"
    )


class HumanReviewDecision(BaseModel):
    """人工复核决策：rejected_indexes 为被否决结论在待复核清单中的 index 集合。"""

    rejected_indexes: list[int] = Field(default_factory=list, description="否决的结论 index 列表")


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_name: str
    document_name: str
    document_type: str | None = None
    domain: str | None = None
    status: str
    progress: int
    stages: dict | None = None  # 各 Agent 节点状态/耗时（PRD §11.3）
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    batch_id: int | None = None
    base_document_name: str | None = None
    diff_changes: list | None = None  # 对比审查变更片段
