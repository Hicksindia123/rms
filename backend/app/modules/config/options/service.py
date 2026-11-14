"""Service for option sets and option items (master plan §3.2, §8.3, §10, prompt P1-07)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config_cache import (
    get_cached_option_set,
    invalidate_option_cache,
    set_cached_option_set,
)
from app.core.context import get_request_id
from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, SystemGuardViolation, ValidationFailed
from app.core.security import CurrentUser
from app.modules.config.options import repository as repo
from app.modules.config.options.schemas import (
    OptionItemCreate,
    OptionItemOut,
    OptionItemUpdate,
    OptionSetOut,
    OptionUsageOut,
)


def _serialize_dict(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    res: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, UUID):
            res[k] = str(v)
        elif hasattr(v, "isoformat"):
            res[k] = v.isoformat()
        else:
            res[k] = v
    return res


class OptionService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_option_sets(
        self, user: CurrentUser, include_inactive: bool = True
    ) -> list[OptionSetOut]:
        with self._uow.transaction(user.id) as session:
            sets = repo.list_option_sets(session, include_inactive=include_inactive)
            result: list[OptionSetOut] = []
            for s in sets:
                items = repo.list_option_items_for_set(session, s["id"])
                s_copy = dict(s)
                s_copy["items"] = items
                result.append(OptionSetOut.model_validate(s_copy))
            return result

    def get_option_set(self, user: CurrentUser, set_id_or_code: str | UUID) -> OptionSetOut:
        cache_key = str(set_id_or_code)
        cached = get_cached_option_set(cache_key)
        if cached is not None:
            return OptionSetOut.model_validate(cached)
        with self._uow.transaction(user.id) as session:
            s = repo.get_option_set(session, set_id_or_code)
            if not s:
                raise NotFound(f"Option set {set_id_or_code} not found")
            items = repo.list_option_items_for_set(session, s["id"])
            s_copy = dict(s)
            s_copy["items"] = items
            set_cached_option_set(cache_key, s_copy)
            if s.get("code"):
                set_cached_option_set(str(s["code"]), s_copy)
            return OptionSetOut.model_validate(s_copy)

    def get_option_item_usage(self, user: CurrentUser, code: str) -> OptionUsageOut:
        with self._uow.transaction(user.id) as session:
            count = repo.count_option_usage(session, code)
            return OptionUsageOut(code=code, usage_count=count)

    def create_item(
        self, user: CurrentUser, option_set_id: UUID, payload: OptionItemCreate
    ) -> OptionItemOut:
        # Options with system_behavior=HAZARD cannot be YES (G-05)
        if payload.system_behavior == "HAZARD" and payload.allowed_status == "YES":
            raise SystemGuardViolation(
                "G-05", "Options with system_behavior=HAZARD cannot be changed to YES"
            )

        with self._uow.transaction(user.id) as session:
            opt_set = repo.get_option_set(session, option_set_id)
            if not opt_set:
                raise NotFound(f"Option set {option_set_id} not found")

            # Check duplicate code within set
            existing_items = repo.list_option_items_for_set(session, option_set_id)
            if any(item["code"] == payload.code for item in existing_items):
                raise Conflict(
                    f"Option item code {payload.code} already exists in this set",
                    code="DUPLICATE_CODE",
                )

            data = payload.model_dump()
            row = repo.insert_option_item(session, option_set_id, data)

            repo.log_config_change(
                session=session,
                entity_type="option_item",
                entity_id=str(row["id"]),
                action="OPTION_ITEM_CREATE",
                before=None,
                after=_serialize_dict(row),
                reason="Created new option item",
                request_id=get_request_id(),
            )
            invalidate_option_cache()
            return OptionItemOut.model_validate(row)

    def update_item(
        self,
        user: CurrentUser,
        option_set_id: UUID,
        item_id: UUID,
        payload: OptionItemUpdate,
    ) -> OptionItemOut:
        with self._uow.transaction(user.id) as session:
            opt_set = repo.get_option_set(session, option_set_id)
            if not opt_set:
                raise NotFound(f"Option set {option_set_id} not found")

            existing = repo.get_option_item(session, item_id)
            if not existing or existing["option_set_id"] != option_set_id:
                raise NotFound(f"Option item {item_id} not found in this option set")

            old_status = existing["allowed_status"]
            new_status = payload.allowed_status or old_status
            old_behavior = existing["system_behavior"]
            new_behavior = (
                payload.system_behavior if payload.system_behavior is not None else old_behavior
            )

            # System guard G-05: Options with system_behavior=HAZARD cannot be changed to YES
            if (old_behavior == "HAZARD" or new_behavior == "HAZARD") and new_status == "YES":
                raise SystemGuardViolation(
                    "G-05", "Options with system_behavior=HAZARD cannot be changed to YES"
                )

            # Changing allowed_status from NO to YES or CONDITIONAL requires a reason
            is_status_upgrade = old_status == "NO" and new_status in ("YES", "CONDITIONAL")
            if is_status_upgrade and (not payload.reason or not payload.reason.strip()):
                raise ValidationFailed(
                    "A reason is required when changing allowed_status from NO to "
                    "YES or CONDITIONAL",
                    code="REASON_REQUIRED",
                )

            update_data: dict[str, Any] = {}
            if payload.label is not None:
                update_data["label"] = payload.label
            if payload.allowed_status is not None:
                update_data["allowed_status"] = payload.allowed_status
            if payload.rule_text is not None:
                update_data["rule_text"] = payload.rule_text
            if payload.next_action_text is not None:
                update_data["next_action_text"] = payload.next_action_text
            if payload.remarks is not None:
                update_data["remarks"] = payload.remarks
            if payload.system_behavior is not None:
                update_data["system_behavior"] = payload.system_behavior
            if payload.required_fields is not None:
                update_data["required_fields"] = payload.required_fields
            if payload.sort_order is not None:
                update_data["sort_order"] = payload.sort_order
            if payload.is_active is not None:
                update_data["is_active"] = payload.is_active

            updated_row = repo.update_option_item(session, item_id, update_data)

            # Raise high-severity log if upgraded from NO, otherwise standard change log
            action_code = "OPTION_STATUS_UPGRADE" if is_status_upgrade else "OPTION_ITEM_UPDATE"
            repo.log_config_change(
                session=session,
                entity_type="option_item",
                entity_id=str(item_id),
                action=action_code,
                before=_serialize_dict(existing),
                after=_serialize_dict(updated_row),
                reason=payload.reason or "Option item updated",
                request_id=get_request_id(),
            )

            invalidate_option_cache()

            return OptionItemOut.model_validate(updated_row)
