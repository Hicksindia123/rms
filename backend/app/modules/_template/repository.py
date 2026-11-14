"""Repository: SQL only, no business rules. Functions take the caller's Session (the service owns
the transaction). Sort/filter fields are mapped through allow-lists, never interpolated."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.shared.pagination import PageParams

_COLUMNS = "id, code, name, is_active, created_at, created_by"
SORTABLE = {"code": "code", "name": "name", "created_at": "created_at"}
FILTERABLE = {"code": "code", "is_active": "is_active::text"}


def list_departments(session: Session, params: PageParams) -> tuple[list[dict[str, object]], int]:
    filters = params.checked_filters(FILTERABLE)
    where = " and ".join(f"{col} = :f{i}" for i, col in enumerate(filters)) or "true"
    binds: dict[str, object] = {f"f{i}": v for i, v in enumerate(filters.values())}
    order = params.order_by_sql(SORTABLE, default="code asc")
    total = session.execute(
        text(f"select count(*) from public.departments where {where}"),  # noqa: S608 - allow-listed
        binds,
    ).scalar_one()
    rows = session.execute(
        text(
            f"select {_COLUMNS} from public.departments where {where} "  # noqa: S608 - allow-listed
            f"order by {order} limit :limit offset :offset"
        ),
        {**binds, "limit": params.page_size, "offset": params.offset},
    ).mappings()
    return [dict(r) for r in rows], int(total)


def code_exists(session: Session, code: str) -> bool:
    return bool(
        session.execute(
            text("select exists (select 1 from public.departments where code = :code)"),
            {"code": code},
        ).scalar_one()
    )


def insert_department(session: Session, code: str, name: str) -> dict[str, object]:
    # created_by defaults to rms_private.current_actor(), i.e. the UoW's app.user_id.
    row = (
        session.execute(
            text(
                f"insert into public.departments (code, name) values (:code, :name) "  # noqa: S608
                f"returning {_COLUMNS}"
            ),
            {"code": code, "name": name},
        )
        .mappings()
        .one()
    )
    return dict(row)


def get_department(session: Session, department_id: UUID) -> dict[str, object] | None:
    row = (
        session.execute(
            text(f"select {_COLUMNS} from public.departments where id = :id"),  # noqa: S608
            {"id": department_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
