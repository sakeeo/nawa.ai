from fastapi import FastAPI
from fastapi.testclient import TestClient

from nawa.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    install_error_handlers,
)
from nawa.core.logging import RequestIdMiddleware


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    @app.get("/missing")
    def missing() -> None:
        raise NotFoundError("workspace not found")

    @app.get("/forbidden")
    def forbidden() -> None:
        raise PermissionDeniedError("role viewer cannot write")

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError("slug taken")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    return TestClient(app, raise_server_exceptions=False)


def test_not_found_is_problem_json() -> None:
    response = make_client().get("/missing", headers={"X-Request-ID": "r1"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["code"] == "not_found"
    assert body["title"] == "Not Found"
    assert body["detail"] == "workspace not found"
    assert body["request_id"] == "r1"


def test_status_codes_per_error() -> None:
    client = make_client()
    assert client.get("/forbidden").status_code == 403
    assert client.get("/conflict").status_code == 409


def test_unhandled_error_hides_internals() -> None:
    response = make_client().get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "secret" not in response.text
