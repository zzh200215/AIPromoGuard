from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class RegulationUpdateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    title: str
    doc_no: str | None = None
    publish_date: date | None = None
    url: str | None = None
    domain: str | None = None
    doc_type: str | None = None
    llm_summary: str | None = None
    matched_regulations: list | None = None
    status: str
    match_type: str | None = None
    created_at: datetime


class ConfirmBody(BaseModel):
    domain: str | None = Field(None, description="覆盖 LLM 判定的领域")
    effective_date: date | None = Field(None, description="生效日期")


class ManualCreate(BaseModel):
    source: str = Field(..., description="nfra/csrc/pbc")
    title: str
    url: str | None = None
    doc_no: str | None = None
    publish_date: date | None = None
