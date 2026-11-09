import importlib
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
