from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import Settings
from app.services.template_seed import seed_templates


def build_engine(settings: Settings):
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_templates(session)
