from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_name: str
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    created_at: datetime
    completed_at: datetime | None = None
    source_type: str | None = None
    source_id: int | None = None
