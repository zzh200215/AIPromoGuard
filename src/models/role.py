from sqlalchemy import JSON, BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.mysql import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    permissions: Mapped[list] = mapped_column(JSON, nullable=False)
