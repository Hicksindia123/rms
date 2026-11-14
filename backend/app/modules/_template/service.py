"""Service: business rules and guards; exactly one transaction per command (UnitOfWork).

Cross-module calls go to the other module's *service*, never to its repository.
"""

from app.core.db import UnitOfWork
from app.core.errors import Conflict
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.security import CurrentUser
from app.modules._template import repository as repo
from app.modules._template.schemas import DepartmentCreate, DepartmentOut
from app.shared.pagination import Page, PageParams


class TemplateService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list(self, user: CurrentUser, params: PageParams) -> Page[DepartmentOut]:
        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_departments(session, params)
        return Page[DepartmentOut](
            items=[DepartmentOut.model_validate(r) for r in rows],
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    def create(
        self, user: CurrentUser, payload: DepartmentCreate, idem: IdempotencyKey
    ) -> IdempotentResult:
        # One transaction: the idempotency key, the row and its audit_log entry (G-17) commit or
        # roll back together.
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, DepartmentOut]:
                if repo.code_exists(session, payload.code):
                    raise Conflict(f"Code {payload.code} already exists", code="DUPLICATE_CODE")
                row = repo.insert_department(session, payload.code, payload.name)
                return 201, DepartmentOut.model_validate(row)

            return run_idempotent(session, idem, user.id, command)
