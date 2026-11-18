"""Party notification repository: SQL only (P3-07, BR-38, DEC-25; Phase 9 AMD-20 party email)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session


def party_contact(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select p.name as party_name, p.code as party_code, p.contact_name, p.phone,
                       p.email::text as email
                  from public.goods_slips g
                  left join public.parties p on p.id = g.party_id
                 where g.id = :gs
                """
            ),
            {"gs": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def issued_credit_notes(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select cn.id, cn.status, cn.cn_type_code, oi.label as cn_type_label, cn.cn_no,
                   cn.cn_date, cn.jv_no, cn.jv_date, cn.total_value, cn.issued_at
              from public.credit_notes cn
              left join public.option_sets os on os.code = 'CN_TYPE'
              left join public.option_items oi on oi.option_set_id = os.id
                                              and oi.code = cn.cn_type_code
             where cn.gs_id = :gs and cn.status = 'ISSUED'
             order by cn.issued_at, cn.id
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_credit_note(session: Session, cn_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, gs_id, status from public.credit_notes where id = :id"),
            {"id": cn_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def credit_note_items(session: Session, cn_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select cl.line_no, coalesce(gi.product_code_snapshot, pr.code) as product_code,
                   coalesce(gi.product_name_snapshot, pr.name) as product_name, cl.qty,
                   cl.rate, cl.total_amount
              from public.credit_note_lines cl
              join public.gs_items gi on gi.id = cl.gs_item_id
              join public.products pr on pr.id = gi.product_id
             where cl.credit_note_id = :cn
             order by cl.line_no
            """
        ),
        {"cn": cn_id},
    ).mappings()
    return [dict(r) for r in rows]


def dispatches(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select rd.dispatch_no, rd.dispatch_type, rd.transporter, rd.docket_no, rd.vehicle_no,
                   rd.dispatched_at,
                   coalesce((select sum(l.qty) from public.replacement_dispatch_lines l
                              where l.dispatch_id = rd.id), 0)::int as qty
              from public.replacement_dispatches rd
             where rd.gs_id = :gs and rd.status = 'DISPATCHED'
             order by rd.dispatched_at
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_attachment(session: Session, attachment_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, gs_id, kind, status from public.attachments where id = :id"),
            {"id": attachment_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def option_label(session: Session, set_code: str, item_code: str) -> str | None:
    row = session.execute(
        text(
            """
            select oi.label from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = :s and oi.code = :c
            """
        ),
        {"s": set_code, "c": item_code},
    ).first()
    return str(row[0]) if row else None


def published_form_version_id(session: Session, form_code: str) -> UUID | None:
    row = session.execute(
        text(
            """
            select fv.id from public.form_versions fv
              join public.form_definitions fd on fd.id = fv.form_definition_id
             where fd.code = :code and fv.status = 'PUBLISHED'
            """
        ),
        {"code": form_code},
    ).first()
    return UUID(str(row[0])) if row else None


def get_setting(session: Session, key: str) -> Any:
    row = session.execute(
        text("select value from public.system_settings where key = :k"), {"k": key}
    ).first()
    return row[0] if row else None


def insert_notification(
    session: Session,
    *,
    gs_id: UUID,
    credit_note_id: UUID | None,
    status_label: str | None,
    channel_code: str,
    recipient: str,
    message: str,
    snapshot: dict[str, Any],
    proof_attachment_id: UUID | None,
    form_version_id: UUID | None,
    by: UUID,
    delivery_mode: str = "RECORDED_MANUALLY",
    party_email_id: UUID | None = None,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.party_notifications (
                      gs_id, credit_note_id, status_code, status_label, channel_code, recipient,
                      message, message_snapshot, proof_attachment_id, form_version_id, sent_by,
                      sent_at, delivery_mode, party_email_id
                    ) values (
                      :gs, :cn, 'PRIOR_INFO_SENT', :label, :channel, :recipient,
                      :message, :snapshot, :proof, :fv, :by, clock_timestamp(), :mode, :mail
                    ) returning id
                    """
                ).bindparams(bindparam("snapshot", type_=JSONB)),
                {
                    "gs": gs_id,
                    "cn": credit_note_id,
                    "label": status_label,
                    "channel": channel_code,
                    "recipient": recipient,
                    "message": message,
                    "snapshot": snapshot,
                    "proof": proof_attachment_id,
                    "fv": form_version_id,
                    "by": by,
                    "mode": delivery_mode,
                    "mail": party_email_id,
                },
            ).scalar_one()
        )
    )


def list_notifications(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select pn.id, pn.gs_id, pn.credit_note_id, coalesce(cn.cn_no, cn.jv_no) as voucher_no,
                   pn.status_code, pn.status_label, pn.channel_code, pn.recipient, pn.message,
                   pn.message_snapshot, pn.delivery_mode, pn.proof_attachment_id, pn.sent_at,
                   pn.party_email_id,
                   p.full_name as sent_by_name
              from public.party_notifications pn
              left join public.credit_notes cn on cn.id = pn.credit_note_id
              left join public.profiles p on p.id = pn.sent_by
             where pn.gs_id = :gs
             order by pn.sent_at, pn.id
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


# --- Phase 9 / AMD-20: party email from the Accounts values ------------------------------------


def _row(session: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


def _rows(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(sql), params).mappings()]


def has_ac_slip(session: Session, gs_id: UUID) -> bool:
    """AMD-17/18: the GS is on the A/c Actions flow once the RM finalised a slip."""
    return bool(
        session.execute(
            text("select exists (select 1 from public.ac_action_slips where gs_id = :gs)"),
            {"gs": gs_id},
        ).scalar_one()
    )


def current_ac_slip(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select s.id, s.slip_no, s.version_no, c.completed_at,
               (c.id is not null) as completed
          from public.ac_action_slips s
          left join public.ac_entry_completions c on c.ac_action_slip_id = s.id
         where s.gs_id = :gs and s.status = 'CURRENT'
         -- DEC-57: one CURRENT slip per round; the email covers the latest round.
         order by s.round_no desc
         limit 1
        """,
        {"gs": gs_id},
    )


def ac_value_lines(session: Session, ac_slip_id: UUID) -> list[dict[str, Any]]:
    """The values Accounts entered per action line (AMD-18), in slip order."""
    return _rows(
        session,
        """
        select e.line_no, e.action_code, e.action_label, e.qty, e.requires_cn,
               e.requires_challan, e.cn_no, e.cn_date, e.cn_value, e.challan_no, e.challan_date,
               coalesce(gi.product_code_snapshot, pr.code) as product_code,
               coalesce(gi.product_name_snapshot, pr.name) as product_name
          from public.ac_entry_lines e
          join public.gs_items gi on gi.id = e.gs_item_id
          left join public.products pr on pr.id = gi.product_id
          left join public.item_field_library lib
                 on lib.field_group = 'ACTION' and lib.code = e.action_code
         where e.ac_action_slip_id = :slip
         order by e.line_no, coalesce(lib.sort_order, 0), e.action_code
        """,
        {"slip": ac_slip_id},
    )


def dispatch_slip(session: Session, ac_slip_id: UUID) -> dict[str, Any] | None:
    """AMD-19 Dispatch Slip of the A/c Actions slip with its DEC-26 tracking data."""
    return _row(
        session,
        """
        select d.slip_no, d.status, d.dispatch_date, d.transporter, d.docket_no, d.vehicle_no,
               coalesce((select sum(l.qty) from public.dispatch_slip_lines l
                          where l.dispatch_slip_id = d.id), 0)::int as total_qty
          from public.dispatch_slips d
         where d.ac_action_slip_id = :slip
        """,
        {"slip": ac_slip_id},
    )


_EMAIL_SELECT = """
    select m.id, m.gs_id, m.ac_action_slip_id, m.trigger_code, m.resend_of_id, m.email_to, m.cc,
           m.subject, m.body, m.snapshot, m.template_snapshot, m.status, m.skip_reason,
           m.attempts, m.next_attempt_at, m.last_error, m.sent_at, m.requested_at,
           m.requested_by, p.full_name as requested_by_name, pn.id as party_notification_id
      from public.party_emails m
      left join public.profiles p on p.id = m.requested_by
      left join public.party_notifications pn on pn.party_email_id = m.id
"""


def insert_party_email(
    session: Session,
    *,
    gs_id: UUID,
    ac_slip_id: UUID,
    trigger_code: str,
    resend_of_id: UUID | None,
    email_to: str | None,
    cc: list[str],
    subject: str,
    body: str,
    snapshot: dict[str, Any],
    template_snapshot: dict[str, Any],
    status: str,
    skip_reason: str | None,
    by: UUID,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.party_emails (
                      gs_id, ac_action_slip_id, trigger_code, resend_of_id, email_to, cc,
                      subject, body, snapshot, template_snapshot, status, skip_reason,
                      requested_by
                    ) values (
                      :gs, :slip, :trigger, :resend_of, :to, cast(:cc as text[]),
                      :subject, :body, :snapshot, :tpl, :status, :skip, :by
                    ) returning id
                    """
                ).bindparams(bindparam("snapshot", type_=JSONB), bindparam("tpl", type_=JSONB)),
                {
                    "gs": gs_id,
                    "slip": ac_slip_id,
                    "trigger": trigger_code,
                    "resend_of": resend_of_id,
                    "to": email_to,
                    "cc": cc,
                    "subject": subject,
                    "body": body,
                    "snapshot": snapshot,
                    "tpl": template_snapshot,
                    "status": status,
                    "skip": skip_reason,
                    "by": by,
                },
            ).scalar_one()
        )
    )


def get_party_email(session: Session, email_id: UUID) -> dict[str, Any] | None:
    return _row(session, _EMAIL_SELECT + " where m.id = :id", {"id": email_id})


def list_party_emails(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        _EMAIL_SELECT + " where m.gs_id = :gs order by m.requested_at desc, m.id",
        {"gs": gs_id},
    )


def lock_queued_email(session: Session, email_id: UUID) -> dict[str, Any] | None:
    """The QUEUED email, locked; None when it is already final or another worker holds it."""
    return _row(
        session,
        """
        select id, gs_id, email_to, cc, subject, body, snapshot, attempts, requested_by
          from public.party_emails
         where id = :id and status = 'QUEUED'
         for update skip locked
        """,
        {"id": email_id},
    )


def due_email_ids(session: Session, *, now: datetime, limit: int) -> list[UUID]:
    rows = session.execute(
        text(
            """
            select id from public.party_emails
             where status = 'QUEUED' and next_attempt_at <= :now
             order by next_attempt_at, requested_at
             limit :limit
            """
        ),
        {"now": now, "limit": limit},
    ).all()
    return [UUID(str(r[0])) for r in rows]


def mark_email_sent(session: Session, email_id: UUID) -> None:
    session.execute(
        text(
            """
            update public.party_emails
               set status = 'SENT', attempts = attempts + 1, sent_at = clock_timestamp(),
                   last_error = null
             where id = :id
            """
        ),
        {"id": email_id},
    )


def mark_email_skipped(session: Session, email_id: UUID, reason: str) -> None:
    session.execute(
        text("update public.party_emails set status = 'SKIPPED', skip_reason = :r where id = :id"),
        {"id": email_id, "r": reason},
    )


def mark_email_attempt_failed(
    session: Session, email_id: UUID, *, error: str, final: bool, backoff_seconds: int
) -> None:
    session.execute(
        text(
            """
            update public.party_emails
               set attempts = attempts + 1,
                   last_error = left(:err, 2000),
                   status = case when :final then 'FAILED' else 'QUEUED' end,
                   next_attempt_at = now() + make_interval(secs => :backoff)
             where id = :id
            """
        ),
        {"id": email_id, "err": error, "final": final, "backoff": backoff_seconds},
    )
