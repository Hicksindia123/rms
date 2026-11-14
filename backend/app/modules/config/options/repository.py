"""Repository for option sets and option items (master plan §3.2, §8.3, §10)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_SET_COLUMNS = (
    "id, code, name, description, control_type, source_kind, "
    "master_ref_type, source_ref, is_system, is_active, created_at, updated_at"
)
_ITEM_COLUMNS = (
    "id, option_set_id, code, label, allowed_status, rule_text, next_action_text, "
    "remarks, system_behavior, required_fields, sort_order, is_active, source_ref, "
    "created_at, updated_at"
)


def list_option_sets(session: Session, include_inactive: bool = True) -> list[dict[str, Any]]:
    where = "true" if include_inactive else "is_active = true"
    rows = session.execute(
        text(
            f"select {_SET_COLUMNS} from public.option_sets where {where} order by code asc"  # noqa: S608
        )
    ).mappings()
    return [dict(r) for r in rows]


def get_option_set(session: Session, set_id_or_code: str | UUID) -> dict[str, Any] | None:
    is_uuid = False
    if isinstance(set_id_or_code, UUID):
        is_uuid = True
    else:
        try:
            UUID(str(set_id_or_code))
            is_uuid = True
        except ValueError:
            is_uuid = False

    cond = "id = :val" if is_uuid else "code = :val"
    row = (
        session.execute(
            text(f"select {_SET_COLUMNS} from public.option_sets where {cond}"),  # noqa: S608
            {"val": str(set_id_or_code)},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_option_items_for_set(session: Session, option_set_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_ITEM_COLUMNS} from public.option_items "  # noqa: S608
            "where option_set_id = :set_id order by sort_order asc, code asc"
        ),
        {"set_id": option_set_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_option_item(session: Session, item_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(f"select {_ITEM_COLUMNS} from public.option_items where id = :id"),  # noqa: S608
            {"id": item_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def insert_option_item(
    session: Session,
    option_set_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                f"""
                insert into public.option_items (
                    option_set_id, code, label, allowed_status, rule_text,
                    next_action_text, remarks, system_behavior, required_fields,
                    sort_order, is_active, source_ref
                ) values (
                    :option_set_id, :code, :label, :allowed_status, :rule_text,
                    :next_action_text, :remarks, :system_behavior, cast(:required_fields as jsonb),
                    :sort_order, :is_active, :source_ref
                )
                returning {_ITEM_COLUMNS}
                """  # noqa: S608
            ),
            {
                "option_set_id": option_set_id,
                "code": data["code"],
                "label": data["label"],
                "allowed_status": data.get("allowed_status", "YES"),
                "rule_text": data.get("rule_text"),
                "next_action_text": data.get("next_action_text"),
                "remarks": data.get("remarks"),
                "system_behavior": data.get("system_behavior"),
                "required_fields": json.dumps(data.get("required_fields", [])),
                "sort_order": data.get("sort_order", 0),
                "is_active": data.get("is_active", True),
                "source_ref": data.get("source_ref"),
            },
        )
        .mappings()
        .one()
    )
    return dict(row)


def update_option_item(
    session: Session,
    item_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    set_clauses: list[str] = ["updated_at = now()"]
    binds: dict[str, Any] = {"id": item_id}

    for k, v in data.items():
        if k == "required_fields":
            set_clauses.append("required_fields = cast(:required_fields as jsonb)")
            binds["required_fields"] = json.dumps(v)
        else:
            set_clauses.append(f"{k} = :{k}")
            binds[k] = v

    clauses_str = ", ".join(set_clauses)
    row = (
        session.execute(
            text(
                f"update public.option_items set {clauses_str} "  # noqa: S608
                f"where id = :id returning {_ITEM_COLUMNS}"
            ),
            binds,
        )
        .mappings()
        .one()
    )
    return dict(row)


def count_option_usage(session: Session, code: str) -> int:
    return int(
        session.execute(
            text("select rms_private.count_option_usage(:code)"),
            {"code": code},
        ).scalar_one()
    )


def log_config_change(
    session: Session,
    entity_type: str,
    entity_id: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None,
    request_id: str | None = None,
) -> None:
    session.execute(
        text(
            """
            insert into public.config_change_log (
                entity_type, entity_id, action, before, after, reason, request_id
            ) values (
                :entity_type, :entity_id, :action, cast(:before as jsonb),
                cast(:after as jsonb), :reason, :request_id
            )
            """
        ),
        {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "action": action,
            "before": json.dumps(before, default=str) if before is not None else None,
            "after": json.dumps(after, default=str) if after is not None else None,
            "reason": reason,
            "request_id": request_id,
        },
    )
