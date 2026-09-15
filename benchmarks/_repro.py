"""Reproducibility sidecar for Cortex benchmark manifests.

source: ADR-0814
"""

from __future__ import annotations

import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any
from importlib.metadata import version
from mcp_server.core.reranker import ensure_reranker_loaded, model_sha256
import benchmarks.lib._composition_root_wiring  # noqa: F401 — source: issue #560


def _git_sha() -> str:
    """Return the HEAD commit SHA, or 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"


def _git_dirty() -> bool | None:
    """Return True if the working tree has any uncommitted changes, None if unknown.

    Precondition: called from within a git working tree (best-effort).
    Postcondition: returns True when git status --porcelain produces any output
        (staged changes, unstaged changes to tracked files, or untracked files);
        returns False when the output is empty (clean tree); returns None when
        git is absent or the call times out.

    Implementation note: ``git diff --quiet`` detects only unstaged changes to
    tracked files — it reports exit-code 0 (clean) for staged-but-uncommitted
    changes and for untracked files.  ``git status --porcelain`` covers all
    three cases and is therefore the correct signal for manifest cleanliness.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            # source: ADR-0814

            return None
        return bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _lib_version(package_name: str) -> str:
    """Return the installed version of *package_name*, or 'not-installed'."""
    try:
        return version(package_name)
    except Exception:  # noqa: BLE001 — source: ADR-0814
        return "not-installed"


def _reranker_manifest_fields() -> dict[str, Any]:
    """Capture the FlashRank reranker's load state for the manifest.

    source: ADR-0814

    Best-effort: does not raise if mcp_server.core.reranker is unimportable
    in the calling environment (e.g. a stripped-down repro checkout).
    """
    try:
        status = ensure_reranker_loaded()
        return {
            "reranker_active": status.state == "loaded",
            "reranker_state": status.state,
            "reranker_model_path": status.model_path,
            "reranker_model_sha256": model_sha256(),
        }
    except Exception:  # noqa: BLE001 — source: ADR-0814
        return {
            "reranker_active": False,
            "reranker_state": "unresolved",
            "reranker_model_path": None,
            "reranker_model_sha256": None,
        }


def build_repro_manifest() -> dict[str, Any]:
    """Capture reproducibility metadata at call time.

    Precondition: called from within a git working tree (best-effort; degrades
    gracefully when git is absent).
    Postcondition: returns a dict with keys:
        git_commit, git_dirty, python_version, platform_system,
        platform_machine, platform_node, timestamp_utc, lib_versions,
        reranker_active, reranker_state, reranker_model_path,
        reranker_model_sha256.
    The dict is JSON-serialisable (all values are str | bool | None | dict).
    """
    sha = _git_sha()
    dirty = _git_dirty()

    lib_versions = {
        "sentence-transformers": _lib_version("sentence-transformers"),
        "torch": _lib_version("torch"),
        "numpy": _lib_version("numpy"),
        "psycopg": _lib_version("psycopg"),
        "pgvector": _lib_version("pgvector"),
        "flashrank": _lib_version("flashrank"),
    }

    return {
        "git_commit": sha,
        "git_dirty": dirty,
        "python_version": sys.version,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "platform_node": platform.node(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "lib_versions": lib_versions,
        **_reranker_manifest_fields(),
    }


def multi_run_stats(values: list[float]) -> dict[str, float | int | None]:
    """Compute mean, std, and 95 % CI for a list of per-run metric values.

    Precondition: values is a non-empty list of finite floats.
    Postcondition: returns dict with keys:
        mean, std, n, ci95_lower, ci95_upper.
    ci95_lower / ci95_upper are computed via normal approximation:
        mean ± 1.96 * std / sqrt(n).
    When n == 1, std == 0.0 and the CI equals the mean (degenerate case).

    source: ADR-0814"""
    n = len(values)
    if n == 0:
        return {
            "mean": None,
            "std": None,
            "n": 0,
            "ci95_lower": None,
            "ci95_upper": None,
        }

    mean = sum(values) / n
    if n == 1:
        return {
            "mean": mean,
            "std": 0.0,
            "n": 1,
            "ci95_lower": mean,
            "ci95_upper": mean,
        }

    variance = sum((x - mean) ** 2 for x in values) / (n - 1)  # Bessel-corrected
    std = math.sqrt(variance)
    # source: ADR-0814
    z = 1.96  # source: ADR-0814
    margin = z * std / math.sqrt(n)
    return {
        "mean": mean,
        "std": std,
        "n": n,
        "ci95_lower": mean - margin,
        "ci95_upper": mean + margin,
    }
