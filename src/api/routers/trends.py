"""监管动态追踪路由：待确认法规列表/详情/抓取/确认/忽略/手动录入。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user, require_permission
from src.api.schemas.trend import ConfirmBody, ManualCreate, RegulationUpdateOut
from src.infrastructure.database.mysql import get_db
from src.models import RegulationUpdate, User
from src.services import regulation_monitor
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/regulatory-updates", tags=["regulatory-updates"])


@router.get("")
def list_updates(
    status: str | None = None,
    source: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    query = db.query(RegulationUpdate)
    if status:
        query = query.filter(RegulationUpdate.status == status)
    if source:
        query = query.filter(RegulationUpdate.source == source)
    total = query.count()
    items = (
        query.order_by(RegulationUpdate.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [RegulationUpdateOut.model_validate(i).model_dump() for i in items],
        }
    )


@router.get("/{update_id}")
def get_update(
    update_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    upd = db.get(RegulationUpdate, update_id)
    if upd is None:
        raise AppError(ErrorCode.REGULATION_UPDATE_NOT_FOUND)
    return ok(RegulationUpdateOut.model_validate(upd).model_dump())


@router.post("/fetch")
def fetch_updates(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    return ok(regulation_monitor.fetch_sources(db))


@router.post("")
def manual_create(
    body: ManualCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    upd = regulation_monitor.create_manual(
        db,
        source=body.source,
        title=body.title,
        url=body.url,
        doc_no=body.doc_no,
        publish_date=body.publish_date.isoformat() if body.publish_date else None,
    )
    return ok(RegulationUpdateOut.model_validate(upd).model_dump())


@router.post("/{update_id}/confirm")
def confirm_update(
    update_id: int,
    body: ConfirmBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    reg = regulation_monitor.confirm_update(db, update_id, body.domain, body.effective_date)
    return ok({"regulation_id": reg.id, "regulation_name": reg.regulation_name})


@router.post("/{update_id}/ignore")
def ignore_update(
    update_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_regulations")),
) -> dict:
    regulation_monitor.ignore_update(db, update_id)
    return ok()
