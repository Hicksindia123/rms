"""Standard list query parameters and the paged response model.

Query string:
    ?page=1&page_size=25&sort=-created_at,code&filter[is_active]=true

* page >= 1; page_size >= 1 and silently capped at PAGE_SIZE_MAX.
* sort: comma-separated field names, `-` prefix for descending.
* filter[<field>]=<value>: equality filters.
Sort and filter fields are validated against an allow-list supplied by the repository, which maps
public field names to SQL column expressions, so no client text ever reaches SQL unescaped.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Query, Request
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import ValidationFailed

_FILTER_PARAM = re.compile(r"^filter\[([a-z][a-z0-9_]*)\]$")
_SORT_TOKEN = re.compile(r"^-?[a-z][a-z0-9_]*$")


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class PageParams:
    page: int
    page_size: int
    sort: tuple[str, ...] = ()
    filters: Mapping[str, str] = field(default_factory=dict)
    cursor: str | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def parse_cursor(self) -> tuple[str, str] | None:
        """Parse keyset cursor format 'timestamp|uuid' -> (timestamp_str, uuid_str)."""
        if not self.cursor:
            return None
        parts = self.cursor.split("|", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])
        return None

    def order_by_sql(self, allowed: Mapping[str, str], default: str) -> str:
        """ORDER BY body built only from allow-listed column expressions."""
        parts: list[str] = []
        for token in self.sort:
            name = token.lstrip("-")
            if name not in allowed:
                raise ValidationFailed(
                    f"Cannot sort by {name!r}",
                    code="INVALID_SORT",
                    details={"allowed": sorted(allowed)},
                )
            parts.append(f"{allowed[name]} {'desc' if token.startswith('-') else 'asc'}")
        return ", ".join(parts) if parts else default

    def checked_filters(self, allowed: Mapping[str, str]) -> dict[str, str]:
        """Return {sql column: value} for the requested filters; unknown fields are rejected."""
        unknown = sorted(set(self.filters) - set(allowed))
        if unknown:
            raise ValidationFailed(
                f"Cannot filter by {', '.join(unknown)}",
                code="INVALID_FILTER",
                details={"allowed": sorted(allowed)},
            )
        return {allowed[name]: value for name, value in self.filters.items()}


def page_params(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(ge=1)] = None,
    sort: Annotated[str | None, Query(max_length=200, examples=["-created_at,code"])] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> PageParams:
    size = min(page_size or settings.page_size_default, settings.page_size_max)
    tokens: tuple[str, ...] = ()
    if sort:
        tokens = tuple(t.strip() for t in sort.split(",") if t.strip())
        bad = [t for t in tokens if not _SORT_TOKEN.fullmatch(t)]
        if bad:
            raise ValidationFailed(
                "Invalid sort expression", code="INVALID_SORT", details={"invalid": bad}
            )
    filters: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        match = _FILTER_PARAM.fullmatch(key)
        if match:
            filters[match.group(1)] = value
    return PageParams(page=page, page_size=size, sort=tokens, filters=filters, cursor=cursor)


PageParamsDep = Annotated[PageParams, Depends(page_params)]
