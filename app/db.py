from __future__ import annotations

from sqlmodel import SQLModel, create_engine

from app.core.config import Settings


def build_engine(settings: Settings):
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
