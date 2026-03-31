from __future__ import annotations

from typing import Generator

from fastapi import Request
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import Settings
from app.services.template_seed import seed_templates


def create_sqlalchemy_engine(settings: Settings):
    connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
    return create_engine(settings.db_url, connect_args=connect_args)


def init_database(engine) -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_templates(session)


def get_session(request: Request) -> Generator[Session, None, None]:
    with Session(request.app.state.engine) as session:
        yield session
