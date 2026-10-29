"""The plugin's semantic-search job: download the pinned embedding model.

Run by ``scripts/launcher.py`` as ``mcp_server.infrastructure.embedding_warmup``
after the launcher installed the locked ML set (``scripts/launcher_ml.py``).
It loads the model the server uses, downloading the pinned revision into the
local cache, and records the outcome in the file the launcher names
(``CORTEX_SEMANTIC_STATUS_FILE``): ``ready``, or ``failed`` with the real
error, which the next SessionStart shows the user.

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import os
from pathlib import Path
from mcp_server.shared import gated_files

STATUS_ENV = "CORTEX_SEMANTIC_STATUS_FILE"  # source: scripts/launcher_ml.py STATUS_ENV
# What download_model fetched; the launcher re-runs a record naming other files.
# source: scripts/launcher_ml.py MODEL_FILES (issue #706)
MODEL_FILES = "all-MiniLM-L6-v2@1110a243+onnx-query-encoder"


def _record(outcome: dict) -> None:
    path = os.environ.get(STATUS_ENV, "")
    if not path:
        raise RuntimeError(
            f"{STATUS_ENV} is unset: run this through scripts/launcher.py"
        )
    gated_files.write_json(Path(path), outcome)


def main() -> None:
    """Download and load the model; record ``ready`` or ``failed``; re-raise."""
    from mcp_server.infrastructure.embedding_factory import get_embedding_engine  # noqa: PLC0415 — imports the ML stack; only this job needs it

    try:
        engine = get_embedding_engine()
        engine.download_model()
    except BaseException as exc:
        _record({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    _record(
        {
            "status": "ready",
            "model": engine.model_name,
            "dim": engine.dimensions,
            "model_files": MODEL_FILES,
        }
    )
    print(f"[cortex] semantic search ready: {engine.model_name} ({engine.dimensions}D)")


if __name__ == "__main__":
    main()
