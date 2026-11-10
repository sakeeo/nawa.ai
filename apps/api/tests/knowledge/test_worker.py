import importlib
import os
import subprocess
import sys

import pytest

from nawa.core.config import get_settings


def test_worker_settings_follow_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://queue:6381/3")
    get_settings.cache_clear()
    sys.modules.pop("nawa.knowledge.worker", None)
    try:
        worker = importlib.import_module("nawa.knowledge.worker")
        cfg = worker.WorkerSettings
        assert (cfg.redis_settings.host, cfg.redis_settings.port) == ("queue", 6381)
        assert cfg.redis_settings.database == 3
        assert cfg.max_jobs == 2 and cfg.job_timeout == 900 and cfg.max_tries == 3
    finally:
        get_settings.cache_clear()
        sys.modules.pop("nawa.knowledge.worker", None)


def test_worker_entrypoint_resolves_foreign_keys_in_a_fresh_process() -> None:
    # In the worker process nothing imports the API, so nawa.worker must register every table
    # that knowledge tables point at. Regression: NoReferencedTableError on 'workspaces'.
    code = (
        "import nawa.worker; "
        ""
        "from nawa.knowledge.models import Document; "
        "Document.__table__.foreign_keys and [fk.column for fk in Document.__table__.foreign_keys]"
    )
    env = {**os.environ, "DATABASE_URL": "postgresql+asyncpg://u:p@h/db"}
    result = subprocess.run(  # noqa: S603  (fixed argv, no untrusted input)
        [sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
