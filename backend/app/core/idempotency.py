"""Idempotency for command endpoints (G-16, master plan §8.7, CLAUDE.md rule f).

Usage in a command (inside the command's own transaction, so the key row commits or rolls back
together with the business change):

    with uow.transaction(user.id) as session:
        result = run_idempotent(session, idem, user.id, lambda: (201, do_the_work(session)))
    return result.to_response()

* First call: the key is inserted, the command runs, the response is stored with it.
* Replay with the same key and the same request hash: the stored status and body are returned
  unchanged (`Idempotency-Replayed: true` header); the command does not run again.
* Same key with a different request (hash, endpoint or user): 409 IDEMPOTENCY_CONFLICT.
* If the command fails, the transaction rolls back and the key is released, so the client can
  retry with the same key.
* Concurrent duplicates: the second INSERT blocks on the first transaction's uncommitted row and
  then sees the stored response.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import bindparam

from app.core.errors import IdempotencyConflict, ValidationFailed

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotency-Replayed"
_MIN_KEY, _MAX_KEY = 8, 200  # rms_private.idempotency_keys.key CHECK


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    key: str
    endpoint: str
    request_hash: str


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    status_code: int
    body: Any
    replayed: bool

    def to_response(self) -> JSONResponse:
        headers = {REPLAYED_HEADER: "true"} if self.replayed else None
        return JSONResponse(status_code=self.status_code, content=self.body, headers=headers)


def request_hash(method: str, path: str, body: bytes) -> str:
    """SHA-256 over method, path and the body (JSON canonicalised: key order does not matter)."""
    try:
        canonical = json.dumps(
            json.loads(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    except (UnicodeDecodeError, json.JSONDecodeError):
        canonical = body
    digest = hashlib.sha256()
    for part in (method.upper().encode(), path.encode(), canonical):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


async def get_idempotency_key(
    request: Request,
    idempotency_key: Annotated[
        str | None,
        Header(alias=IDEMPOTENCY_HEADER, description="Client-generated unique key (8-200 chars)"),
    ] = None,
) -> IdempotencyKey:
    """Dependency for command endpoints. The header is mandatory."""
    if idempotency_key is None or not idempotency_key.strip():
        raise ValidationFailed(
            f"The {IDEMPOTENCY_HEADER} header is required", code="IDEMPOTENCY_KEY_REQUIRED"
        )
    key = idempotency_key.strip()
    if not _MIN_KEY <= len(key) <= _MAX_KEY:
        raise ValidationFailed(
            f"{IDEMPOTENCY_HEADER} must be {_MIN_KEY}-{_MAX_KEY} characters",
            code="IDEMPOTENCY_KEY_INVALID",
        )
    body = await request.body()
    return IdempotencyKey(
        key=key,
        endpoint=f"{request.method} {request.url.path}",
        request_hash=request_hash(request.method, request.url.path, body),
    )


IdempotencyKeyDep = Annotated[IdempotencyKey, Depends(get_idempotency_key)]


# --- repository (SQL only) ----------------------------------------------------------------------

_CLAIM = text(
    """
    insert into rms_private.idempotency_keys (key, user_id, endpoint, request_hash)
    values (:key, :uid, :endpoint, :hash)
    on conflict (key) do nothing
    returning key
    """
)
_LOAD = text(
    """
    select user_id, endpoint, request_hash, response_status, response_body
      from rms_private.idempotency_keys
     where key = :key
    """
)
_COMPLETE = text(
    """
    update rms_private.idempotency_keys
       set response_status = :status, response_body = :body
     where key = :key
    """
).bindparams(bindparam("body", type_=JSONB))


def run_idempotent(
    session: Session,
    idem: IdempotencyKey,
    user_id: UUID,
    command: Callable[[], tuple[int, Any]],
) -> IdempotentResult:
    params = {"key": idem.key, "uid": user_id, "endpoint": idem.endpoint, "hash": idem.request_hash}
    if session.execute(_CLAIM, params).first() is None:
        row = session.execute(_LOAD, {"key": idem.key}).mappings().one()
        if (
            row["user_id"] != user_id
            or row["endpoint"] != idem.endpoint
            or row["request_hash"] != idem.request_hash
        ):
            raise IdempotencyConflict(
                "This Idempotency-Key was already used for a different request",
                details={"idempotency_key": idem.key},
            )
        if row["response_status"] is None:
            raise IdempotencyConflict(
                "A request with this Idempotency-Key is still being processed",
                code="IDEMPOTENCY_IN_PROGRESS",
            )
        return IdempotentResult(row["response_status"], row["response_body"], replayed=True)

    status_code, payload = command()
    body = jsonable_encoder(payload)
    session.execute(_COMPLETE, {"key": idem.key, "status": status_code, "body": body})
    return IdempotentResult(status_code, body, replayed=False)
