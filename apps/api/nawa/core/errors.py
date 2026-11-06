import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from nawa.core.logging import request_id_var

logger = logging.getLogger("nawa.errors")


class DomainError(Exception):
    status_code = 400
    code = "domain_error"
    title = "Bad Request"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"
    title = "Not Found"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"
    title = "Forbidden"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"
    title = "Conflict"


class ValidationFailedError(DomainError):
    status_code = 422
    code = "validation_failed"
    title = "Unprocessable Entity"


class AuthenticationError(DomainError):
    status_code = 401
    code = "unauthenticated"
    title = "Unauthorized"


class RateLimitedError(DomainError):
    status_code = 429
    code = "rate_limited"
    title = "Too Many Requests"


def _problem(
    status: int, title: str, code: str, detail: str, request_id: str | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"about:blank#{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
            "request_id": request_id if request_id is not None else request_id_var.get(),
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _problem(exc.status_code, exc.title, exc.code, exc.detail)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # This handler runs in ServerErrorMiddleware, outside RequestIdMiddleware, so the
        # ContextVar is already reset. The id is recovered from shared request state.
        request_id = getattr(request.state, "request_id", "")
        token = request_id_var.set(request_id)
        try:
            logger.exception("unhandled error", exc_info=exc)
        finally:
            request_id_var.reset(token)
        response = _problem(
            500, "Internal Server Error", "internal_error", "Unexpected error", request_id
        )
        if request_id:
            response.headers["X-Request-ID"] = request_id
        return response
