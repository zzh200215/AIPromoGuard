
from pydantic import BaseModel, ConfigDict, Field


class ArticleCreate(BaseModel):
    chapter_no: str | None = Field(None, description="章")
    section_no: str | None = None
    article_no: str | None = Field(None, description="条，如：第二十六条")
    clause_no: str | None = None
    item_no: str | None = None
    content: str = Field(..., min_length=1, description="条款原文")


class ArticleUpdate(BaseModel):
    chapter_no: str | None = None
    section_no: str | None = None
    article_no: str | None = None
    clause_no: str | None = None
    item_no: str | None = None
    content: str | None = None


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    regulation_id: int
    chapter_no: str | None = None
    section_no: str | None = None
    article_no: str | None = None
    clause_no: str | None = None
    item_no: str | None = None
    content: str
    vector_id: str | None = None
