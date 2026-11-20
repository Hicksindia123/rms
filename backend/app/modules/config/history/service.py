"""Service for querying configuration audit trail and static system guards (prompt P1-08)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.db import UnitOfWork
from app.core.security import CurrentUser
from app.modules.config.history.schemas import (
    ConfigChangeLogItem,
    ConfigHistoryResponse,
    SystemGuardItem,
)

STATIC_SYSTEM_GUARDS: list[dict[str, Any]] = [
    {
        "code": "G-01",
        "name": "GS Inward Identification",
        "statement": (
            "No inward, item or stock record may exist without a goods_slip_id "
            "that has a generated GS number."
        ),
        "enforcement_layer": "PostgreSQL NOT NULL + Foreign Key constraints",
    },
    {
        "code": "G-02",
        "name": "Unboxing Evidence Completeness",
        "statement": (
            "A GS cannot leave UNBOXING until every carton 1..N has a confirmed unboxing "
            "video. No document photo and no Missing Document Exception are required "
            "(DEC-63, 2026-11-20; supersedes DEC-03)."
        ),
        "enforcement_layer": (
            "PostgreSQL trigger goods_slips_g02_guard + Workflow Engine + FastAPI Step-2 guard"
        ),
    },
    {
        "code": "G-03",
        "name": "Complete Sales Return Approval Gate",
        "statement": (
            "A CSR GS cannot advance past CSR_APPROVAL_PENDING without an RM decision "
            "recorded by a user holding the approve permission."
        ),
        "enforcement_layer": "FastAPI CSR service + Workflow transition check",
    },
    {
        "code": "G-04",
        "name": "Not Allowed Stock Segregation",
        "statement": (
            "Stock in a lot whose condition is 'Not Allowed' can never move into a "
            "functional location (location_class = FUNCTIONAL). "
            "Enforced by a trigger on stock_movements."
        ),
        "enforcement_layer": "PostgreSQL Trigger on stock_movements",
    },
    {
        "code": "G-05",
        "name": "Mercury Hazard Quarantine",
        "statement": (
            "Mercury-hazard conditions (PRS_BROKEN_WITH_HG, EO_BODY_BROKEN_HG) can only "
            "be placed in a HAZARD_QUARANTINE location."
        ),
        "enforcement_layer": "Database trigger + Option item hazard lock (cannot change to YES)",
    },
    {
        "code": "G-06",
        "name": "Enclosed Oval Opening Verification",
        "statement": (
            "Enclosed Oval grading cannot be submitted unless full_opening_confirmed = true."
        ),
        "enforcement_layer": "Database CHECK + FastAPI Inspection validator",
    },
    {
        "code": "G-07",
        "name": "Extraction & Received Qty Reconciliation",
        "statement": (
            "Inspection finalisation requires sum of condition quantities = received quantity, "
            "and packaging-extracted + container-extracted = allocated quantity (per DEC-07)."
        ),
        "enforcement_layer": "Dynamic Form cross-field sum validator + Service validation",
    },
    {
        "code": "G-08",
        "name": "Pending (BP) Handover Hold",
        "statement": (
            "Quantities marked Pending (BP) cannot be added to a custody transfer. "
            "A GS with an open blocking pendency cannot advance its workflow status."
        ),
        "enforcement_layer": "Workflow Engine transition guard + Custody service",
    },
    {
        "code": "G-09",
        "name": "Two-Phase Custody Handover Sync",
        "statement": (
            "Custody transfers are two-phase (initiate -> accept). Stock is only credited to "
            "the receiver on acceptance. A discrepancy freezes the transfer until it is reconciled."
        ),
        "enforcement_layer": "Stock Ledger double-entry movements + Status state machine",
    },
    {
        "code": "G-10",
        "name": "Battery Replaced Count Reconciliation",
        "statement": (
            "BATTERY_REPLACED requires pieces_checked > 0 and batteries_installed > 0. "
            "Battery stock is deducted in the same transaction and can never go negative."
        ),
        "enforcement_layer": "Database CHECK + rms_move_stock function",
    },
    {
        "code": "G-11",
        "name": "PCB Model & Supplier Traceability",
        "statement": "PCB recovered-part rows require a PCB model and supplier (DB CHECK).",
        "enforcement_layer": "Database CHECK constraint on recovered_parts",
    },
    {
        "code": "G-12",
        "name": "Functional Intermediate Store Cleanliness",
        "statement": (
            "A location of class FUNCTIONAL (Intermediate Store) rejects non-functional, "
            "non-sellable or scrap lots (trigger)."
        ),
        "enforcement_layer": "Database trigger on stock_movements",
    },
    {
        "code": "G-13",
        "name": "Commercial Credit Note & GST Verification",
        "statement": (
            "A CN cannot be created without an ALLOW_CN decision. A GST CN cannot be issued "
            "unless portal status = GST_REFLECTED. GST_NOT_REFLECTED permits only a JV record."
        ),
        "enforcement_layer": "Database CHECK on credit_notes + FastAPI Commercial service",
    },
    {
        "code": "G-14",
        "name": "Rate Verification Baseline Mandate",
        "statement": ("A CN cannot be issued without >= 1 rate verification record per CN line."),
        "enforcement_layer": "FastAPI Commercial service rate verification gate",
    },
    {
        "code": "G-15",
        "name": "Prior Party Notification Mandate",
        "statement": (
            "A GS cannot be closed while a commercial resolution requiring notification lacks a "
            "PRIOR_INFO_SENT record, while stock for the GS remains in transit or pending, "
            "or while any line is unresolved."
        ),
        "enforcement_layer": "Workflow Engine transition guard + Closure checklist check",
    },
    {
        "code": "G-16",
        "name": "Non-Negative Stock & Idempotency",
        "statement": (
            "No stock balance may be negative. Every stock-changing call carries an "
            "idempotency key, and duplicate keys return the original result."
        ),
        "enforcement_layer": "rms_private.rms_move_stock PL/pgSQL function with row locks",
    },
    {
        "code": "G-17",
        "name": "Audit Attribution & Insert-Only Log",
        "statement": (
            "All inserts, updates and deletes on business tables and all configuration "
            "changes are written to the audit log, attributed to the acting user."
        ),
        "enforcement_layer": "config_change_log and audit_log triggers (UPDATE/DELETE revoked)",
    },
    {
        "code": "G-18",
        "name": "Published Workflow & Form Immutability",
        "statement": (
            "Published workflow and form versions are immutable. Each transaction stores "
            "the version it was created or submitted under."
        ),
        "enforcement_layer": "rms_private.guard_version_row database triggers",
    },
    # Change request 2026-11-12 (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md).
    {
        "code": "G-19",
        "name": "Categorisation Bucket Conservation",
        "statement": (
            "Per GS item, the sum of the categorisation bucket quantities equals the counted "
            "quantity before the GS reaches RM review / the intermediate store (AMD-09)."
        ),
        "enforcement_layer": "validate_item_bucket_conservation + goods_slips_g03_guard triggers",
    },
    {
        "code": "G-20",
        "name": "Department Quantity Reconciliation",
        "statement": (
            "Per GS item, counted = in store + at departments + in outcome heads + actioned; "
            "RM final actions cover outcome-head pieces first, nothing is counted twice (AMD-15)."
        ),
        "enforcement_layer": "validate_department_reconciliation (routing / receipt / action "
        "triggers, serialised per GS)",
    },
    {
        "code": "G-21",
        "name": "RM Final Action Split",
        "statement": (
            "Per GS item, the RM final action quantities sum to the quantity available for "
            "action (counted - at departments), use only actions of the resolved profile, and "
            "are finalised only when nothing is at a department; a finalised A/c Actions slip "
            "is immutable and is superseded only by a reasoned revision (AMD-16, AMD-17). "
            "Per item + current condition no condition gets more actions than it has; a "
            "Pending re-action round re-actions exactly the pieces the previous round left "
            "Pending, after Accounts completed and settled that round (DEC-57)."
        ),
        "enforcement_layer": "validate_final_action_split + rm_item_actions / ac_action_slips "
        "triggers",
    },
    {
        "code": "G-22",
        "name": "Accounts Entry & Dispatch Slip",
        "statement": (
            "Accounts enters CN / Challan data only where the action's flags require it, on the "
            "current A/c Actions slip of a held goods slip, with a CN No. used by one goods slip "
            "only; completion needs every line complete and freezes the entries, the slip and the "
            "RM actions; the Dispatch Slip lists exactly the goods-shipping lines and is "
            "dispatched once (AMD-18, AMD-19). Each final-action round has its own slip, "
            "completion and Dispatch Slip; a re-action round is entered while the goods slip is "
            "open after the store stage (DEC-57)."
        ),
        "enforcement_layer": "ac_entry_lines / ac_entry_completions / dispatch_slips / "
        "dispatch_slip_lines triggers",
    },
]


class ConfigHistoryService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def get_history(
        self,
        user: CurrentUser,
        entity_type: str | None = None,
        entity_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> ConfigHistoryResponse:
        with self._uow.transaction(user.id) as session:
            where_clauses = ["1=1"]
            params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}

            if entity_type:
                where_clauses.append("c.entity_type = :entity_type")
                params["entity_type"] = entity_type

            if entity_id:
                where_clauses.append("c.entity_id = :entity_id")
                params["entity_id"] = entity_id

            where_sql = " and ".join(where_clauses)

            total = (
                session.execute(
                    text(
                        f"select count(*) from public.config_change_log c where {where_sql}"  # noqa: S608
                    ),
                    params,
                ).scalar()
                or 0
            )

            rows = session.execute(
                text(
                    f"""
                    select c.id, c.entity_type, c.entity_id, c.action, c.before, c.after,
                           c.reason, c.changed_by, p.email as actor_email,
                           p.full_name as actor_name, c.request_id, c.changed_at
                    from public.config_change_log c
                    left join public.profiles p on p.id = c.changed_by
                    where {where_sql}
                    order by c.changed_at desc, c.id desc
                    limit :limit offset :offset
                    """  # noqa: S608
                ),
                params,
            ).mappings()

            items = [ConfigChangeLogItem.model_validate(dict(r)) for r in rows]
            return ConfigHistoryResponse(
                items=items,
                total=int(total),
                page=page,
                page_size=page_size,
            )

    def get_system_guards(self) -> list[SystemGuardItem]:
        return [SystemGuardItem.model_validate(g) for g in STATIC_SYSTEM_GUARDS]

    def list_system_guards(self) -> list[SystemGuardItem]:
        return self.get_system_guards()
