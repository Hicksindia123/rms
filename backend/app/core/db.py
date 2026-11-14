"""SQLAlchemy 2 engine (psycopg 3) and the Unit of Work (master plan §6.4, CLAUDE.md rules d, f).

The schema is owned by supabase/migrations; SQLAlchemy only maps onto it (no Alembic, no
`create_all`).

Each command runs in exactly one transaction opened by `UnitOfWork.transaction()`. Before any
statement, the transaction sets the audit context that the G-17 audit trigger and the
`created_by` defaults read:

    SET LOCAL app.user_id = '<profile uuid>'      (rms_private.current_actor())
    SET LOCAL app.request_id = '<request id>'     (audit_log.request_id)

`set_config(name, value, is_local => true)` is used because it is exactly SET LOCAL but accepts
bind parameters (SET itself cannot be parameterised).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.context import get_request_id

_SET_CONTEXT = text(
    "select set_config('app.user_id', :uid, true), set_config('app.request_id', :rid, true)"
)


def create_db_engine(settings: Settings) -> Engine:
    connect_args: dict[str, object] = {
        "application_name": "rms-api",
        "connect_timeout": settings.db_connect_timeout_seconds,
    }
    if settings.db_statement_timeout_ms:
        connect_args["options"] = f"-c statement_timeout={settings.db_statement_timeout_ms}"
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache
def get_engine() -> Engine:
    return create_db_engine(get_settings())


@lru_cache
def _default_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_session_factory() -> sessionmaker[Session]:
    """FastAPI dependency. Tests override it to bind sessions to a rolled-back connection."""
    return _default_session_factory()


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()


def set_transaction_context(
    session: Session, *, user_id: UUID | None, request_id: str | None
) -> None:
    """Attribute every change in the current transaction to `user_id` / `request_id`."""
    session.execute(
        _SET_CONTEXT,
        {"uid": str(user_id) if user_id else "", "rid": request_id or ""},
    )


class UnitOfWork:
    """Opens one DB transaction per command. Commit on success, rollback on any exception.

    Exceptions are never swallowed: `Session.begin()` rolls back and re-raises.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        request_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.request_id = request_id

    @contextmanager
    def transaction(self, user_id: UUID | None = None) -> Iterator[Session]:
        with self._session_factory() as session, session.begin():
            set_transaction_context(session, user_id=user_id, request_id=self.request_id)
            yield session


def get_uow(
    request: Request,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> UnitOfWork:
    return UnitOfWork(session_factory, request_id=get_request_id(request))


UowDep = Annotated[UnitOfWork, Depends(get_uow)]
