"""Append a row to public.config_change_log (insert-only, G-17).

`changed_by` and `request_id` default to the transaction context set by the Unit of Work
(rms_private.current_actor() / current_request_id()), so callers never pass them.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def log_change(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None,
) -> None:
    db.execute(
        text(
            """
            insert into public.config_change_log
                   (entity_type, entity_id, action, before, after, reason)
            values (:et, :eid, :action, cast(:before as jsonb), cast(:after as jsonb), :reason)
            """
        ),
        {
            "et": entity_type,
            "eid": str(entity_id),
            "action": action,
            "before": json.dumps(before, default=str) if before is not None else None,
            "after": json.dumps(after, default=str) if after is not None else None,
            "reason": reason,
        },
    )
