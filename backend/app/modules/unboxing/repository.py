"""Unboxing repository: SQL only, no business rules (prompt P2-03)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_DOC_COLUMNS = """
  d.id, d.gs_id, d.attachment_id, d.classification_code, d.doc_no, d.doc_date, d.amount,
  d.buyer_gstin, d.seller_gstin, d.items_verified, d.qty_matched, d.party_claim_text, d.remarks,
  d.form_version_id, d.labels_snapshot, d.verified_by, vb.full_name as verified_by_name,
  d.verified_at, d.accounts_acknowledged_by, ab.full_name as accounts_acknowledged_by_name,
  d.accounts_acknowledged_at, d.created_at
"""
_DOC_FROM = """
  from public.gs_documents d
  left join public.profiles vb on vb.id = d.verified_by
  left join public.profiles ab on ab.id = d.accounts_acknowledged_by
"""
_EXC_COLUMNS = """
  e.id, e.gs_id, g.gs_no, pa.name as party_name, e.parcel_attachment_id, e.remark, e.status,
  e.requested_by, rq.full_name as requested_by_name, e.requested_at, e.decided_by,
  dc.full_name as decided_by_name, e.decided_at, e.decision_remarks,
  pp.mime_type as parcel_mime_type, pp.preview_unsupported as parcel_preview_unsupported
"""
_EXC_FROM = """
  from public.missing_doc_exceptions e
  join public.goods_slips g on g.id = e.gs_id
  left join public.parties pa on pa.id = g.party_id
  left join public.profiles rq on rq.id = e.requested_by
  left join public.profiles dc on dc.id = e.decided_by
  join public.attachments pp on pp.id = e.parcel_attachment_id
"""


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def get_published_form(session: Session, form_code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select v.id, v.version_no, v.snapshot
                  from public.form_versions v
                  join public.form_definitions d on d.id = v.form_definition_id
                 where d.code = :code and v.status = 'PUBLISHED'
                """
            ),
            {"code": form_code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_form_snapshot(session: Session, version_id: UUID) -> dict[str, Any] | None:
    snapshot = session.execute(
        text("select snapshot from public.form_versions where id = :id"), {"id": version_id}
    ).scalar()
    return dict(snapshot) if snapshot else None


# --- documents --------------------------------------------------------------------------------
def list_documents(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(f"select {_DOC_COLUMNS} {_DOC_FROM} where d.gs_id = :gs_id order by d.created_at"),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_document(
    session: Session, doc_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of d" if for_update else ""
    row = (
        session.execute(
            text(f"select {_DOC_COLUMNS} {_DOC_FROM} where d.id = :id{lock}"),
            {"id": doc_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def document_for_attachment(session: Session, attachment_id: UUID) -> UUID | None:
    found = session.execute(
        text("select id from public.gs_documents where attachment_id = :a"), {"a": attachment_id}
    ).scalar()
    return UUID(str(found)) if found else None


_DOC_WRITE_COLUMNS = (
    "classification_code",
    "doc_no",
    "doc_date",
    "amount",
    "buyer_gstin",
    "seller_gstin",
    "items_verified",
    "qty_matched",
    "party_claim_text",
    "remarks",
)


def insert_document(
    session: Session,
    *,
    gs_id: UUID,
    attachment_id: UUID,
    columns: dict[str, Any],
    form_version_id: UUID,
    labels_snapshot: dict[str, Any],
    by: UUID,
) -> UUID:
    cols = ", ".join(_DOC_WRITE_COLUMNS)
    binds = ", ".join(f":{c}" for c in _DOC_WRITE_COLUMNS)
    return UUID(
        str(
            session.execute(
                text(
                    f"insert into public.gs_documents (gs_id, attachment_id, {cols}, "  # noqa: S608
                    "form_version_id, labels_snapshot, verified_by, verified_at) "
                    f"values (:gs_id, :attachment_id, {binds}, :fv, cast(:labels as jsonb), "
                    ":by, now()) returning id"
                ),
                {
                    **{c: columns.get(c) for c in _DOC_WRITE_COLUMNS},
                    "gs_id": gs_id,
                    "attachment_id": attachment_id,
                    "fv": form_version_id,
                    "labels": json.dumps(labels_snapshot, default=str),
                    "by": by,
                },
            ).scalar_one()
        )
    )


def update_document(
    session: Session,
    doc_id: UUID,
    *,
    columns: dict[str, Any],
    labels_snapshot: dict[str, Any],
    by: UUID,
) -> None:
    sets = ", ".join(f"{c} = :{c}" for c in _DOC_WRITE_COLUMNS)
    session.execute(
        text(
            f"update public.gs_documents set {sets}, "  # noqa: S608 - fixed column list
            "labels_snapshot = cast(:labels as jsonb), verified_by = :by, verified_at = now() "
            "where id = :id"
        ),
        {
            **{c: columns.get(c) for c in _DOC_WRITE_COLUMNS},
            "labels": json.dumps(labels_snapshot, default=str),
            "by": by,
            "id": doc_id,
        },
    )


# --- missing document exceptions (DEC-03; retired by DEC-63: read-only history) -------------
def list_exceptions(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(f"select {_EXC_COLUMNS} {_EXC_FROM} where e.gs_id = :gs_id order by e.requested_at"),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def option_items(session: Session, option_set_code: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select oi.code, oi.label from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = :c and oi.is_active order by oi.sort_order, oi.code
            """
        ),
        {"c": option_set_code},
    ).mappings()
    return [dict(r) for r in rows]


# --- Accounts document queue (WF r3, BR-06, DEC-05) ---------------------------------------------
_QUEUE_WHERE = """
  g.status not in ('GATE_CREATED', 'UNBOXING', 'CANCELLED')
  and exists (select 1 from public.gs_documents d
               where d.gs_id = g.id and d.accounts_acknowledged_at is null
                 and (cast(:cls as text) is null or d.classification_code = cast(:cls as text)))
"""


def accounts_queue(
    session: Session, *, classification: str | None, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    binds = {"cls": classification, "limit": limit, "offset": offset}
    total = session.execute(
        text(f"select count(*) from public.goods_slips g where {_QUEUE_WHERE}"),  # noqa: S608
        binds,
    ).scalar_one()
    rows = session.execute(
        text(
            f"""
            select g.id as gs_id, g.gs_no, g.status, g.missing_documentation,
                   pa.name as party_name, st.name as station_name,
                   (select max(h."at") from public.gs_status_history h
                     where h.gs_id = g.id and h.from_status = 'UNBOXING') as unboxed_at
              from public.goods_slips g
              left join public.parties pa on pa.id = g.party_id
              left join public.stations st on st.id = g.station_id
             where {_QUEUE_WHERE}
             order by unboxed_at desc nulls last, g.created_at desc
             limit :limit offset :offset
            """  # noqa: S608 - fixed SQL
        ),
        binds,
    ).mappings()
    return [dict(r) for r in rows], int(total)


def unacknowledged_documents(session: Session, gs_ids: list[UUID]) -> list[dict[str, Any]]:
    if not gs_ids:
        return []
    rows = session.execute(
        text(
            f"select {_DOC_COLUMNS}, a.mime_type, a.preview_unsupported "
            f"{_DOC_FROM} join public.attachments a on a.id = d.attachment_id "
            "where d.gs_id = any(:ids) and d.accounts_acknowledged_at is null "
            "order by d.created_at"
        ),
        {"ids": gs_ids},
    ).mappings()
    return [dict(r) for r in rows]


def acknowledge_documents(session: Session, gs_id: UUID, *, by: UUID) -> int:
    res = session.execute(
        text(
            """
            update public.gs_documents
               set accounts_acknowledged_by = :by, accounts_acknowledged_at = now()
             where gs_id = :g and accounts_acknowledged_at is null
            """
        ),
        {"g": gs_id, "by": by},
    )
    return int(getattr(res, "rowcount", 0))
