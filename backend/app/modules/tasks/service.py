"""Workflow task inbox service ("My Work", prompt P2-02)."""

from __future__ import annotations

from app.core.db import UnitOfWork
from app.core.errors import ValidationFailed
from app.core.security import CurrentUser
from app.modules.tasks import repository as repo
from app.modules.tasks.schemas import MyTaskOut
from app.shared.pagination import Page, PageParams

TASK_STATUSES = frozenset({"OPEN", "DONE", "CANCELLED"})


class TaskService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def my_tasks(
        self, user: CurrentUser, params: PageParams, *, status: str, step_code: str | None
    ) -> Page[MyTaskOut]:
        if status not in TASK_STATUSES:
            raise ValidationFailed(
                f"Unknown task status {status!r}",
                code="INVALID_FILTER",
                details={"allowed": sorted(TASK_STATUSES)},
            )
        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_tasks_for_user(
                session,
                user_id=user.id,
                all_tasks=user.is_super_admin,
                status=status,
                step_code=step_code,
                limit=params.page_size,
                offset=params.offset,
            )
        return Page[MyTaskOut](
            items=[MyTaskOut(**r) for r in rows],
            total=total,
            page=params.page,
            page_size=params.page_size,
        )
