from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_gs(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
            select gs.id, gs.gs_no, gs.party_id, gs.status, gs.category_code,
                   (gs.category_code = 'CSR') as is_csr, gs.created_at, gs.state_id, gs.station_id,
                   p.name as party_name, p.code as party_code, p.gstin as party_gstin,
                   s.name as party_state_name, s.code as party_state_code,
                   st.name as party_station_name
            from public.goods_slips gs
            join public.parties p on p.id = gs.party_id
            left join public.states s on s.id = p.state_id
            left join public.stations st on st.id = p.station_id
            where gs.id = :gs_id
            """
            ),
            {"gs_id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_gs_items(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select gi.id, gi.gs_id, gi.line_no, gi.product_id,
                   gi.documented_qty, gi.received_qty,
                   p.code as product_code, p.name as product_name
            from public.gs_items gi
            join public.products p on p.id = gi.product_id
            where gi.gs_id = :gs_id
            order by gi.line_no asc
            """
            ),
            {"gs_id": gs_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_current_rm_actions_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select a.id, a.gs_item_id, a.action_code, a.qty,
                   a.action_label  -- G-18 label snapshot (AMD-16)
            from public.rm_item_actions a
            join public.gs_items gi on gi.id = a.gs_item_id
            where gi.gs_id = :gs_id and a.is_current = true
            order by gi.line_no asc
            """
            ),
            {"gs_id": gs_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_current_rm_cn_decision(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
            select d.id, d.gs_id, d.decision_by, d.decision_at,
                   d.deviation_reason, d.is_current,
                   pr.full_name as decision_by_name
            from public.rm_cn_decisions d
            join public.profiles pr on pr.id = d.decision_by
            where d.gs_id = :gs_id and d.is_current = true
            """
            ),
            {"gs_id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_rm_cn_decision_lines(session: Session, decision_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select dl.id, dl.decision_id, dl.gs_item_id, dl.decision_code, dl.qty,
                   gi.line_no, p.code as product_code, p.name as product_name,
                   coalesce(oi.label, dl.decision_code) as decision_label
            from public.rm_cn_decision_lines dl
            join public.gs_items gi on gi.id = dl.gs_item_id
            join public.products p on p.id = gi.product_id
            left join public.option_items oi on oi.code = dl.decision_code
            where dl.decision_id = :decision_id
            order by gi.line_no asc
            """
            ),
            {"decision_id": decision_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def supersede_rm_cn_decisions(session: Session, gs_id: UUID) -> None:
    session.execute(
        text(
            """
            update public.rm_cn_decisions
            set is_current = false, updated_at = now()
            where gs_id = :gs_id and is_current = true
            """
        ),
        {"gs_id": gs_id},
    )


def insert_rm_cn_decision(
    session: Session,
    *,
    gs_id: UUID,
    decision_by: UUID,
    deviation_reason: str | None,
) -> UUID:
    res = session.execute(
        text(
            """
            insert into public.rm_cn_decisions (
                gs_id, decision_by, deviation_reason, is_current
            ) values (
                :gs_id, :decision_by, :deviation_reason, true
            ) returning id
            """
        ),
        {
            "gs_id": gs_id,
            "decision_by": decision_by,
            "deviation_reason": deviation_reason,
        },
    ).scalar_one()
    return UUID(str(res))


def insert_rm_cn_decision_line(
    session: Session,
    *,
    decision_id: UUID,
    gs_item_id: UUID,
    decision_code: str,
    qty: int,
) -> UUID:
    res = session.execute(
        text(
            """
            insert into public.rm_cn_decision_lines (
                decision_id, gs_item_id, decision_code, qty
            ) values (
                :decision_id, :gs_item_id, :decision_code, :qty
            ) returning id
            """
        ),
        {
            "decision_id": decision_id,
            "gs_item_id": gs_item_id,
            "decision_code": decision_code,
            "qty": qty,
        },
    ).scalar_one()
    return UUID(str(res))


def get_allowed_cn_quantities(session: Session, gs_id: UUID) -> dict[UUID, int]:
    rows = (
        session.execute(
            text(
                """
            select dl.gs_item_id, sum(dl.qty)::integer as allowed_qty
            from public.rm_cn_decisions d
            join public.rm_cn_decision_lines dl on dl.decision_id = d.id
            where d.gs_id = :gs_id
              and d.is_current = true
              and dl.decision_code = 'ALLOW_CN'
            group by dl.gs_item_id
            """
            ),
            {"gs_id": gs_id},
        )
        .mappings()
        .all()
    )
    return {r["gs_item_id"]: r["allowed_qty"] for r in rows}


def get_already_credited_quantities(
    session: Session,
    gs_id: UUID,
    exclude_cn_id: UUID | None = None,
) -> dict[UUID, int]:
    if exclude_cn_id:
        query = text(
            """
            select cl.gs_item_id, sum(cl.qty)::integer as credited_qty
            from public.credit_note_lines cl
            join public.credit_notes cn on cn.id = cl.credit_note_id
            where cn.gs_id = :gs_id
              and cn.status <> 'CANCELLED'
              and cn.id <> :exclude_cn_id
            group by cl.gs_item_id
            """
        )
        rows = (
            session.execute(query, {"gs_id": gs_id, "exclude_cn_id": exclude_cn_id})
            .mappings()
            .all()
        )
    else:
        query = text(
            """
            select cl.gs_item_id, sum(cl.qty)::integer as credited_qty
            from public.credit_note_lines cl
            join public.credit_notes cn on cn.id = cl.credit_note_id
            where cn.gs_id = :gs_id
              and cn.status <> 'CANCELLED'
            group by cl.gs_item_id
            """
        )
        rows = session.execute(query, {"gs_id": gs_id}).mappings().all()

    return {r["gs_item_id"]: r["credited_qty"] for r in rows}


def insert_credit_note(
    session: Session,
    *,
    gs_id: UUID,
    cn_type_code: str,
    created_by: UUID,
    is_inter_state: bool,
    status: str = "DRAFT",
    gst_portal_code: str | None = None,
) -> UUID:
    res = session.execute(
        text(
            """
            insert into public.credit_notes (
                gs_id, cn_type_code, status, is_inter_state, gst_portal_code, created_by
            ) values (
                :gs_id, :cn_type_code, :status, :is_inter_state, :gst_portal_code, :created_by
            ) returning id
            """
        ),
        {
            "gs_id": gs_id,
            "cn_type_code": cn_type_code,
            "status": status,
            "is_inter_state": is_inter_state,
            "gst_portal_code": gst_portal_code,
            "created_by": created_by,
        },
    ).scalar_one()
    return UUID(str(res))


def insert_credit_note_line(
    session: Session,
    *,
    credit_note_id: UUID,
    gs_item_id: UUID,
    lot_id: UUID | None,
    line_no: int,
    qty: int,
    rate: Decimal = Decimal("0.00"),
    tax_rate: Decimal = Decimal("18.00"),
) -> UUID:
    taxable_amount = Decimal(qty) * rate
    res = session.execute(
        text(
            """
            insert into public.credit_note_lines (
                credit_note_id, gs_item_id, lot_id, line_no, qty,
                rate, tax_rate, taxable_amount, total_amount
            ) values (
                :credit_note_id, :gs_item_id, :lot_id, :line_no, :qty,
                :rate, :tax_rate, :taxable_amount, :taxable_amount
            ) returning id
            """
        ),
        {
            "credit_note_id": credit_note_id,
            "gs_item_id": gs_item_id,
            "lot_id": lot_id,
            "line_no": line_no,
            "qty": qty,
            "rate": rate,
            "tax_rate": tax_rate,
            "taxable_amount": taxable_amount,
        },
    ).scalar_one()
    return UUID(str(res))


def get_credit_note(session: Session, cn_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
            select cn.id, cn.gs_id, cn.cn_type_code, cn.status,
                   cn.party_doc_code, cn.party_doc_no, cn.party_doc_date,
                   cn.party_doc_amount, cn.party_doc_notes,
                   cn.party_doc_verified_by, cn.party_doc_verified_at,
                   cn.gst_portal_code, cn.gst_return_type, cn.gst_return_period,
                   cn.gst_checked_on, cn.gst_evidence_attachment_id,
                   cn.gst_verified_by, cn.gst_verified_at,
                   cn.cn_no, cn.cn_date, cn.jv_no, cn.jv_date,
                   cn.taxable_value, cn.cgst_rate, cn.cgst_amount,
                   cn.sgst_rate, cn.sgst_amount, cn.igst_rate, cn.igst_amount,
                   cn.total_value, cn.is_inter_state,
                   cn.created_by, cn.created_at, cn.updated_at,
                   cn.issued_by, cn.issued_at, cn.cancelled_by, cn.cancelled_at,
                   cn.cancel_reason,
                   gs.gs_no, gs.party_id,
                   p.name as party_name, p.gstin as party_gstin,
                   s.name as party_state_name, s.code as party_state_code,
                   st.name as party_station_name,
                   c_by.full_name as created_by_name,
                   i_by.full_name as issued_by_name,
                   can_by.full_name as cancelled_by_name,
                   coalesce(ot.label, cn.cn_type_code) as cn_type_label,
                   opd.label as party_doc_label,
                   ogst.label as gst_portal_label
            from public.credit_notes cn
            join public.goods_slips gs on gs.id = cn.gs_id
            join public.parties p on p.id = gs.party_id
            left join public.states s on s.id = p.state_id
            left join public.stations st on st.id = p.station_id
            left join public.profiles c_by on c_by.id = cn.created_by
            left join public.profiles i_by on i_by.id = cn.issued_by
            left join public.profiles can_by on can_by.id = cn.cancelled_by
            left join public.option_items ot on ot.code = cn.cn_type_code
            left join public.option_items opd on opd.code = cn.party_doc_code
            left join public.option_items ogst on ogst.code = cn.gst_portal_code
            where cn.id = :cn_id
            """
            ),
            {"cn_id": cn_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_credit_note_lines(session: Session, cn_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select cl.id, cl.credit_note_id, cl.gs_item_id, cl.lot_id,
                   cl.line_no, cl.qty, cl.rate, cl.tax_rate,
                   cl.taxable_amount, cl.cgst_amount, cl.sgst_amount,
                   cl.igst_amount, cl.total_amount,
                   gi.line_no as gs_line_no,
                   p.code as product_code, p.name as product_name,
                   l.condition_class
            from public.credit_note_lines cl
            join public.gs_items gi on gi.id = cl.gs_item_id
            join public.products p on p.id = gi.product_id
            left join public.stock_lots l on l.id = cl.lot_id
            where cl.credit_note_id = :cn_id
            order by cl.line_no asc
            """
            ),
            {"cn_id": cn_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_rate_verifications_for_line(session: Session, line_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select rv.id, rv.credit_note_line_id, rv.reference_code,
                   rv.ref_doc_no, rv.ref_doc_date, rv.rate, rv.notes,
                   rv.verified_by, rv.verified_at,
                   pr.full_name as verified_by_name,
                   coalesce(oi.label, rv.reference_code) as reference_label
            from public.rate_verifications rv
            join public.profiles pr on pr.id = rv.verified_by
            left join public.option_items oi on oi.code = rv.reference_code
            where rv.credit_note_line_id = :line_id
            order by rv.verified_at asc
            """
            ),
            {"line_id": line_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def insert_rate_verification(
    session: Session,
    *,
    credit_note_line_id: UUID,
    reference_code: str,
    ref_doc_no: str,
    ref_doc_date: date,
    rate: Decimal,
    notes: str | None,
    verified_by: UUID,
) -> UUID:
    res = session.execute(
        text(
            """
            insert into public.rate_verifications (
                credit_note_line_id, reference_code, ref_doc_no,
                ref_doc_date, rate, notes, verified_by
            ) values (
                :credit_note_line_id, :reference_code, :ref_doc_no,
                :ref_doc_date, :rate, :notes, :verified_by
            ) returning id
            """
        ),
        {
            "credit_note_line_id": credit_note_line_id,
            "reference_code": reference_code,
            "ref_doc_no": ref_doc_no,
            "ref_doc_date": ref_doc_date,
            "rate": rate,
            "notes": notes,
            "verified_by": verified_by,
        },
    ).scalar_one()
    return UUID(str(res))


def update_party_document(
    session: Session,
    *,
    cn_id: UUID,
    party_doc_code: str,
    doc_no: str | None,
    doc_date: date | None,
    amount: Decimal | None,
    notes: str | None,
    verified_by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.credit_notes
            set party_doc_code = :party_doc_code,
                party_doc_no = :doc_no,
                party_doc_date = :doc_date,
                party_doc_amount = :amount,
                party_doc_notes = :notes,
                party_doc_verified_by = :verified_by,
                party_doc_verified_at = now(),
                updated_at = now()
            where id = :cn_id
            """
        ),
        {
            "cn_id": cn_id,
            "party_doc_code": party_doc_code,
            "doc_no": doc_no,
            "doc_date": doc_date,
            "amount": amount,
            "notes": notes,
            "verified_by": verified_by,
        },
    )


def update_gst_check(
    session: Session,
    *,
    cn_id: UUID,
    gst_portal_code: str,
    return_type: str | None,
    return_period: str | None,
    checked_on: date,
    evidence_attachment_id: UUID | None,
    verified_by: UUID,
    auto_cn_type_code: str | None = None,
) -> None:
    session.execute(
        text(
            """
            update public.credit_notes
            set gst_portal_code = :gst_portal_code,
                cn_type_code = coalesce(:auto_cn_type_code, cn_type_code),
                gst_return_type = :return_type,
                gst_return_period = :return_period,
                gst_checked_on = :checked_on,
                gst_evidence_attachment_id = :evidence_attachment_id,
                gst_verified_by = :verified_by,
                gst_verified_at = now(),
                updated_at = now()
            where id = :cn_id
            """
        ),
        {
            "cn_id": cn_id,
            "gst_portal_code": gst_portal_code,
            "auto_cn_type_code": auto_cn_type_code,
            "return_type": return_type,
            "return_period": return_period,
            "checked_on": checked_on,
            "evidence_attachment_id": evidence_attachment_id,
            "verified_by": verified_by,
        },
    )


def update_cn_type(session: Session, *, cn_id: UUID, cn_type_code: str) -> None:
    session.execute(
        text(
            """
            update public.credit_notes
            set cn_type_code = :cn_type_code,
                updated_at = now()
            where id = :cn_id
            """
        ),
        {"cn_id": cn_id, "cn_type_code": cn_type_code},
    )


def update_line_rate(
    session: Session,
    *,
    line_id: UUID,
    rate: Decimal,
    taxable_amount: Decimal,
    cgst_amount: Decimal,
    sgst_amount: Decimal,
    igst_amount: Decimal,
    total_amount: Decimal,
) -> None:
    session.execute(
        text(
            """
            update public.credit_note_lines
            set rate = :rate,
                taxable_amount = :taxable_amount,
                cgst_amount = :cgst_amount,
                sgst_amount = :sgst_amount,
                igst_amount = :igst_amount,
                total_amount = :total_amount,
                updated_at = now()
            where id = :line_id
            """
        ),
        {
            "line_id": line_id,
            "rate": rate,
            "taxable_amount": taxable_amount,
            "cgst_amount": cgst_amount,
            "sgst_amount": sgst_amount,
            "igst_amount": igst_amount,
            "total_amount": total_amount,
        },
    )


def update_cn_valuation(
    session: Session,
    *,
    cn_id: UUID,
    taxable_value: Decimal,
    cgst_rate: Decimal,
    cgst_amount: Decimal,
    sgst_rate: Decimal,
    sgst_amount: Decimal,
    igst_rate: Decimal,
    igst_amount: Decimal,
    total_value: Decimal,
    is_inter_state: bool,
) -> None:
    session.execute(
        text(
            """
            update public.credit_notes
            set taxable_value = :taxable_value,
                cgst_rate = :cgst_rate,
                cgst_amount = :cgst_amount,
                sgst_rate = :sgst_rate,
                sgst_amount = :sgst_amount,
                igst_rate = :igst_rate,
                igst_amount = :igst_amount,
                total_value = :total_value,
                is_inter_state = :is_inter_state,
                updated_at = now()
            where id = :cn_id
            """
        ),
        {
            "cn_id": cn_id,
            "taxable_value": taxable_value,
            "cgst_rate": cgst_rate,
            "cgst_amount": cgst_amount,
            "sgst_rate": sgst_rate,
            "sgst_amount": sgst_amount,
            "igst_rate": igst_rate,
            "igst_amount": igst_amount,
            "total_value": total_value,
            "is_inter_state": is_inter_state,
        },
    )


def lock_credit_note(session: Session, cn_id: UUID) -> None:
    """Row lock: concurrent issue / cancel of one CN are serialised (G-16, DEC-22)."""
    session.execute(
        text("select id from public.credit_notes where id = :id for update"), {"id": cn_id}
    )


def voucher_number_taken(
    session: Session, *, cn_id: UUID, cn_no: str | None, jv_no: str | None
) -> bool:
    """DEC-22: CN / JV numbers from the accounting system are unique across credit notes."""
    row = session.execute(
        text(
            """
            select 1 from public.credit_notes
             where id <> :cn_id
               and ((cast(:cn_no as text) is not null and cn_no = :cn_no)
                    or (cast(:jv_no as text) is not null and jv_no = :jv_no))
             limit 1
            """
        ),
        {"cn_id": cn_id, "cn_no": cn_no, "jv_no": jv_no},
    ).first()
    return row is not None


def issue_credit_note(
    session: Session,
    *,
    cn_id: UUID,
    cn_no: str | None,
    cn_date: date | None,
    jv_no: str | None,
    jv_date: date | None,
    issued_by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.credit_notes
            set cn_no = :cn_no,
                cn_date = :cn_date,
                jv_no = :jv_no,
                jv_date = :jv_date,
                status = 'ISSUED',
                issued_by = :issued_by,
                issued_at = now(),
                updated_at = now()
            where id = :cn_id
            """
        ),
        {
            "cn_id": cn_id,
            "cn_no": cn_no,
            "cn_date": cn_date,
            "jv_no": jv_no,
            "jv_date": jv_date,
            "issued_by": issued_by,
        },
    )


def cancel_credit_note(
    session: Session,
    *,
    cn_id: UUID,
    reason: str,
    cancelled_by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.credit_notes
            set status = 'CANCELLED',
                cancelled_by = :cancelled_by,
                cancelled_at = now(),
                cancel_reason = :reason,
                updated_at = now()
            where id = :cn_id
            """
        ),
        {
            "cn_id": cn_id,
            "reason": reason,
            "cancelled_by": cancelled_by,
        },
    )


def delete_credit_note_line(session: Session, line_id: UUID) -> None:
    session.execute(
        text("delete from public.credit_note_lines where id = :line_id"),
        {"line_id": line_id},
    )


def list_credit_notes(
    session: Session,
    *,
    gs_id: UUID | None = None,
    status: str | None = None,
    cn_type_code: str | None = None,
    party_search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where_clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if gs_id:
        where_clauses.append("cn.gs_id = :gs_id")
        params["gs_id"] = gs_id
    if status:
        where_clauses.append("cn.status = :status")
        params["status"] = status
    if cn_type_code:
        where_clauses.append("cn.cn_type_code = :cn_type_code")
        params["cn_type_code"] = cn_type_code
    if party_search:
        where_clauses.append(
            "(p.name ilike :party_search or p.code ilike :party_search "
            "or gs.gs_no ilike :party_search)"
        )
        params["party_search"] = f"%{party_search}%"
    if from_date:
        where_clauses.append("cn.created_at::date >= :from_date")
        params["from_date"] = from_date
    if to_date:
        where_clauses.append("cn.created_at::date <= :to_date")
        params["to_date"] = to_date

    where_sql = " and ".join(where_clauses)

    query = text(
        f"""
        select cn.id, cn.gs_id, cn.cn_type_code, cn.status,
               cn.party_doc_code, cn.gst_portal_code,
               cn.cn_no, cn.cn_date, cn.jv_no, cn.jv_date,
               cn.taxable_value, cn.total_value,
               cn.created_at, cn.issued_at,
               gs.gs_no, gs.party_id,
               p.name as party_name,
               coalesce(ot.label, cn.cn_type_code) as cn_type_label,
               opd.label as party_doc_label,
               ogst.label as gst_portal_label,
               coalesce(sum(cl.qty), 0)::integer as total_qty
        from public.credit_notes cn
        join public.goods_slips gs on gs.id = cn.gs_id
        join public.parties p on p.id = gs.party_id
        left join public.credit_note_lines cl on cl.credit_note_id = cn.id
        left join public.option_items ot on ot.code = cn.cn_type_code
        left join public.option_items opd on opd.code = cn.party_doc_code
        left join public.option_items ogst on ogst.code = cn.gst_portal_code
        where {where_sql}
        group by cn.id, gs.id, p.id, ot.label, opd.label, ogst.label
        order by cn.created_at desc
        limit :limit offset :offset
        """  # noqa: S608
    )
    rows = session.execute(query, params).mappings().all()
    return [dict(r) for r in rows]


def get_work_queue_pending_gs(session: Session) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            with allowed as (
                select d.gs_id, max(d.decision_at) as decision_date,
                       sum(dl.qty)::integer as allowed_qty
                from public.rm_cn_decisions d
                join public.rm_cn_decision_lines dl on dl.decision_id = d.id
                where d.is_current = true and dl.decision_code = 'ALLOW_CN'
                group by d.gs_id
            ),
            draft_cn as (
                select cn.gs_id, coalesce(sum(cl.qty), 0)::integer as draft_qty
                from public.credit_notes cn
                join public.credit_note_lines cl on cl.credit_note_id = cn.id
                where cn.status = 'DRAFT'
                group by cn.gs_id
            ),
            issued_cn as (
                select cn.gs_id, coalesce(sum(cl.qty), 0)::integer as issued_qty,
                       count(distinct cn.id)::integer as cn_count
                from public.credit_notes cn
                join public.credit_note_lines cl on cl.credit_note_id = cn.id
                where cn.status = 'ISSUED'
                group by cn.gs_id
            )
            select a.gs_id, a.allowed_qty, a.decision_date,
                   gs.gs_no, gs.party_id, p.name as party_name,
                   coalesce(d.draft_qty, 0) as draft_cn_qty,
                   coalesce(i.issued_qty, 0) as issued_cn_qty,
                   (a.allowed_qty - coalesce(d.draft_qty, 0) - coalesce(i.issued_qty, 0))
                       as pending_to_credit_qty,
                   coalesce(i.cn_count, 0) as active_credit_notes_count
            from allowed a
            join public.goods_slips gs on gs.id = a.gs_id
            join public.parties p on p.id = gs.party_id
            left join draft_cn d on d.gs_id = a.gs_id
            left join issued_cn i on i.gs_id = a.gs_id
            where (a.allowed_qty - coalesce(i.issued_qty, 0)) > 0
            order by a.decision_date desc
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_step2_documents_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select gd.id, gd.classification_code as document_type_code,
                   gd.doc_no, gd.doc_date, gd.amount,
                   gd.attachment_id,
                   coalesce(oi.label, gd.classification_code) as document_type_label,
                   split_part(att.object_path, '/', -1) as file_name,
                   att.object_path as storage_path
            from public.gs_documents gd
            left join public.option_items oi on oi.code = gd.classification_code
            left join public.attachments att on att.id = gd.attachment_id
            where gd.gs_id = :gs_id
            order by gd.created_at asc
            """
            ),
            {"gs_id": gs_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_system_setting(session: Session, key: str) -> Any:
    val = session.execute(
        text("select value from public.system_settings where key = :key"),
        {"key": key},
    ).scalar_one_or_none()
    return val
