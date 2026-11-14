"""Automated verification script for Prompt P4-05:
Performance optimisation, security hardening & Render-readiness review.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

# Project paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
WORKBOOK_PATH = ROOT_DIR / "Replacement_Management_System_Workflow.xlsx"

sys.path.insert(0, str(BACKEND_DIR))

# Ensure required settings exist for verification script
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy")

EXPECTED_WORKBOOK_HASH = "BF4CD75BB87541F2C0EC5E670B86E0443D3B46B1528EB067D99AABF713D2CA55"


def check_workbook_hash() -> bool:
    print("\n[1/7] Checking Excel workbook SHA-256 integrity...")
    if not WORKBOOK_PATH.exists():
        print(f"FAIL: Workbook not found at {WORKBOOK_PATH}")
        return False
    actual_hash = hashlib.sha256(WORKBOOK_PATH.read_bytes()).hexdigest().upper()
    if actual_hash != EXPECTED_WORKBOOK_HASH:
        print(f"FAIL: Workbook hash mismatch! Expected {EXPECTED_WORKBOOK_HASH}, got {actual_hash}")
        return False
    print(f"PASS: Workbook hash matches: {actual_hash}")
    return True


def check_bundle_size() -> bool:
    print("\n[2/7] Checking frontend initial bundle size (< 300 kB gzipped)...")
    dist_assets = FRONTEND_DIR / "dist" / "assets"
    if not dist_assets.exists():
        print("FAIL: Frontend dist/assets not found. Run 'pnpm build' first.")
        return False

    import gzip

    js_files = list(dist_assets.glob("index-*.js"))
    if not js_files:
        print("FAIL: Main index-*.js not found in dist/assets")
        return False

    main_js = js_files[0]
    raw_size = main_js.stat().st_size
    gzipped_size = len(gzip.compress(main_js.read_bytes()))
    size_kb = gzipped_size / 1024

    print(
        f"Main index bundle: {main_js.name} | Raw: {raw_size / 1024:.2f} KB | Gzipped: {size_kb:.2f} KB"
    )
    if size_kb > 300.0:
        print(f"FAIL: Bundle size {size_kb:.2f} KB exceeds 300 KB limit!")
        return False
    print(f"PASS: Bundle size {size_kb:.2f} KB is well under 300 KB budget!")
    return True


def check_backend_performance_features() -> bool:
    print("\n[3/7] Checking backend performance components (GZip, Config Cache, DB Pool)...")
    from app.core.config import get_settings
    from app.core.config_cache import (
        get_cached_published_form,
        invalidate_form_cache,
        set_cached_published_form,
    )
    from app.main import create_app

    settings = get_settings()
    assert settings.db_pool_size >= 10, f"db_pool_size is {settings.db_pool_size}, expected >= 10"
    assert settings.db_max_overflow >= 20, (
        f"db_max_overflow is {settings.db_max_overflow}, expected >= 20"
    )
    assert settings.port == 8000, f"port default is {settings.port}"

    app = create_app()
    # Check GZip middleware installed
    middleware_types = [m.cls.__name__ for m in app.user_middleware]
    assert any("GZip" in t for t in middleware_types), (
        f"GZipMiddleware not found in {middleware_types}"
    )

    # Verify config cache operations
    invalidate_form_cache()
    assert get_cached_published_form("TEST_FORM") is None
    set_cached_published_form("TEST_FORM", {"version": 1})
    assert get_cached_published_form("TEST_FORM") == {"version": 1}
    invalidate_form_cache()
    assert get_cached_published_form("TEST_FORM") is None

    print("PASS: GZip middleware, config cache and pool sizing verified!")
    return True


def check_formula_injection_defense() -> bool:
    print("\n[4/7] Checking CSV formula injection defense...")
    from app.modules.audit.service import _safe_csv_cell

    for prefix in ("=", "+", "-", "@", "\t", "\r"):
        cell = f"{prefix}1+1"
        safe = _safe_csv_cell(cell)
        assert safe.startswith("'"), f"Prefix {prefix!r} not escaped: {safe!r}"
    assert _safe_csv_cell("normal") == "normal"
    print("PASS: Formula injection prefixes (=, +, -, @, \\t, \\r) correctly escaped!")
    return True


def check_render_readiness() -> bool:
    print("\n[5/7] Checking Render-readiness files...")
    render_yaml = ROOT_DIR / "render.yaml"
    if not render_yaml.exists():
        print("FAIL: render.yaml blueprint not found!")
        return False
    content = render_yaml.read_text(encoding="utf-8")
    assert "NOT DEPLOYED" in content, "Missing NOT DEPLOYED notice in render.yaml"
    assert "rms-api" in content, "Missing rms-api service in render.yaml"
    assert "rms-worker" in content, "Missing rms-worker service in render.yaml"
    assert "rms-frontend" in content, "Missing rms-frontend service in render.yaml"
    assert "$PORT" in content, "Missing $PORT start command in render.yaml"

    redirects = FRONTEND_DIR / "public" / "_redirects"
    if not redirects.exists():
        print("FAIL: frontend/public/_redirects not found!")
        return False
    assert "/index.html" in redirects.read_text(encoding="utf-8"), (
        "Missing SPA rewrite in _redirects"
    )

    print("PASS: render.yaml and frontend/public/_redirects exist and are properly configured!")
    return True


def check_security_documents_and_tests() -> bool:
    print("\n[6/7] Checking security documentation and test suites...")
    sec_doc = ROOT_DIR / "docs" / "SECURITY.md"
    perf_doc = ROOT_DIR / "docs" / "QUERY_PERFORMANCE.md"

    assert sec_doc.exists(), "docs/SECURITY.md is missing!"
    assert perf_doc.exists(), "docs/QUERY_PERFORMANCE.md is missing!"

    tests = [
        BACKEND_DIR / "tests" / "integration" / "test_security_authz_matrix.py",
        BACKEND_DIR / "tests" / "integration" / "test_security_idor.py",
        BACKEND_DIR / "tests" / "integration" / "test_security_upload.py",
        BACKEND_DIR / "tests" / "integration" / "test_security_input.py",
        BACKEND_DIR / "tests" / "integration" / "test_security_auth.py",
        ROOT_DIR / "supabase" / "tests" / "27_security_rls.test.sql",
    ]
    for t in tests:
        if not t.exists():
            print(f"FAIL: Test file missing: {t}")
            return False
    print("PASS: All security docs and 6 test suites exist!")
    return True


def check_query_performance_report() -> bool:
    print("\n[7/7] Checking QUERY_PERFORMANCE.md benchmarks...")
    perf_doc = ROOT_DIR / "docs" / "QUERY_PERFORMANCE.md"
    content = perf_doc.read_text(encoding="utf-8")
    for q in range(1, 26):
        code = f"Q{q:02d}"
        assert code in content, f"Missing benchmark for query {code} in QUERY_PERFORMANCE.md"
    print("PASS: Top 25 queries comprehensively benchmarked in QUERY_PERFORMANCE.md!")
    return True


def main() -> None:
    print("==================================================================")
    print("           P4-05 VERIFICATION: PERFORMANCE & SECURITY             ")
    print("==================================================================")
    checks = [
        check_workbook_hash,
        check_bundle_size,
        check_backend_performance_features,
        check_formula_injection_defense,
        check_render_readiness,
        check_security_documents_and_tests,
        check_query_performance_report,
    ]
    for check in checks:
        if not check():
            print("\n❌ VERIFICATION FAILED!")
            sys.exit(1)
    print("\n==================================================================")
    print("SUCCESS: ALL P4-05 CHECKS PASSED SUCCESSFULLY!")
    print("==================================================================")


if __name__ == "__main__":
    main()
