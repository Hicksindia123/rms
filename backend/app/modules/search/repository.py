"""Repository for Global Search (P4-04).

Queries indexed tables using trigram and pattern matching for instant results (<300ms).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def search_goods_slips(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select g.id, g.gs_no, g.status, p.name as party_name,
               g.docket_no, g.vehicle_no, g.gate_doc_no, g.gate_entry_no, g.created_at
        from public.goods_slips g
        left join public.parties p on p.id = g.party_id
        where g.gs_no ilike :p
           or g.docket_no ilike :p
           or g.vehicle_no ilike :p
           or g.gate_doc_no ilike :p
           or g.transporter_name ilike :p
           or g.gate_entry_no::text ilike :p  -- AMD-02
           or exists (select 1 from public.gs_gate_documents d  -- AMD-04
                       where d.gs_id = g.id and d.doc_no ilike :p)
        order by g.created_at desc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_parties(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select p.id, p.code, p.name, p.gstin, p.contact_name, p.phone,
               st.name as station_name
        from public.parties p
        left join public.stations st on st.id = p.station_id
        where p.name ilike :p
           or p.gstin ilike :p
           or p.phone ilike :p
           or p.contact_name ilike :p
        order by p.name asc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_documents(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select d.id, d.gs_id, d.doc_no, d.classification_code, d.amount,
               g.gs_no
        from public.gs_documents d
        join public.goods_slips g on g.id = d.gs_id
        where d.doc_no ilike :p
           or d.buyer_gstin ilike :p
           or d.seller_gstin ilike :p
        order by d.created_at desc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_credit_notes(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select c.id, c.gs_id, c.cn_no, c.jv_no, c.party_doc_no, c.cn_type_code,
               c.status, c.total_value, g.gs_no
        from public.credit_notes c
        join public.goods_slips g on g.id = c.gs_id
        where c.cn_no ilike :p
           or c.jv_no ilike :p
           or c.party_doc_no ilike :p
        order by c.created_at desc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_transfers(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select t.id, t.transfer_no, t.status, t.gs_id,
               fl.name as from_location_name, tl.name as to_location_name
        from public.custody_transfers t
        left join public.inventory_locations fl on fl.id = t.from_location_id
        left join public.inventory_locations tl on tl.id = t.to_location_id
        where t.transfer_no ilike :p
        order by t.created_at desc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_store_issues(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select s.id, s.issue_no, s.status, s.issue_type_code, s.created_at
        from public.store_issues s
        where s.issue_no ilike :p
        order by s.created_at desc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_dispatches(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select d.id, d.dispatch_no, d.gs_id, d.dispatch_type, d.docket_no,
               d.vehicle_no, d.status, g.gs_no
        from public.replacement_dispatches d
        left join public.goods_slips g on g.id = d.gs_id
        where d.dispatch_no ilike :p
           or d.docket_no ilike :p
           or d.vehicle_no ilike :p
           or d.ref_doc_no ilike :p
        order by d.created_at desc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_batches(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select id, batch_no, status, 'TECHNICIAN' as batch_kind, created_at
        from public.technician_batches
        where batch_no ilike :p
        union all
        select id, batch_no, status, 'DISMANTLE' as batch_kind, created_at
        from public.dismantle_batches
        where batch_no ilike :p
        order by created_at desc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def search_containers(session: Session, pattern: str, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        select c.id, c.code, c.barcode, c.name, c.container_type
        from public.storage_containers c
        where c.barcode ilike :p
           or c.code ilike :p
           or c.name ilike :p
        order by c.code asc
        limit :l
    """
    rows = session.execute(text(sql), {"p": pattern, "l": limit}).mappings().all()
    return [dict(r) for r in rows]


def exact_match_goods_slip(session: Session, term: str) -> dict[str, Any] | None:
    """Find a goods slip by exact ID, exact gs_no, or QR prefix."""
    sql = """
        select id, gs_no, status
        from public.goods_slips
        where gs_no = :term
           or id::text = :term
        limit 1
    """
    row = session.execute(text(sql), {"term": term.strip()}).mappings().one_or_none()
    return dict(row) if row else None


def exact_match_container_barcode(session: Session, barcode: str) -> dict[str, Any] | None:
    sql = """
        select id, code, barcode, name
        from public.storage_containers
        where barcode = :b or code = :b
        limit 1
    """
    row = session.execute(text(sql), {"b": barcode.strip()}).mappings().one_or_none()
    return dict(row) if row else None
