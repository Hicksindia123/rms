"""Attachments repository: SQL only, no business rules (prompt P2-03)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_COLUMNS = """
  a.id, a.gs_id, a.kind, a.bucket, a.object_path, a.mime_type, a.size_bytes, a.box_no, a.status,
  a.uploaded_by, up.full_name as uploaded_by_name, a.confirmed_at, a.confirmed_by,
  a.preview_unsupported, a.created_at, a.gate_document_id
"""


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def insert_attachment(
    session: Session,
    *,
    gs_id: UUID,
    kind: str,
    bucket: str,
    object_path: str,
    mime_type: str,
    size_bytes: int,
    box_no: int | None,
    uploaded_by: UUID,
    gate_document_id: UUID | None = None,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.attachments (gs_id, entity_type, entity_id, kind, bucket,
                                                    object_path, mime_type, size_bytes, box_no,
                                                    uploaded_by, gate_document_id)
                    values (:gs_id, 'goods_slip', :gs_id, :kind, :bucket, :path, :mime, :size,
                            :box_no, :by, :gate_document_id)
                    returning id
                    """
                ),
                {
                    "gs_id": gs_id,
                    "kind": kind,
                    "bucket": bucket,
                    "path": object_path,
                    "mime": mime_type,
                    "size": size_bytes,
                    "box_no": box_no,
                    "by": uploaded_by,
                    "gate_document_id": gate_document_id,
                },
            ).scalar_one()
        )
    )


def get_attachment(
    session: Session, attachment_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of a" if for_update else ""
    row = (
        session.execute(
            text(
                f"select {_COLUMNS} from public.attachments a "  # noqa: S608 - fixed columns
                f"left join public.profiles up on up.id = a.uploaded_by where a.id = :id{lock}"
            ),
            {"id": attachment_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_for_gs(session: Session, gs_id: UUID, kinds: list[str]) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_COLUMNS} from public.attachments a "  # noqa: S608 - fixed columns
            "left join public.profiles up on up.id = a.uploaded_by "
            "where a.gs_id = :gs_id and a.kind = any(:kinds) and a.status <> 'REJECTED' "
            "order by a.created_at"
        ),
        {"gs_id": gs_id, "kinds": kinds},
    ).mappings()
    return [dict(r) for r in rows]


def mark_confirmed(session: Session, attachment_id: UUID, *, by: UUID, size_bytes: int) -> None:
    session.execute(
        text(
            """
            update public.attachments
               set status = 'CONFIRMED', confirmed_at = now(), confirmed_by = :by,
                   size_bytes = :size
             where id = :id
            """
        ),
        {"id": attachment_id, "by": by, "size": size_bytes},
    )


def mark_rejected(session: Session, attachment_id: UUID) -> None:
    session.execute(
        text("update public.attachments set status = 'REJECTED' where id = :id"),
        {"id": attachment_id},
    )


def set_audit_reason(session: Session, reason: str | None) -> None:
    """G-17: the audit trigger copies app.reason into audit_log.reason for this transaction."""
    session.execute(text("select set_config('app.reason', :r, true)"), {"r": reason or ""})


def delete_attachment(session: Session, attachment_id: UUID) -> None:
    session.execute(text("delete from public.attachments where id = :id"), {"id": attachment_id})


def is_referenced_by_exception(session: Session, attachment_id: UUID) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.missing_doc_exceptions "
                "where parcel_attachment_id = :id)"
            ),
            {"id": attachment_id},
        ).scalar_one()
    )


def insert_access_audit(session: Session, *, attachment_id: UUID, details: dict[str, Any]) -> None:
    """G-17: read access (signed download URL issued) as an 'ACCESS' audit row."""
    session.execute(
        text(
            """
            insert into public.audit_log (table_name, row_id, action, "new", actor_id, request_id)
            values ('public.attachments', :row_id, 'ACCESS', cast(:new as jsonb),
                    rms_private.current_actor(), rms_private.current_request_id())
            """
        ),
        {"row_id": str(attachment_id), "new": json.dumps(details, default=str)},
    )


def evidence_counts(session: Session, gs_id: UUID) -> dict[str, Any]:
    """Confirmed Step-2 evidence for G-02 (same predicates as goods_slips_g02_guard)."""
    row = (
        session.execute(
            text(
                """
                select
                  count(*) filter (where a.kind = 'UNBOXING_VIDEO') as video_count,
                  count(*) filter (where a.kind = 'DOC_PHOTO') as doc_photo_count,
                  count(*) filter (where a.kind = 'DOC_PHOTO' and d.id is not null)
                    as classified_doc_photo_count,
                  count(*) filter (where a.kind = 'PARCEL_PHOTO') as parcel_photo_count,
                  coalesce(array_agg(distinct a.box_no)
                    filter (where a.kind = 'UNBOXING_VIDEO' and a.box_no is not null), '{}')
                    as video_boxes
                  from public.attachments a
                  left join public.gs_documents d on d.attachment_id = a.id
                 where a.gs_id = :gs_id and a.status = 'CONFIRMED'
                """
            ),
            {"gs_id": gs_id},
        )
        .mappings()
        .one()
    )
    return dict(row)


def list_stale_pending(session: Session, cutoff: datetime, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select id, bucket, object_path from public.attachments
             where status = 'PENDING_UPLOAD' and created_at < :cutoff
             order by created_at limit :limit
             for update skip locked
            """
        ),
        {"cutoff": cutoff, "limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def get_gate_document(session: Session, gs_id: UUID, document_id: UUID) -> dict[str, Any] | None:
    """AMD-04: a gate document row of this GS (files are linked to it)."""
    row = (
        session.execute(
            text(
                "select id, gs_id, doc_type_code, source_step from public.gs_gate_documents "
                "where id = :id and gs_id = :gs_id"
            ),
            {"id": document_id, "gs_id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
