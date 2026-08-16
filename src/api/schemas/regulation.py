from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class RegulationCreate(BaseModel):
    domain: str = Field(..., description="banking/fund/insurance")
    regulation_name: str
    regulation_no: str | None = Field(None, description="文号")
    issuer: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    status: str = "effective"  # effective/amended/repealed


class RegulationUpdate(BaseModel):
    domain: str | None = None
    regulation_name: str | None = None
    regulation_no: str | None = None
    issuer: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    status: str | None = None


class RegulationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    regulation_name: str
    regulation_no: str | None = None
    issuer: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    status: str
    created_at: datetime
