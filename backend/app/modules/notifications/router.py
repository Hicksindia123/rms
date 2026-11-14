"""Notifications HTTP API (prompts P2-03, P4-03).

* `/notifications/*` — the signed-in user's own notifications and email preferences.
* `/admin/notifications/*` — rules, event catalogue, email templates, escalation rules, delivery
  log and the read-only SMTP status (`notifications.configure`).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query, Response, status

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser, CurrentUserDep
from app.modules.notifications.admin_service import NotificationAdminService
from app.modules.notifications.schemas import (
    EVENT_CODE,
    AdminLookupsOut,
    DeliveryLogOut,
    EmailStatusOut,
    EscalationRuleIn,
    EscalationRuleOut,
    EventTypeIn,
    EventTypeOut,
    NotificationListOut,
    PreferencesIn,
    PreferencesOut,
    ReasonIn,
    RuleIn,
    RuleOut,
    TemplateIn,
    TemplateOut,
    TemplatePreviewIn,
    TemplatePreviewOut,
)
from app.modules.notifications.service import NotificationService, email_status_out

router = APIRouter(prefix="/notifications", tags=["notifications"])
admin_router = APIRouter(prefix="/admin/notifications", tags=["notifications-admin"])

ConfigureUser = Annotated[CurrentUser, Depends(require("notifications", "configure"))]
EventCodePath = Annotated[str, Path(pattern=EVENT_CODE)]


def get_service(uow: UowDep) -> NotificationService:
    return NotificationService(uow)


def get_admin_service(uow: UowDep) -> NotificationAdminService:
    return NotificationAdminService(uow)


ServiceDep = Annotated[NotificationService, Depends(get_service)]
AdminServiceDep = Annotated[NotificationAdminService, Depends(get_admin_service)]


# --- own notifications ------------------------------------------------------------------------


@router.get("/mine", response_model=NotificationListOut)
def my_notifications(
    user: CurrentUserDep,
    service: ServiceDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    event_type: Annotated[str | None, Query(pattern=EVENT_CODE)] = None,
    priority: Literal["LOW", "NORMAL", "HIGH"] | None = None,
) -> NotificationListOut:
    return service.mine(
        user,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
        event_type=event_type,
        priority=priority,
    )


@router.post("/{notification_id}/read")
def mark_read(notification_id: UUID, user: CurrentUserDep, service: ServiceDep) -> dict[str, int]:
    return {"updated": service.mark_read(user, notification_id)}


@router.post("/read-all")
def mark_all_read(user: CurrentUserDep, service: ServiceDep) -> dict[str, int]:
    return {"updated": service.mark_read(user, None)}


@router.get("/preferences", response_model=PreferencesOut)
def my_preferences(user: CurrentUserDep, service: ServiceDep) -> PreferencesOut:
    return service.preferences(user)


@router.put("/preferences", response_model=PreferencesOut)
def update_preferences(
    payload: PreferencesIn, user: CurrentUserDep, service: ServiceDep
) -> PreferencesOut:
    """Email opt-out per event (mandatory events cannot be switched off) and digest mode."""
    return service.update_preferences(user, payload)


# --- admin ------------------------------------------------------------------------------------


@admin_router.get("/email-status", response_model=EmailStatusOut)
def email_status(user: ConfigureUser) -> EmailStatusOut:
    """Read-only SMTP status from the backend env. Credentials are never returned."""
    return email_status_out()


@admin_router.get("/lookups", response_model=AdminLookupsOut)
def lookups(user: ConfigureUser, service: AdminServiceDep) -> AdminLookupsOut:
    """Roles, active users and workflow steps for the rule and escalation editors."""
    return service.lookups(user)


@admin_router.get("/event-types", response_model=list[EventTypeOut])
def event_types(user: ConfigureUser, service: AdminServiceDep) -> list[EventTypeOut]:
    return service.event_types(user)


@admin_router.put("/event-types/{code}", response_model=EventTypeOut)
def update_event_type(
    code: EventCodePath, payload: EventTypeIn, user: ConfigureUser, service: AdminServiceDep
) -> EventTypeOut:
    return service.update_event_type(user, code, payload)


@admin_router.get("/rules", response_model=list[RuleOut])
def rules(
    user: ConfigureUser,
    service: AdminServiceDep,
    event_type: Annotated[str | None, Query(pattern=EVENT_CODE)] = None,
) -> list[RuleOut]:
    return service.rules(user, event_type)


@admin_router.post("/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(payload: RuleIn, user: ConfigureUser, service: AdminServiceDep) -> RuleOut:
    return service.create_rule(user, payload)


@admin_router.put("/rules/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: UUID, payload: RuleIn, user: ConfigureUser, service: AdminServiceDep
) -> RuleOut:
    return service.update_rule(user, rule_id, payload)


@admin_router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: UUID,
    user: ConfigureUser,
    service: AdminServiceDep,
    payload: Annotated[ReasonIn | None, Body()] = None,
) -> Response:
    service.delete_rule(user, rule_id, payload.reason if payload else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/templates", response_model=list[TemplateOut])
def templates(user: ConfigureUser, service: AdminServiceDep) -> list[TemplateOut]:
    return service.templates(user)


@admin_router.get("/templates/{event_type}/versions", response_model=list[TemplateOut])
def template_versions(
    event_type: EventCodePath, user: ConfigureUser, service: AdminServiceDep
) -> list[TemplateOut]:
    return service.template_versions(user, event_type)


@admin_router.put("/templates/{event_type}", response_model=TemplateOut)
def save_template(
    event_type: EventCodePath, payload: TemplateIn, user: ConfigureUser, service: AdminServiceDep
) -> TemplateOut:
    """Publish a new template version (the previous one is retired)."""
    return service.save_template(user, event_type, payload)


@admin_router.post("/templates/preview", response_model=TemplatePreviewOut)
def preview_template(
    payload: TemplatePreviewIn, user: ConfigureUser, service: AdminServiceDep
) -> TemplatePreviewOut:
    return service.preview(user, payload)


@admin_router.get("/escalation-rules", response_model=list[EscalationRuleOut])
def escalation_rules(user: ConfigureUser, service: AdminServiceDep) -> list[EscalationRuleOut]:
    return service.escalation_rules(user)


@admin_router.post(
    "/escalation-rules", response_model=EscalationRuleOut, status_code=status.HTTP_201_CREATED
)
def create_escalation_rule(
    payload: EscalationRuleIn, user: ConfigureUser, service: AdminServiceDep
) -> EscalationRuleOut:
    return service.create_escalation_rule(user, payload)


@admin_router.put("/escalation-rules/{rule_id}", response_model=EscalationRuleOut)
def update_escalation_rule(
    rule_id: UUID, payload: EscalationRuleIn, user: ConfigureUser, service: AdminServiceDep
) -> EscalationRuleOut:
    return service.update_escalation_rule(user, rule_id, payload)


@admin_router.delete("/escalation-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_escalation_rule(
    rule_id: UUID,
    user: ConfigureUser,
    service: AdminServiceDep,
    payload: Annotated[ReasonIn | None, Body()] = None,
) -> Response:
    service.delete_escalation_rule(user, rule_id, payload.reason if payload else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/deliveries", response_model=DeliveryLogOut)
def deliveries(
    user: ConfigureUser,
    service: AdminServiceDep,
    status_: Annotated[
        Literal["PENDING", "DIGEST", "SENT", "SKIPPED", "FAILED"] | None, Query(alias="status")
    ] = None,
    channel: Literal["IN_APP", "EMAIL"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> DeliveryLogOut:
    return service.deliveries(user, status=status_, channel=channel, limit=limit, offset=offset)
