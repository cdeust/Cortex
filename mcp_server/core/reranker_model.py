"""FlashRank model identity, cache location, and the offline-fetch gate.

Pure, stateless helpers describing WHERE the cross-encoder weights live
and WHETHER a network fetch of them is permitted. No process-global
singleton state lives here (that is the concern of ``reranker.py``); these
functions can be called any number of times without side effects beyond
reading the environment and the filesystem.

Model cache directory (fix 2026-07-11, incident: silent reranker skip):
    FlashRank 0.2.10's own default cache_dir is ``/tmp`` (see the
    installed package's ``flashrank/Config.py``: ``default_cache_dir =
    "/tmp"``). macOS periodically purges /tmp; the first process restart
    after a purge hit ``NoSuchFile`` inside ``Ranker.__init__`` -> the
    bare ``except Exception`` in ``reranker._ensure_reranker`` swallowed
    it with no log line -> every subsequent ``rerank_results`` call for
    the rest of that process's life silently returned first-stage-only
    scores. This ran unnoticed through 6 LongMemEval benchmark
    executions; measured impact MRR 0.9163 -> 0.8636 (R@10 nearly
    unaffected — the metric a quick eyeball check would have caught was
    the one metric this bug barely touched). Fix: pass an EXPLICIT,
    DURABLE ``cache_dir`` (``~/.cache/flashrank``, honoring
    ``$XDG_CACHE_HOME`` — see ``mcp_server.shared.platform.cache_dir``)
    instead of the library default, and log (not swallow) any load
    failure. See ``reranker.reranker_status()`` for the
    externally-consumable load state that fix also introduced.

    FlashRank's own download behavior (verified by reading the installed
    0.2.10 package, not assumed): ``Ranker._prepare_model_dir`` checks
    ``if not self.model_dir.exists()`` and, when absent, downloads +
    unzips the model from Hugging Face
    (``https://huggingface.co/prithivida/flashrank/resolve/main/{model}.zip``)
    into ``cache_dir``. This means a durable ``cache_dir`` is
    self-provisioning: first run in a fresh cache downloads once (~34MB
    for ms-marco-MiniLM-L-12-v2), every subsequent run in the same
    process or a new one reuses the on-disk copy. No custom download
    logic is needed in Cortex; the failure mode this module now logs is
    exactly the cases where that self-provisioning itself fails (no
    network, no write permission, corrupted archive, etc.).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from mcp_server.shared.platform import cache_dir as _base_cache_dir

# source: flashrank==0.2.10 installed package, flashrank/Config.py
# model_file_map["ms-marco-MiniLM-L-12-v2"] — verified by reading the
# installed site-packages file directly (see module docstring).
_MODEL_NAME = "ms-marco-MiniLM-L-12-v2"
_MODEL_FILE = "flashrank-MiniLM-L-12-v2_Q.onnx"

# FlashRank downloads its model with a bare ``requests.get(..., stream=True)``
# carrying NO timeout (verified by reading the installed 0.2.10
# ``Ranker._download_model_files``), so a stalled TCP connect blocks the
# calling thread forever rather than raising -- the ``except Exception``
# in ``reranker._ensure_reranker`` cannot engage against a hang. That is not
# hypothetical: CI run 30263190266 (main, Python 3.13, 2026-07-27) hung in
# ``sock.connect`` inside a recall test until pytest-timeout killed the whole
# suite at 300s. ``HF_HUB_OFFLINE``/``TRANSFORMERS_OFFLINE`` do not reach
# FlashRank because it bypasses the ``huggingface_hub`` client entirely, so
# forbidding the fetch needs its own switch.
_OFFLINE_ENV = "CORTEX_RERANKER_OFFLINE"


def _offline_requested() -> bool:
    """True when the caller has forbidden a network fetch of the model.

    Precondition: none.
    Postcondition: True iff ``$CORTEX_RERANKER_OFFLINE`` is set to
        anything other than the empty string, "0", "false", or "no"
        (case- and whitespace-insensitive). Unset means False, so
        production keeps FlashRank's self-provisioning first-run
        download that PRIVACY.md documents; only callers that opt in
        (CI test steps, air-gapped installs) get the strict behavior.
    """
    return os.environ.get(_OFFLINE_ENV, "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    )


@dataclass(frozen=True)
class RerankerStatus:
    """Snapshot of the FlashRank reranker singleton's load state.

    state is one of "loaded" | "failed" | "not_attempted". model_path is
    the ONNX file ``reranker._ensure_reranker`` reads from (or would read
    from), computed without touching disk — callers that need to confirm
    the file is actually present (e.g. to sha256 it for a bench manifest)
    must stat/hash ``model_path`` themselves.
    """

    state: str
    model_path: str
    error: str | None = None


def reranker_cache_dir() -> Path:
    """Durable on-disk cache directory for the FlashRank ONNX model.

    See module docstring for why FlashRank's own ``/tmp`` default is
    unsafe. Honors ``$XDG_CACHE_HOME`` (via
    ``mcp_server.shared.platform.cache_dir``); falls back to
    ``~/.cache/flashrank`` — the location already adopted de facto (a
    manually-placed copy of the model existed there before this fix).
    """
    return _base_cache_dir() / "flashrank"


def _model_path() -> Path:
    return reranker_cache_dir() / _MODEL_NAME / _MODEL_FILE


def model_sha256() -> str | None:
    """Sha256 of the on-disk ONNX weights file, or None if it is absent.

    Used by bench manifests to fingerprint the exact reranker weights a
    run used (mirrors the existing ``embedding_model_revision`` manifest
    field — see benchmarks/reproduce.sh's ``write_manifest``). Reads the
    file in fixed-size chunks to bound memory use regardless of file size.
    """
    path = _model_path()
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
