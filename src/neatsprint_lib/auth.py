"""JWT verification and permission enforcement shared by every service.

The gateway validates tokens for speed; services validate them again for defence in
depth (ADR-007). Tenant identity always comes from the token, never from a header.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, FastAPI, Request
from jwt import PyJWKClient

from neatsprint_lib.errors import ApiError


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    session_id: str | None
    roles: tuple[str, ...]
    permissions: frozenset[str]
    jti: str

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def can_any(self, *permissions: str) -> bool:
        return any(permission in self.permissions for permission in permissions)


class TokenVerifier:
    """Verifies RS256 access tokens with a static public key or a JWKS endpoint."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        public_key: str | None = None,
        jwks_url: str | None = None,
        leeway_seconds: int = 30,
    ) -> None:
        if not public_key and not jwks_url:
            raise ValueError("either public_key or jwks_url is required")
        self.issuer = issuer
        self.audience = audience
        self.leeway = leeway_seconds
        self._public_key = public_key
        self._jwks_client = (
            PyJWKClient(jwks_url, cache_keys=True) if jwks_url and not public_key else None
        )

    def _signing_key(self, token: str) -> Any:
        if self._public_key:
            return self._public_key
        assert self._jwks_client is not None
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def _decode(self, token: str) -> Principal:
        try:
            payload = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "sub", "tid", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ApiError(401, "token_expired", "The access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise ApiError(401, "unauthenticated", "The access token is invalid.") from exc

        permissions = payload.get("scope", [])
        if isinstance(permissions, str):
            permissions = permissions.split()
        roles = payload.get("roles", [])
        if isinstance(roles, str):
            roles = roles.split(",")
        try:
            return Principal(
                user_id=UUID(payload["sub"]),
                tenant_id=UUID(payload["tid"]),
                session_id=payload.get("sid"),
                roles=tuple(roles),
                permissions=frozenset(permissions),
                jti=payload["jti"],
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ApiError(401, "unauthenticated", "The access token is malformed.") from exc

    async def verify(self, token: str) -> Principal:
        # JWKS fetching is blocking (urllib); run it off the event loop on cache misses.
        return await asyncio.to_thread(self._decode, token)


def install_auth(app: FastAPI, verifier: TokenVerifier) -> None:
    app.state.token_verifier = verifier


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "unauthenticated", "A bearer access token is required.")
    return token.strip()


async def get_principal(request: Request) -> Principal:
    cached: Principal | None = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    verifier: TokenVerifier | None = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise ApiError(500, "internal_error", "Authentication is not configured.")
    principal = await verifier.verify(_bearer(request))
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_permission(code: str) -> Any:
    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.can(code):
            raise ApiError(
                403,
                "permission_denied",
                f"You do not have permission '{code}'.",
            )
        return principal

    return dependency


def require_any_permission(*codes: str) -> Any:
    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.can_any(*codes):
            raise ApiError(
                403,
                "permission_denied",
                f"You need one of: {', '.join(codes)}.",
            )
        return principal

    return dependency
