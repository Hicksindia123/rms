"""Shared advanced filter parser, validator and SQL query builder (P4-04).

Defines a safe, typed specification for advanced filtering across list endpoints:
- FilterClause: field, operator (op), value
- FilterGroup: conjunction ('AND' | 'OR'), clauses
- Allowlist validation: strictly validates field names against an allowed set per endpoint,
  preventing SQL injection, unindexed scans, and internal field leakage.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.errors import ValidationFailed

Operator = Literal[
    "eq",  # equals (=)
    "neq",  # not equals (<>)
    "contains",  # ILIKE %val%
    "starts_with",  # ILIKE val%
    "ends_with",  # ILIKE %val
    "in",  # IN (...)
    "not_in",  # NOT IN (...)
    "gt",  # >
    "gte",  # >=
    "lt",  # <
    "lte",  # <=
    "between",  # BETWEEN val1 AND val2
    "is_null",  # IS NULL
    "is_not_null",  # IS NOT NULL
]

VALID_OPERATORS: frozenset[str] = frozenset(
    {
        "eq",
        "neq",
        "contains",
        "starts_with",
        "ends_with",
        "in",
        "not_in",
        "gt",
        "gte",
        "lt",
        "lte",
        "between",
        "is_null",
        "is_not_null",
    }
)


class FilterClause(BaseModel):
    field: str = Field(..., description="Target field name from the endpoint allowlist")
    op: Operator = Field(default="eq", description="Comparison operator")
    value: Any = Field(default=None, description="Operand value (scalar, array, or null)")

    @field_validator("field")
    @classmethod
    def validate_field_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Filter field name cannot be empty")
        return cleaned

    @field_validator("op")
    @classmethod
    def validate_op(cls, v: str) -> str:
        if v not in VALID_OPERATORS:
            raise ValueError(f"Unsupported filter operator '{v}'")
        return v


class FilterGroup(BaseModel):
    conjunction: Literal["AND", "OR"] = "AND"
    clauses: list[FilterClause] = Field(default_factory=list)


def parse_filters_param(raw: str | None) -> list[FilterClause]:
    """Parse a JSON string of filter clauses from a query param."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            # Single clause or wrapped
            data = data.get("clauses", [data])
        if not isinstance(data, list):
            raise ValueError("Expected a list of filter clauses")
        return [FilterClause.model_validate(item) for item in data]
    except Exception as exc:
        raise ValidationFailed(f"Invalid filters format: {exc}", code="INVALID_FILTERS") from exc


def validate_filter_allowlist(
    clauses: list[FilterClause],
    allowlist: frozenset[str],
) -> None:
    """Validate that every clause references an allowed field."""
    for clause in clauses:
        if clause.field not in allowlist:
            raise ValidationFailed(
                f"Filtering on field '{clause.field}' is not allowed",
                code="FILTER_FIELD_NOT_ALLOWED",
                details={"field": clause.field, "allowed": sorted(allowlist)},
            )
