"""System guard implementations for workflow engine and business operations (Â§4.2).

Guards registered here are non-bypassable and automatically invoked by
the workflow engine during transition checks or by domain services.
"""

from __future__ import annotations

from typing import Any

from app.shared.workflow_engine import register_guard


@register_guard("G-01")
def guard_g01(entity: Any, user: Any) -> bool:
    """Guard G-01: Inward/stock records require a goods_slip_id with generated GS number."""
    if not getattr(entity, "id", None):
        return False
    ctx = getattr(entity, "context", {}) or {}
    gs_no = ctx.get("gs_no") or getattr(entity, "gs_no", None)
    return not (gs_no is not None and not str(gs_no).strip())


def g02_missing_evidence(ctx: dict[str, Any]) -> list[str]:
    """G-02 / BR-04 (DEC-63, 2026-11-20): what is still missing before a GS may leave UNBOXING.

    Only the carton videos count: one confirmed video for every carton 1..N. Document photos,
    their classification and the retired Missing Document Exception (DEC-03) are no longer part
    of the guard (user Q8 + Q25), also for a GS flagged missing documentation.

    Context keys (computed by the unboxing service): `video_count` (confirmed videos) and
    `boxes_missing_video` (cartons without a confirmed video, AMD-03). The DB trigger
    `rms_private.goods_slips_g02_guard` enforces the same rule.
    """
    missing: list[str] = []
    if int(ctx.get("video_count") or 0) < 1:
        missing.append("UNBOXING_VIDEO")
    if ctx.get("boxes_missing_video"):
        missing.append("VIDEO_PER_CARTON")
    return missing


@register_guard("G-02")
def guard_g02(entity: Any, user: Any) -> bool:
    """Guard G-02 (DEC-63): a GS cannot leave UNBOXING until every carton has a confirmed video.
    Not configurable; Super Admin cannot bypass it."""
    ctx = getattr(entity, "context", {}) or {}
    return not g02_missing_evidence(ctx)


CSR_DECISIONS = frozenset({"CSR_APPROVED", "CSR_REJECTED_TO_RO"})  # DD r19-r20


def g03_violation(ctx: dict[str, Any]) -> str | None:
    """G-03 / BR-08: why a GS may not advance past CSR_APPROVAL_PENDING (None = it may).

    Context keys: `category_code`, `original_category_code`, `csr_decision` (current decision code
    or None), `csr_decision_authorized` (recorded by an S1_CSR_APPROVAL approver or an active Super
    Admin). The DB trigger `rms_private.goods_slips_g03_guard` enforces the same rule.
    """
    category = ctx.get("category_code")
    if category != "CSR" and ctx.get("original_category_code") != "CSR":
        return None
    decision = ctx.get("csr_decision")
    if decision not in CSR_DECISIONS:
        return "CSR_DECISION_MISSING"
    if not ctx.get("csr_decision_authorized"):
        return "CSR_DECISION_UNAUTHORIZED"
    if (category == "CSR") != (decision == "CSR_APPROVED"):
        return "CSR_DECISION_MISMATCH"
    return None


@register_guard("G-03")
def guard_g03(entity: Any, user: Any) -> bool:
    """Guard G-03: a CSR GS cannot advance past CSR_APPROVAL_PENDING without the Replacement
    Manager's recorded decision. Super Admin cannot bypass it."""
    ctx = getattr(entity, "context", {}) or {}
    return g03_violation(ctx) is None


@register_guard("G-04")
def guard_g04(entity: Any, user: Any) -> bool:
    """Guard G-04: Not Allowed stock can never move into functional locations.

    Enforced in database on stock_movements and verified in workflow transitions.
    """
    ctx = getattr(entity, "context", {}) or {}
    condition_class = ctx.get("condition_class") or ctx.get("lot_condition_class")
    target_loc_class = ctx.get("target_location_class") or ctx.get("location_class")
    forbidden_conditions = {
        "NOT_ALLOWED",
        "HAZARD",
        "NON_GOOD",
        "NON_SELLABLE",
        "SCRAP",
    }
    forbidden_targets = {"FUNCTIONAL", "MAIN_STORE", "DISPATCHED"}
    return not (condition_class in forbidden_conditions and target_loc_class in forbidden_targets)


@register_guard("G-05")
def guard_g05(entity: Any, user: Any) -> bool:
    """Guard G-05: Mercury-hazard conditions can only be placed in HAZARD_QUARANTINE.

    Hazard lots may also move to SCRAP_DISPOSED for certified disposal.
    """
    ctx = getattr(entity, "context", {}) or {}
    condition_class = ctx.get("condition_class") or ctx.get("lot_condition_class")
    source_code = ctx.get("source_condition_code") or ctx.get("condition_code")
    target_loc_class = ctx.get("target_location_class") or ctx.get("location_class")
    is_hazard = condition_class == "HAZARD" or source_code in {
        "PRS_BROKEN_WITH_HG",
        "EO_BODY_BROKEN_HG",
    }
    return not (
        is_hazard
        and target_loc_class
        and target_loc_class not in {"HAZARD_QUARANTINE", "SCRAP_DISPOSED"}
    )


@register_guard("G-06")
def guard_g06(entity: Any, user: Any) -> bool:
    """Guard G-06: Enclosed Oval grading cannot be submitted
    unless full_opening_confirmed = true.
    """
    ctx = getattr(entity, "context", {}) or {}
    if "eo_full_opening_confirmed" in ctx:
        return bool(ctx["eo_full_opening_confirmed"])
    if "has_unconfirmed_eo" in ctx:
        return not bool(ctx["has_unconfirmed_eo"])
    return True


@register_guard("G-07")
def guard_g07(entity: Any, user: Any) -> bool:
    """Guard G-07: Inspection finalisation requires Î£ condition quantities = received quantity,
    and packaging-extracted + container-extracted = allocated quantity (per DEC-07)."""
    ctx = getattr(entity, "context", {}) or {}
    if "inspection_reconciled" in ctx:
        return bool(ctx["inspection_reconciled"])
    if "has_unreconciled_inspection" in ctx:
        return not bool(ctx["has_unreconciled_inspection"])
    return True


@register_guard("G-08")
def guard_g08(entity: Any, user: Any) -> bool:
    """Guard G-08: Quantities marked Pending cannot move to TRANSIT/FUNCTIONAL,

    and a GS with an open blocking pendency cannot advance workflow status.
    """
    ctx = getattr(entity, "context", {}) or {}
    is_pending = ctx.get("is_pending", False)
    target_loc_class = ctx.get("target_location_class") or ctx.get("location_class")
    if is_pending and target_loc_class in {"TRANSIT", "FUNCTIONAL"}:
        return False
    blocks_entire_gs = ctx.get("pending_blocks_entire_gs", False)
    has_open_pendency = ctx.get("has_open_pendency", False)
    return not (blocks_entire_gs and has_open_pendency)


@register_guard("G-12")
def guard_g12(entity: Any, user: Any) -> bool:
    """Guard G-12: Intermediate Store rejects non-functional lots."""
    ctx = getattr(entity, "context", {}) or {}
    target_loc_class = ctx.get("target_location_class") or ctx.get("location_class")
    condition_class = ctx.get("condition_class") or ctx.get("lot_condition_class")
    allowed_conditions = {"AS_RECEIVED", "FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED"}
    return not (
        target_loc_class == "FUNCTIONAL"
        and condition_class
        and condition_class not in allowed_conditions
    )


@register_guard("G-16")
def guard_g16(entity: Any, user: Any) -> bool:
    """Guard G-16: No stock balance may be negative; idempotency key required on movements."""
    ctx = getattr(entity, "context", {}) or {}
    qty = ctx.get("qty")
    balance = ctx.get("balance", ctx.get("current_balance"))
    if qty is not None:
        if qty < 0:
            return False
        if balance is not None and qty > balance:
            return False
    return ctx.get("has_idempotency_key") is not False


@register_guard("G-13")
def guard_g13(entity: Any, user: Any) -> bool:
    """Guard G-13: A CN cannot be created without an ALLOW_CN decision.

    A GST CN cannot be issued unless portal status = GST_REFLECTED.
    GST_NOT_REFLECTED permits only a JV record.
    """
    ctx = getattr(entity, "context", {}) or {}
    has_allow_cn = ctx.get("has_allow_cn")
    if has_allow_cn is False:
        return False
    cn_type = ctx.get("cn_type_code")
    portal_code = ctx.get("gst_portal_code")
    if cn_type == "GST_CN" and portal_code != "GST_REFLECTED":
        return False
    return not (portal_code == "GST_NOT_REFLECTED" and cn_type not in (None, "JV_ONLY"))


@register_guard("G-14")
def guard_g14(entity: Any, user: Any) -> bool:
    """Guard G-14: A CN cannot be issued without >=1 rate verification record per line."""
    ctx = getattr(entity, "context", {}) or {}
    unverified_lines = ctx.get("unverified_line_count", 0)
    return int(unverified_lines) == 0
