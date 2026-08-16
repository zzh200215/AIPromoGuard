"""法规库管理（CRUD + 条款管理，W12 管理后台）。"""


from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user, require_permission
from src.api.schemas.article import ArticleCreate, ArticleOut, ArticleUpdate
from src.api.schemas.regulation import RegulationCreate, RegulationOut, RegulationUpdate
from src.infrastructure.database.mysql import get_db
from src.models import Article, Regulation, User
from src.services import regulation_service
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/regulations", tags=["regulations"])


@router.get("")
def list_regulations(
    domain: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    query = db.query(Regulation)
    if domain:
        query = query.filter(Regulation.domain == domain)
    if keyword:
        query = query.filter(
            or_(
                Regulation.regulation_name.like(f"%{keyword}%"),
                Regulation.regulation_no.like(f"%{keyword}%"),
            )
        )
    total = query.count()
    items = (
        query.order_by(Regulation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [RegulationOut.model_validate(r).model_dump() for r in items],
        }
    )


@router.post("", status_code=201)
def create_regulation(
    body: RegulationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    regulation = Regulation(**body.model_dump())
    db.add(regulation)
    db.commit()
    db.refresh(regulation)
    return ok(RegulationOut.model_validate(regulation).model_dump())


@router.get("/{regulation_id}")
def get_regulation(
    regulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    regulation = db.get(Regulation, regulation_id)
    if regulation is None:
        raise AppError(ErrorCode.PARAM_ERROR, "法规不存在", http_status=404)
    return ok(RegulationOut.model_validate(regulation).model_dump())


@router.put("/{regulation_id}")
def update_regulation(
    regulation_id: int,
    body: RegulationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    regulation = db.get(Regulation, regulation_id)
    if regulation is None:
        raise AppError(ErrorCode.PARAM_ERROR, "法规不存在", http_status=404)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(regulation, field, value)
    db.commit()
    db.refresh(regulation)
    return ok(RegulationOut.model_validate(regulation).model_dump())


@router.delete("/{regulation_id}")
def delete_regulation(
    regulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    regulation = db.get(Regulation, regulation_id)
    if regulation is None:
        raise AppError(ErrorCode.PARAM_ERROR, "法规不存在", http_status=404)
    db.delete(regulation)
    db.commit()
    return ok({"deleted": regulation_id})


class SearchRequest(BaseModel):
    query: str
    search_type: str = Field(default="hybrid", pattern="^(keyword|semantic|hybrid)$")
    domain: list[str] | None = Field(default=None)
    top_k: int = 10


@router.post("/search")
def search_regulations(
    body: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """条款级检索：keyword（关键词）/ semantic（向量语义）/ hybrid（混合）。"""
    results = regulation_service.search(
        db, body.query, body.search_type, body.domain, body.top_k
    )
    return ok({"total": len(results), "results": results})


# ==================== 条款管理（W12 管理后台） ====================


@router.get("/{regulation_id}/articles")
def list_articles(
    regulation_id: int,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """某法规下的条款列表（管理后台维护用）。"""
    if db.get(Regulation, regulation_id) is None:
        raise AppError(ErrorCode.PARAM_ERROR, "法规不存在", http_status=404)
    query = db.query(Article).filter(Article.regulation_id == regulation_id)
    total = query.count()
    items = (
        query.order_by(Article.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "regulation_id": regulation_id,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [ArticleOut.model_validate(a).model_dump() for a in items],
        }
    )


@router.post("/{regulation_id}/articles", status_code=201)
def create_article(
    regulation_id: int,
    body: ArticleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    if db.get(Regulation, regulation_id) is None:
        raise AppError(ErrorCode.PARAM_ERROR, "法规不存在", http_status=404)
    article = Article(regulation_id=regulation_id, **body.model_dump())
    db.add(article)
    db.commit()
    db.refresh(article)
    return ok(ArticleOut.model_validate(article).model_dump())


@router.put("/articles/{article_id}")
def update_article(
    article_id: int,
    body: ArticleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    article = db.get(Article, article_id)
    if article is None:
        raise AppError(ErrorCode.PARAM_ERROR, "条款不存在", http_status=404)
    updates = body.model_dump(exclude_unset=True)
    if updates:
        for field, value in updates.items():
            setattr(article, field, value)
        # 内容变更后失效旧向量，需重新跑 index_articles.py
        if "content" in updates:
            article.vector_id = None
        db.commit()
        db.refresh(article)
    return ok(ArticleOut.model_validate(article).model_dump())


@router.delete("/articles/{article_id}")
def delete_article(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    article = db.get(Article, article_id)
    if article is None:
        raise AppError(ErrorCode.PARAM_ERROR, "条款不存在", http_status=404)
    db.delete(article)
    db.commit()
    return ok({"deleted": article_id})
