from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Outlet(Base):
    __tablename__ = "outlets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address: Mapped[str] = mapped_column(String(512), nullable=False)
    open_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # HH:MM 24h format
    close_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    services: Mapped[list[str]] = mapped_column(JSON, default=list)

