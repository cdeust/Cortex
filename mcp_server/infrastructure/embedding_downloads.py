"""Best-effort background fetches for the embedding subsystem (issue #169).

Non-blocking helpers the model lifecycle uses when it engages the download-free
fallback: kick off the package install (PACKAGE_ABSENT) or the model-weight
download (MODEL_FILES_ABSENT) in a detached subprocess so the current session
serves fallback embeddings immediately and the neural model becomes available
for the NEXT session — the "no first-run cliff" behaviour of #169.

Both helpers honour ``CORTEX_EMBEDDING_ZERO_DOWNLOAD``: when set, no network
fetch is started at all (sandboxed / offline / test use). All failures are
swallowed — a background fetch that cannot start must never affect the caller.

Pure I/O (subprocess). Infrastructure layer.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


def zero_download_requested() -> bool:
    """Whether the operator opted out of any embedding network fetch (#169).

    source: opt-in env contract — ``CORTEX_EMBEDDING_ZERO_DOWNLOAD`` in
    {``1``, ``true``} suppresses both the background package install and the
    background model download, forcing pure download-free operation.
    """
    return os.environ.get("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "").lower() in ("1", "true")


def _spawn_detached(cmd: list[str], what: str) -> None:
    """Start ``cmd`` as a detached, output-suppressed subprocess; swallow errors."""

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Background %s started", what)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Background %s failed to start: %s", what, exc)


def trigger_background_install() -> None:
    """Install sentence-transformers in the background (PACKAGE_ABSENT).

    Next session will have the package and a real model. No-op under
    ``CORTEX_EMBEDDING_ZERO_DOWNLOAD``.
    """
    if zero_download_requested():
        return

    target = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if target:
        target = os.path.join(target, "deps")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "sentence-transformers>=2.2.0,<4.0.0",
    ]
    if target:
        cmd.extend(["--target", target])
    _spawn_detached(cmd, "install of sentence-transformers")


def trigger_background_model_download(
    model_name: str, revision: str | None, cache_folder: str | None
) -> None:
    """Download the embedding model weights in the background (MODEL_FILES_ABSENT).

    Populates the local HF cache so the NEXT session loads the neural model.
    No-op under ``CORTEX_EMBEDDING_ZERO_DOWNLOAD``. The child imports
    sentence-transformers itself; a failure (offline) is silently dropped —
    this session already serves fallback.
    """
    if zero_download_requested():
        return

    # The child constructs the model once to force the download into the cache.
    prog = (
        "import sys\n"
        "from sentence_transformers import SentenceTransformer\n"
        "name, rev, cf = sys.argv[1], sys.argv[2] or None, sys.argv[3] or None\n"
        "SentenceTransformer(name, revision=rev, cache_folder=cf)\n"
    )
    cmd = [sys.executable, "-c", prog, model_name, revision or "", cache_folder or ""]
    _spawn_detached(cmd, f"download of embedding model {model_name}")
