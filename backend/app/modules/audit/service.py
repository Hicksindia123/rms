"""Service for Audit Explorer, Unified GS Activity Timeline, and User Activity (P4-04)."""

from __future__ import annotations

import csv
import io
from collections.abc import Generator
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from app.core.db import UnitOfWork
from app.core.errors import NotFound, PermissionDenied
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.audit import repository as repo
from app.modules.audit.schemas import (
    AuditLogResponse,
    AuditLogRow,
    FieldDiff,
    GsActivityItem,
    GsActivityResponse,
    UserActivityItem,
    UserActivityResponse,
)

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_csv_cell(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    if s.startswith(_FORMULA_PREFIXES):
        return "'" + s
    return s


# Human-readable dictionary mapping database fields to readable labels (P4-04)
FIELD_LABELS: dict[str, str] = {
    "status": "GS Status",
    "category_code": "Product Category",
    "party_id": "Party",
    "delivery_mode_code": "Delivery Mode",
    "courier_name": "Courier Name",
    "docket_no": "Docket Number",
    "vehicle_no": "Vehicle Number",
    "gate_doc_no": "Gate Document Number",
    "gate_doc_date": "Gate Document Date",
    "gate_doc_remarks": "Gate Document Remarks",
    "has_hazard": "Hazard Flag",
    "has_discrepancy": "Discrepancy Flag",
    "has_rejections": "Rejections Flag",
    "has_open_pendency": "Open Pendency Flag",
    "closure_type": "Closure Type",
    "closed_at": "Closed Timestamp",
    "cn_no": "Credit Note Number",
    "jv_no": "Journal Voucher Number",
    "party_doc_no": "Party Document Number",
    "total_value": "Total Valuation",
    "action_code": "RM Decision Code",
    "approved_qty": "Approved Quantity",
    "battery_check": "Battery Check Outcome",
    "batteries_installed": "Batteries Installed",
    "pieces_checked": "Pieces Checked",
    "condition_class": "Condition Class",
    "storage_method_code": "Storage Method",
    "scrap_reason": "Scrap Reason",
    "hazard_manifest_no": "Hazardous Manifest Number",
}


def humanize_field(field_name: str) -> str:
    if field_name in FIELD_LABELS:
        return FIELD_LABELS[field_name]
    return field_name.replace("_", " ").strip().title()


class AuditService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_audit_log(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        *,
        table_name: str | None = None,
        row_id: str | None = None,
        actor_id: UUID | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        request_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditLogResponse:
        # Require audit.view or super admin
        if not user.is_super_admin and not perms.allows("audit", "view"):
            raise PermissionDenied(
                "You do not have permission to view the audit log", code="AUDIT_VIEW_DENIED"
            )

        with self._uow.transaction(user.id) as session:
            rows, total = repo.query_audit_log(
                session,
                table_name=table_name,
                row_id=row_id,
                actor_id=actor_id,
                action=action,
                date_from=date_from,
                date_to=date_to,
                request_id=request_id,
                limit=limit,
                offset=offset,
            )
            items = [AuditLogRow.model_validate(r) for r in rows]
            return AuditLogResponse(items=items, total=total, limit=limit, offset=offset)

    def get_distinct_tables(self, user: CurrentUser, perms: EffectivePermissions) -> list[str]:
        if not user.is_super_admin and not perms.allows("audit", "view"):
            raise PermissionDenied(
                "You do not have permission to view audit tables", code="AUDIT_VIEW_DENIED"
            )

        with self._uow.transaction(user.id) as session:
            return repo.get_distinct_audit_tables(session)

    def export_audit_log_csv(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        *,
        table_name: str | None = None,
        row_id: str | None = None,
        actor_id: UUID | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        request_id: str | None = None,
    ) -> Generator[str, None, None]:
        if not user.is_super_admin and not perms.allows("audit", "export"):
            raise PermissionDenied(
                "You do not have permission to export the audit log", code="AUDIT_EXPORT_DENIED"
            )

        with self._uow.transaction(user.id) as session:
            rows, _ = repo.query_audit_log(
                session,
                table_name=table_name,
                row_id=row_id,
                actor_id=actor_id,
                action=action,
                date_from=date_from,
                date_to=date_to,
                request_id=request_id,
                limit=50000,
                offset=0,
            )

            # Record EXPORT activity
            repo.insert_user_activity(
                session,
                user_id=user.id,
                activity_type="EXPORT",
                entity_type="audit_log",
                details={"exported_count": len(rows)},
            )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "Timestamp (UTC)",
                "Table Name",
                "Row ID",
                "Action",
                "Actor Name",
                "Actor Email",
                "Request ID",
                "Changed Fields",
                "Reason",
            ]
        )
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for r in rows:
            writer.writerow(
                [
                    _safe_csv_cell(r["id"]),
                    _safe_csv_cell(r["at"].isoformat() if r["at"] else ""),
                    _safe_csv_cell(r["table_name"]),
                    _safe_csv_cell(r["row_id"]),
                    _safe_csv_cell(r["action"]),
                    _safe_csv_cell(r["actor_name"]),
                    _safe_csv_cell(r["actor_email"]),
                    _safe_csv_cell(r["request_id"]),
                    _safe_csv_cell(", ".join(r["changed_fields"] or [])),
                    _safe_csv_cell(r["reason"]),
                ]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    def get_gs_activity_timeline(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        *,
        category_filter: str | None = None,
    ) -> GsActivityResponse:
        # Require goods_slips.view
        if not user.is_super_admin and not perms.allows("goods_slips", "view"):
            raise PermissionDenied(
                "You do not have permission to view Goods Slip activity", code="GS_VIEW_DENIED"
            )

        items: list[GsActivityItem] = []

        with self._uow.transaction(user.id) as session:
            # 1. Fetch Goods Slip header to get gs_no
            gs = (
                session.execute(
                    text("select gs_no from public.goods_slips where id = :gid"),
                    {"gid": gs_id},
                )
                .mappings()
                .one_or_none()
            )
            if not gs:
                raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
            gs_no = gs["gs_no"]

            # 2. Status History (Category: STATUS)
            if not category_filter or category_filter.upper() == "STATUS":
                status_rows = repo.get_gs_status_history(session, gs_id)
                for r in status_rows:
                    from_s = r["from_status"] or "Inward Start"
                    to_s = r["to_status"]
                    title = f"Status Changed: {from_s} → {to_s}"
                    desc = f"Transitioned to {to_s}."
                    if r["transition_reason"]:
                        desc += f" Reason: {r['transition_reason']}"

                    diffs = [
                        FieldDiff(
                            field="status",
                            label="GS Status",
                            old_value=r["from_status"],
                            new_value=r["to_status"],
                        )
                    ]
                    items.append(
                        GsActivityItem(
                            id=f"status-{r['id']}",
                            timestamp=r["at"],
                            category="STATUS",
                            action="STATUS_TRANSITION",
                            title=title,
                            description=desc,
                            actor_id=r["actor_id"],
                            actor_name=r["actor_name"],
                            diffs=diffs,
                            metadata={"from_status": r["from_status"], "to_status": r["to_status"]},
                        )
                    )

            # 3. Stock Movements (Category: STOCK)
            if not category_filter or category_filter.upper() == "STOCK":
                movement_rows = repo.get_gs_stock_movements(session, gs_id)
                for r in movement_rows:
                    mtype = r["movement_type"]
                    qty = r["qty"]
                    from_loc = r["from_location_name"] or "Initial"
                    to_loc = r["to_location_name"] or "Disposition"
                    title = f"Stock Movement: {mtype} ({qty} pcs)"
                    desc = f"Moved {qty} pcs from {from_loc} to {to_loc} (Lot)."

                    items.append(
                        GsActivityItem(
                            id=f"movement-{r['id']}",
                            timestamp=r["at"],
                            category="STOCK",
                            action=mtype,
                            title=title,
                            description=desc,
                            actor_id=r["actor_id"],
                            actor_name=r["actor_name"],
                            metadata={
                                "movement_type": mtype,
                                "qty": qty,
                                "from_location": from_loc,
                                "to_location": to_loc,
                                "lot_id": str(r.get("lot_id")),
                            },
                        )
                    )

            # 4. Notifications (Category: NOTIFICATION)
            if not category_filter or category_filter.upper() == "NOTIFICATION":
                notif_rows = repo.get_gs_notification_events(session, gs_id)
                for r in notif_rows:
                    payload = dict(r["payload"] or {})
                    title = payload.get("title") or f"Notification: {r['event_type']}"
                    desc = payload.get("body") or f"Domain event {r['event_type']} published."

                    items.append(
                        GsActivityItem(
                            id=f"notif-{r['id']}",
                            timestamp=r["at"],
                            category="NOTIFICATION",
                            action=r["event_type"],
                            title=title,
                            description=desc,
                            actor_id=r["actor_id"],
                            actor_name=r["actor_name"],
                            metadata={"event_type": r["event_type"], "priority": r["priority"]},
                        )
                    )

            # 5. Audit Log (Category: DOCUMENT, COMMERCIAL, AUDIT)
            audit_rows = repo.get_gs_audit_entries(session, gs_id)
            for r in audit_rows:
                tname = r["table_name"]
                action = r["action"]
                old_val = r["old_values"] or {}
                new_val = r["new_values"] or {}
                changed = r["changed_fields"] or []

                # Categorize by table
                if tname in ("gs_documents", "unboxing_evidence"):
                    cat = "DOCUMENT"
                elif tname in ("credit_notes", "rm_actions"):
                    cat = "COMMERCIAL"
                else:
                    cat = "AUDIT"

                if category_filter and category_filter.upper() != cat:
                    continue

                # Build readable diffs
                audit_diffs: list[FieldDiff] = []
                for field in changed:
                    if field in ("updated_at", "updated_by", "created_at", "created_by"):
                        continue
                    audit_diffs.append(
                        FieldDiff(
                            field=field,
                            label=humanize_field(field),
                            old_value=old_val.get(field),
                            new_value=new_val.get(field),
                        )
                    )

                title = f"{action} on {humanize_field(tname)}"
                desc = f"Record in {tname} was {action.lower()}ed."
                if r["reason"]:
                    desc += f" Reason: {r['reason']}"
                elif audit_diffs:
                    field_names = ", ".join(d.label for d in audit_diffs[:3])
                    desc += f" Changed {field_names}."

                items.append(
                    GsActivityItem(
                        id=f"audit-{r['id']}",
                        timestamp=r["at"],
                        category=cast(Any, cat),
                        action=action,
                        title=title,
                        description=desc,
                        actor_id=r["actor_id"],
                        actor_name=r["actor_name"],
                        request_id=r["request_id"],
                        diffs=audit_diffs,
                        metadata={"table": tname, "row_id": r["row_id"]},
                    )
                )

        # Sort all items chronologically descending
        items.sort(key=lambda x: x.timestamp, reverse=True)

        return GsActivityResponse(
            gs_id=gs_id,
            gs_no=gs_no,
            total=len(items),
            items=items,
        )

    def list_user_activity(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        target_user_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> UserActivityResponse:
        # Users can view their own activity; viewing others requires users.view or super admin
        is_self = target_user_id == user.id
        if not is_self and not user.is_super_admin and not perms.allows("users", "view"):
            raise PermissionDenied(
                "You cannot view activity for other users", code="USER_ACTIVITY_DENIED"
            )

        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_user_activity(session, target_user_id, limit, offset)
            items = [UserActivityItem.model_validate(r) for r in rows]
            return UserActivityResponse(user_id=target_user_id, total=total, items=items)
