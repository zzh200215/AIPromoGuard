"""法规影响中心请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssessmentCreate(BaseModel):
    """触发源二选一：监管动态或处罚案例。"""

    regulation_update_id: int | None = Field(default=None, gt=0)
    penalty_case_id: int | None = Field(default=None, gt=0)


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    regulation_update_id: int | None = None
    title: str
    summary: str | None = None
    status: str
    items: dict | None = None
    high_count: int
    medium_count: int
    low_count: int
    created_by: int | None = None
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    created_at: datetime


class AssessmentConfirm(BaseModel):
    action: Literal["confirm", "dismiss"]
    rule_ids: list[int] = Field(default_factory=list)
    material_ids: list[int] = Field(default_factory=list)


class AssessmentBatchCreate(BaseModel):
    material_ids: list[int] = Field(default_factory=list)


class RemediationDecision(BaseModel):
    """整改决策：审查整改项按 task_id、待更新项（stale）按 material_id 定位。"""

    task_id: int | None = None
    material_id: int | None = None
    decision: Literal["remediate", "reject", "done"]

    @model_validator(mode="after")
    def _require_identifier(self) -> "RemediationDecision":
        if self.task_id is None and self.material_id is None:
            raise ValueError("需提供 task_id 或 material_id")
        return self


class MaterialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    product_type: Literal["fund", "insurance", "wealth"]
    material_type: str = Field(min_length=1, max_length=32)
    version: str = Field(default="v1", max_length=32)
    owner: str | None = Field(default=None, max_length=64)
    document_id: str | None = Field(default=None, pattern=r"^doc_[0-9a-f]{8}$")
    publish_url: str | None = Field(default=None, max_length=512)
    channel: str | None = Field(default=None, max_length=32)


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=32)
    owner: str | None = Field(default=None, max_length=64)
    status: Literal["active", "archived"] | None = None
    document_id: str | None = Field(default=None, pattern=r"^doc_[0-9a-f]{8}$")
    publish_url: str | None = Field(default=None, max_length=512)
    channel: str | None = Field(default=None, max_length=32)


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    product_type: str
    material_type: str
    version: str
    owner: str | None = None
    document_id: str | None = None
    status: str
    last_review_status: str | None = None
    last_reviewed_at: datetime | None = None
    publish_url: str | None = None
    channel: str | None = None
    patrol_status: str | None = None
    patrol_checked_at: datetime | None = None
    created_at: datetime


class PatrolRequest(BaseModel):
    """批量巡检请求：material_ids 为空 = 巡检全部登记了 publish_url 的在用材料。"""

    material_ids: list[int] | None = Field(default=None)
