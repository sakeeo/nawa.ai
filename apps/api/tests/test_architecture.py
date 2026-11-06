import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]


def test_import_contracts_hold() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "importlinter.cli", "--config", "pyproject.toml"],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
