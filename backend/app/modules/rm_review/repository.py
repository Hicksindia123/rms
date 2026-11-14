"""RM Review database repository (AMD-12, AMD-13, G-19)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_rm_review_header(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select g.id, g.gs_no, g.status, g.party_id, p.name as party_name,
                       st.name as station_name,
                       g.gate_document_code as doc_type, g.gate_doc_no as doc_no,
                       g.gate_doc_date as doc_date,
                       coalesce(t.name, g.courier_name) as transporter_name,
                       g.docket_no, g.carton_count, g.counted_by,
                       cb.full_name as counted_by_name,
                       g.category_code, g.transfer_slip_id, g.created_at
                  from public.goods_slips g
                  left join public.parties p on p.id = g.party_id
                  left join public.stations st on st.id = g.station_id
                  left join public.transporters t on t.id = g.transporter_id
                  left join public.profiles cb on cb.id = g.counted_by
                 where g.id = :id
                """
            ),
            {"id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_rm_review_documents(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select coalesce(d.id, a.id) as id,
                   coalesce(d.doc_type_label, d.doc_type_code, a.kind, 'DOCUMENT') as document_type,
                   d.doc_no as document_number,
                   d.doc_date as document_date,
                   a.object_path as file_url,
                   a.object_path as file_name
              from public.attachments a
              left join public.gs_gate_documents d on d.id = a.gate_document_id
             where a.gs_id = :gs_id
               and a.kind in ('DOC_PHOTO', 'GATE_DOC', 'INVOICE')
            union
            select d.id,
                   coalesce(d.doc_type_label, d.doc_type_code) as document_type,
                   d.doc_no as document_number,
                   d.doc_date as document_date,
                   null as file_url,
                   null as file_name
              from public.gs_gate_documents d
             where d.gs_id = :gs_id
               and not exists (select 1 from public.attachments a where a.gate_document_id = d.id)
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_carton_videos(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select a.id, a.box_no as carton_no, a.object_path as file_url,
                   a.object_path as file_name, a.created_at
              from public.attachments a
             where a.gs_id = :gs_id
               and a.kind in ('UNBOXING_VIDEO', 'CARTON_VIDEO', 'DAMAGE_VIDEO')
             order by a.box_no nulls last, a.created_at
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_revisions(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select r.id, r.revision_no, r.action, r.items_snapshot, r.remarks,
                   r.created_by, p.full_name as created_by_name, r.created_at
              from public.rm_review_revisions r
              left join public.profiles p on p.id = r.created_by
             where r.gs_id = :gs_id
             order by r.revision_no asc
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def insert_revision(
    session: Session,
    *,
    gs_id: UUID,
    revision_no: int,
    action: str,
    items_snapshot: list[dict[str, Any]],
    remarks: str | None,
    created_by: UUID,
) -> UUID:
    res = session.execute(
        text(
            """
            insert into public.rm_review_revisions (
                gs_id, revision_no, action, items_snapshot, remarks, created_by
            ) values (
                :gs_id, :revision_no, :action, cast(:snapshot as jsonb), :remarks, :created_by
            )
            returning id
            """
        ),
        {
            "gs_id": gs_id,
            "revision_no": revision_no,
            "action": action,
            "snapshot": json.dumps(items_snapshot),
            "remarks": remarks,
            "created_by": created_by,
        },
    ).scalar_one()
    return UUID(str(res))


def get_next_revision_no(session: Session, gs_id: UUID) -> int:
    val = session.execute(
        text(
            "select coalesce(max(revision_no), 0) + 1 "
            "from public.rm_review_revisions where gs_id = :gs_id"
        ),
        {"gs_id": gs_id},
    ).scalar_one()
    return int(val)


def get_transfer_slip_summary(session: Session, transfer_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select t.id, t.transfer_no, t.status, fl.code as from_location_code,
                       tl.code as to_location_code,
                       count(tl_lines.id) as total_lines,
                       coalesce(sum(tl_lines.qty_sent), 0) as total_qty
                  from public.custody_transfers t
                  join public.inventory_locations fl on fl.id = t.from_location_id
                  join public.inventory_locations tl on tl.id = t.to_location_id
                  left join public.custody_transfer_lines tl_lines on tl_lines.transfer_id = t.id
                 where t.id = :id
                 group by t.id, t.transfer_no, t.status, fl.code, tl.code
                """
            ),
            {"id": transfer_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def set_gs_transfer_slip_id(session: Session, gs_id: UUID, transfer_id: UUID) -> None:
    session.execute(
        text("update public.goods_slips set transfer_slip_id = :t_id where id = :gs_id"),
        {"t_id": transfer_id, "gs_id": gs_id},
    )
