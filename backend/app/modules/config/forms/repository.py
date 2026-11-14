"""Repository for dynamic forms and versions (master plan §8.3, §10, prompt P1-07)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_DEF_COLUMNS = "id, code, step_code, name, is_active, created_at, updated_at"
_VER_COLUMNS = (
    "id, form_definition_id, version_no, status, snapshot, "
    "published_by, published_at, created_at, updated_at"
)
_FIELD_COLUMNS = (
    "f.id, f.form_version_id, f.field_key, f.label, f.control_type, f.option_set_id, "
    "f.master_ref_type, f.is_required, f.visible_when, f.required_when, f.validation, "
    "f.default_value, f.sort_order, f.section, f.help_text, f.is_core, f.is_system_locked, "
    "f.created_at, f.updated_at"
)
_FIELD_RETURNING = (
    "id, form_version_id, field_key, label, control_type, option_set_id, "
    "master_ref_type, is_required, visible_when, required_when, validation, "
    "default_value, sort_order, section, help_text, is_core, is_system_locked, "
    "created_at, updated_at"
)


def list_form_definitions(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select d.{_DEF_COLUMNS},
                   (select v.version_no from public.form_versions v
                     where v.form_definition_id = d.id and v.status = 'PUBLISHED'
                     limit 1) as latest_published_version,
                   exists(select 1 from public.form_versions v
                           where v.form_definition_id = d.id and v.status = 'DRAFT'
                   ) as has_draft,
                   (select v.version_no from public.form_versions v
                     where v.form_definition_id = d.id and v.status = 'DRAFT'
                     limit 1) as draft_version_no
            from public.form_definitions d
            order by d.code asc
            """  # noqa: S608
        )
    ).mappings()
    return [dict(r) for r in rows]


def get_form_definition(session: Session, code_or_id: str | UUID) -> dict[str, Any] | None:
    is_uuid = False
    if isinstance(code_or_id, UUID):
        is_uuid = True
    else:
        try:
            UUID(str(code_or_id))
            is_uuid = True
        except ValueError:
            is_uuid = False

    cond = "id = :val" if is_uuid else "code = :val"
    row = (
        session.execute(
            text(
                f"""
                select d.{_DEF_COLUMNS},
                       (select v.version_no from public.form_versions v
                         where v.form_definition_id = d.id and v.status = 'PUBLISHED'
                         limit 1) as latest_published_version,
                       exists(select 1 from public.form_versions v
                               where v.form_definition_id = d.id and v.status = 'DRAFT'
                       ) as has_draft,
                       (select v.version_no from public.form_versions v
                         where v.form_definition_id = d.id and v.status = 'DRAFT'
                         limit 1) as draft_version_no
                from public.form_definitions d
                where {cond}
                """  # noqa: S608
            ),
            {"val": str(code_or_id)},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_versions_for_form(session: Session, form_definition_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select v.{_VER_COLUMNS},
                   (select count(*)::integer from public.form_fields f
                     where f.form_version_id = v.id) as field_count
            from public.form_versions v
            where v.form_definition_id = :def_id
            order by v.version_no desc
            """  # noqa: S608
        ),
        {"def_id": form_definition_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_form_version(
    session: Session, form_definition_id: UUID, version_no: int
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
                select v.{_VER_COLUMNS},
                       (select count(*)::integer from public.form_fields f
                         where f.form_version_id = v.id) as field_count
                from public.form_versions v
                where v.form_definition_id = :def_id and v.version_no = :vno
                """  # noqa: S608
            ),
            {"def_id": form_definition_id, "vno": version_no},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_published_version(session: Session, form_definition_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
                select v.{_VER_COLUMNS},
                       (select count(*)::integer from public.form_fields f
                         where f.form_version_id = v.id) as field_count
                from public.form_versions v
                where v.form_definition_id = :def_id and v.status = 'PUBLISHED'
                """  # noqa: S608
            ),
            {"def_id": form_definition_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_draft_version(session: Session, form_definition_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
                select v.{_VER_COLUMNS},
                       (select count(*)::integer from public.form_fields f
                         where f.form_version_id = v.id) as field_count
                from public.form_versions v
                where v.form_definition_id = :def_id and v.status = 'DRAFT'
                """  # noqa: S608
            ),
            {"def_id": form_definition_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_latest_version_no(session: Session, form_definition_id: UUID) -> int:
    val = session.execute(
        text(
            "select coalesce(max(version_no), 0) from public.form_versions "
            "where form_definition_id = :def_id"
        ),
        {"def_id": form_definition_id},
    ).scalar_one()
    return int(val)


def create_form_version(
    session: Session,
    form_definition_id: UUID,
    version_no: int,
    status: str = "DRAFT",
    snapshot: dict[str, Any] | None = None,
    published_by: UUID | None = None,
    published_at: str | None = None,
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                f"""
                insert into public.form_versions (
                    form_definition_id, version_no, status, snapshot, published_by, published_at
                ) values (
                    :form_definition_id, :version_no, :status,
                    cast(:snapshot as jsonb), :published_by,
                    cast(:published_at as timestamptz)
                )
                returning {_VER_COLUMNS}
                """  # noqa: S608
            ),
            {
                "form_definition_id": form_definition_id,
                "version_no": version_no,
                "status": status,
                "snapshot": json.dumps(snapshot) if snapshot is not None else None,
                "published_by": published_by,
                "published_at": published_at,
            },
        )
        .mappings()
        .one()
    )
    res = dict(row)
    res["field_count"] = 0
    return res


def list_form_fields(session: Session, form_version_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_FIELD_COLUMNS},
                   os.code as option_set_code
            from public.form_fields f
            left join public.option_sets os on os.id = f.option_set_id
            where f.form_version_id = :ver_id
            order by f.sort_order asc, f.field_key asc
            """  # noqa: S608
        ),
        {"ver_id": form_version_id},
    ).mappings()
    return [dict(r) for r in rows]


def insert_form_field(
    session: Session, form_version_id: UUID, data: dict[str, Any]
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                f"""
                insert into public.form_fields (
                    form_version_id, field_key, label, control_type, option_set_id,
                    master_ref_type, is_required, visible_when, required_when, validation,
                    default_value, sort_order, section, help_text, is_core, is_system_locked
                ) values (
                    :form_version_id, :field_key, :label, :control_type, :option_set_id,
                    :master_ref_type, :is_required, cast(:visible_when as jsonb),
                    cast(:required_when as jsonb), cast(:validation as jsonb),
                    cast(:default_value as jsonb), :sort_order, :section, :help_text,
                    :is_core, :is_system_locked
                )
                returning {_FIELD_RETURNING}
                """  # noqa: S608
            ),
            {
                "form_version_id": form_version_id,
                "field_key": data["field_key"],
                "label": data["label"],
                "control_type": data["control_type"],
                "option_set_id": data.get("option_set_id"),
                "master_ref_type": data.get("master_ref_type"),
                "is_required": data.get("is_required", False),
                "visible_when": (
                    json.dumps(data["visible_when"])
                    if data.get("visible_when") is not None
                    else None
                ),
                "required_when": (
                    json.dumps(data["required_when"])
                    if data.get("required_when") is not None
                    else None
                ),
                "validation": (
                    json.dumps(data["validation"]) if data.get("validation") is not None else None
                ),
                "default_value": (
                    json.dumps(data["default_value"])
                    if data.get("default_value") is not None
                    else None
                ),
                "sort_order": data.get("sort_order", 0),
                "section": data.get("section"),
                "help_text": data.get("help_text"),
                "is_core": data.get("is_core", False),
                "is_system_locked": data.get("is_system_locked", False),
            },
        )
        .mappings()
        .one()
    )
    return dict(row)


def delete_form_fields(session: Session, form_version_id: UUID) -> None:
    session.execute(
        text("delete from public.form_fields where form_version_id = :ver_id"),
        {"ver_id": form_version_id},
    )


def retire_published_version(session: Session, form_definition_id: UUID) -> None:
    session.execute(
        text(
            """
            update public.form_versions
            set status = 'RETIRED', updated_at = now()
            where form_definition_id = :def_id and status = 'PUBLISHED'
            """
        ),
        {"def_id": form_definition_id},
    )


def publish_version(
    session: Session, draft_version_id: UUID, snapshot: dict[str, Any], published_by: UUID
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                f"""
                update public.form_versions
                set status = 'PUBLISHED',
                    snapshot = cast(:snapshot as jsonb),
                    published_by = :published_by,
                    published_at = now(),
                    updated_at = now()
                where id = :id
                returning {_VER_COLUMNS}
                """  # noqa: S608
            ),
            {
                "id": draft_version_id,
                "snapshot": json.dumps(snapshot, default=str),
                "published_by": published_by,
            },
        )
        .mappings()
        .one()
    )
    return dict(row)
