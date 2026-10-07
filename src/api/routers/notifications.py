"""站内通知：我的通知列表 / 标记已读 / 全部已读。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.middleware.auth import get_current_user
from src.infrastructure.database.mysql import get_db
from src.models import Notification, User
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.is_read == 0)
    total = query.count()
    items = (
        query.order_by(Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    unread = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == current_user.id, Notification.is_read == 0)
        .scalar()
        or 0
    )
    return ok(
        {
            "total": total,
            "unread": unread,
            "items": [
                {
                    "id": n.id,
                    "type": n.type,
                    "title": n.title,
                    "body": n.body,
                    "link": n.link,
                    "is_read": n.is_read,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
                for n in items
            ],
        }
    )


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    n = db.get(Notification, notification_id)
    # 通知按用户隔离：别人的通知按不存在处理
    if n is None or n.user_id != current_user.id:
        raise AppError(ErrorCode.PARAM_ERROR, "通知不存在", http_status=404)
    n.is_read = 1
    db.commit()
    return ok({"id": n.id, "is_read": 1})


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == 0)
        .update({"is_read": 1}, synchronize_session=False)
    )
    db.commit()
    return ok({"updated": updated})
