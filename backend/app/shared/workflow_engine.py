"""Authoritative Workflow Engine Core (master plan §2, §4.2, §6.1, §6.5, prompt P1-08).

Enforces workflow transitions, step assignments, conditional rules,
and non-bypassable system guards (G-01..G-18).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from app.core.errors import PermissionDenied, ValidationFailed
from app.shared.rules_engine import evaluate_rule


class TransitionError(ValidationFailed):
    """Raised when a requested transition is invalid or condition is not met."""


class TransitionNotAllowed(PermissionDenied):
    """Raised when the user does not have permission for the step transition."""


class SystemGuardViolation(ValidationFailed):
    """Raised when a non-bypassable system guard fails."""


@runtime_checkable
class WorkflowEntity(Protocol):
    id: UUID
    workflow_version_id: UUID
    current_step_code: str
    status: str
    context: dict[str, Any]


@dataclass
class InMemoryWorkflowEntity:
    """In-memory entity for testing workflow transitions without database access."""

    id: UUID = field(default_factory=uuid4)
    workflow_version_id: UUID = field(default_factory=uuid4)
    current_step_code: str = "S1_GATE"
    status: str = "GATE_CREATED"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowUser:
    """Represents the acting user in workflow transitions."""

    id: UUID = field(default_factory=uuid4)
    roles: list[str] = field(default_factory=list)
    is_super_admin: bool = False


# Type signature for a system guard handler: (entity, user) -> bool
GuardCallable = Callable[[Any, Any], bool]

# Global registry of guard handlers: "G-01" -> callable
# Unimplemented guards raise NotImplementedError per master plan §4.2 / prompt P1-08 specification.
SYSTEM_GUARD_REGISTRY: dict[str, GuardCallable] = {}


def register_guard(guard_code: str) -> Callable[[GuardCallable], GuardCallable]:
    """Decorator to register a callable for a system guard code."""

    def decorator(fn: GuardCallable) -> GuardCallable:
        SYSTEM_GUARD_REGISTRY[guard_code] = fn
        return fn

    return decorator


class WorkflowEngine:
    """Authoritative workflow evaluator for transition checks and execution."""

    def __init__(
        self,
        snapshot: dict[str, Any],
        guard_registry: dict[str, GuardCallable] | None = None,
    ) -> None:
        """Initialize engine with a frozen workflow snapshot dict."""
        self.snapshot = snapshot
        self.guard_registry = (
            guard_registry if guard_registry is not None else SYSTEM_GUARD_REGISTRY
        )

        # Index steps by code
        self._steps_by_code: dict[str, dict[str, Any]] = {}
        for s in snapshot.get("steps", []):
            self._steps_by_code[s["code"]] = s

        # Index transitions by from_step_code
        self._transitions_by_from: dict[str, list[dict[str, Any]]] = {}
        for t in snapshot.get("transitions", []):
            from_code = t.get("from_step_code")
            if from_code:
                self._transitions_by_from.setdefault(from_code, []).append(t)

    @classmethod
    def from_version(cls, version_snapshot: dict[str, Any]) -> WorkflowEngine:
        return cls(version_snapshot)

    def is_user_assigned_to_step(
        self,
        step_code: str,
        user: WorkflowUser | Any,
        assignment_type: str | None = None,
    ) -> bool:
        """Check whether the user is authorized for the given step."""
        if getattr(user, "is_super_admin", False):
            return True

        step = self._steps_by_code.get(step_code)
        if not step:
            return False

        assignments = step.get("assignments", [])
        if not assignments:
            # If no assignments explicitly configured, allow any authenticated user
            return True

        user_roles = set(getattr(user, "role_codes", None) or getattr(user, "roles", []))
        user_id = str(getattr(user, "id", ""))

        for a in assignments:
            if assignment_type and a.get("assignment_type") != assignment_type:
                continue

            # Role match
            role_code = a.get("role_code")
            if role_code and role_code in user_roles:
                return True

            # Specific user match
            assigned_uid = a.get("user_id")
            if assigned_uid and str(assigned_uid) == user_id:
                return True

        return False

    def available_transitions(
        self,
        entity: Any,
        user: WorkflowUser | Any,
    ) -> list[dict[str, Any]]:
        """Return all transitions currently permissible for the entity and user."""
        current_step = getattr(entity, "current_step_code", None)
        if not current_step:
            return []

        candidates = self._transitions_by_from.get(current_step, [])
        available: list[dict[str, Any]] = []

        context = getattr(entity, "context", {}) or {}

        for tr in candidates:
            to_step = tr.get("to_step_code")
            if not to_step:
                continue

            # Check condition
            cond = tr.get("condition")
            if cond and not evaluate_rule(cond, context, context):
                continue

            # Check assignment on target step
            req_type = (
                "APPROVE"
                if self._steps_by_code.get(to_step, {}).get("requires_approval")
                else "PERFORM"
            )
            if not self.is_user_assigned_to_step(to_step, user, req_type):
                continue

            available.append(tr)

        return available

    def assert_can_transition(
        self,
        entity: Any,
        to_step: str,
        user: WorkflowUser | Any,
        raise_unimplemented_guards: bool = True,
        *,
        actor_step_code: str | None = None,
        actor_assignment_type: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate condition and system guards.

        By default the user must be assigned to the *target* step. With `actor_step_code` the user
        is authorised on the step they are completing instead (e.g. the Inward Verifier routes a
        CSR from S1_ITEMIZE to the Replacement Manager's S1_CSR_APPROVAL step), with
        `actor_assignment_type` (default PERFORM). System guards are evaluated either way.

        Raises TransitionError / TransitionNotAllowed / SystemGuardViolation.
        Unimplemented system guards raise NotImplementedError unless explicitly stubbed.
        """
        current_step = getattr(entity, "current_step_code", None)
        if not current_step:
            raise TransitionError(
                f"Entity has no current step set (id={getattr(entity, 'id', None)})"
            )

        candidates = self._transitions_by_from.get(current_step, [])
        transition = next((t for t in candidates if t.get("to_step_code") == to_step), None)
        if not transition:
            raise TransitionError(
                f"No transition defined from step '{current_step}' to step '{to_step}'"
            )

        # 1. Authorization check
        if actor_step_code is not None:
            if actor_step_code != current_step:
                raise TransitionError(
                    f"Acting step '{actor_step_code}' is not the current step '{current_step}'"
                )
            req_type = actor_assignment_type or "PERFORM"
            if not self.is_user_assigned_to_step(actor_step_code, user, req_type):
                raise TransitionNotAllowed(
                    f"User does not have required {req_type} role for step '{actor_step_code}'"
                )
        else:
            req_type = (
                "APPROVE"
                if self._steps_by_code.get(to_step, {}).get("requires_approval")
                else "PERFORM"
            )
            if not self.is_user_assigned_to_step(to_step, user, req_type):
                raise TransitionNotAllowed(
                    f"User does not have required {req_type} role for target step '{to_step}'"
                )

        # 2. Rule condition check
        context = getattr(entity, "context", {}) or {}
        cond = transition.get("condition")
        if cond and not evaluate_rule(cond, context, context):
            raise TransitionError(
                f"Transition condition not satisfied for '{current_step}' -> '{to_step}'"
            )

        # 3. System guards check (G-01..G-18)
        system_guards = transition.get("system_guards") or []
        for guard in system_guards:
            guard_fn = self.guard_registry.get(guard)
            if guard_fn is None:
                if raise_unimplemented_guards:
                    raise NotImplementedError(
                        f"System guard '{guard}' is not implemented in the guard registry"
                    )
                continue

            try:
                passed = guard_fn(entity, user)
            except Exception as e:
                raise SystemGuardViolation(
                    f"System guard '{guard}' failed with error: {e}",
                    code=guard,
                    details={"guard": guard},
                ) from e

            if not passed:
                raise SystemGuardViolation(
                    f"System guard '{guard}' check failed for entity {getattr(entity, 'id', None)}",
                    code=guard,
                    details={"guard": guard},
                )

        return transition

    def record_transition(
        self,
        entity: Any,
        to_step: str,
        user: WorkflowUser | Any,
        reason: str | None = None,
        session: Any | None = None,
    ) -> None:
        """Update entity current step and record transition history in database."""
        from_step = getattr(entity, "current_step_code", "")
        from_status = getattr(entity, "status", "")

        # Target step info
        target_step_meta = self._steps_by_code.get(to_step, {})
        to_status = target_step_meta.get("target_status", to_step)

        # In-memory entity update
        if hasattr(entity, "current_step_code"):
            entity.current_step_code = to_step
        if hasattr(entity, "status"):
            entity.status = to_status

        # If a DB session is provided, write to gs_status_history
        if session is not None and hasattr(entity, "id"):
            from sqlalchemy import text

            session.execute(
                text(
                    """
                    insert into public.gs_status_history (
                      gs_id, from_status, to_status, step_code, reason, "by", "at"
                    ) values (
                      :gs_id, :from_status, :to_status, :step_code, :reason, :by, now()
                    )
                    """
                ),
                {
                    "gs_id": str(entity.id),
                    "from_status": from_status,
                    "to_status": to_status,
                    "step_code": to_step,
                    "reason": reason or f"Transition from {from_step} to {to_step}",
                    "by": str(getattr(user, "id", None)),
                },
            )


# Load standard guard implementations into the registry
import app.shared.guards  # noqa: F401, E402
