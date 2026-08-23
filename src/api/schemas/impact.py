"""法规影响中心请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssessmentCreate(BaseModel):
    regulation_update_id: int = Field(gt=0)


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
