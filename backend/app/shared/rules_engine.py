"""Shared conditional-rules engine and field validation evaluator.

Contract (master plan §6.1, §10, prompt P1-07):
1. JSON rule format:
   {"all": [...]} | {"any": [...]} | {"not": {...}} |
   {"field": "delivery_mode", "op": "eq|neq|in|nin|gt|gte|lt|lte|empty|not_empty", "value": ...}
   Also "context" operands such as {"context": "product_category.code", "op": "eq", "value": "DMT"}.
2. Python evaluator (this module) is authoritative for all operational services and API validation.
3. TypeScript evaluator (src/lib/rules) mirrors this exact logic for client UX.
4. shared/rules-test-vectors.json defines the shared test suite for both evaluators.
"""

from __future__ import annotations

import contextlib
import re
from datetime import date, datetime
from typing import Any


def resolve_path(target: dict[str, Any] | None, path: str) -> Any:
    """Resolve a dot-separated path in a nested dictionary."""
    if not target or not path:
        return None
    if path in target:
        return target[path]

    parts = path.split(".")
    current: Any = target
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def is_empty_value(val: Any) -> bool:
    """Determine if a value is considered empty for conditional rules and validation."""
    if val is None:
        return True
    if isinstance(val, str):
        return len(val.strip()) == 0
    if isinstance(val, (list, tuple, dict, set)):
        return len(val) == 0
    return False


def _compare_numbers(left: Any, right: Any, op: str) -> bool:
    try:
        n_left = float(left)
        n_right = float(right)
    except (ValueError, TypeError):
        return False

    if op == "gt":
        return n_left > n_right
    if op == "gte":
        return n_left >= n_right
    if op == "lt":
        return n_left < n_right
    if op == "lte":
        return n_left <= n_right
    return False


def evaluate_rule(
    rule: dict[str, Any] | None,
    values: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> bool:
    """Authoritative Python evaluator for conditional rules."""
    if not rule:
        return True

    # Boolean compound groups
    if "all" in rule:
        children = rule["all"]
        if not isinstance(children, list) or len(children) == 0:
            return True
        return all(evaluate_rule(child, values, context) for child in children)

    if "any" in rule:
        children = rule["any"]
        if not isinstance(children, list) or len(children) == 0:
            return False
        return any(evaluate_rule(child, values, context) for child in children)

    if "not" in rule:
        child = rule["not"]
        return not evaluate_rule(child, values, context)

    # Leaf rule: field or context operand
    op = rule.get("op", "eq")
    expected_value = rule.get("value")

    if "context" in rule:
        actual_value = resolve_path(context, str(rule["context"]))
    elif "field" in rule:
        field_key = str(rule["field"])
        actual_value = resolve_path(values, field_key)
    else:
        # Empty leaf or unknown structure defaults to true
        return True

    if op == "empty":
        return is_empty_value(actual_value)
    if op == "not_empty":
        return not is_empty_value(actual_value)

    if op == "eq":
        return bool(actual_value == expected_value)
    if op == "neq":
        return bool(actual_value != expected_value)

    if op == "in":
        if not isinstance(expected_value, (list, tuple, set)):
            return False
        return actual_value in expected_value

    if op == "nin":
        if not isinstance(expected_value, (list, tuple, set)):
            return False
        return actual_value not in expected_value

    if op in ("gt", "gte", "lt", "lte"):
        return _compare_numbers(actual_value, expected_value, op)

    return False


def evaluate_validation(
    validation: dict[str, Any] | None,
    field_value: Any,
    values: dict[str, Any],
    *,
    is_required: bool = False,
    label: str = "Field",
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Validate a field value according to the validation spec.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    # 1. Required check
    if is_required and is_empty_value(field_value):
        errors.append(f"{label} is required")
        return errors

    # Check cross-field sums even if current field is empty
    if validation and "cross_field_sums" in validation:
        sums_spec = validation["cross_field_sums"]
        if "sum_equals" in sums_spec:
            eq_spec = sums_spec["sum_equals"]
            fields = eq_spec.get("fields", [])
            target = eq_spec.get("target")

            total = 0.0
            for f in fields:
                val = values.get(f)
                with contextlib.suppress(ValueError, TypeError):
                    total += float(val) if val is not None and val != "" else 0.0

            target_val = 0.0
            target_label = str(target)
            if isinstance(target, str):
                raw_target = values.get(target)
                with contextlib.suppress(ValueError, TypeError):
                    target_val = (
                        float(raw_target) if raw_target is not None and raw_target != "" else 0.0
                    )
            else:
                with contextlib.suppress(ValueError, TypeError):
                    target_val = float(target)

            if abs(total - target_val) > 1e-6:
                t_str = int(target_val) if target_val.is_integer() else target_val
                tot_str = int(total) if total.is_integer() else total
                errors.append(f"Sum of fields ({tot_str}) must equal {target_label} ({t_str})")

    # If field is empty and not required, skip value-specific constraints
    if is_empty_value(field_value):
        return errors

    if not validation:
        return errors

    # 2. Min / Max numeric
    if "min" in validation:
        try:
            n_val = float(field_value)
            if n_val < float(validation["min"]):
                errors.append(f"Value must be at least {validation['min']}")
        except (ValueError, TypeError):
            errors.append(f"{label} must be a valid number")

    if "max" in validation:
        try:
            n_val = float(field_value)
            if n_val > float(validation["max"]):
                errors.append(f"Value must be at most {validation['max']}")
        except (ValueError, TypeError):
            errors.append(f"{label} must be a valid number")

    # 3. Min / Max length
    if "min_length" in validation and len(str(field_value)) < int(validation["min_length"]):
        errors.append(f"{label} must have at least {validation['min_length']} characters")

    if "max_length" in validation and len(str(field_value)) > int(validation["max_length"]):
        errors.append(f"{label} must have at most {validation['max_length']} characters")

    # 4. Regex
    if "regex" in validation:
        pattern = validation["regex"]
        if not re.search(pattern, str(field_value)):
            errors.append("Value does not match required format")

    # 5. Date not in future
    if validation.get("date_not_in_future") is True:
        parsed_date: date | None = None
        if isinstance(field_value, datetime):
            parsed_date = field_value.date()
        elif isinstance(field_value, date):
            parsed_date = field_value
        elif isinstance(field_value, str):
            try:
                parsed_date = datetime.strptime(field_value.strip()[:10], "%Y-%m-%d").date()
            except ValueError:
                errors.append(f"{label} must be a valid date in YYYY-MM-DD format")

        if parsed_date and parsed_date > date.today():
            errors.append("Date cannot be in the future")

    # 6. File types / size
    if "file_types" in validation and isinstance(field_value, str):
        allowed = [ext.lower() for ext in validation["file_types"]]
        val_lower = field_value.lower()
        if not any(
            val_lower.endswith(ext) or (ext.startswith(".") and val_lower.endswith(ext))
            for ext in allowed
        ):
            errors.append(f"File must be of allowed type: {', '.join(validation['file_types'])}")

    # 7. Restricted when conditional restriction
    if "restricted_when" in validation:
        res = validation["restricted_when"]
        cond = res.get("condition")
        allowed_values = res.get("allowed_values", [])
        if evaluate_rule(cond, values, context) and field_value not in allowed_values:
            errors.append("Selected option is not allowed under current conditions")

    return errors
