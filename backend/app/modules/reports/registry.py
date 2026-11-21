"""Report registry (prompt P4-02, master plan §10 "Report columns").

Each report = stable code + permission requirement + data-scope owner + SQL (reports/sql.py) +
typed column definitions (default visibility, totals, drill-down link) + filter definitions.

Titles, descriptions, groups and column-label overrides are configuration
(`public.report_definitions`, rule e); everything that decides *what data* a user may read lives
HERE, so no configuration edit can widen access. Every report additionally requires
`reports.view`; exports require `reports.export`.

Data scope (§8.1 role_permissions.scope of `reports.view`):
  all         every row;
  department  rows whose owner (``owner_expr``) is in the caller's department;
  own         rows whose owner is the caller.
Facility-wide reports without a per-row owner (owner_expr = None: container audit, battery
reconciliation, inventory position, stock reconciliation) need scope ``all`` and are hidden from
callers with a narrower scope (docs/DECISIONS.md, P4-02).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.modules.reports import sql

Permission = tuple[str, str]
ColType = Literal[
    "text",
    "code",
    "int",
    "decimal",
    "money",
    "hours",
    "days",
    "percent",
    "date",
    "datetime",
    "bool",
]
TotalKind = Literal["sum", "avg", "max", "count_true"]
FilterType = Literal["date", "text", "enum", "uuid", "bool"]
FilterMode = Literal["inner", "outer", "param"]
FilterOp = Literal["eq", "gte", "lte", "ilike"]
DefaultKind = Literal["window_start", "today", "false", "true"]

GS_STATUSES = (
    "GATE_CREATED",
    "UNBOXING",
    "ITEMIZATION",
    "CATEGORISATION",  # AMD-08 (change plan Phase 3)
    "CSR_APPROVAL_PENDING",
    "INSPECTION",
    "RM_REVIEW",
    "PENDING_TRANSFER_SLIP",  # DEC-64
    "SALES_RETURN_HOLD",  # DEC-64 / Q11
    "IN_PROCESS",
    "COMMERCIAL_RESOLUTION",
    "AWAITING_NOTIFICATION",
    "CLOSED",
    "CANCELLED",
)
TRANSFER_STATUSES = ("INITIATED", "ACCEPTED", "DISCREPANCY", "RECONCILED", "CANCELLED")
LOCATION_CLASSES = (
    "INWARD",
    "TRANSIT",
    "FUNCTIONAL",
    "TECHNICIAN",
    "NON_FUNCTIONAL",
    "SPARE_PARTS",
    "REJECTED_HOLD",
    "HAZARD_QUARANTINE",
    "MAIN_STORE",
    "DISPATCHED",
    "SCRAP_DISPOSED",
    "CREDITED",
    "PENDING_HOLD",
)
CONDITION_CLASSES = (
    "AS_RECEIVED",
    "NOT_ALLOWED",
    "HAZARD",
    "FUNCTIONAL_GOOD",
    "FUNCTIONAL_REPAIRED",
    "NON_GOOD",
    "NON_SELLABLE",
    "SALVAGED",
    "SCRAP",
)
ITEM_KINDS = ("FINISHED_GOOD", "SPARE_PART", "BATTERY", "PACKAGING")
AGEING_BUCKETS = ("0-1", "1-3", "3-7", ">7")
ACTION_CODES = (
    "STATUS_CHANGE",
    "TRANSFER_INITIATE",
    "TRANSFER_ACCEPT",
    "TECH_ALLOT",
    "TECH_RECEIVE",
    "DISMANTLE_COMPLETE",
    "STORE_ISSUE",
    "CN_ISSUE",
    "PARTY_NOTIFY",
    "DISPATCH",
)
CN_STAGES = ("AWAITING_CN", "AWAITING_ISSUE", "AWAITING_NOTIFICATION", "NOTIFIED")
RECON_CHECKS = ("IC-01", "IC-02", "IC-03", "IC-05", "IC-09")


@dataclass(frozen=True, slots=True)
class Total:
    kind: TotalKind | Literal["ratio"]
    # ratio = 100 * sum(numerator) / sum(denominator) (weighted rate, e.g. battery replacement rate)
    numerator: str | None = None
    denominator: str | None = None


SUM = Total("sum")
AVG = Total("avg")
MAX = Total("max")
COUNT_TRUE = Total("count_true")


@dataclass(frozen=True, slots=True)
class Col:
    key: str
    label: str
    type: ColType = "text"
    default: bool = True
    total: Total | None = None
    # Hash-route template with {key} placeholders of row values (hidden id columns allowed).
    link: str | None = None
    # Phone card role: 1 = card title, 2 = highlighted value, 0 = body.
    card: int = 0
    sortable: bool = True


@dataclass(frozen=True, slots=True)
class Filt:
    key: str
    label: str
    type: FilterType
    mode: FilterMode = "inner"
    # inner: SQL expression inside the base query; outer: a result column key.
    expr: str = ""
    op: FilterOp = "eq"
    choices: tuple[str, ...] = ()
    option_set: str | None = None
    lookup: str | None = None
    default: DefaultKind | None = None


@dataclass(frozen=True, slots=True)
class ReportDef:
    code: str
    requires: tuple[Permission, ...]
    sql: str
    columns: tuple[Col, ...]
    filters: tuple[Filt, ...]
    default_sort: tuple[str, Literal["asc", "desc"]]
    tiebreak: str
    owner_expr: str | None
    hidden: tuple[str, ...] = field(default=())
    # Longest date_from..date_to span (days) for reports that emit one row per day.
    max_span_days: int | None = None

    def column(self, key: str) -> Col | None:
        return next((c for c in self.columns if c.key == key), None)

    def filter(self, key: str) -> Filt | None:
        return next((f for f in self.filters if f.key == key), None)

    @property
    def default_columns(self) -> list[str]:
        return [c.key for c in self.columns if c.default]


# --- reusable filters -----------------------------------------------------------------------------
def _date_range(expr: str, label: str = "Date", *, default: bool = False) -> tuple[Filt, Filt]:
    return (
        Filt(
            "date_from",
            f"{label} from",
            "date",
            expr=expr,
            op="gte",
            default="window_start" if default else None,
        ),
        Filt(
            "date_to",
            f"{label} to",
            "date",
            expr=expr,
            op="lte",
            default="today" if default else None,
        ),
    )


def _param_range(label: str = "Date", *, required: bool = True) -> tuple[Filt, Filt]:
    return (
        Filt(
            "date_from",
            f"{label} from",
            "date",
            mode="param",
            default="window_start" if required else None,
        ),
        Filt("date_to", f"{label} to", "date", mode="param", default="today" if required else None),
    )


def _local_date(col: str) -> str:
    return f"({col} at time zone :tz)::date"


_GS_LINK = "/gs/{gs_id}"


REPORTS: tuple[ReportDef, ...] = (
    # R-01 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-01",
        requires=(("goods_slips", "view"),),
        sql=sql.R01,
        owner_expr="t.assigned_user_id",
        default_sort=("oldest_days", "desc"),
        tiebreak="step_code",
        columns=(
            Col("step_label", "Step", card=1, link="/mywork?step={step_code}"),
            Col("step_code", "Step code", "code", default=False),
            Col("assignee", "Assigned to", card=2),
            Col("assignee_type", "Assigned as", "code", default=False),
            Col("open_tasks", "Open", "int", total=SUM),
            Col("age_0_1", "0-1 days", "int", total=SUM),
            Col("age_1_3", "1-3 days", "int", total=SUM),
            Col("age_3_7", "3-7 days", "int", total=SUM),
            Col("age_over_7", "Over 7 days", "int", total=SUM),
            Col("overdue", "Overdue", "int", total=SUM),
            Col("oldest_days", "Oldest (days)", "days", total=MAX),
        ),
        filters=(
            Filt("step", "Step", "enum", expr="t.step_code", lookup="steps"),
            Filt(
                "assignee_type",
                "Assigned as",
                "enum",
                expr="(case when t.assigned_user_id is not null then 'USER' else 'ROLE' end)",
                choices=("USER", "ROLE"),
            ),
        ),
    ),
    # R-02 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-02",
        requires=(("goods_slips", "view"),),
        sql=sql.R02,
        owner_expr="g.created_by",
        default_sort=("gate_at", "desc"),
        tiebreak="gs_no",
        hidden=("gs_id",),
        columns=(
            Col("gs_no", "GS No.", card=1, link=_GS_LINK),
            Col("gs_date", "GS date", "date", default=False),
            Col("party_name", "Party", card=2),
            Col("category_code", "Category", "code"),
            Col("status", "Status", "code"),
            Col("gate_at", "Gate", "datetime", default=False),
            Col("unboxing_started_at", "Unboxing started", "datetime", default=False),
            Col("evidence_completed_at", "Step-2 complete", "datetime", default=False),
            Col("categorized_at", "Categorised", "datetime", default=False),
            Col("csr_decided_at", "CSR decided", "datetime", default=False),
            Col("inspected_at", "Inspected", "datetime", default=False),
            Col("in_process_at", "In process", "datetime", default=False),
            Col("commercial_at", "Commercial resolution", "datetime", default=False),
            Col("notified_at", "Party notified", "datetime", default=False),
            Col("closed_at", "Closed", "datetime", default=False),
            Col("h_gate_to_evidence", "Gate → Step-2 (h)", "hours", total=AVG),
            Col("h_evidence_to_review", "Step-2 → inspected / CSR (h)", "hours", total=AVG),
            Col("h_review_to_process", "Inspected → in process (h)", "hours", total=AVG),
            Col("h_process_to_commercial", "In process → commercial (h)", "hours", total=AVG),
            Col("h_commercial_to_close", "Commercial → closed (h)", "hours", total=AVG),
            Col("h_total", "Lifecycle (h)", "hours", total=AVG),
            Col("days_in_status", "Days in status", "days", total=AVG),
            Col("flags", "Flags", "code"),
        ),
        filters=(
            *_date_range(_local_date("g.created_at"), "GS date"),
            Filt("status", "Status", "enum", expr="g.status", choices=GS_STATUSES),
            Filt(
                "category", "Category", "enum", expr="g.category_code", option_set="RETURN_CATEGORY"
            ),
            Filt("party", "Party", "text", expr="pa.name", op="ilike"),
        ),
    ),
    # R-03 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-03",
        requires=(("goods_slips", "view"),),
        sql=sql.R03,
        owner_expr="g.created_by",
        default_sort=("gs_date", "desc"),
        tiebreak="gs_no",
        hidden=("gs_id",),
        columns=(
            Col("gs_no", "GS No.", card=1, link=_GS_LINK),
            Col("gs_date", "Date", "date"),
            Col("party_code", "Party code", default=False),
            Col("party_name", "Party", card=2),
            Col("state_name", "State"),
            Col("station_name", "Station"),
            Col("delivery_mode_code", "Delivery mode", "code", default=False),
            # Change plan 2026-11-12 Phase 2: AMD-01 / AMD-02 / AMD-03 / AMD-04
            Col("return_type_code", "Return type", "code", default=False),
            Col("gate_entry_date", "Gate entry date", "date", default=False),
            Col("gate_entry_no", "Gate entry no.", default=False),
            Col("carton_count", "Cartons", "int", total=SUM),
            Col("gate_documents", "Gate documents", default=False),
            Col("category_code", "Category", "code"),
            Col("status", "Status", "code"),
            Col("lines", "Lines", "int", total=SUM, default=False),
            Col("documented_qty", "Documented qty", "int", total=SUM),
            Col("received_qty", "Received qty", "int", total=SUM),
            Col("short_qty", "Short qty", "int", total=SUM),
            Col("missing_documentation", "Missing docs", "bool", total=COUNT_TRUE, default=False),
            Col("has_open_pendency", "Open pendency", "bool", total=COUNT_TRUE, default=False),
            Col("has_discrepancy", "Discrepancy", "bool", total=COUNT_TRUE, default=False),
            Col("has_hazard", "Hazard", "bool", total=COUNT_TRUE, default=False),
            Col("has_rejections", "Rejections", "bool", total=COUNT_TRUE, default=False),
            Col("closed_at", "Closed", "datetime", default=False),
            Col("closure_type", "Closure type", "code", default=False),
        ),
        filters=(
            *_date_range(_local_date("g.created_at"), "GS date"),
            Filt("party", "Party", "text", expr="pa.name", op="ilike"),
            Filt("state", "State", "uuid", expr="g.state_id", lookup="states"),
            Filt("station", "Station", "uuid", expr="g.station_id", lookup="stations"),
            Filt(
                "category", "Category", "enum", expr="g.category_code", option_set="RETURN_CATEGORY"
            ),
            Filt("status", "Status", "enum", expr="g.status", choices=GS_STATUSES),
        ),
    ),
    # R-04 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-04",
        requires=(("unboxing", "view"),),
        sql=sql.R04,
        owner_expr="g.created_by",
        default_sort=("gs_date", "desc"),
        tiebreak="gs_no",
        hidden=("gs_id",),
        columns=(
            Col("gs_no", "GS No.", card=1, link=_GS_LINK),
            Col("gs_date", "Date", "date"),
            Col("party_name", "Party", default=False),
            Col("status", "Status", "code"),
            Col("gate_documents", "Gate documents", default=False),  # AMD-04
            Col("missing_documentation", "Missing docs", "bool", total=COUNT_TRUE),
            Col("videos", "Videos", "int", total=SUM),
            Col("doc_photos", "Document photos", "int", total=SUM),
            Col("docs_classified", "Documents classified", "int", total=SUM, default=False),
            Col("missing_doc_exception", "Missing-doc exception", "code", default=False),
            Col("evidence_complete", "Evidence complete", "bool", total=COUNT_TRUE, card=2),
            Col("unboxing_started_at", "Unboxing started", "datetime", default=False),
            Col("evidence_completed_at", "Step-2 complete", "datetime", default=False),
            Col("h_gate_to_step2", "Gate → Step-2 (h)", "hours", total=AVG),
            Col("h_step2", "Step-2 duration (h)", "hours", total=AVG),
        ),
        filters=(
            *_date_range(_local_date("g.created_at"), "GS date"),
            Filt("status", "Status", "enum", expr="g.status", choices=GS_STATUSES),
            Filt("evidence_complete", "Evidence complete", "bool", mode="outer"),
            Filt("missing_documentation", "Missing docs", "bool", expr="g.missing_documentation"),
        ),
    ),
    # R-05 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-05",
        requires=(("inspection", "view"),),
        sql=sql.R05,
        owner_expr="i.inspected_by",
        default_sort=("category_code", "asc"),
        tiebreak="condition_code",
        columns=(
            Col("category_code", "Category", "code", card=1),
            Col("condition_code", "Condition code", "code", default=False),
            Col("condition_label", "Condition", card=2),
            Col("allowed_status", "Allowed", "code"),
            Col("system_behavior", "Handling", "code", default=False),
            Col("gs_count", "Goods slips", "int"),
            Col("lines", "Lines", "int", total=SUM),
            Col("qty", "Quantity", "int", total=SUM),
            Col("not_allowed_qty", "Not allowed", "int", total=SUM),
            Col("hazard_qty", "Hazard", "int", total=SUM),
        ),
        filters=(
            *_date_range(_local_date("i.inspected_at"), "Inspected"),
            Filt(
                "category",
                "Category",
                "enum",
                expr="coalesce(gi.category_code_snapshot, pc.code)",
                lookup="categories",
            ),
        ),
    ),
    # R-06 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-06",
        requires=(("inspection", "view"),),
        sql=sql.R06,
        owner_expr="r.created_by",
        default_sort=("rejected_on", "desc"),
        tiebreak="gs_no",
        hidden=("gs_id", "rejection_id"),
        columns=(
            Col("gs_no", "GS No.", card=1, link=_GS_LINK),
            Col("rejected_on", "Date", "date"),
            Col("party_name", "Party", default=False),
            Col("line_no", "Line", "int", default=False),
            Col("product_code", "Product code", default=False),
            Col("product_name", "Product"),
            Col("category_code", "Category", "code"),
            Col("condition_code", "Condition code", "code", default=False),
            Col("condition_label", "Condition", card=2),
            Col("qty", "Qty", "int", total=SUM),
            Col("reason", "Reason"),
            Col("disposition", "Disposition", "code"),
            Col("hazard", "Hazard", "bool", total=COUNT_TRUE),
            Col("current_location", "Now at"),
            Col("scrap_status", "Disposal", "code", default=False),
            Col("manifest_ref", "Manifest", default=False),
        ),
        filters=(
            *_date_range(_local_date("r.created_at"), "Rejected"),
            Filt("hazard", "Hazard only", "bool", expr="r.hazard"),
            Filt(
                "disposition",
                "Disposition",
                "enum",
                expr="r.disposition",
                choices=(
                    "HOLD_PARTY_RETURN",
                    "HAZARD_QUARANTINE",
                    "TO_SPARE_PARTS",
                    "RECORDED_REJECT",
                ),
            ),
            Filt(
                "category",
                "Category",
                "enum",
                expr="coalesce(gi.category_code_snapshot, pc.code)",
                lookup="categories",
            ),
        ),
    ),
    # R-07 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-07",
        max_span_days=366,
        requires=(("container_audit", "view"),),
        sql=sql.R07,
        owner_expr=None,
        default_sort=("audit_date", "desc"),
        tiebreak="audit_date",
        columns=(
            Col("audit_date", "Date", "date", card=1),
            Col("status", "Status", "code", card=2),
            Col("recorded", "Recorded", "bool", total=COUNT_TRUE, default=False),
            Col("on_time", "Confirmed on time", "bool", total=COUNT_TRUE),
            Col("late", "Confirmed late", "bool", total=COUNT_TRUE),
            Col("confirmed_by_name", "Confirmed by"),
            Col("confirmed_at", "Confirmed at", "datetime", default=False),
            Col("containers_counted", "Containers", "int", total=SUM),
            Col("counted_qty", "Counted qty", "int", total=SUM),
            Col("sellable_packaging_qty", "Sellable packaging", "int", total=SUM),
            Col("late_reason", "Late reason", default=False),
            Col("remarks", "Remarks", default=False),
        ),
        filters=(
            *_param_range("Audit date"),
            Filt(
                "status",
                "Status",
                "enum",
                mode="outer",
                choices=("PENDING", "CONFIRMED", "LATE", "MISSED"),
            ),
        ),
    ),
    # R-08 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-08",
        requires=(("goods_slips", "view"),),
        sql=sql.R08,
        owner_expr="pd.opened_by",
        default_sort=("age_days", "desc"),
        tiebreak="gs_no",
        hidden=("gs_id", "pendency_id"),
        columns=(
            Col("gs_no", "GS No.", card=1, link=_GS_LINK),
            Col("party_name", "Party", default=False),
            Col("line_no", "Line", "int", default=False),
            Col("product_name", "Product"),
            Col("product_code", "Product code", default=False),
            Col("qty", "Qty", "int", total=SUM),
            Col("reason", "Reason"),
            Col("sent_to", "Sent to"),
            Col("blocks_gs", "Blocks GS", "bool", total=COUNT_TRUE),
            Col("status", "Status", "code"),
            Col("opened_by_name", "Opened by", default=False),
            Col("opened_at", "Opened", "datetime"),
            Col("age_days", "Age (days)", "days", total=AVG, card=2),
            Col("ageing_bucket", "Ageing", "text"),
            Col("cleared_by_name", "Cleared by", default=False),
            Col("cleared_at", "Cleared", "datetime", default=False),
            Col("resolution_action", "Resolution", "code", default=False),
        ),
        filters=(
            Filt("status", "Status", "enum", expr="pd.status", choices=("OPEN", "CLEARED")),
            *_date_range(_local_date("pd.opened_at"), "Opened"),
            Filt("ageing_bucket", "Ageing", "enum", mode="outer", choices=AGEING_BUCKETS),
            Filt("blocks_gs", "Blocks GS", "bool", expr="pd.blocks_gs"),
        ),
    ),
    # R-09 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-09",
        requires=(("custody", "view"),),
        sql=sql.R09,
        owner_expr="t.initiated_by",
        default_sort=("initiated_at", "desc"),
        tiebreak="transfer_no",
        hidden=("transfer_id", "gs_id"),
        columns=(
            Col("transfer_no", "Transfer No.", card=1, link="/custody/transfers/{transfer_id}"),
            Col("gs_no", "GS No.", link=_GS_LINK),
            Col("purpose_code", "Purpose", "code", default=False),
            Col("from_location", "From"),
            Col("to_location", "To"),
            Col("status", "Status", "code", card=2),
            Col("initiated_by_name", "Initiated by", default=False),
            Col("initiated_at", "Initiated", "datetime"),
            Col("accepted_by_name", "Accepted by", default=False),
            Col("accepted_at", "Accepted", "datetime", default=False),
            Col("h_to_accept", "Hours to accept", "hours", total=AVG),
            Col("qty_sent", "Sent", "int", total=SUM),
            Col("qty_counted", "Counted", "int", total=SUM),
            Col("qty_accepted", "Accepted", "int", total=SUM),
            Col("qty_difference", "Counted - sent", "int", total=SUM),
            Col("had_discrepancy", "Discrepancy", "bool", total=COUNT_TRUE),
            Col("discrepancy_notes", "Discrepancy notes", default=False),
            Col("resolution_code", "Resolution", "code", default=False),
            Col("reconciliation_status", "Reconciliation", "code", default=False),
            Col("reconciled_at", "Reconciled", "datetime", default=False),
        ),
        filters=(
            *_date_range(_local_date("t.initiated_at"), "Initiated"),
            Filt("status", "Status", "enum", expr="t.status", choices=TRANSFER_STATUSES),
            Filt("had_discrepancy", "Discrepancies only", "bool", mode="outer"),
            Filt("from_location", "From", "uuid", expr="t.from_location_id", lookup="locations"),
            Filt("to_location", "To", "uuid", expr="t.to_location_id", lookup="locations"),
        ),
    ),
    # R-10 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-10",
        requires=(("servicing", "view"),),
        sql=sql.R10,
        owner_expr="te.profile_id",
        default_sort=("pieces_received", "desc"),
        tiebreak="technician_name",
        hidden=("technician_id",),
        columns=(
            Col("technician_name", "Technician", card=1),
            Col("batches", "Batches", "int", total=SUM),
            Col("pieces_allotted", "Allotted", "int", total=SUM),
            Col("pieces_received", "Serviced", "int", total=SUM, card=2),
            Col("pieces_checked", "Pieces checked", "int", total=SUM),
            Col("batteries_installed", "Batteries installed", "int", total=SUM),
            Col(
                "battery_replacement_rate",
                "Battery replacement %",
                "percent",
                total=Total("ratio", "batteries_installed", "pieces_checked"),
            ),
            Col("functional_good", "Good", "int", total=SUM),
            Col("functional_repaired", "Repaired", "int", total=SUM),
            Col("non_good", "Non-good", "int", total=SUM),
            Col("non_sellable", "Non-sellable", "int", total=SUM),
            Col("avg_turnaround_hours", "Avg turnaround (h)", "hours", total=AVG),
        ),
        filters=(
            *_param_range("Activity date"),
            Filt("technician", "Technician", "uuid", expr="te.id", lookup="technicians"),
        ),
    ),
    # R-11 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-11",
        requires=(("inventory", "view"), ("servicing", "view")),
        sql=sql.R11,
        owner_expr=None,
        default_sort=("battery_code", "asc"),
        tiebreak="battery_name",
        hidden=("battery_type_id",),
        columns=(
            Col("battery_code", "Battery type", card=1),
            Col("battery_name", "Name"),
            Col("pieces_checked", "Pieces checked", "int", total=SUM),
            Col("replaced_records", "Replacement entries", "int", total=SUM, default=False),
            Col("batteries_installed", "Installed", "int", total=SUM),
            Col("opening_qty", "Opening stock", "int", total=SUM),
            Col("received_qty", "Received", "int", total=SUM),
            Col("adjusted_qty", "Adjusted", "int", total=SUM),
            Col("consumed_qty", "Consumed (ledger)", "int", total=SUM),
            Col("closing_qty", "Closing stock", "int", total=SUM),
            Col("current_balance", "Current balance", "int", total=SUM, default=False),
            Col("installed_minus_consumed", "Installed - consumed", "int", total=SUM, card=2),
            Col("reconciled", "Reconciled", "bool", total=COUNT_TRUE),
        ),
        filters=(
            *_param_range("Movement date"),
            Filt("battery_type", "Battery type", "uuid", expr="bt.id", lookup="battery_types"),
        ),
    ),
    # R-12 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-12",
        requires=(("dismantling", "view"),),
        sql=sql.R12,
        owner_expr="rp.created_by",
        default_sort=("qty_recovered", "desc"),
        tiebreak="part_type",
        columns=(
            Col("part_type", "Part type", "code", card=1),
            Col("pcb_model", "PCB model"),
            Col("pcb_supplier", "PCB supplier"),
            Col("container_code", "Container"),
            Col("partition_code", "Partition", default=False),
            Col("batches", "Batches", "int"),
            Col("qty_recovered", "Recovered qty", "int", total=SUM, card=2),
            Col("first_recovered_at", "First", "datetime", default=False),
            Col("last_recovered_at", "Last", "datetime", default=False),
        ),
        filters=(
            *_date_range(_local_date("rp.created_at"), "Recovered"),
            Filt(
                "part_type",
                "Part type",
                "enum",
                expr="rp.part_type",
                option_set="RECOVERABLE_PART_TYPE",
            ),
            Filt(
                "supplier",
                "PCB supplier",
                "uuid",
                expr="rp.pcb_supplier_id",
                lookup="pcb_suppliers",
            ),
        ),
    ),
    # R-13 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-13",
        requires=(("inventory", "view"),),
        sql=sql.R13,
        owner_expr=None,
        default_sort=("location_code", "asc"),
        tiebreak="item_code",
        hidden=("location_id",),
        columns=(
            Col("location_code", "Location", card=1),
            Col("location_name", "Location name", default=False),
            Col("location_class", "Class", "code", default=False),
            Col("custodian", "Custodian"),
            Col("condition_class", "Condition", "code"),
            Col("item_kind", "Kind", "code", default=False),
            Col("item_code", "Item"),
            Col("item_name", "Item name"),
            Col("lots", "Lots", "int", total=SUM, default=False),
            Col("gs_count", "Goods slips", "int", default=False),
            Col("qty", "Quantity", "int", total=SUM, card=2),
        ),
        filters=(
            Filt("as_on", "As on", "date", mode="param", default="today"),
            Filt("location", "Location", "uuid", expr="il.id", lookup="locations"),
            Filt(
                "location_class",
                "Location class",
                "enum",
                expr="il.location_class",
                choices=LOCATION_CLASSES,
            ),
            Filt(
                "condition_class",
                "Condition",
                "enum",
                expr="l.condition_class",
                choices=CONDITION_CLASSES,
            ),
            Filt("item_kind", "Item kind", "enum", expr="si.item_kind", choices=ITEM_KINDS),
            Filt(
                "include_terminal",
                "Include dispatched / credited / disposed",
                "bool",
                mode="param",
                default="false",
            ),
        ),
    ),
    # R-14 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-14",
        requires=(("inventory", "view"),),
        sql=sql.R14,
        owner_expr=None,
        default_sort=("check_code", "asc"),
        tiebreak="detail",
        hidden=("gs_id",),
        columns=(
            Col("check_code", "Check", card=1),
            Col("check_label", "Description", card=2),
            Col("gs_no", "GS No.", link=_GS_LINK),
            Col("line_no", "Line", "int"),
            Col("lot_ref", "Lot", default=False),
            Col("location_code", "Location"),
            Col("expected_qty", "Expected", "int", total=SUM),
            Col("actual_qty", "Actual", "int", total=SUM),
            Col("difference", "Difference", "int", total=SUM),
            Col("detail", "Detail"),
        ),
        filters=(Filt("check_code", "Check", "enum", expr="x.check_code", choices=RECON_CHECKS),),
    ),
    # R-15 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-15",
        requires=(("inventory", "view"),),
        sql=sql.R15,
        owner_expr="u.done_by_id",
        default_sort=("doc_at", "desc"),
        tiebreak="doc_no",
        hidden=("doc_id", "gs_id", "done_by_id"),
        columns=(
            Col("doc_no", "Document No.", card=1),
            Col("doc_kind", "Kind", "code"),
            Col("doc_type", "Type", "code"),
            Col("doc_date", "Date", "date"),
            Col("doc_at", "Time", "datetime", default=False),
            Col("gs_nos", "GS No.", link=_GS_LINK),
            Col("from_location", "From"),
            Col("to_location", "To"),
            Col("lines", "Lines", "int", total=SUM, default=False),
            Col("qty", "Qty", "int", total=SUM, card=2),
            Col("status", "Status", "code"),
            Col("done_by_name", "By"),
            Col("acknowledged_by_name", "Acknowledged by", default=False),
            Col("acknowledged_at", "Acknowledged", "datetime", default=False),
            Col("transporter", "Transporter", default=False),
            Col("docket_or_vehicle", "Docket / vehicle", default=False),
            Col("ref_doc_no", "Reference doc", default=False),
        ),
        filters=(
            *_date_range("u.doc_date", "Date"),
            Filt(
                "doc_kind", "Kind", "enum", expr="u.doc_kind", choices=("STORE_ISSUE", "DISPATCH")
            ),
            Filt("gs_no", "GS No.", "text", expr="u.gs_nos", op="ilike"),
        ),
    ),
    # R-16 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-16",
        requires=(("credit_notes", "view"),),
        sql=sql.R16,
        owner_expr="c.created_by",
        default_sort=("voucher_date", "desc"),
        tiebreak="gs_no",
        hidden=("cn_id", "gs_id"),
        columns=(
            Col("voucher_no", "CN / JV No.", card=1, link="/credit-notes/{cn_id}"),
            Col("voucher_date", "Date", "date"),
            Col("gs_no", "GS No.", link=_GS_LINK),
            Col("party_name", "Party"),
            Col("party_gstin", "Party GSTIN", default=False),
            Col("cn_type_code", "Type", "code"),
            Col("status", "Status", "code"),
            Col("party_doc_code", "Party document", "code"),
            Col("party_doc_no", "Party doc no.", default=False),
            Col("party_doc_date", "Party doc date", "date", default=False),
            Col("party_doc_amount", "Party doc amount", "money", total=SUM, default=False),
            Col("gst_portal_code", "GST portal", "code"),
            Col("gst_return_type", "Return", default=False),
            Col("gst_return_period", "Return period", default=False),
            Col("lines", "Lines", "int", total=SUM, default=False),
            Col("qty", "Qty", "int", total=SUM),
            Col("taxable_value", "Taxable", "money", total=SUM),
            Col("cgst_amount", "CGST", "money", total=SUM, default=False),
            Col("sgst_amount", "SGST", "money", total=SUM, default=False),
            Col("igst_amount", "IGST", "money", total=SUM, default=False),
            Col("total_value", "Total", "money", total=SUM, card=2),
            Col("rate_sources", "Rate sources", "code"),
            Col("lines_rate_verified", "Lines rate-verified", "int", total=SUM, default=False),
            Col("notified", "Party notified", "bool", total=COUNT_TRUE),
            Col("notified_at", "Notified at", "datetime", default=False),
            Col("notification_channel", "Channel", "code", default=False),
            Col("issued_by_name", "Issued by", default=False),
            Col("issued_at", "Issued at", "datetime", default=False),
        ),
        filters=(
            *_date_range(
                "coalesce(c.cn_date, c.jv_date, (c.created_at at time zone :tz)::date)",
                "Voucher date",
            ),
            Filt("cn_type", "Type", "enum", expr="c.cn_type_code", option_set="CN_TYPE"),
            Filt(
                "status",
                "Status",
                "enum",
                expr="c.status",
                choices=("DRAFT", "VERIFIED", "ISSUED", "CANCELLED"),
            ),
            Filt(
                "gst_portal",
                "GST portal",
                "enum",
                expr="c.gst_portal_code",
                option_set="GST_PORTAL_VERIFICATION",
            ),
            Filt("notified", "Party notified", "bool", mode="outer"),
        ),
    ),
    # R-17 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-17",
        requires=(("credit_notes", "view"),),
        sql=sql.R17,
        owner_expr="d.decision_by",
        default_sort=("days_total", "desc"),
        tiebreak="gs_no",
        hidden=("gs_id", "cn_id"),
        columns=(
            Col("gs_no", "GS No.", card=1, link=_GS_LINK),
            Col("party_name", "Party", default=False),
            Col("stage", "Stage", "code", card=2),
            Col("decision_at", "CN decision", "datetime"),
            Col("voucher_no", "CN / JV No.", link="/credit-notes/{cn_id}"),
            Col("cn_type_code", "Type", "code", default=False),
            Col("cn_status", "CN status", "code", default=False),
            Col("issued_at", "Issued", "datetime", default=False),
            Col("notified_at", "Notified", "datetime", default=False),
            Col("days_decision_to_issue", "Decision → issue (days)", "days", total=AVG),
            Col("days_issue_to_notification", "Issue → notification (days)", "days", total=AVG),
            Col("days_total", "Decision → notification (days)", "days", total=AVG),
            Col("days_in_stage", "Days in stage", "days", total=MAX),
        ),
        filters=(
            *_date_range(_local_date("d.decision_at"), "Decision"),
            Filt("stage", "Stage", "enum", expr="st.stage", choices=CN_STAGES),
        ),
    ),
    # R-18 -----------------------------------------------------------------------------------------
    ReportDef(
        code="R-18",
        requires=(("audit", "view"),),
        sql=sql.R18,
        owner_expr="e.user_id",
        default_sort=("actions", "desc"),
        tiebreak="user_name",
        hidden=("user_id",),
        columns=(
            Col("user_name", "User", card=1),
            Col("step_label", "Step"),
            Col("step_code", "Step code", "code", default=False),
            Col("action_code", "Action", "code"),
            Col("actions", "Actions", "int", total=SUM, card=2),
            Col("gs_count", "Goods slips", "int", default=False),
            Col("avg_handling_hours", "Avg handling (h)", "hours", total=AVG),
            Col("max_handling_hours", "Max handling (h)", "hours", total=MAX, default=False),
            Col("first_action_at", "First action", "datetime", default=False),
            Col("last_action_at", "Last action", "datetime"),
        ),
        filters=(
            *_param_range("Action date"),
            Filt("user", "User", "text", mode="outer", expr="user_name", op="ilike"),
            Filt("step", "Step", "enum", expr="e.step_code", lookup="steps"),
            Filt("action", "Action", "enum", expr="e.action_code", choices=ACTION_CODES),
        ),
    ),
)

REGISTRY: dict[str, ReportDef] = {r.code: r for r in REPORTS}
RESERVED_PARAMS = frozenset({"page", "page_size", "sort", "dir", "columns", "format"})
