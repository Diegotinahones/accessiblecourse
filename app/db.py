from __future__ import annotations

from collections.abc import Iterable

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import Settings
from app.services.template_seed import seed_templates


def build_engine(settings: Settings):
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


def _sqlite_existing_columns(connection, table_name: str) -> set[str]:
    rows: Iterable[tuple] = connection.exec_driver_sql(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in rows}


def _apply_sqlite_schema_updates(engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    resource_column_updates = {
        "can_access": "ALTER TABLE resources ADD COLUMN can_access BOOLEAN NOT NULL DEFAULT 0",
        "access_status": "ALTER TABLE resources ADD COLUMN access_status VARCHAR(32) NOT NULL DEFAULT 'ERROR'",
        "http_status": "ALTER TABLE resources ADD COLUMN http_status INTEGER",
        "can_download": "ALTER TABLE resources ADD COLUMN can_download BOOLEAN NOT NULL DEFAULT 0",
        "error_message": "ALTER TABLE resources ADD COLUMN error_message TEXT",
    }

    with engine.begin() as connection:
        table_rows = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        existing_tables = {str(row[0]) for row in table_rows}
        if "resources" not in existing_tables:
            return

        existing_columns = _sqlite_existing_columns(connection, "resources")
        for column_name, ddl in resource_column_updates.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(ddl)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    _apply_sqlite_schema_updates(engine)
    with Session(engine) as session:
        seed_templates(session)
