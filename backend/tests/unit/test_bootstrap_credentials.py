"""bootstrap_super_admin.py credential rules (production audit 2026-11-14, credentials policy)."""

import pytest

from scripts.bootstrap_super_admin import LOCAL_EMAIL, LOCAL_PASSWORD, resolve_credentials


def test_local_keeps_the_documented_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("SUPER_ADMIN_EMAIL", "SUPER_ADMIN_PASSWORD", "SUPER_ADMIN_NAME"):
        monkeypatch.delenv(var, raising=False)
    assert resolve_credentials(None, None, None, is_local=True)[:2] == (LOCAL_EMAIL, LOCAL_PASSWORD)


def test_environment_is_used_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPER_ADMIN_EMAIL", "Owner@Example.com")
    monkeypatch.setenv("SUPER_ADMIN_PASSWORD", "Str0ngEnough")
    monkeypatch.setenv("SUPER_ADMIN_NAME", "Owner")
    assert resolve_credentials(None, None, None, is_local=False) == (
        "owner@example.com",
        "Str0ngEnough",
        "Owner",
    )


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("admin@rms.local", "Str0ngEnough"),  # local-only address
        ("owner@example.com", LOCAL_PASSWORD),  # published default password
        ("owner@example.com", "short1"),  # DEC-50: too short
        ("owner@example.com", "lettersonly"),  # DEC-50: no digit
        ("not-an-email", "Str0ngEnough"),
    ],
)
def test_unsafe_credentials_are_refused_outside_local(email: str, password: str) -> None:
    with pytest.raises(ValueError):
        resolve_credentials(email, password, None, is_local=False)
