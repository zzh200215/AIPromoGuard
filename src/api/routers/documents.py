import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile

from src.api.middleware.auth import get_current_user
from src.models import User
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTS = {"pdf", "doc", "docx", "txt", "png", "jpg", "jpeg", "bmp"}
MAX_SIZE = 50 * 1024 * 1024  # 50MB，对齐 PRD 错误码 1003


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict:
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTS:
        raise AppError(ErrorCode.FILE_TYPE_NOT_SUPPORTED)

    doc_id = "doc_" + uuid.uuid4().hex[:8]
    dest_dir = Path(settings.upload_dir) / str(current_user.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{doc_id}.{ext}"
    size = 0
    try:
        with dest.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_SIZE:
                    raise AppError(ErrorCode.FILE_TOO_LARGE)
                output.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    return ok(
        {
            "document_id": doc_id,
            "file_name": filename,
            "file_size": size,
            "status": "uploaded",
        }
    )
