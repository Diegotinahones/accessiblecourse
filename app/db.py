from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.exc import OperationalError, SQLAlchemyError
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
        "access_status": "ALTER TABLE resources ADD COLUMN access_status VARCHAR(32) NOT NULL DEFAULT 'NO_ACCEDE'",
        "http_status": "ALTER TABLE resources ADD COLUMN http_status INTEGER",
        "access_status_code": "ALTER TABLE resources ADD COLUMN access_status_code INTEGER",
        "can_download": "ALTER TABLE resources ADD COLUMN can_download BOOLEAN NOT NULL DEFAULT 0",
        "download_url": "ALTER TABLE resources ADD COLUMN download_url VARCHAR(2000)",
        "final_url": "ALTER TABLE resources ADD COLUMN final_url VARCHAR(2000)",
        "download_status": "ALTER TABLE resources ADD COLUMN download_status VARCHAR(64)",
        "download_status_code": "ALTER TABLE resources ADD COLUMN download_status_code INTEGER",
        "discovered_children_count": "ALTER TABLE resources ADD COLUMN discovered_children_count INTEGER NOT NULL DEFAULT 0",
        "parent_resource_id": "ALTER TABLE resources ADD COLUMN parent_resource_id VARCHAR(255)",
        "discovered": "ALTER TABLE resources ADD COLUMN discovered BOOLEAN NOT NULL DEFAULT 0",
        "reason_code": "ALTER TABLE resources ADD COLUMN reason_code VARCHAR(64)",
        "reason_detail": "ALTER TABLE resources ADD COLUMN reason_detail TEXT",
        "content_available": "ALTER TABLE resources ADD COLUMN content_available BOOLEAN NOT NULL DEFAULT 0",
        "access_note": "ALTER TABLE resources ADD COLUMN access_note TEXT",
        "error_message": "ALTER TABLE resources ADD COLUMN error_message TEXT",
    }
    review_summary_column_updates = {
        "accessible_resources": "ALTER TABLE review_summaries ADD COLUMN accessible_resources INTEGER NOT NULL DEFAULT 0",
        "downloadable_resources": "ALTER TABLE review_summaries ADD COLUMN downloadable_resources INTEGER NOT NULL DEFAULT 0",
    }
    job_column_updates = {
        "phase": "ALTER TABLE job ADD COLUMN phase VARCHAR(32) NOT NULL DEFAULT 'UPLOAD'",
        "course_structure": "ALTER TABLE job ADD COLUMN course_structure JSON",
    }

    with engine.begin() as connection:
        table_rows = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        existing_tables = {str(row[0]) for row in table_rows}
        if "job" in existing_tables:
            existing_columns = _sqlite_existing_columns(connection, "job")
            for column_name, ddl in job_column_updates.items():
                if column_name not in existing_columns:
                    _exec_sqlite_ddl_if_missing(connection, ddl)

        if "resources" in existing_tables:
            existing_columns = _sqlite_existing_columns(connection, "resources")
            for column_name, ddl in resource_column_updates.items():
                if column_name not in existing_columns:
                    _exec_sqlite_ddl_if_missing(connection, ddl)

        if "review_summaries" in existing_tables:
            existing_columns = _sqlite_existing_columns(connection, "review_summaries")
            for column_name, ddl in review_summary_column_updates.items():
                if column_name not in existing_columns:
                    _exec_sqlite_ddl_if_missing(connection, ddl)


def _apply_postgres_schema_updates(engine) -> None:
    if engine.dialect.name != "postgresql":
        return

    enum_values = ("NO_ACCEDE", "REQUIERE_INTERACCION", "REQUIERE_SSO", "NO_ANALIZABLE")
    resource_type_values = ("FILE",)
    resource_columns = (
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS download_url VARCHAR(2000)",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS final_url VARCHAR(2000)",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS download_status VARCHAR(64)",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS parent_resource_id VARCHAR(255)",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS discovered BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS reason_code VARCHAR(64)",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS reason_detail TEXT",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS content_available BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS access_note TEXT",
    )

    with engine.begin() as connection:
        for value in enum_values:
            try:
                connection.exec_driver_sql(f"ALTER TYPE resourceaccessstatus ADD VALUE IF NOT EXISTS '{value}'")
            except SQLAlchemyError:
                # Fresh databases create the enum during SQLModel.create_all; existing ones may already have it.
                pass
        for value in resource_type_values:
            try:
                connection.exec_driver_sql(f"ALTER TYPE resourcetype ADD VALUE IF NOT EXISTS '{value}'")
            except SQLAlchemyError:
                pass
        for ddl in resource_columns:
            connection.exec_driver_sql(ddl)


def _exec_sqlite_ddl_if_missing(connection, ddl: str) -> None:
    try:
        connection.exec_driver_sql(ddl)
    except OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    _apply_sqlite_schema_updates(engine)
    _apply_postgres_schema_updates(engine)
    with Session(engine) as session:
        seed_templates(session)
