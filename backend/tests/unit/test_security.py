"""Access-token verification: exp, aud, iss, signature, algorithm policy (§9.2)."""

import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import Settings
from app.core.errors import Unauthenticated
from app.core.security import TokenVerifier
from tests.conftest import TEST_JWT_SECRET, JwtFactory


def test_valid_hs256_token_in_test_env(settings: Settings, make_token: JwtFactory) -> None:
    uid = uuid.uuid4()
    claims = TokenVerifier(settings).verify(make_token(uid, email="a@b.test"))
    assert claims.user_id == uid
    assert claims.email == "a@b.test"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"expires_in": -120}, "TOKEN_EXPIRED"),
        ({"audience": "anon"}, "INVALID_TOKEN"),
        ({"issuer": "https://evil.test/auth/v1"}, "INVALID_TOKEN"),
        ({"secret": "wrong-secret-" + "x" * 40}, "INVALID_TOKEN"),
    ],
)
def test_invalid_tokens_are_rejected(
    settings: Settings, make_token: JwtFactory, kwargs: dict[str, Any], code: str
) -> None:
    with pytest.raises(Unauthenticated) as exc:
        TokenVerifier(settings).verify(make_token(uuid.uuid4(), **kwargs))
    assert exc.value.code == code
    assert exc.value.status_code == 401


def test_non_uuid_subject_is_rejected(settings: Settings, make_token: JwtFactory) -> None:
    with pytest.raises(Unauthenticated):
        TokenVerifier(settings).verify(make_token("service-account"))


def test_hs256_is_refused_outside_local(make_token: JwtFactory) -> None:
    prod = Settings(  # type: ignore[call-arg]
        app_env="prod",
        supabase_jwt_secret=TEST_JWT_SECRET,
        database_url="postgresql://rms_api:x@db.example.invalid:5432/postgres?sslmode=require",
    )
    token = make_token(uuid.uuid4(), issuer=prod.jwt_issuer)
    with pytest.raises(Unauthenticated) as exc:
        TokenVerifier(prod).verify(token)
    assert exc.value.code == "INVALID_TOKEN"


def test_alg_none_and_garbage_are_rejected(settings: Settings) -> None:
    unsigned = jwt.encode({"sub": str(uuid.uuid4())}, key=None, algorithm="none")  # type: ignore[arg-type]
    for token in (unsigned, "not-a-jwt"):
        with pytest.raises(Unauthenticated):
            TokenVerifier(settings).verify(token)


class _FakeJwks:
    """Stands in for PyJWKClient (no network in unit tests)."""

    def __init__(self, public_key: Any) -> None:
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        assert jwt.get_unverified_header(token)["kid"] == "test-kid"

        class _Key:
            key = self.public_key

        return _Key()


def test_es256_token_is_verified_with_jwks(settings: Settings) -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    verifier = TokenVerifier(settings)
    verifier._jwks = _FakeJwks(private.public_key())  # type: ignore[assignment]
    uid = uuid.uuid4()
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(uid), "aud": "authenticated", "iss": settings.jwt_issuer, "exp": now + 60},
        private,
        algorithm="ES256",
        headers={"kid": "test-kid"},
    )
    assert verifier.verify(token).user_id == uid

    other = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode(
        {"sub": str(uid), "aud": "authenticated", "iss": settings.jwt_issuer, "exp": now + 60},
        other,
        algorithm="ES256",
        headers={"kid": "test-kid"},
    )
    with pytest.raises(Unauthenticated):
        verifier.verify(forged)
