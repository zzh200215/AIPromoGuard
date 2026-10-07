from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuleCreate(BaseModel):
    domain: str = Field(..., description="banking/fund/insurance")
    rule_name: str
    rule_type: str = Field(..., description="regex/keyword/condition/composite")
    rule_content: dict[str, Any] = Field(..., description="规则 DSL")
    severity: str = "medium"  # high/medium/low
    description: str | None = None
    # 创建一律落草稿，生效走 POST /rules/{id}/publish，接口不接受 is_active


class RuleUpdate(BaseModel):
    domain: str | None = None
    rule_name: str | None = None
    rule_type: str | None = None
    rule_content: dict[str, Any] | None = None
    severity: str | None = None
    description: str | None = None
    is_active: bool | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    rule_name: str
    rule_type: str
    rule_content: dict[str, Any]
    severity: str
    description: str | None = None
    is_active: int
    version: int
    status: str = "active"
    created_at: datetime
    updated_at: datetime
