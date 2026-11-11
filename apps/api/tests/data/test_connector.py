from sqlalchemy.engine import make_url

from nawa.data import connector
from nawa.data.connector import ConnectionParams, build_url, scrub

TRICKY = "p@ss:w/ord?#%&=' \""


def _params(password: str = TRICKY, **overrides: object) -> ConnectionParams:
    values: dict[str, object] = {
        "host": "db.internal",
        "port": 5432,
        "database": "sales",
        "username": "ro",
        "password": password,
        "ssl_mode": "prefer",
    }
    values.update(overrides)
    return ConnectionParams(**values)  # type: ignore[arg-type]


def test_build_url_keeps_special_characters_in_the_password() -> None:
    url = build_url(_params())
    assert url.password == TRICKY
    rendered = url.render_as_string(hide_password=False)
    assert make_url(rendered).password == TRICKY
    assert url.drivername == "postgresql+asyncpg"
    assert (url.host, url.port, url.database, url.username) == ("db.internal", 5432, "sales", "ro")


def test_params_repr_never_shows_the_password() -> None:
    assert TRICKY not in repr(_params())
    assert "secret-value" not in str(_params("secret-value"))


def test_scrub_removes_the_password_everywhere() -> None:
    message = "FATAL: password authentication failed (secret-value) for secret-value"
    assert "secret-value" not in scrub(message, "secret-value")
    assert scrub("nothing here", "") == "nothing here"


async def test_failed_connection_reports_a_problem_without_the_password() -> None:
    report = await connector.test_connection(_params("secret-value", host="127.0.0.1", port=1))
    assert report.ok is False
    assert report.server_version is None
    assert report.problems
    assert all("secret-value" not in problem for problem in report.problems)
