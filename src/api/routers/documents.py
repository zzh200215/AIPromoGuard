import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from src.api.middleware.auth import get_current_user
from src.models import User
from src.utils.config import settings
from src.utils.errors import AppError, ErrorCode
from src.utils.response import ok

router = APIRouter(prefix="/documents", tags=["documents"])

# "doc"/"xls" 不收：解析器不支持旧版二进制格式，收了任务也必失败，上传端直接拒绝
ALLOWED_EXTS = {"pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg", "bmp"}
MAX_SIZE = 50 * 1024 * 1024  # 50MB，对齐 PRD 错误码 1003
MAX_TEXT_CHARS = 200_000  # 粘贴文本上限（约 20 万字）


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


class TextDocumentCreate(BaseModel):
    text: str = Field(..., min_length=1, description="待审文本内容")
    title: str | None = Field(None, max_length=100, description="文档名称（生成任务名）")


@router.post("/text", status_code=201)
def create_text_document(
    body: TextDocumentCreate,
    current_user: User = Depends(get_current_user),
) -> dict:
    """粘贴文本直接审查：落成 .txt 文档（走同一解析管线），无需先有文件。

    适合网页片段、聊天记录、PPT 大纲等不成文件的内容快速送审。
    """
    content = body.text.strip()
    if not content:
        raise AppError(ErrorCode.PARAM_ERROR, "文本内容不能为空")
    if len(content) > MAX_TEXT_CHARS:
        raise AppError(
            ErrorCode.PARAM_ERROR, "文本过长（上限 20 万字），请拆分后分次送审"
        )

    doc_id = "doc_" + uuid.uuid4().hex[:8]
    title = (body.title or "").strip() or "粘贴文本"
    dest_dir = Path(settings.upload_dir) / str(current_user.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{doc_id}.txt"
    dest.write_text(content, encoding="utf-8")

    return ok(
        {
            "document_id": doc_id,
            "file_name": f"{title}.txt",
            "file_size": len(content.encode("utf-8")),
            "status": "uploaded",
        }
    )
