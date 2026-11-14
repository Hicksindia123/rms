"""Service for workflow configuration, versioning, graph reachability,
and guard validation (prompt P1-08).
"""

from __future__ import annotations

from typing import Any

from app.core.config_cache import (
    get_cached_published_workflow,
    invalidate_workflow_cache,
    set_cached_published_workflow,
)
from app.core.context import get_request_id
from app.core.db import UnitOfWork
from app.core.errors import NotFound, ValidationFailed
from app.core.security import CurrentUser
from app.modules.config.options import repository as options_repo
from app.modules.config.workflow import repository as repo
from app.modules.config.workflow.schemas import (
    WorkflowDefinitionOut,
    WorkflowDiffOut,
    WorkflowStageOut,
    WorkflowStepOut,
    WorkflowTransitionIn,
    WorkflowTransitionOut,
    WorkflowValidateOut,
    WorkflowVersionDetailOut,
    WorkflowVersionOut,
)

# Mandatory locked system guards per transition (master plan §4.2, prompt P1-08)
LOCKED_SYSTEM_GUARDS: dict[tuple[str, str], list[str]] = {
    ("S1_GATE", "S1_UNBOX"): ["G-01"],
    ("S1_UNBOX", "S1_ITEMIZE"): ["G-02"],
    ("S1_CSR_APPROVAL", "S2_HANDOVER"): ["G-03"],
    ("S1_INSPECT", "S1A_RM_ACTION"): ["G-06", "G-07"],
    ("S1A_RM_ACTION", "S2_HANDOVER"): ["G-08"],
    ("S2_HANDOVER", "S3_TECHNICAL"): ["G-09"],
    ("S2_HANDOVER", "S6_STORE_ISSUE"): ["G-09"],
    ("S3_TECHNICAL", "S4_DISMANTLE"): ["G-10"],
    ("S3_TECHNICAL", "S5_SEGREGATE"): ["G-10"],
    ("S4_DISMANTLE", "S5_SEGREGATE"): ["G-11"],
    ("S5_SEGREGATE", "S6_STORE_ISSUE"): ["G-12"],
    ("S6_CN_DECISION", "S6_ACCOUNTS_CN"): ["G-13"],
    ("S6_ACCOUNTS_CN", "S6_NOTIFY"): ["G-13", "G-14"],
    ("S6_NOTIFY", "S6_CLOSE"): ["G-15"],
}


class WorkflowService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_workflows(self, user: CurrentUser) -> list[WorkflowDefinitionOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_workflow_definitions(session)
            return [WorkflowDefinitionOut.model_validate(r) for r in rows]

    def get_workflow(self, user: CurrentUser, code: str) -> WorkflowDefinitionOut:
        with self._uow.transaction(user.id) as session:
            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")
            return WorkflowDefinitionOut.model_validate(wf)

    def get_published_snapshot(self, code: str) -> dict[str, Any]:
        cached = get_cached_published_workflow(code)
        if cached is not None:
            return cached
        with self._uow.transaction() as session:
            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")
            pub_ver = repo.get_published_version(session, wf["id"])
            if not pub_ver or not pub_ver.get("snapshot"):
                raise NotFound(f"No published version found for workflow '{code}'")
            snapshot = dict(pub_ver["snapshot"])
            set_cached_published_workflow(code, snapshot)
            return snapshot

    def get_version(
        self, user: CurrentUser, code: str, version_no: int
    ) -> WorkflowVersionDetailOut:
        with self._uow.transaction(user.id) as session:
            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")
            ver = repo.get_workflow_version(session, wf["id"], version_no)
            if not ver:
                raise NotFound(f"Version {version_no} not found for workflow '{code}'")

            stages = repo.list_stages(session, ver["id"])
            steps = repo.list_steps(session, ver["id"])
            transitions = repo.list_transitions(session, ver["id"])

            return WorkflowVersionDetailOut(
                **ver,
                stages=[WorkflowStageOut.model_validate(s) for s in stages],
                steps=[WorkflowStepOut.model_validate(s) for s in steps],
                transitions=[WorkflowTransitionOut.model_validate(t) for t in transitions],
            )

    def create_draft(self, user: CurrentUser, code: str) -> WorkflowVersionDetailOut:
        with self._uow.transaction(user.id) as session:
            from sqlalchemy import text

            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")

            existing_draft = repo.get_draft_version(session, wf["id"])
            if existing_draft:
                return self.get_version(user, code, existing_draft["version_no"])

            max_v = repo.get_max_version_no(session, wf["id"])
            new_v = max_v + 1
            draft_ver = repo.create_draft_version(session, wf["id"], new_v)

            # Clone from latest published version if available
            pub_ver = repo.get_published_version(session, wf["id"])
            if pub_ver:
                old_stages = repo.list_stages(session, pub_ver["id"])
                old_steps = repo.list_steps(session, pub_ver["id"])
                old_transitions = repo.list_transitions(session, pub_ver["id"])

                # Clone stages with mapping
                stage_id_map: dict[str, str] = {}
                for stg in old_stages:
                    row = session.execute(
                        text(
                            """
                            insert into public.workflow_stages (
                                workflow_version_id, code, label, sort_order
                            ) values (:vid, :code, :label, :sort)
                            returning id
                            """
                        ),
                        {
                            "vid": draft_ver["id"],
                            "code": stg["code"],
                            "label": stg["label"],
                            "sort": stg["sort_order"],
                        },
                    ).first()
                    if row:
                        stage_id_map[str(stg["id"])] = str(row[0])

                # Clone steps with mapping
                step_id_map: dict[str, str] = {}
                for stp in old_steps:
                    new_stage_id = stage_id_map.get(str(stp["stage_id"]))
                    row = session.execute(
                        text(
                            """
                            insert into public.workflow_steps (
                              workflow_version_id, stage_id, code, label, form_definition_id,
                              sla_hours, requires_approval, sort_order, is_active
                            ) values (
                              :vid, :stg_id, :code, :label, :form_id,
                              :sla, :appr, :sort, :active
                            ) returning id
                            """
                        ),
                        {
                            "vid": draft_ver["id"],
                            "stg_id": new_stage_id,
                            "code": stp["code"],
                            "label": stp["label"],
                            "form_id": stp.get("form_definition_id"),
                            "sla": stp.get("sla_hours"),
                            "appr": stp.get("requires_approval", False),
                            "sort": stp.get("sort_order", 0),
                            "active": stp.get("is_active", True),
                        },
                    ).first()
                    if row:
                        new_step_id = str(row[0])
                        step_id_map[str(stp["id"])] = new_step_id

                        # Clone step assignments
                        for a in stp.get("assignments", []):
                            session.execute(
                                text(
                                    """
                                    insert into public.step_assignments (
                                        workflow_step_id, role_id, user_id, assignment_type
                                    ) values (:sid, :rid, :uid, :atype)
                                    """
                                ),
                                {
                                    "sid": new_step_id,
                                    "rid": a.get("role_id"),
                                    "uid": a.get("user_id"),
                                    "atype": a["assignment_type"],
                                },
                            )

                # Clone transitions
                for tr in old_transitions:
                    new_from = step_id_map.get(str(tr["from_step_id"]))
                    new_to = step_id_map.get(str(tr["to_step_id"]))
                    if new_from and new_to:
                        import json

                        session.execute(
                            text(
                                """
                                insert into public.workflow_transitions (
                                  workflow_version_id, from_step_id, to_step_id,
                                  condition, system_guards, priority
                                ) values (
                                  :vid, :from_id, :to_id, cast(:cond as jsonb), :guards, :prio
                                )
                                """
                            ),
                            {
                                "vid": draft_ver["id"],
                                "from_id": new_from,
                                "to_id": new_to,
                                "cond": json.dumps(tr.get("condition")),
                                "guards": tr.get("system_guards") or [],
                                "prio": tr.get("priority", 0),
                            },
                        )

            return self.get_version(user, code, new_v)

    def update_draft_step_label(
        self, user: CurrentUser, code: str, step_code: str, new_label: str
    ) -> WorkflowVersionDetailOut:
        with self._uow.transaction(user.id) as session:
            from sqlalchemy import text

            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")
            draft_ver = repo.get_draft_version(session, wf["id"])
            if not draft_ver:
                raise NotFound(f"No active draft found for workflow '{code}'")

            session.execute(
                text(
                    """
                    update public.workflow_steps
                    set label = :lbl, updated_at = now()
                    where workflow_version_id = :vid and code = :code
                    """
                ),
                {"vid": draft_ver["id"], "lbl": new_label, "code": step_code},
            )

            return self.get_version(user, code, draft_ver["version_no"])

    def update_draft_transitions(
        self,
        user: CurrentUser,
        code: str,
        transitions: list[WorkflowTransitionIn],
    ) -> WorkflowVersionDetailOut:
        with self._uow.transaction(user.id) as session:
            import json

            from sqlalchemy import text

            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")
            draft_ver = repo.get_draft_version(session, wf["id"])
            if not draft_ver:
                raise NotFound(f"No active draft found for workflow '{code}'")

            steps = repo.list_steps(session, draft_ver["id"])
            step_code_by_id = {str(s["id"]): s["code"] for s in steps}

            # Check locked guards on submitted transitions
            for tr in transitions:
                from_code = step_code_by_id.get(str(tr.from_step_id))
                to_code = step_code_by_id.get(str(tr.to_step_id))
                if from_code and to_code:
                    locked = LOCKED_SYSTEM_GUARDS.get((from_code, to_code), [])
                    guards_present = set(tr.system_guards)
                    for g in locked:
                        if g not in guards_present:
                            raise ValidationFailed(
                                f"System guard '{g}' is locked on transition "
                                f"'{from_code}' -> '{to_code}' and cannot be removed.",
                                code="SYSTEM_GUARD_LOCKED",
                                details={"guard": g, "from_step": from_code, "to_step": to_code},
                            )

            # Replace transitions
            session.execute(
                text("delete from public.workflow_transitions where workflow_version_id = :vid"),
                {"vid": draft_ver["id"]},
            )
            for tr in transitions:
                session.execute(
                    text(
                        """
                        insert into public.workflow_transitions (
                          workflow_version_id, from_step_id, to_step_id,
                          condition, system_guards, priority
                        ) values (
                          :vid, :from_id, :to_id, cast(:cond as jsonb), :guards, :prio
                        )
                        """
                    ),
                    {
                        "vid": draft_ver["id"],
                        "from_id": str(tr.from_step_id),
                        "to_id": str(tr.to_step_id),
                        "cond": json.dumps(tr.condition) if tr.condition else None,
                        "guards": tr.system_guards,
                        "prio": tr.priority,
                    },
                )

            return self.get_version(user, code, draft_ver["version_no"])

    def validate_draft(self, user: CurrentUser, code: str) -> WorkflowValidateOut:
        with self._uow.transaction(user.id) as session:
            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")
            draft_ver = repo.get_draft_version(session, wf["id"])
            if not draft_ver:
                raise NotFound(f"No active draft found for workflow '{code}'")

            steps = repo.list_steps(session, draft_ver["id"])
            transitions = repo.list_transitions(session, draft_ver["id"])

            errors: list[str] = []
            warnings: list[str] = []

            step_codes = {s["code"] for s in steps if s.get("is_active", True)}
            if "S1_GATE" not in step_codes:
                errors.append("Start step 'S1_GATE' is missing or inactive")
            if "S6_CLOSE" not in step_codes:
                errors.append("Terminal step 'S6_CLOSE' is missing or inactive")

            # Build adjacency graph
            adj_forward: dict[str, set[str]] = {s: set() for s in step_codes}
            adj_reverse: dict[str, set[str]] = {s: set() for s in step_codes}

            step_id_to_code = {str(s["id"]): s["code"] for s in steps}

            for t in transitions:
                f_code = step_id_to_code.get(str(t["from_step_id"]))
                t_code = step_id_to_code.get(str(t["to_step_id"]))
                if (
                    f_code is not None
                    and t_code is not None
                    and f_code in step_codes
                    and t_code in step_codes
                ):
                    adj_forward[f_code].add(t_code)
                    adj_reverse[t_code].add(f_code)

            # Reachability from S1_GATE
            visited_from_start: set[str] = set()

            def dfs_forward(node: str) -> None:
                visited_from_start.add(node)
                for nxt in adj_forward.get(node, []):
                    if nxt not in visited_from_start:
                        dfs_forward(nxt)

            if "S1_GATE" in step_codes:
                dfs_forward("S1_GATE")
                unreachable = step_codes - visited_from_start
                if unreachable:
                    errors.append(
                        f"Unreachable active steps from S1_GATE: {', '.join(sorted(unreachable))}"
                    )

            # Able to reach S6_CLOSE
            can_reach_end: set[str] = set()

            def dfs_reverse(node: str) -> None:
                can_reach_end.add(node)
                for prev in adj_reverse.get(node, []):
                    if prev not in can_reach_end:
                        dfs_reverse(prev)

            if "S6_CLOSE" in step_codes:
                dfs_reverse("S6_CLOSE")
                dead_ends = step_codes - can_reach_end
                if dead_ends:
                    errors.append(
                        f"Active steps that cannot reach S6_CLOSE: {', '.join(sorted(dead_ends))}"
                    )

            # Check locked guards
            for (from_c, to_c), locked_guards in LOCKED_SYSTEM_GUARDS.items():
                if from_c in step_codes and to_c in step_codes:
                    # Find transition
                    matched_tr = [
                        t
                        for t in transitions
                        if step_id_to_code.get(str(t["from_step_id"])) == from_c
                        and step_id_to_code.get(str(t["to_step_id"])) == to_c
                    ]
                    if not matched_tr:
                        errors.append(
                            f"Mandatory transition '{from_c}' -> '{to_c}' "
                            f"with locked guards is missing"
                        )
                    else:
                        tr_guards = set(matched_tr[0].get("system_guards") or [])
                        for g in locked_guards:
                            if g not in tr_guards:
                                errors.append(
                                    f"Locked system guard '{g}' missing on transition "
                                    f"'{from_c}' -> '{to_c}'"
                                )

            return WorkflowValidateOut(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
            )

    def publish_draft(self, user: CurrentUser, code: str, reason: str) -> WorkflowVersionOut:
        if not reason or len(reason.strip()) < 3:
            raise ValidationFailed(
                "A non-empty reason (at least 3 characters) is required to publish "
                "a workflow version."
            )

        with self._uow.transaction(user.id) as session:
            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")
            draft_ver = repo.get_draft_version(session, wf["id"])
            if not draft_ver:
                raise NotFound(f"No active draft found for workflow '{code}'")

            # Validate reachability and locked guards
            val_out = self.validate_draft(user, code)
            if not val_out.is_valid:
                # If a locked guard was missing, return SYSTEM_GUARD_LOCKED code
                has_guard_error = any("Locked system guard" in e for e in val_out.errors)
                err_code = "SYSTEM_GUARD_LOCKED" if has_guard_error else "UNREACHABLE_STEP"
                raise ValidationFailed(
                    f"Workflow draft validation failed: {'; '.join(val_out.errors)}",
                    code=err_code,
                    details={"errors": val_out.errors},
                )

            # Build frozen snapshot
            stages = repo.list_stages(session, draft_ver["id"])
            steps = repo.list_steps(session, draft_ver["id"])
            transitions = repo.list_transitions(session, draft_ver["id"])

            snapshot = {
                "workflow_code": code,
                "name": wf["name"],
                "version_no": draft_ver["version_no"],
                "version_notes": reason,
                "stages": [
                    {
                        "id": str(s["id"]),
                        "code": s["code"],
                        "label": s["label"],
                        "sort_order": s["sort_order"],
                    }
                    for s in stages
                ],
                "steps": [
                    {
                        "id": str(s["id"]),
                        "code": s["code"],
                        "label": s["label"],
                        "stage_id": str(s["stage_id"]),
                        "stage_code": s.get("stage_code"),
                        "form_definition_id": str(s["form_definition_id"])
                        if s.get("form_definition_id")
                        else None,
                        "form_code": s.get("form_code"),
                        "sla_hours": float(s["sla_hours"])
                        if s.get("sla_hours") is not None
                        else None,
                        "requires_approval": s.get("requires_approval", False),
                        "sort_order": s["sort_order"],
                        "is_active": s.get("is_active", True),
                        "assignments": [
                            {
                                "assignment_type": a["assignment_type"],
                                "role_id": str(a["role_id"]) if a.get("role_id") else None,
                                "role_code": a.get("role_code"),
                                "user_id": str(a["user_id"]) if a.get("user_id") else None,
                            }
                            for a in s.get("assignments", [])
                        ],
                    }
                    for s in steps
                ],
                "transitions": [
                    {
                        "id": str(t["id"]),
                        "from_step_id": str(t["from_step_id"]),
                        "from_step_code": t.get("from_step_code"),
                        "to_step_id": str(t["to_step_id"]),
                        "to_step_code": t.get("to_step_code"),
                        "condition": t.get("condition"),
                        "system_guards": t.get("system_guards") or [],
                        "priority": t.get("priority", 0),
                    }
                    for t in transitions
                ],
            }

            # Retire current published version
            repo.retire_published_version(session, wf["id"])

            # Publish the draft
            pub_row = repo.publish_version(session, draft_ver["id"], snapshot, user.id)

            # Audit to config_change_log with reason
            options_repo.log_config_change(
                session=session,
                entity_type="workflow_version",
                entity_id=str(draft_ver["id"]),
                action="WORKFLOW_PUBLISH",
                before=None,
                after={"workflow_code": code, "version_no": draft_ver["version_no"]},
                reason=reason,
                request_id=get_request_id(),
            )

            invalidate_workflow_cache(code)

            return WorkflowVersionOut.model_validate(pub_row)

    def diff_versions(self, user: CurrentUser, code: str, v1: int, v2: int) -> WorkflowDiffOut:
        with self._uow.transaction(user.id) as session:
            wf = repo.get_workflow_definition(session, code)
            if not wf:
                raise NotFound(f"Workflow '{code}' not found")

            ver1 = repo.get_workflow_version(session, wf["id"], v1)
            ver2 = repo.get_workflow_version(session, wf["id"], v2)
            if not ver1 or not ver2:
                raise NotFound(f"Version {v1} or {v2} not found for workflow '{code}'")

            stages1 = {s["code"]: s for s in repo.list_stages(session, ver1["id"])}
            stages2 = {s["code"]: s for s in repo.list_stages(session, ver2["id"])}
            stages_diff = {
                "added": [c for c in stages2 if c not in stages1],
                "removed": [c for c in stages1 if c not in stages2],
                "changed": [
                    {"code": c, "before": stages1[c]["label"], "after": stages2[c]["label"]}
                    for c in stages1
                    if c in stages2 and stages1[c]["label"] != stages2[c]["label"]
                ],
            }

            steps1 = {s["code"]: s for s in repo.list_steps(session, ver1["id"])}
            steps2 = {s["code"]: s for s in repo.list_steps(session, ver2["id"])}
            steps_diff = {
                "added": [c for c in steps2 if c not in steps1],
                "removed": [c for c in steps1 if c not in steps2],
                "changed": [
                    {"code": c, "before": steps1[c]["label"], "after": steps2[c]["label"]}
                    for c in steps1
                    if c in steps2 and steps1[c]["label"] != steps2[c]["label"]
                ],
            }

            tr1 = {
                (t["from_step_code"], t["to_step_code"]): t
                for t in repo.list_transitions(session, ver1["id"])
            }
            tr2 = {
                (t["from_step_code"], t["to_step_code"]): t
                for t in repo.list_transitions(session, ver2["id"])
            }
            transitions_diff = {
                "added": [f"{f}->{t}" for f, t in tr2 if (f, t) not in tr1],
                "removed": [f"{f}->{t}" for f, t in tr1 if (f, t) not in tr2],
                "changed": [],
            }

            return WorkflowDiffOut(
                v1=v1,
                v2=v2,
                stages_diff=stages_diff,
                steps_diff=steps_diff,
                transitions_diff=transitions_diff,
            )
