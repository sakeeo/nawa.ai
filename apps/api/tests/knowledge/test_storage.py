import uuid
from pathlib import Path

import pytest

from nawa.knowledge.storage import FileStorage

WS = uuid.uuid4()
DOC = uuid.uuid4()


def test_save_then_read_round_trips(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)
    path = storage.save(WS, DOC, b"hello")
    assert path == tmp_path / str(WS) / str(DOC)
    assert storage.read(WS, DOC) == b"hello"
    assert storage.exists(WS, DOC)


def test_save_overwrites_existing(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)
    storage.save(WS, DOC, b"one")
    storage.save(WS, DOC, b"two")
    assert storage.read(WS, DOC) == b"two"


def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)
    storage.save(WS, DOC, b"x")
    storage.delete(WS, DOC)
    assert not storage.exists(WS, DOC)
    storage.delete(WS, DOC)


def test_read_missing_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FileStorage(tmp_path).read(WS, DOC)


@pytest.mark.parametrize("bad", ["..", "../x", "not-a-uuid", "", "a/b"])
def test_non_uuid_ids_are_rejected(tmp_path: Path, bad: str) -> None:
    storage = FileStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.save(bad, DOC, b"x")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        storage.read(WS, bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        storage.delete(WS, bad)  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []


def test_uuid_strings_are_accepted(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)
    storage.save(str(WS), str(DOC), b"x")  # type: ignore[arg-type]
    assert storage.read(WS, DOC) == b"x"


def test_crash_mid_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = FileStorage(tmp_path)

    def boom(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError):
        storage.save(WS, DOC, b"data")
    assert not storage.exists(WS, DOC)
    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftovers == []
