import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nawa.core.logging import (
    JsonFormatter,
    RequestIdMiddleware,
    request_id_var,
    trace_id_var,
)


def test_json_formatter_includes_request_and_trace_ids() -> None:
    request_id_var.set("req-1")
    trace_id_var.set("trace-1")
    record = logging.LogRecord("nawa", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "req-1"
    assert payload["trace_id"] == "trace-1"
    request_id_var.set("")
    trace_id_var.set("")


def test_middleware_echoes_given_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"request_id": request_id_var.get()}

    client = TestClient(app)
    response = client.get("/ping", headers={"X-Request-ID": "abc"})
    assert response.headers["X-Request-ID"] == "abc"
    assert response.json() == {"request_id": "abc"}


def test_middleware_generates_request_id_when_missing() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {}

    response = TestClient(app).get("/ping")
    assert len(response.headers["X-Request-ID"]) == 32
