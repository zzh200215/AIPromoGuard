"""法规影响中心请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    task_id: int
    decision: Literal["remediate", "reject", "done"]


class MaterialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    product_type: Literal["fund", "insurance", "wealth"]
    material_type: str = Field(min_length=1, max_length=32)
    version: str = Field(default="v1", max_length=32)
    owner: str | None = Field(default=None, max_length=64)
    document_id: str | None = Field(default=None, pattern=r"^doc_[0-9a-f]{8}$")


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=32)
    owner: str | None = Field(default=None, max_length=64)
    status: Literal["active", "archived"] | None = None
    document_id: str | None = Field(default=None, pattern=r"^doc_[0-9a-f]{8}$")


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
    created_at: datetime
