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


def _problem(status: int, title: str, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"about:blank#{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
            "request_id": request_id_var.get(),
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _problem(exc.status_code, exc.title, exc.code, exc.detail)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return _problem(500, "Internal Server Error", "internal_error", "Unexpected error")
