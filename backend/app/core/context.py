"""Per-request context shared by logging, error handling and the Unit of Work.

The request id lives in a ContextVar (set by RequestContextMiddleware) and in the ASGI scope state,
so both async code and sync endpoints running in the threadpool can read it.
"""

import re
import uuid
from contextvars import ContextVar

from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

request_id_var: ContextVar[str | None] = ContextVar("rms_request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def accept_request_id(incoming: str | None) -> str:
    """Use the caller's X-Request-ID when it is well-formed, otherwise generate one."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return new_request_id()


def get_request_id(request: Request | None = None) -> str | None:
    if request is not None:
        rid = getattr(request.state, "request_id", None)
        if isinstance(rid, str):
            return rid
    return request_id_var.get()
