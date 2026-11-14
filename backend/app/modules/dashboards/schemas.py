"""Pydantic I/O for dashboards and the widget registry (prompt P4-01, master plan §10, §11)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

WidgetSize = Literal["S", "M", "L"]
WidgetPriority = Literal["action", "insight"]


# --- widget parameters (one model per widget; unknown keys are rejected) -----------------------
class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrendParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weeks: int = Field(default=8, ge=4, le=26, description="Weeks of history (4-26)")


class CnIssuedParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    months: int = Field(default=6, ge=1, le=12, description="Months of history (1-12)")


# --- layouts ------------------------------------------------------------------------------------
class RoleRef(BaseModel):
    code: str
    name: str


class PermissionRef(BaseModel):
    module: str
    action: str


class LayoutWidgetOut(BaseModel):
    code: str
    title: str
    description: str | None
    size: WidgetSize
    priority: WidgetPriority
    live: bool = Field(description="Refreshed on task/notification events, not cached")


class DashboardOut(BaseModel):
    role: RoleRef | None
    available_roles: list[RoleRef]
    widgets: list[LayoutWidgetOut]
    hidden_widget_count: int = Field(
        description="Widgets in the role layout the user lacks permission for (never returned)"
    )
    poll_seconds: int


class WidgetDataOut(BaseModel):
    code: str
    title: str
    generated_at: datetime
    cached: bool
    data: dict[str, Any]


# --- admin --------------------------------------------------------------------------------------
class WidgetCatalogueItem(BaseModel):
    code: str
    title: str
    description: str | None
    default_size: WidgetSize
    priority: WidgetPriority
    is_active: bool
    requires: list[PermissionRef]
    params_schema: dict[str, Any]


class LayoutEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=60, pattern=r"^[A-Z][A-Z0-9_]+$")
    size: WidgetSize


class LayoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    widgets: list[LayoutEntryIn] = Field(max_length=30)
    reason: str | None = Field(default=None, max_length=500)


class LayoutEntryOut(BaseModel):
    code: str
    title: str
    size: WidgetSize
    allowed_for_role: bool = Field(description="The role's own permissions allow this widget")
    missing: list[PermissionRef]


class RoleLayoutOut(BaseModel):
    role: RoleRef
    has_layout: bool
    widgets: list[LayoutEntryOut]
    role_permissions: list[PermissionRef] = Field(
        description="The role's own permissions (lets the editor check widgets before saving)"
    )
    updated_at: datetime | None
    updated_by_name: str | None


# --- widget data models (documented shapes of WidgetDataOut.data) --------------------------------
class StepCount(BaseModel):
    step_code: str
    step_label: str | None
    count: int
    overdue: int
    oldest_created_at: datetime | None


class MyTasksData(BaseModel):
    total: int
    overdue: int
    by_step: list[StepCount]


class StatusCount(BaseModel):
    status: str
    count: int
    avg_age_days: float


class GsPipelineData(BaseModel):
    total_open: int
    by_status: list[StatusCount]


class GateTodayData(BaseModel):
    date: date
    count: int
    boxes: int
    missing_documentation: int


class GsQueueData(BaseModel):
    statuses: list[str]
    count: int
    oldest_created_at: datetime | None


class ContainerAuditData(BaseModel):
    today: date
    today_status: str
    window_from: date
    window_to: date
    window_days: int
    confirmed_on_time: int
    confirmed_late: int
    missed_or_pending: int
    compliance_pct: float


class PendencyData(BaseModel):
    open_count: int
    open_qty: int
    blocking_count: int
    oldest_opened_at: datetime | None


class TransfersData(BaseModel):
    awaiting_acceptance: int
    in_discrepancy: int
    oldest_awaiting_at: datetime | None


class TechnicianWipData(BaseModel):
    open_batches: int
    pieces_with_technicians: int
    oldest_age_days: int | None
    avg_age_days: float | None
    by_status: list[StatusCount]


class BatteryTypeBalance(BaseModel):
    code: str
    name: str
    balance: int


class BatteryData(BaseModel):
    total_balance: int
    consumed_7d: int
    consumed_30d: int
    by_type: list[BatteryTypeBalance]


class PartTypeQty(BaseModel):
    part_type: str
    label: str
    qty: int


class DismantlingData(BaseModel):
    queue_lots: int
    queue_qty: int
    recovered_30d: int
    recovered_by_type: list[PartTypeQty]


class StockCount(BaseModel):
    key: str
    rows: int
    qty: int


class FunctionalStockData(BaseModel):
    total_rows: int
    total_qty: int
    by_condition: list[StockCount]


class NonFunctionalStockData(BaseModel):
    non_functional_rows: int
    non_functional_qty: int
    spare_parts_visible: bool
    spare_parts_rows: int | None
    spare_parts_qty: int | None


class HazardData(BaseModel):
    rows: int
    qty: int


class CnPipelineData(BaseModel):
    awaiting_credit_gs: int
    draft: int
    verified: int
    issued_30d: int


class CnTypeLabel(BaseModel):
    code: str
    label: str


class CnMonthRow(BaseModel):
    month: date
    cn_type_code: str
    count: int
    value: float


class CnIssuedData(BaseModel):
    months: int
    types: list[CnTypeLabel]
    rows: list[CnMonthRow]
    total_count: int
    total_value: float


class TrendWeek(BaseModel):
    week_start: date
    opened: int
    closed: int


class GsTrendData(BaseModel):
    weeks: int
    rows: list[TrendWeek]


class AccountsQueueData(BaseModel):
    count: int
    oldest_created_at: datetime | None


class GuardCount(BaseModel):
    guard_code: str
    count: int


class AdminHealthData(BaseModel):
    window_days: int
    users_active: int
    users_inactive: int
    logins: int
    users_logged_in: int
    config_changes: int
    guard_violations: int
    guard_violations_by_code: list[GuardCount]
    job_runs: int
    failed_jobs: int
    last_failed_job: str | None
    last_failed_at: datetime | None
