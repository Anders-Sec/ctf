"""The single error shape the API speaks.

Every failure leaves the API as ``{"error": {"code": ..., "message": ...}}``.
``code`` is a stable snake_case string the frontend switches on; ``message`` is
human-facing prose that may be reworded at any time without breaking a client.
"""

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base for errors that carry a machine-readable code.

    Raise a subclass (or this, with an explicit code) from services rather than
    HTTPException, so business logic stays free of HTTP details.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource does not exist."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state."


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A dependency is unavailable."


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


# Starlette raises bare HTTPExceptions for routing failures, which carry no code of
# their own. Map the ones players can actually hit to stable codes.
_STATUS_CODES = {
    status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        # HTTPException(detail={"code": ..., "message": ...}) keeps its code.
        if isinstance(detail, dict) and "code" in detail:
            return error_response(
                exc.status_code,
                str(detail["code"]),
                str(detail.get("message", "")),
            )
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        message = detail if isinstance(detail, str) else "Request failed."
        return error_response(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "The request body or parameters are invalid.",
            {"fields": _summarise_validation(exc)},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Never leak a traceback or exception message to a player — an unhandled
        # error may well be a stack trace containing a flag or a connection string.
        logger.exception("unhandled_exception", extra={"error_type": type(exc).__name__})
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Something went wrong. The dungeon masters have been notified.",
        )

    # FastAPI's HTTPException subclasses Starlette's, so the handler above covers
    # both; registering it explicitly keeps the intent obvious.
    app.add_exception_handler(HTTPException, _http_error)  # type: ignore[arg-type]


def _summarise_validation(exc: RequestValidationError) -> list[dict[str, str]]:
    fields = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"] if part != "body")
        fields.append({"field": location or "body", "reason": error["msg"]})
    return fields
