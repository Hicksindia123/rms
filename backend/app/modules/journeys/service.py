"""Role journeys (change plan Phase 10, AMD-22, DEC-49).

Each role sees only its own menu, ordered as its working journey, and My Work shows the count and
the next GS per step. The menu comes from configuration (`journey_steps`, `role_journey_steps`);
entries are further filtered by the user's effective permissions and by `features.on_hold`
(AMD-21, DEC-44). The menu is navigation only: every endpoint keeps its own permission checks.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.context import get_request_id
from app.core.db import UnitOfWork
from app.core.errors import NotFound, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.config.options import repository as options_repo
from app.modules.journeys import repository as repo
from app.modules.journeys.schemas import (
    JourneyConfigOut,
    JourneyEntry,
    JourneyNext,
    JourneyQueueItem,
    JourneyQueueOut,
    JourneyStepOut,
    JourneyStepUpdate,
    MyJourneyOut,
    RoleJourneyOut,
    RoleJourneyUpdate,
)

log = logging.getLogger(__name__)

ON_HOLD_KEY = "features.on_hold"
QUEUE_PAGE_LIMIT = 200


def _on_hold(value: Any) -> list[str]:
    """`features.on_hold` is a JSON list of feature codes; anything else is a config error."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        log.error("setting %s is not a list of codes: %r", ON_HOLD_KEY, value)
        raise ValidationFailed(
            f"Setting {ON_HOLD_KEY} must be a list of feature codes",
            code="INVALID_SETTING",
            details={"key": ON_HOLD_KEY},
        )
    return sorted(set(value))


def _visible(step: dict[str, Any], perms: EffectivePermissions, hold: list[str]) -> bool:
    if step["feature_code"] and step["feature_code"] in hold:
        return False
    return perms.allows(step["perm_module"], step["perm_action"])


class JourneyService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- the signed-in user's journey -------------------------------------------------------

    def _user_steps(self, session: Any, user: CurrentUser) -> list[dict[str, Any]]:
        if user.is_super_admin:
            # Super Admin: the whole active catalogue, steps first, in workflow order.
            steps = [s for s in repo.list_catalogue(session) if s["is_active"]]
            return sorted(steps, key=lambda s: (s["kind"] == "TOOL", s["sort_order"]))
        return repo.list_user_steps(session, user.id)

    def my_journey(self, user: CurrentUser, perms: EffectivePermissions) -> MyJourneyOut:
        with self._uow.transaction(user.id) as session:
            hold = _on_hold(repo.get_setting(session, ON_HOLD_KEY))
            entries: list[JourneyEntry] = []
            for s in self._user_steps(session, user):
                if not _visible(s, perms, hold):
                    continue
                count: int | None = None
                nxt: JourneyNext | None = None
                if s["queue_code"]:
                    count, first = repo.queue_summary(session, s["queue_code"])
                    nxt = JourneyNext(**first) if first else None
                entries.append(
                    JourneyEntry(
                        code=s["code"],
                        label=s["label"],
                        hint=s["hint"],
                        kind=s["kind"],
                        screen_key=s["screen_key"],
                        item_screen_key=s["item_screen_key"],
                        queue_code=s["queue_code"],
                        count=count,
                        next=nxt,
                    )
                )
        return MyJourneyOut(entries=entries, hidden_features=hold)

    def queue(self, user: CurrentUser, perms: EffectivePermissions, code: str) -> JourneyQueueOut:
        """The GS list of one of the user's journey steps (404 for a step not on their menu)."""
        with self._uow.transaction(user.id) as session:
            hold = _on_hold(repo.get_setting(session, ON_HOLD_KEY))
            step = next(
                (
                    s
                    for s in self._user_steps(session, user)
                    if s["code"] == code and _visible(s, perms, hold)
                ),
                None,
            )
            if step is None or not step["queue_code"]:
                raise NotFound(
                    f"Journey step {code} is not on your menu", code="JOURNEY_STEP_NOT_FOUND"
                )
            rows, total = repo.queue_items(session, step["queue_code"], QUEUE_PAGE_LIMIT)
        return JourneyQueueOut(
            code=step["code"],
            label=step["label"],
            hint=step["hint"],
            item_screen_key=step["item_screen_key"],
            items=[JourneyQueueItem(**r) for r in rows],
            total=total,
        )

    # --- admin configuration ------------------------------------------------------------------

    def config(self, user: CurrentUser) -> JourneyConfigOut:
        with self._uow.transaction(user.id) as session:
            steps = repo.list_catalogue(session)
            roles = repo.list_roles(session)
            by_role: dict[str, list[str]] = {}
            for a in repo.list_role_assignments(session):
                by_role.setdefault(a["role_code"], []).append(a["step_code"])
            hold = _on_hold(repo.get_setting(session, ON_HOLD_KEY))
        return JourneyConfigOut(
            steps=[JourneyStepOut(**s) for s in steps],
            roles=[
                RoleJourneyOut(
                    role_code=r["code"], role_name=r["name"], step_codes=by_role.get(r["code"], [])
                )
                for r in roles
            ],
            on_hold=hold,
        )

    def set_role_journey(
        self, user: CurrentUser, role_code: str, payload: RoleJourneyUpdate
    ) -> RoleJourneyOut:
        codes = payload.step_codes
        if len(set(codes)) != len(codes):
            raise ValidationFailed(
                "A step can appear only once in a role's journey", code="DUPLICATE_STEP"
            )
        with self._uow.transaction(user.id) as session:
            role = repo.get_role(session, role_code)
            if role is None or role["code"] == "SUPER_ADMIN":
                raise NotFound(f"Role {role_code} not found", code="ROLE_NOT_FOUND")
            ids = repo.step_ids_by_code(session, codes)
            unknown = [c for c in codes if c not in ids]
            if unknown:
                raise ValidationFailed(
                    "Unknown journey step code(s)",
                    code="UNKNOWN_JOURNEY_STEP",
                    details={"codes": unknown},
                )
            before = repo.role_step_codes(session, role["id"])
            repo.replace_role_steps(session, role["id"], [ids[c] for c in codes])
            options_repo.log_config_change(
                session=session,
                entity_type="role_journey",
                entity_id=role_code,
                action="UPDATE_ROLE_JOURNEY",
                before={"step_codes": before},
                after={"step_codes": codes},
                reason=payload.reason,
                request_id=get_request_id(),
            )
        return RoleJourneyOut(role_code=role["code"], role_name=role["name"], step_codes=codes)

    def update_step(
        self, user: CurrentUser, code: str, payload: JourneyStepUpdate
    ) -> JourneyStepOut:
        with self._uow.transaction(user.id) as session:
            before = repo.get_step(session, code)
            if before is None:
                raise NotFound(f"Journey step {code} not found", code="JOURNEY_STEP_NOT_FOUND")
            after = repo.update_step_label(
                session,
                code,
                label=payload.label.strip(),
                hint=(payload.hint or "").strip() or None,
                is_active=payload.is_active,
            )
            if after is None:
                raise NotFound(f"Journey step {code} not found", code="JOURNEY_STEP_NOT_FOUND")
            options_repo.log_config_change(
                session=session,
                entity_type="journey_step",
                entity_id=code,
                action="UPDATE_JOURNEY_STEP",
                before={k: before[k] for k in ("label", "hint", "is_active")},
                after={k: after[k] for k in ("label", "hint", "is_active")},
                reason=payload.reason,
                request_id=get_request_id(),
            )
        return JourneyStepOut(**{k: v for k, v in after.items() if k != "id"})
