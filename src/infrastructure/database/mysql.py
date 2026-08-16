"""SQLAlchemy 引擎与会话管理（连接池 + 请求级依赖）。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.utils.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_engine(
    settings.mysql_url,
    pool_pre_ping=True,      # 连接前探测，避免取到已断开的连接
    pool_recycle=3600,       # 连接回收，防止 MySQL 8 的 wait_timeout 断连
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
