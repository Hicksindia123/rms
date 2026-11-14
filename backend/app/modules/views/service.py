"""Service for Saved Views (P4-04)."""

from __future__ import annotations

from uuid import UUID

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import CurrentUser
from app.modules.views import repository as repo
from app.modules.views.schemas import SavedViewIn, SavedViewOut, SavedViewUpdateIn

MAX_SAVED_VIEWS_PER_USER_AND_CODE = 50


class SavedViewService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_views(self, user: CurrentUser, view_code: str | None = None) -> list[SavedViewOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_saved_views(session, user.id, view_code)
            return [SavedViewOut.model_validate(r) for r in rows]

    def create_view(self, user: CurrentUser, payload: SavedViewIn) -> SavedViewOut:
        vcode = payload.view_code or "default"
        with self._uow.transaction(user.id) as session:
            existing = repo.list_saved_views(session, user.id, vcode)
            if len(existing) >= MAX_SAVED_VIEWS_PER_USER_AND_CODE:
                raise ValidationFailed(
                    f"Maximum limit of {MAX_SAVED_VIEWS_PER_USER_AND_CODE} saved views "
                    f"reached for {vcode}",
                    code="TOO_MANY_SAVED_VIEWS",
                )
            if repo.name_exists(session, user.id, vcode, payload.name):
                raise Conflict(
                    f"A saved view named '{payload.name}' already exists",
                    code="SAVED_VIEW_EXISTS",
                )
            filters_data = [
                f.model_dump()
                if hasattr(f, "model_dump")
                else (dict(f) if isinstance(f, dict) else {})
                for f in payload.filters
            ]
            row = repo.insert_saved_view(
                session,
                user_id=user.id,
                view_code=vcode,
                name=payload.name,
                filters=filters_data,
                columns=payload.columns,
                sort_by=payload.sort_by,
                sort_dir=payload.sort_dir,
                is_default=payload.is_default,
            )
            return SavedViewOut.model_validate(row)

    def update_view(
        self, user: CurrentUser, view_id: UUID, payload: SavedViewUpdateIn
    ) -> SavedViewOut:
        with self._uow.transaction(user.id) as session:
            current = repo.get_saved_view(session, view_id, user.id)
            if not current:
                raise NotFound("Saved view not found", code="SAVED_VIEW_NOT_FOUND")
            if payload.name and repo.name_exists(
                session, user.id, current["view_code"], payload.name, exclude_id=view_id
            ):
                raise Conflict(
                    f"A saved view named '{payload.name}' already exists",
                    code="SAVED_VIEW_EXISTS",
                )
            row = repo.update_saved_view(
                session,
                view_id,
                user.id,
                name=payload.name,
                filters=[f.model_dump() for f in payload.filters]
                if payload.filters is not None
                else None,
                columns=payload.columns,
                sort_by=payload.sort_by,
                sort_dir=payload.sort_dir,
                is_default=payload.is_default,
            )
            if not row:
                raise NotFound("Saved view not found", code="SAVED_VIEW_NOT_FOUND")
            return SavedViewOut.model_validate(row)

    def delete_view(self, user: CurrentUser, view_id: UUID) -> None:
        with self._uow.transaction(user.id) as session:
            deleted = repo.delete_saved_view(session, view_id, user.id)
            if not deleted:
                raise NotFound("Saved view not found", code="SAVED_VIEW_NOT_FOUND")
