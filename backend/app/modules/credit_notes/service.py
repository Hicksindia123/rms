from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork, get_session_factory
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.closure import service as closure_service
from app.modules.credit_notes import repository as repo
from app.modules.credit_notes.schemas import (
    CnTypeUpdateIn,
    CreditNoteCancelIn,
    CreditNoteCreateIn,
    CreditNoteDetailOut,
    CreditNoteIssueIn,
    CreditNoteLineOut,
    CreditNoteListItemOut,
    CreditNotePrintOut,
    CreditNoteWorkQueueItem,
    CreditNoteWorkQueueOut,
    GstCheckIn,
    LinkedStep2Document,
    PartyDocumentVerifyIn,
    PrintSignatureBlock,
    RateVerificationIn,
    RateVerificationOut,
    RateVerificationResultOut,
    RmCnDecisionIn,
    RmCnDecisionLineOut,
    RmCnDecisionOut,
    RmCnDecisionPrefillLine,
    RmCnDecisionPrefillOut,
)
from app.modules.goods_slips import service as gs_service
from app.modules.notifications import service as notif_service

log = structlog.get_logger(__name__)


class CreditNotesService:
    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self._uow = uow or UnitOfWork(get_session_factory())

    # =========================================================================
    # 1. RM CN Decision (BR-32, DEC-13, G-13)
    # =========================================================================

    def get_cn_decision_prefill(
        self,
        gs_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> RmCnDecisionPrefillOut:
        if not (perms.allows("credit_notes", "view") or perms.allows("goods_slips", "view")):
            raise PermissionDenied("You do not have permission to view CN decisions")

        with self._uow.transaction(user.id) as session:
            gs = repo.get_gs(session, gs_id)
            if not gs:
                raise NotFound(f"Goods slip {gs_id} not found")

            items = repo.get_gs_items(session, gs_id)
            planned = _planned_commercial(
                repo.get_current_rm_actions_for_gs(session, gs_id), is_csr=bool(gs["is_csr"])
            )

            prefill_lines: list[RmCnDecisionPrefillLine] = []
            for item in items:
                # DEC-13: one prefill row per planned commercial outcome of the line. A line can
                # carry several Step-3 a) actions (e.g. ISSUE_CN 5 + NOT_ALLOWED 1, or SEND_NEW 3 +
                # PENDING_BP 1); NOT_ALLOWED / PENDING_BP quantities are not commercial outcomes.
                plan = planned.get(item["id"])
                rows = (
                    plan.rows()
                    if plan is not None
                    else [("ISSUE_CN", "ISSUE_CN", int(item["received_qty"]), "ALLOW_CN")]
                )
                for planned_code, planned_label, planned_qty, default_dec in rows:
                    prefill_lines.append(
                        RmCnDecisionPrefillLine(
                            gs_item_id=item["id"],
                            line_no=item["line_no"],
                            product_code=item["product_code"],
                            product_name=item["product_name"],
                            received_qty=item["received_qty"],
                            planned_action_code=planned_code,
                            planned_action_label=planned_label,
                            planned_qty=planned_qty,
                            default_decision_code=default_dec,
                            allowed_qty=planned_qty if default_dec == "ALLOW_CN" else 0,
                        )
                    )

            curr_dec = repo.get_current_rm_cn_decision(session, gs_id)
            curr_dec_out: RmCnDecisionOut | None = None
            if curr_dec:
                dec_lines = repo.get_rm_cn_decision_lines(session, curr_dec["id"])
                curr_dec_out = RmCnDecisionOut(
                    id=curr_dec["id"],
                    gs_id=curr_dec["gs_id"],
                    gs_no=gs["gs_no"],
                    party_name=gs["party_name"],
                    decision_by=curr_dec["decision_by"],
                    decision_by_name=curr_dec["decision_by_name"],
                    decision_at=curr_dec["decision_at"],
                    deviation_reason=curr_dec["deviation_reason"],
                    is_current=curr_dec["is_current"],
                    lines=[RmCnDecisionLineOut(**ln) for ln in dec_lines],
                )

            return RmCnDecisionPrefillOut(
                gs_id=gs["id"],
                gs_no=gs["gs_no"],
                party_name=gs["party_name"],
                is_csr=bool(gs["is_csr"]),
                has_existing_decision=curr_dec is not None,
                current_decision=curr_dec_out,
                prefill_lines=prefill_lines,
            )

    def record_cn_decision(
        self,
        gs_id: UUID,
        payload: RmCnDecisionIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> RmCnDecisionOut:
        # Step-7 CN decision is made by Replacement Manager (or super admin)
        if not (perms.allows("credit_notes", "approve") or user.is_super_admin):
            raise PermissionDenied("Only Replacement Manager or Admin may record CN decision")

        with self._uow.transaction(user.id) as session:
            gs = repo.get_gs(session, gs_id)
            if not gs:
                raise NotFound(f"Goods slip {gs_id} not found")

            items = repo.get_gs_items(session, gs_id)
            item_map = {item["id"]: item for item in items}
            planned = _planned_commercial(
                repo.get_current_rm_actions_for_gs(session, gs_id), is_csr=bool(gs["is_csr"])
            )

            # DEC-13: compare the submitted ALLOW / DENY quantities per line with the planned
            # Step-3 a) commercial quantities (all action rows of the line, not just one).
            submitted: dict[UUID, dict[str, int]] = {}
            for line in payload.lines:
                if line.gs_item_id not in item_map:
                    raise ValidationFailed(
                        f"Item {line.gs_item_id} does not belong to GS {gs['gs_no']}"
                    )
                per_item = submitted.setdefault(line.gs_item_id, {})
                per_item[line.decision] = per_item.get(line.decision, 0) + line.qty

            has_deviation = False
            for item_id in set(submitted) | set(planned):
                got = submitted.get(item_id, {})
                plan = planned.get(item_id)
                expected = (
                    plan.expected()
                    if plan is not None
                    else {"ALLOW_CN": int(item_map[item_id]["received_qty"])}
                )
                if {k: v for k, v in got.items() if v} != {k: v for k, v in expected.items() if v}:
                    has_deviation = True

            if has_deviation and not (
                payload.deviation_reason and payload.deviation_reason.strip()
            ):
                raise ValidationFailed(
                    "DEC-13: RM CN decision diverges from planned RM actions. "
                    "A non-empty deviation_reason is required."
                )

            # Supersede old decisions for this GS
            repo.supersede_rm_cn_decisions(session, gs_id)

            decision_id = repo.insert_rm_cn_decision(
                session,
                gs_id=gs_id,
                decision_by=user.id,
                deviation_reason=payload.deviation_reason.strip()
                if payload.deviation_reason
                else None,
            )

            has_allow_lines = False
            for line in payload.lines:
                repo.insert_rm_cn_decision_line(
                    session,
                    decision_id=decision_id,
                    gs_item_id=line.gs_item_id,
                    decision_code=line.decision,
                    qty=line.qty,
                )
                if line.decision == "ALLOW_CN":
                    has_allow_lines = True

            # If any line has ALLOW_CN, create/sync workflow task for ACCOUNTS
            if has_allow_lines:
                role_row = (
                    session.execute(text("select id from public.roles where code = 'ACCOUNTS'"))
                    .mappings()
                    .first()
                )
                accounts_role_id = role_row["id"] if role_row else None

                gs_service.sync_step_task(
                    session,
                    gs_id=gs_id,
                    step_code="S6_ACCOUNTS_CN",
                    role_id=accounts_role_id,
                    needed=True,
                )

                notif_service.publish(
                    session,
                    "CN_DECISION_ALLOWED",
                    role_codes=["ACCOUNTS"],
                    notification_type="CN_DECISION_ALLOWED",
                    title=f"Credit Note Approved for GS {gs['gs_no']}",
                    body=(
                        f"RM has allowed Credit Note processing for {gs['party_name']}. "
                        "Please verify party documents and GST portal."
                    ),
                    entity_type="goods_slips",
                    entity_id=gs_id,
                    gs_id=gs_id,
                    data={"gs_no": gs["gs_no"]},
                    priority="HIGH",
                )

        return self.get_cn_decision_detail(decision_id, user, perms)

    def get_cn_decision_detail(
        self,
        decision_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> RmCnDecisionOut:
        with self._uow.transaction(user.id) as session:
            dec_row = (
                session.execute(
                    text(
                        """
                    select d.id, d.gs_id, d.decision_by, d.decision_at,
                           d.deviation_reason, d.is_current,
                           pr.full_name as decision_by_name,
                           gs.gs_no, p.name as party_name
                    from public.rm_cn_decisions d
                    join public.goods_slips gs on gs.id = d.gs_id
                    join public.parties p on p.id = gs.party_id
                    join public.profiles pr on pr.id = d.decision_by
                    where d.id = :id
                    """
                    ),
                    {"id": decision_id},
                )
                .mappings()
                .first()
            )
            if not dec_row:
                raise NotFound(f"Decision {decision_id} not found")

            lines = repo.get_rm_cn_decision_lines(session, decision_id)
            return RmCnDecisionOut(
                id=dec_row["id"],
                gs_id=dec_row["gs_id"],
                gs_no=dec_row["gs_no"],
                party_name=dec_row["party_name"],
                decision_by=dec_row["decision_by"],
                decision_by_name=dec_row["decision_by_name"],
                decision_at=dec_row["decision_at"],
                deviation_reason=dec_row["deviation_reason"],
                is_current=dec_row["is_current"],
                lines=[RmCnDecisionLineOut(**ln) for ln in lines],
            )

    # =========================================================================
    # 2. Credit Note Draft Creation (G-13)
    # =========================================================================

    def create_credit_note(
        self,
        payload: CreditNoteCreateIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteDetailOut:
        if not perms.allows("credit_notes", "create"):
            raise PermissionDenied("Only Accounts team or Admin can create Credit Notes")

        with self._uow.transaction(user.id) as session:
            gs = repo.get_gs(session, payload.gs_id)
            if not gs:
                raise NotFound(f"Goods slip {payload.gs_id} not found")

            # G-13: Validate RM ALLOW_CN decision exists
            allowed_qtys = repo.get_allowed_cn_quantities(session, payload.gs_id)
            if not allowed_qtys:
                raise ValidationFailed(
                    f"G-13: No active RM ALLOW_CN decision found for Goods Slip {gs['gs_no']}. "
                    "Credit Note creation blocked."
                )

            already_credited = repo.get_already_credited_quantities(session, payload.gs_id)

            for line in payload.lines:
                allowed = allowed_qtys.get(line.gs_item_id, 0)
                credited = already_credited.get(line.gs_item_id, 0)
                available = max(0, allowed - credited)
                if line.qty > available:
                    raise ValidationFailed(
                        f"G-13: Requested qty {line.qty} exceeds available uncredited quantity "
                        f"{available} (allowed: {allowed}, already credited: {credited}) "
                        f"for item {line.gs_item_id}."
                    )

            # Determine intra-state vs inter-state
            company_state_setting = repo.get_system_setting(session, "company_state_code")
            company_state = "UP"
            if isinstance(company_state_setting, str):
                company_state = company_state_setting.replace('"', "").strip().upper()

            party_state = (gs.get("party_state_code") or "").strip().upper()
            is_inter_state = bool(party_state and party_state != company_state)

            cn_id = repo.insert_credit_note(
                session,
                gs_id=payload.gs_id,
                cn_type_code=payload.cn_type_code,
                created_by=user.id,
                is_inter_state=is_inter_state,
                status="DRAFT",
                gst_portal_code=payload.gst_portal_code,
            )

            for idx, line in enumerate(payload.lines, start=1):
                repo.insert_credit_note_line(
                    session,
                    credit_note_id=cn_id,
                    gs_item_id=line.gs_item_id,
                    lot_id=line.lot_id,
                    line_no=idx,
                    qty=line.qty,
                )

            self._recalculate_valuation(session, cn_id)

        return self.get_credit_note(cn_id, user, perms)

    # =========================================================================
    # 3. Party Document Verification (BR-33, DD r72-r74)
    # =========================================================================

    def verify_party_document(
        self,
        cn_id: UUID,
        payload: PartyDocumentVerifyIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteDetailOut:
        if not perms.allows("credit_notes", "edit"):
            raise PermissionDenied("Only Accounts team or Admin can verify party documents")

        with self._uow.transaction(user.id) as session:
            cn = repo.get_credit_note(session, cn_id)
            if not cn:
                raise NotFound(f"Credit Note {cn_id} not found")
            if cn["status"] in ("ISSUED", "CANCELLED"):
                raise Conflict(f"Cannot edit party document on an {cn['status']} credit note")

            repo.update_party_document(
                session,
                cn_id=cn_id,
                party_doc_code=payload.party_doc_code,
                doc_no=payload.doc_no,
                doc_date=payload.doc_date,
                amount=payload.amount,
                notes=payload.notes,
                verified_by=user.id,
            )

        return self.get_credit_note(cn_id, user, perms)

    # =========================================================================
    # 4. GST Portal Verification (BR-34, DD r75-r76, G-13)
    # =========================================================================

    def verify_gst_check(
        self,
        cn_id: UUID,
        payload: GstCheckIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteDetailOut:
        if not perms.allows("credit_notes", "edit"):
            raise PermissionDenied("Only Accounts team or Admin can perform GST check")

        with self._uow.transaction(user.id) as session:
            cn = repo.get_credit_note(session, cn_id)
            if not cn:
                raise NotFound(f"Credit Note {cn_id} not found")
            if cn["status"] in ("ISSUED", "CANCELLED"):
                raise Conflict(f"Cannot update GST check on an {cn['status']} credit note")

            # Strict compliance (DD r76): if return not reflected, only JV_ONLY permitted!
            auto_cn_type = "JV_ONLY" if payload.gst_portal_code == "GST_NOT_REFLECTED" else None

            repo.update_gst_check(
                session,
                cn_id=cn_id,
                gst_portal_code=payload.gst_portal_code,
                return_type=payload.return_type,
                return_period=payload.return_period,
                checked_on=payload.checked_on,
                evidence_attachment_id=payload.evidence_attachment_id,
                verified_by=user.id,
                auto_cn_type_code=auto_cn_type,
            )

            self._recalculate_valuation(session, cn_id)

        return self.get_credit_note(cn_id, user, perms)

    # =========================================================================
    # 5. CN Type Selection & Split Action (G-13, DEC-23)
    # =========================================================================

    def update_cn_type(
        self,
        cn_id: UUID,
        payload: CnTypeUpdateIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteDetailOut:
        if not perms.allows("credit_notes", "edit"):
            raise PermissionDenied("Only Accounts team or Admin can change Credit Note type")

        with self._uow.transaction(user.id) as session:
            cn = repo.get_credit_note(session, cn_id)
            if not cn:
                raise NotFound(f"Credit Note {cn_id} not found")
            if cn["status"] in ("ISSUED", "CANCELLED"):
                raise Conflict(f"Cannot update type on an {cn['status']} credit note")

            new_type = payload.cn_type_code
            portal_status = cn.get("gst_portal_code")

            if new_type == "GST_CN":
                if portal_status != "GST_REFLECTED":
                    raise ValidationFailed(
                        "G-13: GST Credit Note requires the return to be reflected "
                        "on the GST portal (GST_REFLECTED)."
                    )
            elif portal_status == "GST_NOT_REFLECTED" and new_type != "JV_ONLY":
                raise ValidationFailed(
                    "G-13: Return NOT reflected on GST portal permits ONLY "
                    "Journal Voucher (JV_ONLY) per strict compliance rule (DD r76)."
                )

            # Check line condition classes
            lines = repo.get_credit_note_lines(session, cn_id)
            for ln in lines:
                cond = ln.get("condition_class")
                if cond:
                    if new_type == "GST_CN" and cond not in ("FUNCTIONAL_GOOD", "AS_RECEIVED"):
                        raise ValidationFailed(
                            f"G-13: GST Credit Note only applies to FUNCTIONAL_GOOD items. "
                            f"Line {ln['line_no']} is {cond}. Please use Split Credit Note "
                            "to separate repaired pieces into a General CN."
                        )
                    elif new_type == "GENERAL_CN" and cond != "FUNCTIONAL_REPAIRED":
                        raise ValidationFailed(
                            f"G-13: General Credit Note only applies to FUNCTIONAL_REPAIRED items. "
                            f"Line {ln['line_no']} is {cond}. Please use Split Credit Note "
                            "to separate good pieces into a GST CN."
                        )

            repo.update_cn_type(session, cn_id=cn_id, cn_type_code=new_type)
            self._recalculate_valuation(session, cn_id)

        return self.get_credit_note(cn_id, user, perms)

    def split_credit_note(
        self,
        cn_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> dict[str, Any]:
        """Automatically splits a CN that mixes good and repaired lines into separate CN records."""
        if not perms.allows("credit_notes", "edit"):
            raise PermissionDenied("Only Accounts team or Admin can split Credit Notes")

        with self._uow.transaction(user.id) as session:
            cn = repo.get_credit_note(session, cn_id)
            if not cn:
                raise NotFound(f"Credit Note {cn_id} not found")
            if cn["status"] in ("ISSUED", "CANCELLED"):
                raise Conflict(f"Cannot split an {cn['status']} credit note")

            lines = repo.get_credit_note_lines(session, cn_id)
            repaired_lines = [
                line for line in lines if line.get("condition_class") == "FUNCTIONAL_REPAIRED"
            ]
            good_lines = [
                line
                for line in lines
                if line.get("condition_class") in ("FUNCTIONAL_GOOD", "AS_RECEIVED")
            ]

            if not repaired_lines or not good_lines:
                return {
                    "split_performed": False,
                    "message": (
                        "Credit note does not contain a mix of Good and Repaired lines. "
                        "No split needed."
                    ),
                    "original_cn_id": str(cn_id),
                }

            # Create second CN for repaired lines
            repaired_cn_type = (
                "JV_ONLY" if cn.get("gst_portal_code") == "GST_NOT_REFLECTED" else "GENERAL_CN"
            )
            new_cn_id = repo.insert_credit_note(
                session,
                gs_id=cn["gs_id"],
                cn_type_code=repaired_cn_type,
                created_by=user.id,
                is_inter_state=bool(cn.get("is_inter_state")),
                status="DRAFT",
            )

            # Move repaired lines to new CN
            for idx, r_ln in enumerate(repaired_lines, start=1):
                repo.delete_credit_note_line(session, r_ln["id"])
                repo.insert_credit_note_line(
                    session,
                    credit_note_id=new_cn_id,
                    gs_item_id=r_ln["gs_item_id"],
                    lot_id=r_ln["lot_id"],
                    line_no=idx,
                    qty=r_ln["qty"],
                    rate=Decimal(str(r_ln["rate"])),
                    tax_rate=Decimal(str(r_ln["tax_rate"])),
                )

            # Original CN gets GST_CN if reflected, else JV_ONLY
            good_cn_type = "GST_CN" if cn.get("gst_portal_code") == "GST_REFLECTED" else "JV_ONLY"
            repo.update_cn_type(session, cn_id=cn_id, cn_type_code=good_cn_type)

            self._recalculate_valuation(session, cn_id)
            self._recalculate_valuation(session, new_cn_id)

            return {
                "split_performed": True,
                "message": "Credit note split successfully into Good and Repaired records.",
                "good_cn_id": str(cn_id),
                "good_cn_type": good_cn_type,
                "repaired_cn_id": str(new_cn_id),
                "repaired_cn_type": repaired_cn_type,
            }

    # =========================================================================
    # 6. Rate Verification (G-14, BR-36, DEC-24)
    # =========================================================================

    def verify_rate(
        self,
        line_id: UUID,
        payload: RateVerificationIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> RateVerificationResultOut:
        if not perms.allows("credit_notes", "edit"):
            raise PermissionDenied("Only Accounts team or Admin can record rate verification")

        with self._uow.transaction(user.id) as session:
            line_row = (
                session.execute(
                    text(
                        """
                    select cl.id, cl.credit_note_id, cl.qty, cl.rate, cl.tax_rate,
                           cn.status, cn.cn_type_code
                    from public.credit_note_lines cl
                    join public.credit_notes cn on cn.id = cl.credit_note_id
                    where cl.id = :id
                    """
                    ),
                    {"id": line_id},
                )
                .mappings()
                .first()
            )
            if not line_row:
                raise NotFound(f"Credit Note line {line_id} not found")
            if line_row["status"] in ("ISSUED", "CANCELLED"):
                raise Conflict(f"Cannot verify rates on an {line_row['status']} credit note")

            verif_id = repo.insert_rate_verification(
                session,
                credit_note_line_id=line_id,
                reference_code=payload.reference_code,
                ref_doc_no=payload.ref_doc_no,
                ref_doc_date=payload.ref_doc_date,
                rate=payload.rate,
                notes=payload.notes,
                verified_by=user.id,
            )

            # DEC-24: RATE_SALES determines the CN line rate
            if payload.reference_code == "RATE_SALES":
                new_rate = payload.rate
                qty = int(line_row["qty"])
                tax_rate = Decimal(str(line_row["tax_rate"]))
                taxable = (Decimal(qty) * new_rate).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

                cn = repo.get_credit_note(session, line_row["credit_note_id"])
                if not cn:
                    raise NotFound(f"Credit note {line_row['credit_note_id']} not found")

                is_inter_state = bool(cn.get("is_inter_state"))
                cn_type = cn.get("cn_type_code")

                if cn_type == "GST_CN":
                    if is_inter_state:
                        igst = (taxable * (tax_rate / Decimal("100"))).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        cgst = Decimal("0.00")
                        sgst = Decimal("0.00")
                    else:
                        half_tax = tax_rate / Decimal("200")
                        cgst = (taxable * half_tax).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        sgst = (taxable * half_tax).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        igst = Decimal("0.00")
                    total = taxable + cgst + sgst + igst
                else:
                    cgst = Decimal("0.00")
                    sgst = Decimal("0.00")
                    igst = Decimal("0.00")
                    total = taxable

                repo.update_line_rate(
                    session,
                    line_id=line_id,
                    rate=new_rate,
                    taxable_amount=taxable,
                    cgst_amount=cgst,
                    sgst_amount=sgst,
                    igst_amount=igst,
                    total_amount=total,
                )
                self._recalculate_valuation(session, line_row["credit_note_id"])

            # Check variance between sales and purchase rates
            all_verifs = repo.get_rate_verifications_for_line(session, line_id)
            sales_rate: Decimal | None = None
            purchase_rate: Decimal | None = None
            for v in all_verifs:
                if v["reference_code"] == "RATE_SALES":
                    sales_rate = Decimal(str(v["rate"]))
                elif v["reference_code"] == "RATE_PURCHASE":
                    purchase_rate = Decimal(str(v["rate"]))

            has_variance_warning = False
            variance_pct: Decimal | None = None
            warning_msg: str | None = None

            threshold_setting = repo.get_system_setting(session, "rate_variance_warning_percent")
            threshold = Decimal("15.0")
            if threshold_setting is not None:
                try:
                    threshold = Decimal(str(threshold_setting))
                except InvalidOperation:
                    log.warning(
                        "invalid_setting",
                        key="rate_variance_warning_percent",
                        value=str(threshold_setting),
                        fallback=str(threshold),
                    )

            if sales_rate is not None and purchase_rate is not None and purchase_rate > 0:
                diff = abs(sales_rate - purchase_rate)
                variance_pct = ((diff / purchase_rate) * Decimal("100")).quantize(Decimal("0.1"))
                if variance_pct > threshold:
                    has_variance_warning = True
                    warning_msg = (
                        f"Rate variance warning: Verified sales rate (₹{sales_rate}) differs from "
                        f"purchase baseline (₹{purchase_rate}) by {variance_pct}% "
                        f"(exceeds {threshold}% limit)."
                    )

            verif_row = next(v for v in all_verifs if v["id"] == verif_id)
            verif_out = RateVerificationOut(
                id=verif_row["id"],
                credit_note_line_id=verif_row["credit_note_line_id"],
                reference_code=verif_row["reference_code"],
                reference_label=verif_row["reference_label"],
                ref_doc_no=verif_row["ref_doc_no"],
                ref_doc_date=verif_row["ref_doc_date"],
                rate=verif_row["rate"],
                notes=verif_row["notes"],
                verified_by=verif_row["verified_by"],
                verified_by_name=verif_row["verified_by_name"],
                verified_at=verif_row["verified_at"],
            )

            return RateVerificationResultOut(
                verification=verif_out,
                sales_rate=sales_rate,
                purchase_rate=purchase_rate,
                variance_percent=variance_pct,
                has_variance_warning=has_variance_warning,
                variance_warning_message=warning_msg,
            )

    # =========================================================================
    # 7. Issue Credit Note (BR-37, G-14, DEC-22)
    # =========================================================================

    def issue_credit_note(
        self,
        cn_id: UUID,
        payload: CreditNoteIssueIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteDetailOut:
        if not perms.allows("credit_notes", "approve"):
            raise PermissionDenied("Only Accounts team or Admin can issue Credit Notes")

        with self._uow.transaction(user.id) as session:
            repo.lock_credit_note(session, cn_id)
            cn = repo.get_credit_note(session, cn_id)
            if not cn:
                raise NotFound(f"Credit Note {cn_id} not found")
            if cn["status"] == "ISSUED":
                raise Conflict(f"Credit Note {cn_id} is already issued")
            if cn["status"] == "CANCELLED":
                raise Conflict(f"Credit Note {cn_id} is cancelled and cannot be issued")

            cn_type = cn["cn_type_code"]
            clean_cn_no = payload.cn_no.strip() if payload.cn_no else None
            clean_jv_no = payload.jv_no.strip() if payload.jv_no else None

            # Validate voucher numbers per DEC-22
            if cn_type in ("GST_CN", "GENERAL_CN"):
                if not clean_cn_no:
                    raise ValidationFailed(
                        f"{cn['cn_type_label']} requires a non-empty Credit Note Number (cn_no)."
                    )
                if not payload.cn_date:
                    raise ValidationFailed(
                        f"{cn['cn_type_label']} requires a valid Credit Note Date (cn_date)."
                    )
            elif cn_type == "JV_ONLY":
                if not clean_jv_no:
                    raise ValidationFailed(
                        "Journal Voucher (JV_ONLY) requires a non-empty JV Number (jv_no)."
                    )
                if not payload.jv_date:
                    raise ValidationFailed(
                        "Journal Voucher (JV_ONLY) requires a valid JV Date (jv_date)."
                    )

            # G-14: Ensure every line has at least 1 rate verification
            lines = repo.get_credit_note_lines(session, cn_id)
            if not lines:
                raise ValidationFailed("G-14: Credit Note has zero lines. Cannot issue.")

            for ln in lines:
                verifs = repo.get_rate_verifications_for_line(session, ln["id"])
                if not verifs:
                    raise ValidationFailed(
                        f"G-14: Line {ln['line_no']} ({ln['product_code']}) "
                        "has no rate verification. "
                        "Every line requires at least 1 rate verification before issue."
                    )

            # DEC-22: the voucher number is unique. Pre-check for a clear message; a concurrent
            # issue with the same number is caught by the unique index and reported the same way.
            taken = Conflict(
                "This CN / JV number is already recorded on another credit note (DEC-22)",
                code="VOUCHER_NUMBER_TAKEN",
                details={"cn_no": clean_cn_no, "jv_no": clean_jv_no},
            )
            if repo.voucher_number_taken(
                session, cn_id=cn_id, cn_no=clean_cn_no, jv_no=clean_jv_no
            ):
                raise taken
            try:
                repo.issue_credit_note(
                    session,
                    cn_id=cn_id,
                    cn_no=clean_cn_no,
                    cn_date=payload.cn_date,
                    jv_no=clean_jv_no,
                    jv_date=payload.jv_date,
                    issued_by=user.id,
                )
            except IntegrityError as exc:
                constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                if constraint in ("credit_notes_cn_no_idx", "credit_notes_jv_no_idx"):
                    raise taken from exc
                raise

            # Check if all allowed quantities for this GS have been credited
            gs_id = cn["gs_id"]
            allowed = repo.get_allowed_cn_quantities(session, gs_id)
            total_allowed = sum(allowed.values())
            credited = repo.get_already_credited_quantities(session, gs_id)
            total_credited = sum(credited.values())

            if total_credited >= total_allowed and total_allowed > 0:
                role_row = (
                    session.execute(text("select id from public.roles where code = 'ACCOUNTS'"))
                    .mappings()
                    .first()
                )
                accounts_role_id = role_row["id"] if role_row else None

                gs_service.sync_step_task(
                    session,
                    gs_id=gs_id,
                    step_code="S6_ACCOUNTS_CN",
                    role_id=accounts_role_id,
                    needed=False,
                )

            # P3-07 / §6.5: CN work done → AWAITING_NOTIFICATION while BR-38 notice is due.
            closure_service.sync_status(session, gs_id, user.id)

            # Notify RM of issuance
            voucher_display = clean_cn_no or clean_jv_no or str(cn_id)
            notif_service.publish(
                session,
                "CN_ISSUED",
                role_codes=["REPLACEMENT_MANAGER"],
                notification_type="CN_ISSUED",
                title=f"Credit Note Issued: {voucher_display}",
                body=(
                    f"Accounts team issued {cn['cn_type_label']} ({voucher_display}) "
                    f"for GS {cn['gs_no']} ({cn['party_name']})."
                ),
                entity_type="credit_notes",
                entity_id=cn_id,
                gs_id=cn.get("gs_id"),
                data={"gs_no": cn["gs_no"]},
                priority="NORMAL",
            )

        return self.get_credit_note(cn_id, user, perms)

    # =========================================================================
    # 8. Cancel Credit Note
    # =========================================================================

    def cancel_credit_note(
        self,
        cn_id: UUID,
        payload: CreditNoteCancelIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteDetailOut:
        # Requires Admin or Accounts approval with reason
        if not (perms.allows("credit_notes", "approve") or user.is_super_admin):
            raise PermissionDenied("Only Accounts team or Admin can cancel a Credit Note")

        if not payload.reason or len(payload.reason.strip()) < 3:
            raise ValidationFailed("A non-empty cancellation reason (>= 3 chars) is required.")

        with self._uow.transaction(user.id) as session:
            cn = repo.get_credit_note(session, cn_id)
            if not cn:
                raise NotFound(f"Credit Note {cn_id} not found")
            if cn["status"] == "CANCELLED":
                raise Conflict(f"Credit Note {cn_id} is already cancelled")

            repo.cancel_credit_note(
                session,
                cn_id=cn_id,
                reason=payload.reason.strip(),
                cancelled_by=user.id,
            )

        return self.get_credit_note(cn_id, user, perms)

    # =========================================================================
    # 9. Query & Print Methods
    # =========================================================================

    def get_credit_note(
        self,
        cn_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteDetailOut:
        if not (perms.allows("credit_notes", "view") or perms.allows("goods_slips", "view")):
            raise PermissionDenied("You do not have permission to view credit notes")

        with self._uow.transaction(user.id) as session:
            cn = repo.get_credit_note(session, cn_id)
            if not cn:
                raise NotFound(f"Credit Note {cn_id} not found")

            raw_lines = repo.get_credit_note_lines(session, cn_id)
            lines_out: list[CreditNoteLineOut] = []

            for r_ln in raw_lines:
                verifs = repo.get_rate_verifications_for_line(session, r_ln["id"])
                verifs_out = [
                    RateVerificationOut(
                        id=v["id"],
                        credit_note_line_id=v["credit_note_line_id"],
                        reference_code=v["reference_code"],
                        reference_label=v["reference_label"],
                        ref_doc_no=v["ref_doc_no"],
                        ref_doc_date=v["ref_doc_date"],
                        rate=v["rate"],
                        notes=v["notes"],
                        verified_by=v["verified_by"],
                        verified_by_name=v["verified_by_name"],
                        verified_at=v["verified_at"],
                    )
                    for v in verifs
                ]
                lines_out.append(
                    CreditNoteLineOut(
                        id=r_ln["id"],
                        credit_note_id=r_ln["credit_note_id"],
                        gs_item_id=r_ln["gs_item_id"],
                        line_no=r_ln["line_no"],
                        product_code=r_ln["product_code"],
                        product_name=r_ln["product_name"],
                        lot_id=r_ln["lot_id"],
                        condition_class=r_ln["condition_class"],
                        qty=r_ln["qty"],
                        rate=r_ln["rate"],
                        tax_rate=r_ln["tax_rate"],
                        taxable_amount=r_ln["taxable_amount"],
                        cgst_amount=r_ln["cgst_amount"],
                        sgst_amount=r_ln["sgst_amount"],
                        igst_amount=r_ln["igst_amount"],
                        total_amount=r_ln["total_amount"],
                        rate_verifications=verifs_out,
                        is_rate_verified=len(verifs_out) > 0,
                    )
                )

            # Step-2 documents for side-by-side evidence
            raw_docs = repo.get_step2_documents_for_gs(session, cn["gs_id"])
            step2_docs: list[LinkedStep2Document] = []
            for d in raw_docs:
                url = None
                if d.get("attachment_id"):
                    url = f"/api/v1/attachments/{d['attachment_id']}/download-url"

                step2_docs.append(
                    LinkedStep2Document(
                        id=d["id"],
                        document_type_code=d["document_type_code"],
                        document_type_label=d["document_type_label"],
                        doc_no=d["doc_no"],
                        doc_date=d["doc_date"],
                        amount=d["amount"],
                        attachment_id=d["attachment_id"],
                        file_name=d["file_name"],
                        download_url=url,
                    )
                )

            return CreditNoteDetailOut(
                id=cn["id"],
                gs_id=cn["gs_id"],
                gs_no=cn["gs_no"],
                party_id=cn["party_id"],
                party_name=cn["party_name"],
                party_gstin=cn["party_gstin"],
                party_state=cn["party_state_name"] or cn["party_state_code"],
                cn_type_code=cn["cn_type_code"],
                cn_type_label=cn["cn_type_label"],
                status=cn["status"],
                party_doc_code=cn["party_doc_code"],
                party_doc_label=cn["party_doc_label"],
                party_doc_no=cn["party_doc_no"],
                party_doc_date=cn["party_doc_date"],
                party_doc_amount=cn["party_doc_amount"],
                party_doc_notes=cn["party_doc_notes"],
                gst_portal_code=cn["gst_portal_code"],
                gst_portal_label=cn["gst_portal_label"],
                gst_return_type=cn["gst_return_type"],
                gst_return_period=cn["gst_return_period"],
                gst_checked_on=cn["gst_checked_on"],
                gst_evidence_attachment_id=cn["gst_evidence_attachment_id"],
                cn_no=cn["cn_no"],
                cn_date=cn["cn_date"],
                jv_no=cn["jv_no"],
                jv_date=cn["jv_date"],
                taxable_value=cn["taxable_value"],
                cgst_rate=cn["cgst_rate"],
                cgst_amount=cn["cgst_amount"],
                sgst_rate=cn["sgst_rate"],
                sgst_amount=cn["sgst_amount"],
                igst_rate=cn["igst_rate"],
                igst_amount=cn["igst_amount"],
                total_value=cn["total_value"],
                is_inter_state=cn["is_inter_state"],
                created_by=cn["created_by"],
                created_by_name=cn["created_by_name"] or "Accounts User",
                created_at=cn["created_at"],
                issued_by=cn["issued_by"],
                issued_by_name=cn["issued_by_name"],
                issued_at=cn["issued_at"],
                cancelled_by_name=cn["cancelled_by_name"],
                cancelled_at=cn["cancelled_at"],
                cancel_reason=cn["cancel_reason"],
                lines=lines_out,
                linked_step2_documents=step2_docs,
            )

    def list_credit_notes(
        self,
        *,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID | None = None,
        status: str | None = None,
        cn_type_code: str | None = None,
        party_search: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CreditNoteListItemOut]:
        if not (perms.allows("credit_notes", "view") or perms.allows("goods_slips", "view")):
            raise PermissionDenied("You do not have permission to list credit notes")

        with self._uow.transaction(user.id) as session:
            rows = repo.list_credit_notes(
                session,
                gs_id=gs_id,
                status=status,
                cn_type_code=cn_type_code,
                party_search=party_search,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                offset=offset,
            )
            return [
                CreditNoteListItemOut(
                    id=r["id"],
                    gs_id=r["gs_id"],
                    gs_no=r["gs_no"],
                    party_id=r["party_id"],
                    party_name=r["party_name"],
                    cn_type_code=r["cn_type_code"],
                    cn_type_label=r["cn_type_label"],
                    status=r["status"],
                    party_doc_code=r["party_doc_code"],
                    party_doc_label=r["party_doc_label"],
                    gst_portal_code=r["gst_portal_code"],
                    gst_portal_label=r["gst_portal_label"],
                    cn_no=r["cn_no"],
                    cn_date=r["cn_date"],
                    jv_no=r["jv_no"],
                    jv_date=r["jv_date"],
                    total_qty=r["total_qty"],
                    taxable_value=r["taxable_value"],
                    total_value=r["total_value"],
                    created_at=r["created_at"],
                    issued_at=r["issued_at"],
                )
                for r in rows
            ]

    def get_work_queue(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNoteWorkQueueOut:
        if not (perms.allows("credit_notes", "view") or perms.allows("goods_slips", "view")):
            raise PermissionDenied("You do not have permission to view the Accounts work queue")

        with self._uow.transaction(user.id) as session:
            pending_raw = repo.get_work_queue_pending_gs(session)
            pending_items = [
                CreditNoteWorkQueueItem(
                    gs_id=r["gs_id"],
                    gs_no=r["gs_no"],
                    party_id=r["party_id"],
                    party_name=r["party_name"],
                    allowed_cn_qty=r["allowed_qty"],
                    draft_cn_qty=r["draft_cn_qty"],
                    issued_cn_qty=r["issued_cn_qty"],
                    pending_to_credit_qty=r["pending_to_credit_qty"],
                    rm_decision_date=r["decision_date"],
                    active_credit_notes_count=r["active_credit_notes_count"],
                )
                for r in pending_raw
            ]

            active_notes = self.list_credit_notes(
                user=user,
                perms=perms,
                limit=100,
            )

            return CreditNoteWorkQueueOut(
                pending_gs=pending_items,
                active_notes=active_notes,
            )

    def get_credit_note_print(
        self,
        cn_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> CreditNotePrintOut:
        cn = self.get_credit_note(cn_id, user, perms)

        voucher_no = cn.cn_no or cn.jv_no or "PROVISIONAL-DRAFT"
        voucher_date = cn.cn_date or cn.jv_date or date.today()

        lines_summary = []
        for ln in cn.lines:
            rate_ref_doc = None
            if ln.rate_verifications:
                rv0 = ln.rate_verifications[0]
                rate_ref_doc = f"{rv0.reference_label} ({rv0.ref_doc_no})"

            lines_summary.append(
                {
                    "line_no": ln.line_no,
                    "product_code": ln.product_code,
                    "product_name": ln.product_name,
                    "qty": ln.qty,
                    "rate": float(ln.rate),
                    "tax_rate": float(ln.tax_rate),
                    "taxable_amount": float(ln.taxable_amount),
                    "cgst_amount": float(ln.cgst_amount),
                    "sgst_amount": float(ln.sgst_amount),
                    "igst_amount": float(ln.igst_amount),
                    "total_amount": float(ln.total_amount),
                    "rate_ref_doc": rate_ref_doc,
                }
            )

        signature_blocks = [
            PrintSignatureBlock(
                label="Verified & Prepared By",
                name=cn.issued_by_name or "Deepak Ji",
                role="Accounts Team",
            ),
            PrintSignatureBlock(
                label="Approved By", name="Pratham Pratap Singh", role="Replacement Manager"
            ),
        ]

        voucher_name = (
            "GST Credit Note"
            if cn.cn_type_code == "GST_CN"
            else ("General Credit Note" if cn.cn_type_code == "GENERAL_CN" else "Journal Voucher")
        )

        return CreditNotePrintOut(
            credit_note_id=cn.id,
            gs_id=cn.gs_id,
            gs_no=cn.gs_no,
            party_name=cn.party_name,
            party_gstin=cn.party_gstin,
            party_station=cn.party_state,
            party_state=cn.party_state,
            cn_type_code=cn.cn_type_code,
            cn_type_label=cn.cn_type_label,
            voucher_no=voucher_no,
            voucher_date=voucher_date,
            voucher_type_name=voucher_name,
            party_doc_type=cn.party_doc_label,
            party_doc_no=cn.party_doc_no,
            party_doc_date=cn.party_doc_date,
            gst_portal_status=cn.gst_portal_label,
            gst_return_period=cn.gst_return_period,
            taxable_value=cn.taxable_value,
            cgst_amount=cn.cgst_amount,
            sgst_amount=cn.sgst_amount,
            igst_amount=cn.igst_amount,
            total_value=cn.total_value,
            is_inter_state=cn.is_inter_state,
            lines=lines_summary,
            signature_blocks=signature_blocks,
        )

    # =========================================================================
    # Internal Valuation Calculations
    # =========================================================================

    def _recalculate_valuation(self, session: Session, cn_id: UUID) -> None:
        cn = repo.get_credit_note(session, cn_id)
        if not cn:
            return

        lines = repo.get_credit_note_lines(session, cn_id)
        cn_type = cn.get("cn_type_code")
        is_inter_state = bool(cn.get("is_inter_state"))

        sum_taxable = Decimal("0.00")
        sum_cgst = Decimal("0.00")
        sum_sgst = Decimal("0.00")
        sum_igst = Decimal("0.00")
        sum_total = Decimal("0.00")

        for ln in lines:
            qty = Decimal(str(ln["qty"]))
            rate = Decimal(str(ln["rate"]))
            tax_rate = Decimal(str(ln["tax_rate"]))
            line_taxable = (qty * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            if cn_type == "GST_CN":
                if is_inter_state:
                    line_igst = (line_taxable * (tax_rate / Decimal("100"))).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    line_cgst = Decimal("0.00")
                    line_sgst = Decimal("0.00")
                else:
                    half_rate = tax_rate / Decimal("200")
                    line_cgst = (line_taxable * half_rate).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    line_sgst = (line_taxable * half_rate).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    line_igst = Decimal("0.00")
                line_total = line_taxable + line_cgst + line_sgst + line_igst
            else:
                line_cgst = Decimal("0.00")
                line_sgst = Decimal("0.00")
                line_igst = Decimal("0.00")
                line_total = line_taxable

            repo.update_line_rate(
                session,
                line_id=ln["id"],
                rate=rate,
                taxable_amount=line_taxable,
                cgst_amount=line_cgst,
                sgst_amount=line_sgst,
                igst_amount=line_igst,
                total_amount=line_total,
            )

            sum_taxable += line_taxable
            sum_cgst += line_cgst
            sum_sgst += line_sgst
            sum_igst += line_igst
            sum_total += line_total

        cgst_rate = (
            Decimal("9.00") if (cn_type == "GST_CN" and not is_inter_state) else Decimal("0.00")
        )
        sgst_rate = (
            Decimal("9.00") if (cn_type == "GST_CN" and not is_inter_state) else Decimal("0.00")
        )
        igst_rate = (
            Decimal("18.00") if (cn_type == "GST_CN" and is_inter_state) else Decimal("0.00")
        )

        repo.update_cn_valuation(
            session,
            cn_id=cn_id,
            taxable_value=sum_taxable,
            cgst_rate=cgst_rate,
            cgst_amount=sum_cgst,
            sgst_rate=sgst_rate,
            sgst_amount=sum_sgst,
            igst_rate=igst_rate,
            igst_amount=sum_igst,
            total_value=sum_total,
            is_inter_state=is_inter_state,
        )


@dataclass
class _PlannedCommercial:
    """Planned commercial outcome of one GS line from its current Step-3 a) actions (DEC-13)."""

    allow_qty: int = 0
    deny: dict[str, int] = field(default_factory=dict)  # SEND_NEW / SEND_REPAIRED → qty
    labels: dict[str, str] = field(default_factory=dict)

    def expected(self) -> dict[str, int]:
        return {"ALLOW_CN": self.allow_qty, "DENY_CN_SEND_REPLACEMENT": sum(self.deny.values())}

    def rows(self) -> list[tuple[str, str, int, str]]:
        out: list[tuple[str, str, int, str]] = []
        if self.allow_qty:
            out.append(
                ("ISSUE_CN", self.labels.get("ISSUE_CN", "ISSUE_CN"), self.allow_qty, "ALLOW_CN")
            )
        deny_qty = sum(self.deny.values())
        if deny_qty:
            code = max(self.deny, key=lambda c: self.deny[c])
            out.append((code, self.labels.get(code, code), deny_qty, "DENY_CN_SEND_REPLACEMENT"))
        return out


def _planned_commercial(
    actions: list[dict[str, Any]], *, is_csr: bool
) -> dict[UUID, _PlannedCommercial]:
    """Aggregate every current RM action row per line (BR-19, BR-32, DEC-13).

    ISSUE_CN plans a credit note; SEND_NEW / SEND_REPAIRED plan a replacement (CN denied). For a
    Complete Sales Return every commercial quantity is credited (BR-09). NOT_ALLOWED and
    PENDING_BP quantities carry no commercial outcome.
    """
    plans: dict[UUID, _PlannedCommercial] = {}
    for a in actions:
        plan = plans.setdefault(a["gs_item_id"], _PlannedCommercial())
        code, qty = str(a["action_code"]), int(a["qty"])
        plan.labels[code] = a.get("action_label") or code
        if code == "ISSUE_CN" or (is_csr and code in ("SEND_NEW", "SEND_REPAIRED")):
            plan.allow_qty += qty
        elif code in ("SEND_NEW", "SEND_REPAIRED"):
            plan.deny[code] = plan.deny.get(code, 0) + qty
    return plans
