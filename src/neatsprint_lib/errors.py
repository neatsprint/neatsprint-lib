"""RFC 7807 problem-details errors with stable machine-readable codes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PROBLEM_BASE = "https://docs.neatsprint.com/errors/"
DEFAULT_TITLE = "Request failed"


class FieldError(BaseModel):
    field: str
    code: str
    message: str


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[FieldError] = Field(default_factory=list)


class ApiError(Exception):
    """Domain error that renders as an RFC 7807 response.

    ``code`` is part of the API contract; ``detail`` is for humans and may change.
    """

    def __init__(
        self,
        status: int,
        code: str,
        detail: str | None = None,
        *,
        title: str | None = None,
        errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or code)
        self.status = status
        self.code = code
        self.detail = detail
        self.title = title or DEFAULT_TITLE
        self.errors = errors or []
        self.headers = headers or {}


def _problem(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = ProblemDetail(
        type=f"{PROBLEM_BASE}{code}",
        title=title,
        status=status,
        code=code,
        detail=detail,
        instance=request.url.path,
        request_id=request_id,
        errors=[FieldError(**item) for item in (errors or [])],
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every error is a problem-details document."""

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _problem(
            request,
            status=exc.status,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            errors=exc.errors,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for err in exc.errors():
            location = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            errors.append(
                {
                    "field": location or "body",
                    "code": str(err.get("type", "invalid")),
                    "message": str(err.get("msg", "Invalid value")),
                }
            )
        return _problem(
            request,
            status=422,
            code="validation_failed",
            title="Validation failed",
            detail="One or more fields are invalid.",
            errors=errors,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled_error", extra={"request_id": request_id})
        return _problem(
            request,
            status=500,
            code="internal_error",
            title="Internal server error",
            detail="An unexpected error occurred. Quote the request id when contacting support.",
        )


def error_payload(
    *, code: str, title: str, status: int, detail: str | None = None
) -> dict[str, Any]:
    """Build a problem document for tests or non-HTTP contexts."""
    body = ProblemDetail(
        type=f"{PROBLEM_BASE}{code}", title=title, status=status, code=code, detail=detail
    )
    return body.model_dump(mode="json", exclude_none=True)
