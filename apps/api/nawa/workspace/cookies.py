from typing import Protocol

from starlette.responses import Response

from nawa.core.config import Settings

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

AUTH_PATH = "/api/v1/auth"


class _Tokens(Protocol):
    @property
    def access(self) -> str: ...

    @property
    def refresh(self) -> str: ...

    @property
    def csrf(self) -> str: ...


def set_auth_cookies(response: Response, settings: Settings, tokens: _Tokens) -> None:
    secure = settings.cookie_secure
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access,
        max_age=settings.access_token_ttl_seconds,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh,
        max_age=settings.refresh_token_ttl_seconds,
        path=AUTH_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    # Readable by the web app on purpose: it echoes the value in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE,
        tokens.csrf,
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
        httponly=False,
        secure=secure,
        samesite="lax",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=AUTH_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")
