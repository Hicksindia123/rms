"""Supabase access-token verification and the `get_current_user` dependency (master plan §9.2).

* Asymmetric tokens (RS256 / ES256) are verified against the JWKS fetched from SUPABASE_JWKS_URL
  and cached (PyJWKClient; refetched on an unknown `kid` and after JWKS_CACHE_TTL_SECONDS).
* HS256 tokens are accepted only when APP_ENV is local/test and SUPABASE_JWT_SECRET is set
  (the Supabase CLI's local fallback). In dev/prod they are rejected.
* `exp`, `aud` (= SUPABASE_JWT_AUDIENCE, "authenticated") and `iss` are always validated.
* The token itself is never logged.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import identity_repository as repo
from app.core.config import Settings, get_settings
from app.core.db import UowDep
from app.core.errors import PermissionDenied, ServiceUnavailable, Unauthenticated

log = structlog.get_logger("rms.auth")

ASYMMETRIC_ALGORITHMS = ("RS256", "ES256")
_CLOCK_SKEW_SECONDS = 30


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: UUID
    email: str | None
    session_id: str | None
    expires_at: int


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks = jwt.PyJWKClient(
            settings.jwks_url,
            cache_jwk_set=True,
            lifespan=settings.jwks_cache_ttl_seconds,
            timeout=5,
        )

    def _signing_key(self, token: str, alg: str) -> Any:
        if alg == "HS256":
            secret = self._settings.supabase_jwt_secret
            if not self._settings.is_local or secret is None:
                raise Unauthenticated("Token algorithm is not accepted", code="INVALID_TOKEN")
            return secret.get_secret_value()
        if alg in ASYMMETRIC_ALGORITHMS:
            try:
                return self._jwks.get_signing_key_from_jwt(token).key
            except jwt.PyJWKClientConnectionError as exc:
                log.error("jwks_unavailable", jwks_url=self._settings.jwks_url, error=str(exc))
                raise ServiceUnavailable(
                    "Authentication service is unavailable", code="AUTH_UNAVAILABLE"
                ) from exc
            except jwt.PyJWKClientError as exc:
                raise Unauthenticated("Unknown token signing key", code="INVALID_TOKEN") from exc
        raise Unauthenticated("Token algorithm is not accepted", code="INVALID_TOKEN")

    def verify(self, token: str) -> TokenClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise Unauthenticated("Malformed token", code="INVALID_TOKEN") from exc
        alg = str(header.get("alg", ""))
        key = self._signing_key(token, alg)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience=self._settings.supabase_jwt_audience,
                issuer=self._settings.jwt_issuer,
                leeway=_CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthenticated("Token has expired", code="TOKEN_EXPIRED") from exc
        except jwt.InvalidTokenError as exc:
            log.info("token_rejected", reason=type(exc).__name__)
            raise Unauthenticated("Invalid token", code="INVALID_TOKEN") from exc
        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError as exc:
            raise Unauthenticated("Invalid token subject", code="INVALID_TOKEN") from exc
        return TokenClaims(
            user_id=user_id,
            email=claims.get("email"),
            session_id=claims.get("session_id"),
            expires_at=int(claims["exp"]),
        )


@lru_cache
def _default_verifier() -> TokenVerifier:
    return TokenVerifier(get_settings())


def get_token_verifier() -> TokenVerifier:
    return _default_verifier()


@dataclass(frozen=True, slots=True)
class Department:
    id: UUID
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class Role:
    id: UUID
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: UUID
    email: str | None
    full_name: str
    employee_code: str | None
    phone: str | None
    is_super_admin: bool
    department: Department | None
    roles: tuple[Role, ...]
    must_change_password: bool = False

    @property
    def role_codes(self) -> frozenset[str]:
        return frozenset(r.code for r in self.roles)


_bearer = HTTPBearer(auto_error=False, description="Supabase access token")

# Reachable while profiles.must_change_password is set (P1-05, DEC-50).
_PASSWORD_CHANGE_ALLOWED_PATHS = frozenset({"/api/v1/me", "/api/v1/me/password"})


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    uow: UowDep,
) -> CurrentUser:
    """401 for a missing/invalid token; 403 ACCOUNT_INACTIVE for an inactive or unknown profile."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthenticated("Missing bearer token")
    claims = verifier.verify(credentials.credentials)

    with uow.transaction() as session:
        profile = repo.get_profile(session, claims.user_id)
        roles = repo.get_roles(session, claims.user_id) if profile else []

    if profile is None or not profile.is_active:
        log.info("inactive_account", user_id=str(claims.user_id), has_profile=profile is not None)
        raise PermissionDenied("This account is not active", code="ACCOUNT_INACTIVE")

    request.state.user_id = profile.id
    # P1-05 / DEC-50: after an admin-issued temporary password the user must set their own
    # password first. Only the profile and the password-change endpoint stay reachable.
    if profile.must_change_password and request.url.path not in _PASSWORD_CHANGE_ALLOWED_PATHS:
        raise PermissionDenied(
            "You must change your temporary password first", code="PASSWORD_CHANGE_REQUIRED"
        )
    department = (
        Department(profile.department_id, profile.department_code, profile.department_name)
        if profile.department_id and profile.department_code and profile.department_name
        else None
    )
    return CurrentUser(
        id=profile.id,
        email=profile.email,
        full_name=profile.full_name,
        employee_code=profile.employee_code,
        phone=profile.phone,
        is_super_admin=profile.is_super_admin,
        department=department,
        roles=tuple(Role(r.id, r.code, r.name) for r in roles),
        must_change_password=profile.must_change_password,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
