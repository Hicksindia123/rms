"""Service for number series management and preview (prompt P1-08)."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import text

from app.core.context import get_request_id
from app.core.db import UnitOfWork
from app.core.errors import NotFound, ValidationFailed
from app.core.security import CurrentUser
from app.modules.config.numbering.schemas import (
    NumberPreviewOut,
    NumberSeriesOut,
    NumberSeriesUpdate,
)
from app.modules.config.options import repository as options_repo


def render_number_pattern(
    pattern: str,
    prefix: str | None,
    seq: int,
    on_date: date,
    fy_start_month: int = 4,
    fy_format: str = "LONG",
    reset_policy: str = "YEARLY_FY",
    scope: str | None = None,
) -> tuple[str, str, str]:
    """Render a pattern string into a formatted number along with (fy_string, period_key).

    `scope` replaces the {STORE} token (DEC-65: one counter per Intermediate Store), same as
    rms_private.next_number(series, date, scope)."""
    year = on_date.year
    month = on_date.month

    # FY calculation
    fy_start = year if month >= fy_start_month else year - 1

    if fy_start_month == 1:
        fy_str = str(fy_start)
    else:
        next_yr_short = (fy_start + 1) % 100
        cur_yr_short = fy_start % 100
        if fy_format == "LONG":
            fy_str = f"{fy_start}-{next_yr_short:02d}"
        elif fy_format == "COMPACT":
            fy_str = f"{cur_yr_short:02d}{next_yr_short:02d}"
        elif fy_format == "SHORT":
            fy_str = f"{cur_yr_short:02d}-{next_yr_short:02d}"
        else:
            fy_str = f"{fy_start}-{next_yr_short:02d}"

    # Period key
    if reset_policy == "NEVER":
        period_key = "ALL"
    elif reset_policy == "YEARLY_FY":
        period_key = f"FY{fy_start}"
    elif reset_policy == "MONTHLY":
        period_key = f"{year:04d}-{month:02d}"
    else:
        period_key = f"FY{fy_start}"

    if "{STORE}" in pattern:
        period_key = f"{period_key}:{scope or ''}"

    # String token replacements
    res = pattern
    res = res.replace("{PREFIX}", prefix or "")
    res = res.replace("{STORE}", scope or "")
    res = res.replace("{FY}", fy_str)
    res = res.replace("{YYYY}", f"{year:04d}")
    res = res.replace("{YY}", f"{year % 100:02d}")
    res = res.replace("{MM}", f"{month:02d}")

    # Sequence padding {SEQ:n}
    pad_match = re.search(r"\{SEQ:([0-9]+)\}", res)
    if pad_match:
        pad_len = int(pad_match.group(1))
        seq_str = str(seq)
        if len(seq_str) < pad_len:
            seq_str = seq_str.zfill(pad_len)
        res = re.sub(r"\{SEQ:[0-9]+\}", seq_str, res)

    # Standard {SEQ}
    res = res.replace("{SEQ}", str(seq))

    return res, fy_str, period_key


class NumberSeriesService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_series(self, user: CurrentUser) -> list[NumberSeriesOut]:
        with self._uow.transaction(user.id) as session:
            rows = session.execute(
                text(
                    """
                    select s.*,
                           coalesce(
                             (select max(c.last_value)
                              from public.number_series_counters c
                              where c.series_id = s.id), 0
                           ) as max_used_counter
                    from public.number_series s
                    order by s.code asc
                    """
                )
            ).mappings()
            result = []
            for r in rows:
                item = dict(r)
                item["is_provisional_gs"] = item["code"] == "GS"
                result.append(NumberSeriesOut.model_validate(item))
            return result

    def get_series(self, user: CurrentUser, code: str) -> NumberSeriesOut:
        with self._uow.transaction(user.id) as session:
            row = (
                session.execute(
                    text(
                        """
                    select s.*,
                           coalesce(
                             (select max(c.last_value)
                              from public.number_series_counters c
                              where c.series_id = s.id), 0
                           ) as max_used_counter
                    from public.number_series s
                    where s.code = :code
                    """
                    ),
                    {"code": code},
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound(f"Number series '{code}' not found")
            item = dict(row)
            item["is_provisional_gs"] = item["code"] == "GS"
            return NumberSeriesOut.model_validate(item)

    def update_series(
        self, user: CurrentUser, code: str, payload: NumberSeriesUpdate
    ) -> NumberSeriesOut:
        with self._uow.transaction(user.id) as session:
            current = self.get_series(user, code)

            # Validate start_value cannot be lower than max counter used
            if payload.start_value < current.max_used_counter:
                raise ValidationFailed(
                    f"Start value ({payload.start_value}) cannot be lower than "
                    f"the maximum used counter ({current.max_used_counter})."
                )

            # Update number series
            row = (
                session.execute(
                    text(
                        """
                    update public.number_series
                    set name = coalesce(:name, name),
                        prefix = :prefix,
                        pattern = :pattern,
                        reset_policy = :reset_policy,
                        fy_start_month = :fy_start_month,
                        fy_format = :fy_format,
                        start_value = :start_value,
                        is_active = :is_active,
                        updated_at = now()
                    where code = :code
                    returning *
                    """
                    ),
                    {
                        "code": code,
                        "name": payload.name,
                        "prefix": payload.prefix,
                        "pattern": payload.pattern,
                        "reset_policy": payload.reset_policy,
                        "fy_start_month": payload.fy_start_month,
                        "fy_format": payload.fy_format,
                        "start_value": payload.start_value,
                        "is_active": payload.is_active,
                    },
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound(f"Number series '{code}' not found")

            # Audit to config_change_log
            options_repo.log_config_change(
                session=session,
                entity_type="number_series",
                entity_id=code,
                action="UPDATE_NUMBER_SERIES",
                before=current.model_dump(mode="json"),
                after=dict(row),
                reason=payload.reason or f"Updated number series {code}",
                request_id=get_request_id(),
            )

            updated_dict = dict(row)
            updated_dict["is_provisional_gs"] = code == "GS"
            updated_dict["max_used_counter"] = current.max_used_counter
            return NumberSeriesOut.model_validate(updated_dict)

    def preview_numbers(
        self,
        user: CurrentUser,
        code: str,
        count: int = 3,
        on_date: date | None = None,
    ) -> NumberPreviewOut:
        target_date = on_date or date.today()
        series = self.get_series(user, code)

        with self._uow.transaction(user.id) as session:
            # DEC-65: a {STORE} series is previewed for the default Intermediate Store.
            scope = (
                session.execute(
                    text(
                        "select code from public.intermediate_stores where is_default and is_active"
                    )
                ).scalar()
                if "{STORE}" in series.pattern
                else None
            )
            # Determine period key
            _, fy_str, period_key = render_number_pattern(
                series.pattern,
                series.prefix,
                series.start_value,
                target_date,
                series.fy_start_month,
                series.fy_format,
                series.reset_policy,
                scope,
            )

            # Query existing counter for that period
            counter_val = session.execute(
                text(
                    """
                    select last_value from public.number_series_counters
                    where series_id = :sid and period_key = :pkey
                    """
                ),
                {"sid": series.id, "pkey": period_key},
            ).scalar()

            start_seq = counter_val + 1 if counter_val is not None else series.start_value

            next_numbers = []
            for i in range(count):
                formatted, _, _ = render_number_pattern(
                    series.pattern,
                    series.prefix,
                    start_seq + i,
                    target_date,
                    series.fy_start_month,
                    series.fy_format,
                    series.reset_policy,
                    scope,
                )
                next_numbers.append(formatted)

            return NumberPreviewOut(
                code=code,
                pattern=series.pattern,
                on_date=target_date,
                fy_string=fy_str,
                period_key=period_key,
                next_numbers=next_numbers,
            )
