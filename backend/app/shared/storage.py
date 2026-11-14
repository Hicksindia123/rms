"""Supabase Storage helper (master plan §8.8, §9.6).

* Uses the service-role key. Besides the users admin service, this is the only place the key is
  used (CLAUDE.md rule i).
* Object paths are generated here, `gs/{gs_id}/{kind}/{uuid}.{ext}`, never from user file names.
* Download URLs are short-lived (SIGNED_URL_TTL_SECONDS). Callers check permissions first.
"""

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any, Protocol

import structlog
from storage3.exceptions import StorageApiError

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailable

log = structlog.get_logger("rms.storage")


class Bucket(StrEnum):
    """Buckets created by supabase/migrations/20261102000600_storage.sql."""

    VIDEOS = "rms-videos"
    DOCUMENTS = "rms-documents"
    BRANDING = "rms-branding"


_KIND = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_EXT = re.compile(r"^[a-z0-9]{1,8}$")


def build_object_path(gs_id: uuid.UUID, kind: str, ext: str) -> str:
    """Server-generated object path `gs/{gs_id}/{kind}/{uuid}.{ext}` (§8.8)."""
    ext = ext.lower().lstrip(".")
    if not _KIND.fullmatch(kind):
        raise ValueError(f"invalid object kind {kind!r}")
    if not _EXT.fullmatch(ext):
        raise ValueError(f"invalid file extension {ext!r}")
    return f"gs/{gs_id}/{kind}/{uuid.uuid4()}.{ext}"


@dataclass(frozen=True, slots=True)
class SignedUpload:
    bucket: str
    path: str
    signed_url: str
    token: str


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    exists: bool
    size: int | None
    content_type: str | None = None
    name: str | None = None
    bucket: str | None = None


@dataclass(frozen=True, slots=True)
class ResumableUpload:
    """Supabase Storage TUS endpoint for signed resumable uploads (header `x-signature`)."""

    endpoint: str
    bucket: str
    path: str
    token: str


class _BucketApi(Protocol):
    def create_signed_upload_url(self, path: str) -> Any: ...
    def create_signed_url(self, path: str, expires_in: int) -> Any: ...
    def exists(self, path: str) -> bool: ...
    def info(self, path: str) -> dict[str, Any]: ...
    def remove(self, paths: list[str]) -> Any: ...
    def upload(self, path: str, file: bytes, file_options: Any = None) -> Any: ...


class _StorageApi(Protocol):
    def from_(self, bucket_id: str) -> _BucketApi: ...


class StorageService:
    def __init__(
        self, storage: _StorageApi, *, signed_url_ttl_seconds: int, public_url: str = ""
    ) -> None:
        self._storage = storage
        self._ttl = signed_url_ttl_seconds
        self._public_url = public_url.rstrip("/")

    def _bucket(self, bucket: Bucket) -> _BucketApi:
        return self._storage.from_(bucket.value)

    def create_signed_upload_url(self, bucket: Bucket, path: str) -> SignedUpload:
        try:
            data = self._bucket(bucket).create_signed_upload_url(path)
        except StorageApiError as exc:
            raise self._unavailable("create_signed_upload_url", bucket, exc) from exc
        return SignedUpload(bucket.value, path, data["signed_url"], data["token"])

    def create_resumable_upload(self, bucket: Bucket, path: str) -> ResumableUpload:
        """Signed TUS upload (Supabase resumable uploads, for large videos). The token is the
        signed-upload token for exactly this bucket/path; the client sends it as `x-signature`."""
        signed = self.create_signed_upload_url(bucket, path)
        return ResumableUpload(
            endpoint=f"{self._public_url}/storage/v1/upload/resumable/sign",
            bucket=bucket.value,
            path=path,
            token=signed.token,
        )

    def create_signed_url(self, bucket: Bucket, path: str, ttl_seconds: int | None = None) -> str:
        try:
            data = self._bucket(bucket).create_signed_url(path, ttl_seconds or self._ttl)
        except StorageApiError as exc:
            raise self._unavailable("create_signed_url", bucket, exc) from exc
        url = data.get("signedURL") or data.get("signedUrl")
        if not url:
            raise ServiceUnavailable("Storage did not return a signed URL", code="STORAGE_ERROR")
        return str(url)

    def object_info(self, bucket: Bucket, path: str) -> ObjectInfo:
        try:
            if not self._bucket(bucket).exists(path):
                return ObjectInfo(exists=False, size=None)
            info = self._bucket(bucket).info(path)
        except StorageApiError as exc:
            raise self._unavailable("object_info", bucket, exc) from exc
        raw_meta = info.get("metadata")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        size = info.get("size")
        if size is None:
            size = meta.get("size")
        content_type = info.get("content_type") or meta.get("mimetype")
        return ObjectInfo(
            exists=True,
            size=int(size) if size is not None else None,
            content_type=str(content_type) if content_type else None,
            name=str(info["name"]) if info.get("name") else None,
            bucket=str(info["bucket_id"]) if info.get("bucket_id") else None,
        )

    def upload(self, bucket: Bucket, path: str, data: bytes, content_type: str) -> None:
        """Server-side upload of a file the backend generated itself (e.g. a slip PDF, DEC-41).
        Never overwrites: object paths are server generated and unique (§8.8)."""
        try:
            self._bucket(bucket).upload(
                path, data, {"content-type": content_type, "upsert": "false"}
            )
        except StorageApiError as exc:
            raise self._unavailable("upload", bucket, exc) from exc

    def delete(self, bucket: Bucket, path: str) -> None:
        try:
            self._bucket(bucket).remove([path])
        except StorageApiError as exc:
            raise self._unavailable("delete", bucket, exc) from exc

    @staticmethod
    def _unavailable(op: str, bucket: Bucket, exc: StorageApiError) -> ServiceUnavailable:
        log.error(
            "storage_error", op=op, bucket=bucket.value, status=str(exc.status), error=exc.message
        )
        return ServiceUnavailable("File storage request failed", code="STORAGE_ERROR")


def create_storage_service(settings: Settings) -> StorageService:
    from supabase import create_client

    if settings.supabase_service_role_key is None:
        raise ServiceUnavailable(
            "File storage is not configured (SUPABASE_SERVICE_ROLE_KEY)", code="STORAGE_DISABLED"
        )
    client = create_client(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value()
    )
    return StorageService(
        client.storage,
        signed_url_ttl_seconds=settings.signed_url_ttl_seconds,
        public_url=settings.supabase_url,
    )


@lru_cache
def _default_storage() -> StorageService:
    return create_storage_service(get_settings())


def get_storage() -> StorageService:
    """FastAPI dependency (lazy: no network access until a storage endpoint is used)."""
    return _default_storage()
