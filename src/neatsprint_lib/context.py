"""Request context: correlation id, tenant id and user id.

The gateway injects trusted identity headers after validating a token. Services still
validate the token themselves (ADR-007); this context is for logging and scoping, not
for authorisation decisions.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
tenant_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tenant_id", default=None
)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)

REQUEST_ID_HEADER = "X-Request-ID"
TENANT_ID_HEADER = "X-Tenant-ID"
USER_ID_HEADER = "X-User-ID"


def get_request_id() -> str | None:
    return request_id_var.get()


def get_tenant_id() -> str | None:
    return tenant_id_var.get()


def get_user_id() -> str | None:
    return user_id_var.get()


class RequestContextMiddleware:
    """Pure ASGI middleware that assigns and echoes a correlation id."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or str(uuid.uuid4())
        request.state.request_id = request_id
        request_id_var.set(request_id)
        tenant_id_var.set(request.headers.get(TENANT_ID_HEADER))
        user_id_var.set(request.headers.get(USER_ID_HEADER))

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def attach_identity(request: Request) -> None:
    """Refresh context vars after auth middleware resolves the token."""
    tenant_id_var.set(request.headers.get(TENANT_ID_HEADER))
    user_id_var.set(request.headers.get(USER_ID_HEADER))


def response_with_request_id(response: Response, request_id: str) -> Response:
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
