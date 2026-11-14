"""Local verification fixtures for P3-07 (party notification & GS closure engine).

Creates (and COMMITS) three goods slips in the local database, owned by the demo Replacement
Manager, and prints their ids as JSON:

* ``ro``         RO GS: stock in the Main Store, CN of 2 issued, replacement of 2 dispatched;
                 only the prior party notification (BR-38) is missing.
* ``csr``        approved CSR: handover with packaging accepted, packaging check, CN of 4 issued;
                 only the prior party notification is missing.
* ``incomplete`` RO GS whose replacement was never dispatched and whose CN party was not told:
                 closing it lists DENY_QTY_DISPATCHED and PRIOR_NOTIFICATION (G-15).

Local development only (the fixture builder is the integration-test one). Usage:
    uv run python scripts/verify_p3_07.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(backend_root / ".env")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from tests.integration.test_closure import _build_gs  # noqa: E402

RM_EMAIL = os.environ.get("RMS_DEMO_RM_EMAIL", "pratham@rms.local")
# Fixture setup needs the local superuser (the CSR handover end state is written with triggers
# suspended, as in the integration tests). Default: the Supabase CLI's local database URL.
LOCAL_SUPERUSER_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"


def main() -> int:
    url = make_url(os.environ.get("RMS_FIXTURE_DATABASE_URL", LOCAL_SUPERUSER_URL))
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"Refusing to write fixtures to non-local host {url.host!r}", file=sys.stderr)
        return 2
    engine = create_engine(url)
    with engine.begin() as conn:
        rm_id = conn.execute(
            text("select id from public.profiles where email = :e"), {"e": RM_EMAIL}
        ).scalar_one()
        out = {}
        for name, kwargs in (
            ("ro", {}),
            ("csr", {"csr": True}),
            ("incomplete", {"dispatch": False}),
        ):
            gs = _build_gs(conn, rm_id, **kwargs)
            out[name] = {"gs_id": str(gs["gs_id"]), "gs_no": gs["gs_no"]}
    engine.dispose()
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
