"""Migrations must schema-qualify objects from extensions installed in schema `extensions`.

The `supabase db push` session on Supabase Cloud has no `extensions` in its search_path, so an
unqualified `gin_trgm_ops` failed there with SQLSTATE 42704 (20261106000600, fixed 2026-11-14)
although it worked locally. Statements inside function bodies with `set search_path` are covered by
the pgTAP suites; this test guards top-level DDL such as index definitions and column types.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"

# Objects from pg_trgm / citext / pgcrypto (created `with schema extensions` in 20261102000100).
_UNQUALIFIED = re.compile(
    r"(?<![.\w])(gin_trgm_ops|gist_trgm_ops|citext|similarity\s*\(|word_similarity\s*\("
    r"|gen_random_bytes\s*\(|digest\s*\(|crypt\s*\(|gen_salt\s*\(|hmac\s*\()",
    re.IGNORECASE,
)


def _code_lines(sql: str) -> list[tuple[int, str]]:
    """Lines without `--` comments and without `create extension` statements."""
    out: list[tuple[int, str]] = []
    for no, line in enumerate(sql.splitlines(), start=1):
        code = line.split("--", 1)[0]
        if not code.strip() or re.match(r"\s*create\s+extension", code, re.IGNORECASE):
            continue
        out.append((no, code))
    return out


def test_migrations_directory_exists() -> None:
    assert MIGRATIONS.is_dir(), MIGRATIONS
    assert any(MIGRATIONS.glob("*.sql"))


def test_extension_objects_are_schema_qualified() -> None:
    offenders = [
        f"{path.name}:{no}: {code.strip()}"
        for path in sorted(MIGRATIONS.glob("*.sql"))
        for no, code in _code_lines(path.read_text(encoding="utf-8"))
        if _UNQUALIFIED.search(code)
    ]
    assert not offenders, "Qualify with `extensions.`:\n" + "\n".join(offenders)
