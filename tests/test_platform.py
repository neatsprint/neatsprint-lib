from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from neatsprint_lib.api import create_health_router
from neatsprint_lib.context import RequestContextMiddleware
from neatsprint_lib.errors import ApiError, install_error_handlers


class Payload(BaseModel):
    title: str


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(create_health_router("unit-test", {"db": lambda: True}))

    @app.get("/boom")
    async def boom() -> None:
        raise ApiError(403, "permission_denied", "You cannot do that.")

    @app.post("/items")
    async def create(payload: Payload) -> dict[str, str]:
        return {"title": payload.title}

    return app


def test_healthz_ok() -> None:
    client = TestClient(build_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["service"] == "unit-test"


def test_readyz_ok() -> None:
    client = TestClient(build_app())
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {"db": "ok"}


def test_readyz_reports_failure() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(create_health_router("unit-test", {"db": lambda: False}))
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["db"] == "unavailable"


def test_domain_error_is_problem_details() -> None:
    response = TestClient(build_app()).get("/boom")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "permission_denied"
    assert body["type"].endswith("/permission_denied")
    assert body["instance"] == "/boom"


def test_validation_error_shape() -> None:
    response = TestClient(build_app()).post("/items", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["errors"][0]["field"] == "title"


def test_request_id_is_echoed() -> None:
    client = TestClient(build_app())
    response = client.get("/healthz", headers={"X-Request-ID": "req-123"})
    assert response.headers["x-request-id"] == "req-123"
