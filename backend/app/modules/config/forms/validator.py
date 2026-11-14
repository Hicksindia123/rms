"""Authoritative submission validator for dynamic forms (master plan §10, prompt P1-07)."""

from __future__ import annotations

from typing import Any, NamedTuple

from app.shared.rules_engine import evaluate_rule, evaluate_validation, is_empty_value


class ValidationResult(NamedTuple):
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_values: dict[str, Any]


def validate_submission(
    snapshot: dict[str, Any],
    values: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate submitted form values against a frozen form snapshot.

    - Evaluates visible_when: hidden fields are pruned from sanitized_values.
    - Evaluates required / required_when: required visible fields must have values.
    - Evaluates field validations: min/max, length, regex, date, and cross-field sums.
    - Evaluates option validity and allowed_status.
    """
    errors: dict[str, list[str]] = {}
    sanitized: dict[str, Any] = {}

    fields = snapshot.get("fields", [])

    for field in fields:
        field_key = field.get("field_key")
        if not field_key:
            continue

        label = field.get("label", field_key)
        visible_when = field.get("visible_when")
        required_when = field.get("required_when")
        is_required_base = field.get("is_required", False)
        validation_spec = field.get("validation") or {}
        control_type = field.get("control_type", "text")

        # 1. Evaluate visibility
        is_visible = evaluate_rule(visible_when, values, context)
        if not is_visible:
            # Field is not visible; prune any supplied value and do not enforce validation
            continue

        # 2. Evaluate required
        is_required = is_required_base or (
            bool(required_when) and evaluate_rule(required_when, values, context)
        )

        val = values.get(field_key)

        if is_required and is_empty_value(val):
            errors.setdefault(field_key, []).append(f"{label} is required")
            continue

        # 3. If field is present, validate control type and option sets
        if not is_empty_value(val):
            # Control type formatting
            if control_type == "number":
                try:
                    str_v = str(val)
                    val = float(str_v) if "." in str_v else int(str_v)
                except (ValueError, TypeError):
                    errors.setdefault(field_key, []).append(f"{label} must be a valid number")

            # Validate against embedded option items if dropdown/radio/multiselect
            option_items = field.get("option_items") or []
            if option_items and control_type in ("dropdown", "radio", "multiselect"):
                item_map = {item["code"]: item for item in option_items}
                vals_to_check = val if isinstance(val, list) else [val]
                for v in vals_to_check:
                    if v not in item_map:
                        errors.setdefault(field_key, []).append(f"Invalid option '{v}' for {label}")

            # Field validation rules
            field_errors = evaluate_validation(
                validation_spec,
                val,
                values,
                is_required=is_required,
                label=label,
                context=context,
            )
            if field_errors:
                errors.setdefault(field_key, []).extend(field_errors)

            sanitized[field_key] = val
        else:
            # Even if value is empty/omitted, check cross_field_sums if defined
            if validation_spec and "cross_field_sums" in validation_spec:
                field_errors = evaluate_validation(
                    validation_spec,
                    val,
                    values,
                    is_required=is_required,
                    label=label,
                    context=context,
                )
                if field_errors:
                    errors.setdefault(field_key, []).extend(field_errors)

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, sanitized_values=sanitized)
