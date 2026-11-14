"""Notification administration (prompt P4-03; master plan §10 "Notifications").

Every save writes config_change_log with before/after and the optional reason (§10).
SMTP settings are read-only here: they live in the backend env (rule i).
"""

from __future__ import annotations

import string
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import CurrentUser
from app.modules.notifications import repository as repo
from app.modules.notifications.email import PLACEHOLDERS, SAMPLE_CONTEXT, render
from app.modules.notifications.schemas import (
    AdminLookupsOut,
    DeliveryLogOut,
    DeliveryOut,
    EscalationRuleIn,
    EscalationRuleOut,
    EventTypeIn,
    EventTypeOut,
    LookupRole,
    LookupStep,
    LookupUser,
    RuleIn,
    RuleOut,
    TemplateIn,
    TemplateOut,
    TemplatePreviewIn,
    TemplatePreviewOut,
)
from app.modules.notifications.service import email_status_out


def _placeholders_in(template: str) -> set[str]:
    names: set[str] = set()
    try:
        for _, field, _, _ in string.Formatter().parse(template):
            if field:
                names.add(field.split(".")[0].split("[")[0])
    except ValueError as exc:
        raise ValidationFailed(
            f"Template has an unbalanced brace: {exc}", code="TEMPLATE_SYNTAX"
        ) from exc
    return names


def _rule_out(row: dict[str, Any]) -> RuleOut:
    return RuleOut(
        **{
            **row,
            "recipient_role_codes": list(row["recipient_role_codes"] or []),
            "recipient_user_ids": list(row["recipient_user_ids"] or []),
            "channels": list(row["channels"] or []),
        }
    )


def _rule_snapshot(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = (
        "event_type",
        "name",
        "include_context_recipients",
        "include_step_assignees",
        "recipient_role_codes",
        "recipient_user_ids",
        "channels",
        "priority",
        "is_active",
    )
    return {k: row.get(k) for k in keys}


class NotificationAdminService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- event catalogue ----------------------------------------------------------------------

    def event_types(self, user: CurrentUser) -> list[EventTypeOut]:
        with self._uow.transaction(user.id) as session:
            return [EventTypeOut(**r) for r in repo.list_event_types(session)]

    def update_event_type(self, user: CurrentUser, code: str, payload: EventTypeIn) -> EventTypeOut:
        with self._uow.transaction(user.id) as session:
            before = repo.get_event_type(session, code, for_update=True)
            if before is None:
                raise NotFound("Notification event type not found")
            values = payload.model_dump(exclude={"reason"})
            values["label"] = values["label"].strip()
            repo.update_event_type(session, code, values)
            after = repo.get_event_type(session, code)
            repo.insert_config_change(
                session,
                entity_type="notification_event_type",
                entity_id=code,
                action="UPDATE",
                before=before,
                after=after,
                reason=payload.reason,
            )
            return EventTypeOut(**(after or {}))

    # --- rules --------------------------------------------------------------------------------

    def rules(self, user: CurrentUser, event_type: str | None) -> list[RuleOut]:
        with self._uow.transaction(user.id) as session:
            return [_rule_out(r) for r in repo.list_rules(session, event_type)]

    def create_rule(self, user: CurrentUser, payload: RuleIn) -> RuleOut:
        with self._uow.transaction(user.id) as session:
            values = self._validated_rule(session, payload)
            rule_id = repo.insert_rule(session, values)
            row = repo.get_rule(session, rule_id)
            repo.insert_config_change(
                session,
                entity_type="notification_rule",
                entity_id=str(rule_id),
                action="CREATE",
                before=None,
                after=_rule_snapshot(row),
                reason=payload.reason,
            )
            return _rule_out(row or {})

    def update_rule(self, user: CurrentUser, rule_id: UUID, payload: RuleIn) -> RuleOut:
        with self._uow.transaction(user.id) as session:
            before = repo.get_rule(session, rule_id, for_update=True)
            if before is None:
                raise NotFound("Notification rule not found")
            values = self._validated_rule(session, payload)
            repo.update_rule(session, rule_id, values)
            row = repo.get_rule(session, rule_id)
            repo.insert_config_change(
                session,
                entity_type="notification_rule",
                entity_id=str(rule_id),
                action="UPDATE",
                before=_rule_snapshot(before),
                after=_rule_snapshot(row),
                reason=payload.reason,
            )
            return _rule_out(row or {})

    def delete_rule(self, user: CurrentUser, rule_id: UUID, reason: str | None) -> None:
        with self._uow.transaction(user.id) as session:
            before = repo.get_rule(session, rule_id, for_update=True)
            if before is None:
                raise NotFound("Notification rule not found")
            repo.delete_rule(session, rule_id)
            repo.insert_config_change(
                session,
                entity_type="notification_rule",
                entity_id=str(rule_id),
                action="DELETE",
                before=_rule_snapshot(before),
                after=None,
                reason=reason,
            )

    def _validated_rule(self, session: Session, payload: RuleIn) -> dict[str, Any]:
        if repo.get_event_type(session, payload.event_type) is None:
            raise ValidationFailed(
                f"Unknown notification event {payload.event_type}", code="UNKNOWN_EVENT_TYPE"
            )
        if not (
            payload.include_context_recipients
            or payload.include_step_assignees
            or payload.recipient_role_codes
            or payload.recipient_user_ids
        ):
            raise ValidationFailed(
                "A rule needs at least one recipient source", code="RULE_WITHOUT_RECIPIENTS"
            )
        unknown_roles = sorted(
            set(payload.recipient_role_codes)
            - repo.existing_role_codes(session, payload.recipient_role_codes)
        )
        if unknown_roles:
            raise ValidationFailed(
                "Unknown role codes", code="UNKNOWN_ROLE", details={"roles": unknown_roles}
            )
        unknown_users = sorted(
            str(u)
            for u in set(payload.recipient_user_ids)
            - repo.existing_user_ids(session, payload.recipient_user_ids)
        )
        if unknown_users:
            raise ValidationFailed(
                "Unknown users", code="UNKNOWN_USER", details={"users": unknown_users}
            )
        values = payload.model_dump(exclude={"reason"})
        values["name"] = values["name"].strip()
        return values

    # --- templates ----------------------------------------------------------------------------

    def templates(self, user: CurrentUser) -> list[TemplateOut]:
        with self._uow.transaction(user.id) as session:
            return [TemplateOut(**r) for r in repo.list_published_templates(session)]

    def template_versions(self, user: CurrentUser, event_type: str) -> list[TemplateOut]:
        with self._uow.transaction(user.id) as session:
            if repo.get_event_type(session, event_type) is None:
                raise NotFound("Notification event type not found")
            return [TemplateOut(**r) for r in repo.template_versions(session, event_type)]

    def save_template(self, user: CurrentUser, event_type: str, payload: TemplateIn) -> TemplateOut:
        """Each save publishes a new version and retires the previous one (versioned, §10)."""
        self._check_placeholders(payload.subject, payload.body)
        with self._uow.transaction(user.id) as session:
            etype = repo.get_event_type(session, event_type)
            if etype is None:
                raise NotFound("Notification event type not found")
            current = repo.lock_published_template(session, event_type)
            if (
                current
                and current["subject"] == payload.subject
                and current["body"] == payload.body
            ):
                raise Conflict("The template is unchanged", code="TEMPLATE_UNCHANGED")
            if current:
                repo.retire_template(session, UUID(str(current["id"])))
            row = repo.insert_template(
                session,
                event_type=event_type,
                version_no=repo.max_template_version(session, event_type) + 1,
                subject=payload.subject,
                body=payload.body,
                reason=payload.reason,
            )
            repo.insert_config_change(
                session,
                entity_type="notification_template",
                entity_id=event_type,
                action="UPDATE",
                before={k: current[k] for k in ("version_no", "subject", "body")}
                if current
                else None,
                after={k: row[k] for k in ("version_no", "subject", "body")},
                reason=payload.reason,
            )
            return TemplateOut(**{**row, "event_label": etype["label"]})

    def preview(self, user: CurrentUser, payload: TemplatePreviewIn) -> TemplatePreviewOut:
        unknown = self._check_placeholders(payload.subject, payload.body, strict=False)
        with self._uow.transaction(user.id) as session:
            etype = repo.get_event_type(session, payload.event_type)
            if etype is None:
                raise NotFound("Notification event type not found")
            app_name = repo.get_setting(session, "app_name") or SAMPLE_CONTEXT["app_name"]
        ctx = {
            **SAMPLE_CONTEXT,
            "app_name": str(app_name),
            "event_label": str(etype["label"]),
            "event_type": payload.event_type,
            "priority": str(etype["default_priority"]),
        }
        return TemplatePreviewOut(
            subject=render(payload.subject, ctx),
            body=render(payload.body, ctx),
            placeholders=list(PLACEHOLDERS),
            unknown_placeholders=sorted(unknown),
        )

    @staticmethod
    def _check_placeholders(subject: str, body: str, *, strict: bool = True) -> set[str]:
        if "\n" in subject or "\r" in subject:
            raise ValidationFailed("The subject must be a single line", code="TEMPLATE_SUBJECT")
        unknown = (_placeholders_in(subject) | _placeholders_in(body)) - set(PLACEHOLDERS)
        if strict and unknown:
            raise ValidationFailed(
                "Unknown placeholders",
                code="TEMPLATE_PLACEHOLDER",
                details={"unknown": sorted(unknown), "allowed": list(PLACEHOLDERS)},
            )
        return unknown

    # --- escalation rules (DEC-30) -----------------------------------------------------------

    def escalation_rules(self, user: CurrentUser) -> list[EscalationRuleOut]:
        with self._uow.transaction(user.id) as session:
            return self._escalations_out(repo.list_escalation_rules(session))

    @staticmethod
    def _escalations_out(rows: list[dict[str, Any]]) -> list[EscalationRuleOut]:
        # Level = rank among the step's ACTIVE rules by after_hours (same as the worker); inactive
        # rules show the level they would take if switched on alone after the active ones.
        out: list[EscalationRuleOut] = []
        by_step: dict[Any, list[dict[str, Any]]] = {}
        for r in rows:
            by_step.setdefault(r["workflow_step_id"], []).append(r)
        for step_rows in by_step.values():
            ordered = sorted(
                step_rows, key=lambda r: (not r["is_active"], float(r["after_hours"]), str(r["id"]))
            )
            for i, r in enumerate(ordered, start=1):
                out.append(
                    EscalationRuleOut(
                        **{
                            **r,
                            "after_hours": float(r["after_hours"]),
                            "sla_hours": float(r["sla_hours"])
                            if r["sla_hours"] is not None
                            else None,
                            "level_no": i,
                        }
                    )
                )
        order = {r["id"]: i for i, r in enumerate(rows)}
        return sorted(out, key=lambda o: order[o.id])

    def create_escalation_rule(
        self, user: CurrentUser, payload: EscalationRuleIn
    ) -> EscalationRuleOut:
        with self._uow.transaction(user.id) as session:
            values = self._validated_escalation(session, payload)
            rule_id = repo.insert_escalation_rule(session, values)
            row = repo.get_escalation_rule(session, rule_id)
            repo.insert_config_change(
                session,
                entity_type="escalation_rule",
                entity_id=str(rule_id),
                action="CREATE",
                before=None,
                after=values,
                reason=payload.reason,
            )
            return self._one_escalation(session, row)

    def update_escalation_rule(
        self, user: CurrentUser, rule_id: UUID, payload: EscalationRuleIn
    ) -> EscalationRuleOut:
        with self._uow.transaction(user.id) as session:
            before = repo.get_escalation_rule(session, rule_id, for_update=True)
            if before is None:
                raise NotFound("Escalation rule not found")
            values = self._validated_escalation(session, payload)
            if values["step"] != before["workflow_step_id"] and repo.escalation_rule_used(
                session, rule_id
            ):
                raise Conflict(
                    "This escalation level has already fired; create a new rule for another step",
                    code="ESCALATION_RULE_USED",
                )
            repo.update_escalation_rule(session, rule_id, values)
            row = repo.get_escalation_rule(session, rule_id)
            repo.insert_config_change(
                session,
                entity_type="escalation_rule",
                entity_id=str(rule_id),
                action="UPDATE",
                before={
                    "step": before["workflow_step_id"],
                    "after": before["after_hours"],
                    "role": before["notify_role_id"],
                    "user": before["notify_user_id"],
                    "active": before["is_active"],
                },
                after=values,
                reason=payload.reason,
            )
            return self._one_escalation(session, row)

    def delete_escalation_rule(self, user: CurrentUser, rule_id: UUID, reason: str | None) -> None:
        with self._uow.transaction(user.id) as session:
            before = repo.get_escalation_rule(session, rule_id, for_update=True)
            if before is None:
                raise NotFound("Escalation rule not found")
            if repo.escalation_rule_used(session, rule_id):
                raise Conflict(
                    "This escalation level has already fired; deactivate it instead",
                    code="ESCALATION_RULE_USED",
                )
            repo.delete_escalation_rule(session, rule_id)
            repo.insert_config_change(
                session,
                entity_type="escalation_rule",
                entity_id=str(rule_id),
                action="DELETE",
                before={
                    k: before[k]
                    for k in (
                        "workflow_step_id",
                        "after_hours",
                        "notify_role_id",
                        "notify_user_id",
                        "is_active",
                    )
                },
                after=None,
                reason=reason,
            )

    def _one_escalation(self, session: Session, row: dict[str, Any] | None) -> EscalationRuleOut:
        if row is None:
            raise NotFound("Escalation rule not found")
        all_rows = repo.list_escalation_rules(session)
        return next(o for o in self._escalations_out(all_rows) if o.id == row["id"])

    def _validated_escalation(self, session: Session, payload: EscalationRuleIn) -> dict[str, Any]:
        if (payload.notify_role_code is None) == (payload.notify_user_id is None):
            raise ValidationFailed(
                "Choose exactly one escalation target: a role or a user",
                code="ESCALATION_TARGET",
            )
        if repo.workflow_step(session, payload.workflow_step_id) is None:
            raise ValidationFailed("Unknown workflow step", code="UNKNOWN_STEP")
        role_id = None
        if payload.notify_role_code:
            role_id = repo.role_id_by_code(session, payload.notify_role_code)
            if role_id is None:
                raise ValidationFailed("Unknown role", code="UNKNOWN_ROLE")
        if payload.notify_user_id and not repo.existing_user_ids(session, [payload.notify_user_id]):
            raise ValidationFailed("Unknown user", code="UNKNOWN_USER")
        return {
            "step": payload.workflow_step_id,
            "after": payload.after_hours,
            "role": role_id,
            "user": payload.notify_user_id,
            "active": payload.is_active,
        }

    # --- lookups ------------------------------------------------------------------------------

    def lookups(self, user: CurrentUser) -> AdminLookupsOut:
        with self._uow.transaction(user.id) as session:
            steps = [
                LookupStep(
                    **{
                        **r,
                        "sla_hours": None if r["sla_hours"] is None else float(r["sla_hours"]),
                    }
                )
                for r in repo.lookup_steps(session)
            ]
            return AdminLookupsOut(
                roles=[LookupRole(**r) for r in repo.lookup_roles(session)],
                users=[LookupUser(**r) for r in repo.lookup_users(session)],
                steps=steps,
            )

    # --- delivery log -------------------------------------------------------------------------

    def deliveries(
        self, user: CurrentUser, *, status: str | None, channel: str | None, limit: int, offset: int
    ) -> DeliveryLogOut:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_deliveries(
                session, status=status, channel=channel, limit=limit, offset=offset
            )
            return DeliveryLogOut(
                items=[DeliveryOut(**r) for r in rows],
                outbox=repo.outbox_summary(session),
                deliveries=repo.delivery_summary(session),
                email_channel=email_status_out(),
            )
