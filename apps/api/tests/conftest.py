import pytest


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "t" * 48)


@pytest.fixture(autouse=True)
def _no_ambient_owner_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # litellm calls load_dotenv() on import, which can pull the repo-root .env into
    # os.environ mid-run on a dev machine. Tests must not depend on it.
    monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
