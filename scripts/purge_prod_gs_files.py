"""Delete the uploaded goods-slip files (gs/ prefix) from Supabase Storage.

Companion to RMS_PROD_RESET_TEST_DATA.sql: the SQL clears the goods slips, this clears their
files (gate documents, unboxing photos/videos) through the Storage API, which is the supported
way to delete Storage objects. Only the gs/ folder of rms-documents and rms-videos is touched;
rms-branding (logo) is never touched.

Usage (PowerShell, from the repo root):
    $env:RMS_PURGE_SUPABASE_URL = "https://<project-ref>.supabase.co"
    $env:RMS_PURGE_SERVICE_ROLE_KEY = "<service_role key: Dashboard > Project Settings > API>"
    python scripts/purge_prod_gs_files.py            # dry run: lists what would be deleted
    python scripts/purge_prod_gs_files.py --delete   # deletes

The key is read from the environment only; it is never written to disk.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BUCKETS = ("rms-documents", "rms-videos")
PREFIX = "gs"
PAGE = 1000


def _request(method: str, url: str, key: str, body: dict[str, object]) -> object:
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc


def list_files(base: str, key: str, bucket: str, prefix: str) -> list[str]:
    """Every object path under prefix (folders are walked recursively)."""
    found: list[str] = []
    offset = 0
    while True:
        rows = _request(
            "POST",
            f"{base}/storage/v1/object/list/{bucket}",
            key,
            {"prefix": prefix, "limit": PAGE, "offset": offset},
        )
        assert isinstance(rows, list)
        for row in rows:
            path = f"{prefix}/{row['name']}"
            if row.get("id") is None:  # a folder
                found.extend(list_files(base, key, bucket, path))
            else:
                found.append(path)
        if len(rows) < PAGE:
            return found
        offset += PAGE


def main() -> int:
    base = os.environ.get("RMS_PURGE_SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("RMS_PURGE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        print("Set RMS_PURGE_SUPABASE_URL and RMS_PURGE_SERVICE_ROLE_KEY first.", file=sys.stderr)
        return 2
    delete = "--delete" in sys.argv[1:]

    total = 0
    for bucket in BUCKETS:
        files = list_files(base, key, bucket, PREFIX)
        total += len(files)
        print(f"{bucket}: {len(files)} file(s) under {PREFIX}/")
        for path in files:
            print(f"  {path}")
        if delete and files:
            for i in range(0, len(files), PAGE):
                chunk = files[i : i + PAGE]
                _request("DELETE", f"{base}/storage/v1/object/{bucket}", key, {"prefixes": chunk})
            left = list_files(base, key, bucket, PREFIX)
            print(f"{bucket}: deleted; {len(left)} file(s) left under {PREFIX}/")

    if not delete:
        print(f"\nDry run: {total} file(s) would be deleted. Re-run with --delete to delete them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
