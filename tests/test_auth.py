from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from neatsprint_lib.auth import (
    Principal,
    TokenVerifier,
    get_principal,
    install_auth,
    require_permission,
)
from neatsprint_lib.errors import install_error_handlers

ISSUER = "neatsprint-iam"
AUDIENCE = "neatsprint"


def _keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def _token(private_pem: str, **overrides: object) -> str:
    now = datetime.now(tz=UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "018f1c2d-7a3b-7c4d-9e5f-0123456789ab",
        "tid": "018f1c2d-7a3b-7c4d-9e5f-0123456789ac",
        "sid": "session-1",
        "jti": str(uuid4()),
        "roles": ["MANAGER"],
        "scope": ["task:item:create", "task:project:view"],
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_pem, algorithm="RS256")


def _app(public_pem: str) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    install_auth(
        app,
        TokenVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=public_pem),
    )

    @app.get("/me")
    async def me(principal: Principal = Depends(get_principal)) -> dict[str, str]:
        return {"tenant": str(principal.tenant_id), "user": str(principal.user_id)}

    @app.get("/protected")
    async def protected(
        principal: Principal = Depends(require_permission("task:item:create")),
    ) -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_valid_token_is_accepted() -> None:
    private_pem, public_pem = _keys()
    client = TestClient(_app(public_pem))
    response = client.get("/me", headers={"Authorization": f"Bearer {_token(private_pem)}"})
    assert response.status_code == 200
    assert response.json()["tenant"] == "018f1c2d-7a3b-7c4d-9e5f-0123456789ac"


def test_missing_token_is_401() -> None:
    _, public_pem = _keys()
    response = TestClient(_app(public_pem)).get("/me")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_expired_token_is_401() -> None:
    private_pem, public_pem = _keys()
    expired = _token(
        private_pem,
        iat=datetime.now(tz=UTC) - timedelta(hours=2),
        exp=datetime.now(tz=UTC) - timedelta(hours=1),
    )
    response = TestClient(_app(public_pem)).get(
        "/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "token_expired"


def test_wrong_issuer_is_401() -> None:
    private_pem, public_pem = _keys()
    response = TestClient(_app(public_pem)).get(
        "/me", headers={"Authorization": f"Bearer {_token(private_pem, iss='someone-else')}"}
    )
    assert response.status_code == 401


def test_permission_granted_and_denied() -> None:
    private_pem, public_pem = _keys()
    client = TestClient(_app(public_pem))
    allowed = client.get(
        "/protected", headers={"Authorization": f"Bearer {_token(private_pem)}"}
    )
    assert allowed.status_code == 200
    denied = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {_token(private_pem, scope=['task:project:view'])}"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"


def test_principal_can_helpers() -> None:
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        session_id=None,
        roles=("MEMBER",),
        permissions=frozenset({"a:b:c"}),
        jti="x",
    )
    assert principal.can("a:b:c")
    assert not principal.can("x:y:z")
    assert principal.can_any("x:y:z", "a:b:c")


def test_verifier_requires_key_or_jwks() -> None:
    with pytest.raises(ValueError):
        TokenVerifier(issuer=ISSUER, audience=AUDIENCE)
