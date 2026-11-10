"""Worker entrypoint (composition root): `arq nawa.worker.WorkerSettings`.

The ingestion job lives in `nawa.knowledge`, which must not import `nawa.workspace` (import-linter).
Documents hold a foreign key to `workspaces`, so the worker process has to register the workspace
models itself or the first commit fails with `NoReferencedTableError`. The API gets them through
`nawa.main`; this module does the same for the worker.
"""

import nawa.workspace.models  # noqa: F401  (registers the workspaces table for foreign keys)
from nawa.knowledge.worker import WorkerSettings

__all__ = ["WorkerSettings"]
