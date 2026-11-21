"""Health, metrics and middleware wiring shared by every service."""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import APIRouter, FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from neatsprint_lib.context import RequestContextMiddleware

logger = logging.getLogger(__name__)

REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP requests processed",
    ["service", "method", "route", "status"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["service", "method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

ReadinessCheck = Callable[[], bool | Awaitable[bool]]


def _run_check(check: ReadinessCheck) -> Awaitable[bool]:
    async def _inner() -> bool:
        result = check()
        if inspect.isawaitable(result):
            return bool(await result)
        return bool(result)

    return _inner()


def create_health_router(
    service_name: str,
    readiness_checks: Mapping[str, ReadinessCheck] | None = None,
    *,
    version: str = "0.1.0",
) -> APIRouter:
    """Liveness and readiness endpoints.

    ``/healthz`` never touches dependencies (Kubernetes liveness).
    ``/readyz`` runs the provided checks (Kubernetes readiness) and returns 503 with
    per-dependency detail when any check fails.
    """
    router = APIRouter(tags=["platform"])
    checks = dict(readiness_checks or {})

    @router.get("/healthz", summary="Liveness probe")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": service_name, "version": version}

    @router.get("/readyz", summary="Readiness probe")
    async def readyz(response: Response) -> dict[str, Any]:
        results: dict[str, str] = {}
        healthy = True
        for name, check in checks.items():
            try:
                ok = await _run_check(check)
            except Exception:  # noqa: BLE001 - a failing check is a failed readiness
                logger.exception("readiness_check_failed", extra={"check": name})
                ok = False
            results[name] = "ok" if ok else "unavailable"
            healthy = healthy and ok
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if healthy else "unavailable",
            "service": service_name,
            "version": version,
            "checks": results,
        }

    return router


class _MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, service_name: str) -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response: Response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", None) or "unmatched"
        elapsed = time.perf_counter() - started
        labels = (self.service_name, request.method, path, str(response.status_code))
        REQUEST_COUNT.labels(*labels).inc()
        REQUEST_DURATION.labels(*labels).observe(elapsed)
        return response


def install_platform_middleware(
    app: FastAPI,
    service_name: str,
    *,
    metrics_enabled: bool = True,
) -> None:
    app.add_middleware(RequestContextMiddleware)
    if metrics_enabled:
        app.add_middleware(_MetricsMiddleware, service_name=service_name)

        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
