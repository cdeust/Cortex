"""Reproducibility sidecar for Cortex benchmark manifests.

Every benchmark manifest must include sufficient metadata for an independent
researcher to reproduce a reported score.  This module captures that metadata
at runtime: the exact code revision, working-tree cleanliness, key library
versions, Python interpreter, hardware platform, and wall-clock timestamp.

It also provides the ``multi_run_stats`` helper: given a list of per-run scalar
results it computes mean, std, and a 95 % confidence interval so callers can
report variance alongside a single headline figure.

Design notes
------------
- All captures are *best-effort*: missing or uninstallable libraries produce
  sentinel strings rather than raising.  The manifest writer must not fail
  because a library is absent in the current environment.
- ``git rev-parse HEAD`` is executed via subprocess so the SHA is always the
  actual on-disk commit, not something baked at import time.
- Library versions are read from ``importlib.metadata``; the same package name
  used by ``pip``/``pyproject.toml`` is used here, not the import name.
- The CI formula for a 95 % normal-approximation CI is:
    mean ± 1.96 * std / sqrt(n)
  The multiplier 1.96 is z_{0.975}, the 97.5th percentile of the standard
  normal distribution, yielding a two-sided 95 % interval.
  Source: Casella & Berger (2002) "Statistical Inference", 2nd ed., §8.3.
  For n < 30 the approximation is reported as-is; callers should interpret
  it with caution.  Bootstrap CI would be more accurate for small n but is
  not needed for the reproducibility metadata use-case (documenting
  measurement uncertainty, not statistical inference).
"""

from __future__ import annotations

import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


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
            # git is present but the call failed (not a repo, permission error,
            # etc.) — fall back to None (unknown) rather than falsely claiming clean.
            return None
        return bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _lib_version(package_name: str) -> str:
    """Return the installed version of *package_name*, or 'not-installed'."""
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:  # noqa: BLE001 — best-effort, no specific exception set
        return "not-installed"


def build_repro_manifest() -> dict[str, Any]:
    """Capture reproducibility metadata at call time.

    Precondition: called from within a git working tree (best-effort; degrades
    gracefully when git is absent).
    Postcondition: returns a dict with keys:
        git_commit, git_dirty, python_version, platform_system,
        platform_machine, platform_node, timestamp_utc, lib_versions.
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
    }


def multi_run_stats(values: list[float]) -> dict[str, float | int | None]:
    """Compute mean, std, and 95 % CI for a list of per-run metric values.

    Precondition: values is a non-empty list of finite floats.
    Postcondition: returns dict with keys:
        mean, std, n, ci95_lower, ci95_upper.
    ci95_lower / ci95_upper are computed via normal approximation:
        mean ± 1.96 * std / sqrt(n).
    When n == 1, std == 0.0 and the CI equals the mean (degenerate case).

    Source: normal approximation to the mean's sampling distribution.
    Valid asymptotically (CLT); reported as approximation for n < 30.
    The 1.96 multiplier is the 97.5th percentile of the standard normal
    distribution (z_{0.975}), yielding a two-sided 95 % interval.
    Source: Casella & Berger (2002) "Statistical Inference", 2nd ed., §8.3.
    """
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
    # z_{0.975} = 1.96; source: Casella & Berger (2002) §8.3
    z = 1.96  # source: Casella & Berger (2002), Statistical Inference, §8.3
    margin = z * std / math.sqrt(n)
    return {
        "mean": mean,
        "std": std,
        "n": n,
        "ci95_lower": mean - margin,
        "ci95_upper": mean + margin,
    }
