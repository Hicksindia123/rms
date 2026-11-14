"""Settings, idempotency hashing, pagination, storage paths and log redaction (no DB)."""

import re
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, ValidationFailed
from app.core.idempotency import request_hash
from app.core.logging import REDACTED, redact_sensitive
from app.shared.pagination import PageParams
from app.shared.storage import Bucket, StorageService, build_object_path

# --- settings ------------------------------------------------------------------------------------


def test_missing_required_settings_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_app_env_is_restricted() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="staging")  # type: ignore[arg-type,call-arg]


def test_settings_normalisation() -> None:
    s = Settings(  # type: ignore[call-arg]
        database_url="postgresql://rms_api:pw@127.0.0.1:54322/postgres",
        supabase_url="http://127.0.0.1:54321/",
        cors_origins="http://localhost:5173/, https://rms.example.test",
        supabase_jwks_url="",
    )
    assert s.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert "pw" not in repr(s)
    assert s.cors_origins == ["http://localhost:5173", "https://rms.example.test"]
    assert s.jwks_url == "http://127.0.0.1:54321/auth/v1/.well-known/jwks.json"
    assert s.jwt_issuer == "http://127.0.0.1:54321/auth/v1"


def test_wildcard_cors_rejected_in_prod() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(app_env="prod", cors_origins="*")  # type: ignore[call-arg]


# --- idempotency hash ----------------------------------------------------------------------------


def test_request_hash_is_canonical_for_json() -> None:
    a = request_hash("POST", "/api/v1/x", b'{"a": 1, "b": [1, 2]}')
    b = request_hash("post", "/api/v1/x", b'{"b":[1,2],"a":1}')
    assert a == b


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PUT", "/api/v1/x", b'{"a":1}'),
        ("POST", "/api/v1/y", b'{"a":1}'),
        ("POST", "/api/v1/x", b'{"a":2}'),
    ],
)
def test_request_hash_differs_by_method_path_body(method: str, path: str, body: bytes) -> None:
    assert request_hash("POST", "/api/v1/x", b'{"a":1}') != request_hash(method, path, body)


# --- pagination ----------------------------------------------------------------------------------


def test_order_by_uses_allow_list() -> None:
    params = PageParams(page=2, page_size=10, sort=("-created_at", "code"))
    assert params.offset == 10
    allowed = {"code": "d.code", "created_at": "d.created_at"}
    assert params.order_by_sql(allowed, "d.code asc") == "d.created_at desc, d.code asc"
    assert PageParams(1, 10).order_by_sql(allowed, "d.code asc") == "d.code asc"
    with pytest.raises(ValidationFailed):
        PageParams(1, 10, sort=("password",)).order_by_sql(allowed, "x")


def test_filters_use_allow_list() -> None:
    params = PageParams(1, 10, filters={"code": "A"})
    assert params.checked_filters({"code": "d.code"}) == {"d.code": "A"}
    with pytest.raises(ValidationFailed):
        PageParams(1, 10, filters={"secret": "x"}).checked_filters({"code": "d.code"})


# --- storage -------------------------------------------------------------------------------------


def test_object_paths_are_server_generated() -> None:
    gs = uuid.uuid4()
    path = build_object_path(gs, "video", ".MP4")
    assert re.fullmatch(rf"gs/{gs}/video/[0-9a-f-]{{36}}\.mp4", path)
    assert build_object_path(gs, "video", "mp4") != path
    for kind, ext in [("../etc", "mp4"), ("video", "mp4/../x"), ("Video", "mp4"), ("video", "")]:
        with pytest.raises(ValueError, match="invalid"):
            build_object_path(gs, kind, ext)


class _FakeBucket:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def create_signed_upload_url(self, path: str) -> dict[str, str]:
        self.calls.append(("upload", path))
        return {
            "signed_url": f"http://s/{path}?token=t",
            "signedUrl": "",
            "token": "t",
            "path": path,
        }

    def create_signed_url(self, path: str, expires_in: int) -> dict[str, Any]:
        self.calls.append(("sign", (path, expires_in)))
        return {"signedURL": f"http://s/{path}?e={expires_in}"}

    def exists(self, path: str) -> bool:
        return path.endswith("present.mp4")

    def info(self, path: str) -> dict[str, Any]:
        return {"size": 1234}

    def remove(self, paths: list[str]) -> list[Any]:
        self.calls.append(("remove", paths))
        return []


class _FakeStorage:
    def __init__(self) -> None:
        self.bucket = _FakeBucket()
        self.used: list[str] = []

    def from_(self, bucket_id: str) -> _FakeBucket:
        self.used.append(bucket_id)
        return self.bucket


def test_storage_service_wraps_client() -> None:
    fake = _FakeStorage()
    svc = StorageService(fake, signed_url_ttl_seconds=600)
    up = svc.create_signed_upload_url(Bucket.VIDEOS, "gs/1/video/a.mp4")
    assert up.token == "t"  # noqa: S105 - fake token from the fake client
    assert up.bucket == "rms-videos"
    assert svc.create_signed_url(Bucket.DOCUMENTS, "p") == "http://s/p?e=600"  # TTL from settings
    assert svc.create_signed_url(Bucket.DOCUMENTS, "p", ttl_seconds=30).endswith("e=30")
    assert svc.object_info(Bucket.VIDEOS, "gs/present.mp4").size == 1234
    assert svc.object_info(Bucket.VIDEOS, "gs/missing.mp4").exists is False
    svc.delete(Bucket.VIDEOS, "gs/1/video/a.mp4")
    assert ("remove", ["gs/1/video/a.mp4"]) in fake.bucket.calls
    assert set(fake.used) == {"rms-videos", "rms-documents"}


def test_storage_requires_service_role_key(settings: Settings) -> None:
    from app.shared.storage import create_storage_service

    assert settings.supabase_service_role_key is None
    with pytest.raises(ServiceUnavailable) as exc:
        create_storage_service(settings)
    assert exc.value.code == "STORAGE_DISABLED"


# --- logging -------------------------------------------------------------------------------------


def test_sensitive_log_fields_are_redacted() -> None:
    event = {
        "event": "x",
        "authorization": "Bearer abc",
        "access_token": "t",
        "Password": "p",
        "user_id": "u",
    }
    out = redact_sensitive(None, "info", event)
    assert out["authorization"] == out["access_token"] == out["Password"] == REDACTED
    assert out["user_id"] == "u"
