import os
import tempfile
import uuid
from pathlib import Path


def _uuid(value: uuid.UUID | str, label: str) -> str:
    """Validate an id so a path built from it can never leave the storage root."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc


class FileStorage:
    """Uploaded files on disk at <root>/<workspace_id>/<document_id>."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, workspace_id: uuid.UUID | str, document_id: uuid.UUID | str) -> Path:
        return self._root / _uuid(workspace_id, "workspace_id") / _uuid(document_id, "document_id")

    def save(
        self, workspace_id: uuid.UUID | str, document_id: uuid.UUID | str, data: bytes
    ) -> Path:
        target = self._path(workspace_id, document_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(target)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        return target

    def read(self, workspace_id: uuid.UUID | str, document_id: uuid.UUID | str) -> bytes:
        return self._path(workspace_id, document_id).read_bytes()

    def exists(self, workspace_id: uuid.UUID | str, document_id: uuid.UUID | str) -> bool:
        return self._path(workspace_id, document_id).is_file()

    def delete(self, workspace_id: uuid.UUID | str, document_id: uuid.UUID | str) -> None:
        self._path(workspace_id, document_id).unlink(missing_ok=True)
