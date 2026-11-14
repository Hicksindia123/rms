"""Service for dynamic forms and form builder (master plan §8.3, §10, prompt P1-07)."""

from __future__ import annotations

from typing import Any

from app.core.config_cache import (
    get_cached_published_form,
    invalidate_form_cache,
    set_cached_published_form,
)
from app.core.context import get_request_id
from app.core.db import UnitOfWork
from app.core.errors import NotFound, ValidationFailed
from app.core.security import CurrentUser
from app.modules.config.forms import repository as repo
from app.modules.config.forms.core_registry import FORM_CORE_FIELDS
from app.modules.config.forms.schemas import (
    FormDefinitionOut,
    FormDiffOut,
    FormDraftUpdate,
    FormFieldOut,
    FormValidateOut,
    FormVersionDetailOut,
    FormVersionOut,
    SubmissionValidationResponse,
)
from app.modules.config.forms.validator import validate_submission as run_submission_validation
from app.modules.config.options import repository as options_repo


def _extract_referenced_fields(rule: dict[str, Any] | None) -> set[str]:
    """Recursively extract all field keys referenced by a conditional rule."""
    if not rule:
        return set()
    fields: set[str] = set()
    if "all" in rule and isinstance(rule["all"], list):
        for child in rule["all"]:
            fields.update(_extract_referenced_fields(child))
    if "any" in rule and isinstance(rule["any"], list):
        for child in rule["any"]:
            fields.update(_extract_referenced_fields(child))
    if "not" in rule and isinstance(rule["not"], dict):
        fields.update(_extract_referenced_fields(rule["not"]))
    if "field" in rule and isinstance(rule["field"], str):
        fields.add(rule["field"])
    return fields


def _detect_cycle(adj: dict[str, list[str]]) -> list[str] | None:
    """Return a cycle as a list of nodes, or None if the graph is a DAG."""
    visited: dict[str, int] = {}  # 0 = unvisited, 1 = visiting, 2 = visited

    def dfs(node: str, path: list[str]) -> list[str] | None:
        visited[node] = 1
        path.append(node)
        for neighbor in adj.get(node, []):
            if visited.get(neighbor, 0) == 1:
                idx = path.index(neighbor)
                return [*path[idx:], neighbor]
            if visited.get(neighbor, 0) == 0:
                cycle = dfs(neighbor, path)
                if cycle:
                    return cycle
        path.pop()
        visited[node] = 2
        return None

    for n in list(adj.keys()):
        if visited.get(n, 0) == 0:
            cycle = dfs(n, [])
            if cycle:
                return cycle
    return None


class FormService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_forms(self, user: CurrentUser) -> list[FormDefinitionOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_form_definitions(session)
            return [FormDefinitionOut.model_validate(r) for r in rows]

    def get_form(self, user: CurrentUser, form_code: str) -> FormDefinitionOut:
        with self._uow.transaction(user.id) as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")
            return FormDefinitionOut.model_validate(f)

    def get_published_snapshot(self, form_code: str) -> dict[str, Any]:
        """Returns the published snapshot used by operational screens."""
        cached = get_cached_published_form(form_code)
        if cached is not None:
            return cached
        with self._uow.transaction() as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")
            pub_ver = repo.get_published_version(session, f["id"])
            if not pub_ver or not pub_ver.get("snapshot"):
                raise NotFound(f"No published version found for form {form_code}")
            snapshot = dict(pub_ver["snapshot"])
            if form_code == "S1_GATE_INWARD":
                fields = list(snapshot.get("fields") or [])
                # v1 forms only: form v2 (AMD-04) carries files per gate document row.
                is_v1 = any(f.get("field_key") == "accompanying_doc" for f in fields)
                if is_v1 and not any(f.get("field_key") == "gate_doc_image" for f in fields):
                    fields.append(
                        {
                            "field_key": "gate_doc_image",
                            "label": "Document Picture / Image",
                            "control_type": "file",
                            "is_required": False,
                            "is_core": False,
                            "sort_order": 145,
                            "section": "Documentation",
                            "help_text": "Upload or take photo of the physical invoice or slip",
                            "visible_when": {
                                "field": "accompanying_doc",
                                "op": "in",
                                "value": [
                                    "INVOICE",
                                    "DEBIT_NOTE",
                                    "DELIVERY_CHALLAN",
                                    "HANDWRITTEN_SLIP",
                                ],
                            },
                            "required_when": None,
                            "validation": None,
                            "option_items": [],
                        }
                    )
                    snapshot["fields"] = sorted(fields, key=lambda f: f.get("sort_order", 0))
            set_cached_published_form(form_code, snapshot)
            return snapshot

    def get_version(
        self, user: CurrentUser, form_code: str, version_no: int
    ) -> FormVersionDetailOut:
        with self._uow.transaction(user.id) as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")
            ver = repo.get_form_version(session, f["id"], version_no)
            if not ver:
                raise NotFound(f"Version {version_no} not found for form {form_code}")
            fields = repo.list_form_fields(session, ver["id"])

            # Populate option items for fields with option_set_id
            field_outs: list[FormFieldOut] = []
            for fld in fields:
                fld_dict = dict(fld)
                if fld["option_set_id"]:
                    fld_dict["option_items"] = options_repo.list_option_items_for_set(
                        session, fld["option_set_id"]
                    )
                field_outs.append(FormFieldOut.model_validate(fld_dict))

            ver_copy = dict(ver)
            ver_copy["fields"] = field_outs
            return FormVersionDetailOut.model_validate(ver_copy)

    def create_draft(self, user: CurrentUser, form_code: str) -> FormVersionDetailOut:
        with self._uow.transaction(user.id) as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")

            # Check if a draft already exists
            existing_draft = repo.get_draft_version(session, f["id"])
            if existing_draft:
                fields = repo.list_form_fields(session, existing_draft["id"])
                res = dict(existing_draft)
                res["fields"] = [FormFieldOut.model_validate(fld) for fld in fields]
                return FormVersionDetailOut.model_validate(res)

            # Determine next version number
            latest_vno = repo.get_latest_version_no(session, f["id"])
            next_vno = latest_vno + 1

            new_draft = repo.create_form_version(
                session, form_definition_id=f["id"], version_no=next_vno, status="DRAFT"
            )

            # If there was a published version, copy its fields into the draft
            pub_ver = repo.get_published_version(session, f["id"])
            copied_fields: list[dict[str, Any]] = []
            if pub_ver:
                source_fields = repo.list_form_fields(session, pub_ver["id"])
                for sf in source_fields:
                    inserted = repo.insert_form_field(session, new_draft["id"], sf)
                    copied_fields.append(inserted)

            res = dict(new_draft)
            res["fields"] = [FormFieldOut.model_validate(cf) for cf in copied_fields]
            return FormVersionDetailOut.model_validate(res)

    def update_draft_fields(
        self, user: CurrentUser, form_code: str, payload: FormDraftUpdate
    ) -> FormVersionDetailOut:
        with self._uow.transaction(user.id) as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")

            draft_ver = repo.get_draft_version(session, f["id"])
            if not draft_ver:
                raise NotFound(f"No active draft found for form {form_code}")

            # Enforce is_core protections
            core_defs = FORM_CORE_FIELDS.get(form_code, {})
            field_keys = {fld.field_key for fld in payload.fields}

            # Check core fields cannot be deleted
            missing_cores = set(core_defs.keys()) - field_keys
            if missing_cores:
                raise ValidationFailed(
                    f"Core fields cannot be removed: {', '.join(sorted(missing_cores))}",
                    code="CANNOT_DELETE_CORE_FIELD",
                )

            for fld in payload.fields:
                core_def = core_defs.get(fld.field_key)
                if core_def:
                    # Check control type cannot be changed
                    if fld.control_type != core_def.control_type:
                        raise ValidationFailed(
                            f"Control type of core field '{fld.field_key}' cannot be changed "
                            f"(must remain {core_def.control_type})",
                            code="CANNOT_CHANGE_CORE_TYPE",
                        )
                    # Check guarded required
                    if core_def.guarded_required and not fld.is_required:
                        raise ValidationFailed(
                            f"Core field '{fld.field_key}' is required by system guard "
                            f"{core_def.system_guard or ''} and cannot be optional",
                            code="CORE_FIELD_MUST_BE_REQUIRED",
                        )

            # Replace fields in the draft
            repo.delete_form_fields(session, draft_ver["id"])
            inserted_fields: list[dict[str, Any]] = []
            for fld in payload.fields:
                data = fld.model_dump()
                inserted = repo.insert_form_field(session, draft_ver["id"], data)
                inserted_fields.append(inserted)

            res = dict(draft_ver)
            res["fields"] = [FormFieldOut.model_validate(cf) for cf in inserted_fields]
            return FormVersionDetailOut.model_validate(res)

    def validate_draft(self, user: CurrentUser, form_code: str) -> FormValidateOut:
        with self._uow.transaction(user.id) as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")

            draft_ver = repo.get_draft_version(session, f["id"])
            if not draft_ver:
                raise NotFound(f"No active draft found for form {form_code}")

            fields = repo.list_form_fields(session, draft_ver["id"])
            errors: list[str] = []
            warnings: list[str] = []

            if not fields:
                errors.append("Draft form contains no fields")

            field_keys = {fld["field_key"] for fld in fields}

            # Check rule references & option set existence
            dependency_graph: dict[str, list[str]] = {k: [] for k in field_keys}

            for fld in fields:
                key = fld["field_key"]
                # Option set reference check
                if fld["control_type"] in ("dropdown", "radio", "multiselect"):
                    if not fld["option_set_id"]:
                        errors.append(
                            f"Field '{key}' has control type {fld['control_type']} "
                            "but no option set assigned"
                        )
                    else:
                        opt_set = options_repo.get_option_set(session, fld["option_set_id"])
                        if not opt_set:
                            errors.append(
                                f"Field '{key}' references non-existent option set ID "
                                f"{fld['option_set_id']}"
                            )

                # Master ref check
                if fld["control_type"] == "master_ref" and not fld.get("master_ref_type"):
                    errors.append(
                        f"Field '{key}' has master_ref type but no master_ref_type assigned"
                    )

                # Visible when references
                vw_refs = _extract_referenced_fields(fld.get("visible_when"))
                for ref in vw_refs:
                    if ref not in field_keys:
                        errors.append(
                            f"Field '{key}' visible_when references unknown field '{ref}'"
                        )
                    else:
                        dependency_graph[ref].append(key)

                # Required when references
                rw_refs = _extract_referenced_fields(fld.get("required_when"))
                for ref in rw_refs:
                    if ref not in field_keys:
                        errors.append(
                            f"Field '{key}' required_when references unknown field '{ref}'"
                        )

            # Check for dependency cycles in visible_when
            cycle = _detect_cycle(dependency_graph)
            if cycle:
                errors.append(f"Cycle detected in visible_when dependencies: {' -> '.join(cycle)}")

            # Check core field requirements
            core_defs = FORM_CORE_FIELDS.get(form_code, {})
            for ck, _cdef in core_defs.items():
                if ck not in field_keys:
                    errors.append(f"Missing mandatory core field '{ck}'")

            is_valid = len(errors) == 0
            return FormValidateOut(is_valid=is_valid, errors=errors, warnings=warnings)

    def publish_draft(
        self, user: CurrentUser, form_code: str, version_notes: str | None = None
    ) -> FormVersionOut:
        validation = self.validate_draft(user, form_code)
        if not validation.is_valid:
            raise ValidationFailed(
                f"Cannot publish invalid form draft: {'; '.join(validation.errors)}",
                details={"errors": validation.errors},
            )

        with self._uow.transaction(user.id) as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")

            draft_ver = repo.get_draft_version(session, f["id"])
            if not draft_ver:
                raise NotFound(f"No active draft found for form {form_code}")

            fields = repo.list_form_fields(session, draft_ver["id"])

            # Assemble frozen snapshot jsonb
            frozen_fields: list[dict[str, Any]] = []
            for fld in fields:
                f_dict = dict(fld)
                # Embed option items snapshot for offline / reliable rendering
                if fld["option_set_id"]:
                    items = options_repo.list_option_items_for_set(session, fld["option_set_id"])
                    f_dict["option_items"] = [
                        {
                            "code": item["code"],
                            "label": item["label"],
                            "allowed_status": item["allowed_status"],
                            "rule_text": item.get("rule_text"),
                            "next_action_text": item.get("next_action_text"),
                            "remarks": item.get("remarks"),
                            "system_behavior": item.get("system_behavior"),
                            "sort_order": item.get("sort_order", 0),
                            "is_active": item.get("is_active", True),
                        }
                        for item in items
                    ]
                frozen_fields.append(f_dict)

            snapshot: dict[str, Any] = {
                "form_code": form_code,
                "name": f["name"],
                "step_code": f.get("step_code"),
                "version_no": draft_ver["version_no"],
                "version_notes": version_notes,
                "fields": frozen_fields,
            }

            # 1. Retire previous published version
            repo.retire_published_version(session, f["id"])

            # 2. Publish the draft
            pub_row = repo.publish_version(session, draft_ver["id"], snapshot, user.id)

            # 3. Log to config_change_log
            options_repo.log_config_change(
                session=session,
                entity_type="form_version",
                entity_id=str(draft_ver["id"]),
                action="FORM_PUBLISH",
                before=None,
                after={"form_code": form_code, "version_no": draft_ver["version_no"]},
                reason=version_notes or f"Published version {draft_ver['version_no']}",
                request_id=get_request_id(),
            )

            invalidate_form_cache(form_code)

            return FormVersionOut.model_validate(pub_row)

    def diff_versions(self, user: CurrentUser, form_code: str, v1: int, v2: int) -> FormDiffOut:
        with self._uow.transaction(user.id) as session:
            f = repo.get_form_definition(session, form_code)
            if not f:
                raise NotFound(f"Form {form_code} not found")

            ver1 = repo.get_form_version(session, f["id"], v1)
            ver2 = repo.get_form_version(session, f["id"], v2)
            if not ver1 or not ver2:
                raise NotFound(f"One or both versions ({v1}, {v2}) not found")

            fields1 = {fld["field_key"]: fld for fld in repo.list_form_fields(session, ver1["id"])}
            fields2 = {fld["field_key"]: fld for fld in repo.list_form_fields(session, ver2["id"])}

            added = [fields2[k] for k in fields2 if k not in fields1]
            removed = [fields1[k] for k in fields1 if k not in fields2]

            modified: list[dict[str, Any]] = []
            for k in fields1:
                if k in fields2:
                    diffs: dict[str, Any] = {}
                    for prop in (
                        "label",
                        "control_type",
                        "is_required",
                        "visible_when",
                        "validation",
                        "section",
                    ):
                        if fields1[k].get(prop) != fields2[k].get(prop):
                            diffs[prop] = {"from": fields1[k].get(prop), "to": fields2[k].get(prop)}
                    if diffs:
                        modified.append({"field_key": k, "changes": diffs})

            return FormDiffOut(
                form_code=form_code,
                version_a=v1,
                version_b=v2,
                added_fields=added,
                removed_fields=removed,
                modified_fields=modified,
            )

    def validate_submission_payload(
        self, form_code: str, values: dict[str, Any], context: dict[str, Any] | None = None
    ) -> SubmissionValidationResponse:
        snapshot = self.get_published_snapshot(form_code)
        res = run_submission_validation(snapshot, values, context)
        return SubmissionValidationResponse(
            is_valid=res.is_valid,
            errors=res.errors,
            sanitized_values=res.sanitized_values,
        )
