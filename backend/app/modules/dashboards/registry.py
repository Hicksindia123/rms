"""Widget registry (prompt P4-01, master plan Â§10 "Dashboard widgets").

Each widget = stable code + permission requirement + parameter schema + query function. Titles and
descriptions are configuration (`public.dashboard_widgets`, rule e). Permission requirements live
HERE, not in configuration, so no layout or label edit can widen what a user may see; the service
never returns a widget (layout entry or data) the caller lacks a permission for.

Query functions aggregate in SQL (dashboards/repository.py) or call another module's service, so
the numbers match that module's list screen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import UnitOfWork
from app.core.errors import PermissionDenied
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.container_audit.service import get_today_ist
from app.modules.dashboards import repository as repo
from app.modules.dashboards.schemas import (
    AccountsQueueData,
    AdminHealthData,
    BatteryData,
    BatteryTypeBalance,
    CnIssuedData,
    CnIssuedParams,
    CnMonthRow,
    CnPipelineData,
    CnTypeLabel,
    ContainerAuditData,
    DismantlingData,
    FunctionalStockData,
    GateTodayData,
    GsPipelineData,
    GsQueueData,
    GsTrendData,
    GuardCount,
    HazardData,
    MyTasksData,
    NonFunctionalStockData,
    NoParams,
    PartTypeQty,
    PendencyData,
    StatusCount,
    StepCount,
    StockCount,
    TechnicianWipData,
    TransfersData,
    TrendParams,
    TrendWeek,
    WidgetPriority,
)
from app.modules.inventory.battery_service import get_battery_balances
from app.modules.inventory.service import InventoryService, StockFilters

Permission = tuple[str, str]

# Â§6.5 GS lifecycle (system statuses, in lifecycle order). CLOSED / CANCELLED are not "open".
GS_OPEN_STATUSES: tuple[str, ...] = (
    "GATE_CREATED",
    "UNBOXING",
    "ITEMIZATION",
    "CATEGORISATION",  # AMD-08 (change plan Phase 3)
    "CSR_APPROVAL_PENDING",
    "INSPECTION",
    "RM_REVIEW",
    "IN_PROCESS",
    "COMMERCIAL_RESOLUTION",
    "AWAITING_NOTIFICATION",
)
EVIDENCE_STATUSES = ["GATE_CREATED", "UNBOXING"]  # Step-2 not yet completed (G-02)
INSPECTION_STATUSES = ["INSPECTION"]
TECH_WIP_STATUSES = ["ALLOTTED", "IN_PROGRESS", "PARTIALLY_RECEIVED"]
FUNCTIONAL_CONDITIONS = ("FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED", "AS_RECEIVED")
CN_TYPE_ORDER = ("GST_CN", "GENERAL_CN", "JV_ONLY")
ADMIN_WINDOW_DAYS = 7


@dataclass(frozen=True, slots=True)
class WidgetContext:
    uow: UnitOfWork
    user: CurrentUser
    perms: EffectivePermissions

    def scope_args(self, module: str = "goods_slips") -> dict[str, Any]:
        """Data scope of the linked list (own / department / all), as goods_slips lists apply it."""
        scope = self.perms.scope(module, "view")
        return {
            "scope_created_by": self.user.id if scope == "own" else None,
            "scope_department_of": self.user.id if scope == "department" else None,
        }


QueryFn = Callable[[WidgetContext, Any], BaseModel]


@dataclass(frozen=True, slots=True)
class WidgetDef:
    code: str
    requires: tuple[Permission, ...]
    params: type[BaseModel]
    query: QueryFn
    priority: WidgetPriority = "insight"
    # Live widgets are never cached and are refreshed on realtime notification events.
    live: bool = False

    def allowed(self, perms: EffectivePermissions) -> bool:
        return all(perms.allows(m, a) for m, a in self.requires)

    def missing(self, grants: set[Permission]) -> list[Permission]:
        return [p for p in self.requires if p not in grants]


def _timezone(session: Session) -> str:
    tz = repo.get_setting(session, "timezone")
    return tz if isinstance(tz, str) and tz else get_settings().tz


def _now() -> datetime:
    return datetime.now(UTC)


# --- query functions ------------------------------------------------------------------------------


def q_my_tasks(ctx: WidgetContext, _p: NoParams) -> MyTasksData:
    with ctx.uow.transaction(ctx.user.id) as session:
        rows = repo.my_tasks_by_step(
            session, user_id=ctx.user.id, all_tasks=ctx.user.is_super_admin
        )
    steps = [StepCount(**r) for r in rows]
    return MyTasksData(
        total=sum(s.count for s in steps),
        overdue=sum(s.overdue for s in steps),
        by_step=steps,
    )


def q_gs_pipeline(ctx: WidgetContext, _p: NoParams) -> GsPipelineData:
    with ctx.uow.transaction(ctx.user.id) as session:
        rows = repo.gs_pipeline(session, open_statuses=list(GS_OPEN_STATUSES), **ctx.scope_args())
    found = {r["status"]: r for r in rows}
    by_status = [
        StatusCount(
            status=s,
            count=int(found[s]["count"]) if s in found else 0,
            avg_age_days=float(found[s]["avg_age_days"] or 0) if s in found else 0.0,
        )
        for s in GS_OPEN_STATUSES
    ]
    return GsPipelineData(total_open=sum(s.count for s in by_status), by_status=by_status)


def q_gate_today(ctx: WidgetContext, _p: NoParams) -> GateTodayData:
    with ctx.uow.transaction(ctx.user.id) as session:
        tz = _timezone(session)
        day = repo.today_in(session, tz)
        row = repo.gs_created_on(session, day=day, timezone=tz, **ctx.scope_args())
    return GateTodayData(date=day, **row)


def _gs_queue(ctx: WidgetContext, statuses: list[str]) -> GsQueueData:
    with ctx.uow.transaction(ctx.user.id) as session:
        row = repo.gs_in_statuses(session, statuses=statuses, **ctx.scope_args())
    return GsQueueData(statuses=statuses, **row)


def q_evidence_pending(ctx: WidgetContext, _p: NoParams) -> GsQueueData:
    return _gs_queue(ctx, EVIDENCE_STATUSES)


def q_inspections_pending(ctx: WidgetContext, _p: NoParams) -> GsQueueData:
    return _gs_queue(ctx, INSPECTION_STATUSES)


def q_csr_pending(ctx: WidgetContext, _p: NoParams) -> GsQueueData:
    with ctx.uow.transaction(ctx.user.id) as session:
        row = repo.csr_pending(session)
    return GsQueueData(statuses=["CSR_APPROVAL_PENDING"], **row)


def q_container_audit(ctx: WidgetContext, _p: NoParams) -> ContainerAuditData:
    today = get_today_ist()
    with ctx.uow.transaction(ctx.user.id) as session:
        raw = repo.get_setting(session, "container_audit_compliance_days")
        days = raw if isinstance(raw, int) and 1 <= raw <= 365 else 30
        window_to = today - timedelta(days=1)
        window_from = today - timedelta(days=days)
        row = repo.container_audit_summary(
            session, today=today, window_from=window_from, window_to=window_to
        )
    on_time, late = int(row["confirmed_on_time"]), int(row["confirmed_late"])
    return ContainerAuditData(
        today=today,
        today_status=row["today_status"] or "PENDING",
        window_from=window_from,
        window_to=window_to,
        window_days=days,
        confirmed_on_time=on_time,
        confirmed_late=late,
        missed_or_pending=days - on_time - late,
        compliance_pct=round(100.0 * (on_time + late) / days, 1),
    )


def q_pendencies(ctx: WidgetContext, _p: NoParams) -> PendencyData:
    with ctx.uow.transaction(ctx.user.id) as session:
        return PendencyData(**repo.open_pendencies(session))


def q_transfers(ctx: WidgetContext, _p: NoParams) -> TransfersData:
    with ctx.uow.transaction(ctx.user.id) as session:
        return TransfersData(**repo.transfers_attention(session))


def q_technician_wip(ctx: WidgetContext, _p: NoParams) -> TechnicianWipData:
    with ctx.uow.transaction(ctx.user.id) as session:
        rows = repo.technician_wip(session, statuses=TECH_WIP_STATUSES)
    found = {r["status"]: r for r in rows}
    batches = sum(int(r["count"]) for r in rows)
    weighted = sum(float(r["avg_age_days"] or 0) * int(r["count"]) for r in rows)
    return TechnicianWipData(
        open_batches=batches,
        pieces_with_technicians=sum(int(r["pieces_out"]) for r in rows),
        oldest_age_days=max((int(r["oldest_age_days"]) for r in rows), default=None),
        avg_age_days=round(weighted / batches, 1) if batches else None,
        by_status=[
            StatusCount(
                status=s,
                count=int(found[s]["count"]) if s in found else 0,
                avg_age_days=float(found[s]["avg_age_days"] or 0) if s in found else 0.0,
            )
            for s in TECH_WIP_STATUSES
        ],
    )


def q_batteries(ctx: WidgetContext, _p: NoParams) -> BatteryData:
    now = _now()
    with ctx.uow.transaction(ctx.user.id) as session:
        # Same balances as GET /inventory/batteries/balances (one row per active battery type).
        balances = get_battery_balances(session)
        consumed_7 = repo.batteries_installed_since(session, since=now - timedelta(days=7))
        consumed_30 = repo.batteries_installed_since(session, since=now - timedelta(days=30))
    by_type = [
        BatteryTypeBalance(code=b.code, name=b.name, balance=int(b.balance)) for b in balances
    ]
    return BatteryData(
        total_balance=sum(b.balance for b in by_type),
        consumed_7d=consumed_7,
        consumed_30d=consumed_30,
        by_type=by_type,
    )


def q_dismantling(ctx: WidgetContext, _p: NoParams) -> DismantlingData:
    with ctx.uow.transaction(ctx.user.id) as session:
        queue = repo.dismantling_queue(session)
        recovered = repo.parts_recovered_since(session, since=_now() - timedelta(days=30))
        labels = repo.option_labels(session, "RECOVERABLE_PART_TYPE")
    parts = [
        PartTypeQty(
            part_type=r["part_type"], label=labels.get(r["part_type"], r["part_type"]), qty=r["qty"]
        )
        for r in recovered
    ]
    return DismantlingData(
        queue_lots=queue["queue_lots"],
        queue_qty=queue["queue_qty"],
        recovered_30d=sum(p.qty for p in parts),
        recovered_by_type=parts,
    )


def _stock_total(
    ctx: WidgetContext, view: Any, condition_class: str | None = None
) -> tuple[int, int]:
    """Totals of one inventory view via InventoryService (the same query as the list screen)."""
    page = InventoryService(ctx.uow).stock(
        ctx.user, view, StockFilters(condition_class=condition_class), page=1, page_size=1
    )
    return page.total, page.total_qty


def q_functional_stock(ctx: WidgetContext, _p: NoParams) -> FunctionalStockData:
    total_rows, total_qty = _stock_total(ctx, "FUNCTIONAL")
    by_condition = []
    for cond in FUNCTIONAL_CONDITIONS:
        rows, qty = _stock_total(ctx, "FUNCTIONAL", cond)
        by_condition.append(StockCount(key=cond, rows=rows, qty=qty))
    return FunctionalStockData(
        total_rows=total_rows, total_qty=total_qty, by_condition=by_condition
    )


def q_non_functional_stock(ctx: WidgetContext, _p: NoParams) -> NonFunctionalStockData:
    nf_rows, nf_qty = _stock_total(ctx, "NON_FUNCTIONAL")
    try:
        sp: tuple[int, int] | None = _stock_total(ctx, "SPARE_PARTS")
    except PermissionDenied as exc:
        if exc.code != "SPARE_PARTS_LEDGER_RESTRICTED":
            raise
        sp = None  # BR-30: the spare-parts ledger is restricted to configured roles
    return NonFunctionalStockData(
        non_functional_rows=nf_rows,
        non_functional_qty=nf_qty,
        spare_parts_visible=sp is not None,
        spare_parts_rows=sp[0] if sp else None,
        spare_parts_qty=sp[1] if sp else None,
    )


def q_hazard(ctx: WidgetContext, _p: NoParams) -> HazardData:
    rows, qty = _stock_total(ctx, "HAZARD_QUARANTINE")
    return HazardData(rows=rows, qty=qty)


def q_cn_pipeline(ctx: WidgetContext, _p: NoParams) -> CnPipelineData:
    with ctx.uow.transaction(ctx.user.id) as session:
        return CnPipelineData(**repo.cn_pipeline(session, issued_since=_now() - timedelta(days=30)))


def q_cn_issued(ctx: WidgetContext, p: CnIssuedParams) -> CnIssuedData:
    with ctx.uow.transaction(ctx.user.id) as session:
        rows = repo.cn_issued_by_month(session, months=p.months, timezone=_timezone(session))
        labels = repo.option_labels(session, "CN_TYPE")
    out = [CnMonthRow(**r) for r in rows]
    return CnIssuedData(
        months=p.months,
        types=[CnTypeLabel(code=c, label=labels.get(c, c)) for c in CN_TYPE_ORDER],
        rows=out,
        total_count=sum(r.count for r in out),
        total_value=round(sum(r.value for r in out), 2),
    )


def q_gs_trend(ctx: WidgetContext, p: TrendParams) -> GsTrendData:
    with ctx.uow.transaction(ctx.user.id) as session:
        rows = repo.gs_trend(
            session, weeks=p.weeks, timezone=_timezone(session), **ctx.scope_args()
        )
    return GsTrendData(weeks=p.weeks, rows=[TrendWeek(**r) for r in rows])


def q_accounts_queue(ctx: WidgetContext, _p: NoParams) -> AccountsQueueData:
    with ctx.uow.transaction(ctx.user.id) as session:
        return AccountsQueueData(**repo.accounts_doc_queue(session))


def q_admin_health(ctx: WidgetContext, _p: NoParams) -> AdminHealthData:
    since = _now() - timedelta(days=ADMIN_WINDOW_DAYS)
    with ctx.uow.transaction(ctx.user.id) as session:
        row = repo.admin_health(session, since=since)
        by_code = repo.guard_events_by_code(session, since=since)
        last = repo.last_failed_job(session, since=since)
    return AdminHealthData(
        window_days=ADMIN_WINDOW_DAYS,
        guard_violations_by_code=[GuardCount(**r) for r in by_code],
        last_failed_job=last["job_code"] if last else None,
        last_failed_at=last["finished_at"] if last else None,
        **row,
    )


# --- the registry ---------------------------------------------------------------------------

_GS: Permission = ("goods_slips", "view")

WIDGETS: Sequence[WidgetDef] = (
    WidgetDef("MY_TASKS", (("dashboards", "view"),), NoParams, q_my_tasks, "action", live=True),
    WidgetDef("GS_PIPELINE", (_GS,), NoParams, q_gs_pipeline),
    WidgetDef("GATE_INWARDS_TODAY", (_GS,), NoParams, q_gate_today, "action"),
    WidgetDef(
        "EVIDENCE_PENDING", (_GS, ("unboxing", "view")), NoParams, q_evidence_pending, "action"
    ),
    WidgetDef(
        "CSR_APPROVALS_PENDING", (("itemization", "approve"),), NoParams, q_csr_pending, "action"
    ),
    WidgetDef(
        "INSPECTIONS_PENDING",
        (_GS, ("inspection", "view")),
        NoParams,
        q_inspections_pending,
        "action",
    ),
    WidgetDef(
        "CONTAINER_AUDIT", (("container_audit", "view"),), NoParams, q_container_audit, "action"
    ),
    WidgetDef("OPEN_PENDENCIES", (_GS,), NoParams, q_pendencies, "action"),
    WidgetDef("TRANSFERS_ATTENTION", (("custody", "view"),), NoParams, q_transfers, "action"),
    WidgetDef("TECHNICIAN_WIP", (("servicing", "view"),), NoParams, q_technician_wip, "action"),
    WidgetDef("BATTERY_STOCK", (("inventory", "view"),), NoParams, q_batteries),
    WidgetDef("DISMANTLING", (("dismantling", "view"),), NoParams, q_dismantling, "action"),
    WidgetDef("FUNCTIONAL_STOCK", (("inventory", "view"),), NoParams, q_functional_stock),
    WidgetDef("NON_FUNCTIONAL_STOCK", (("inventory", "view"),), NoParams, q_non_functional_stock),
    WidgetDef("HAZARD_QUARANTINE", (("inventory", "view"),), NoParams, q_hazard, "action"),
    WidgetDef("CN_PIPELINE", (("credit_notes", "view"),), NoParams, q_cn_pipeline, "action"),
    WidgetDef("CN_ISSUED", (("credit_notes", "view"),), CnIssuedParams, q_cn_issued),
    WidgetDef("GS_TREND", (_GS,), TrendParams, q_gs_trend),
    WidgetDef(
        "ACCOUNTS_DOC_QUEUE", (("credit_notes", "view"),), NoParams, q_accounts_queue, "action"
    ),
    # Â§10: admin screens require `configure` permissions.
    WidgetDef("ADMIN_HEALTH", (("config", "configure"),), NoParams, q_admin_health, "action"),
)

REGISTRY: dict[str, WidgetDef] = {w.code: w for w in WIDGETS}
