"""Shared E2 condition primitives — env-var toggles for cortex_full vs cortex_flat.

Extracted from n_scan_runner.py so the latency runner (synthetic, formerly
n_scan) and the new E2 retrieval runners (subsample, zipf) share a single
source of truth for the ablation condition. Production write paths read
the env vars; this module only sets/restores them.

Per E2 falsifiability protocol (tasks/verification-protocol.md §E2):
- cortex_full:  no env overrides; production defaults active.
- cortex_flat:  decay disabled, heat constant 0.5, consolidation disabled.
"""

from __future__ import annotations

import os

# source: tasks/verification-protocol.md §E2 flat-baseline definition.
FLAT_ENV_VARS: dict[str, str] = {
    "CORTEX_DECAY_DISABLED": "1",
    "CORTEX_HEAT_CONSTANT": "0.5",
    "CORTEX_CONSOLIDATION_DISABLED": "1",
}

CONDITIONS: tuple[str, ...] = ("cortex_full", "cortex_flat")


def apply_condition(condition: str) -> dict[str, str | None]:
    """Set env vars for ``condition``; return saved env for restore.

    Pre: condition in CONDITIONS.
    Post: for cortex_flat, FLAT_ENV_VARS keys are set in os.environ; the
        returned dict maps each touched key to its prior value (or None
        if absent). For cortex_full, returns an empty dict (no-op).
    """
    if condition not in CONDITIONS:
        raise ValueError(
            f"unknown condition: {condition!r}; expected one of {CONDITIONS}"
        )
    saved: dict[str, str | None] = {}
    if condition == "cortex_flat":
        for key, val in FLAT_ENV_VARS.items():
            saved[key] = os.environ.get(key)
            os.environ[key] = val
    return saved


def restore_env(saved: dict[str, str | None]) -> None:
    """Restore env vars saved by ``apply_condition``.

    Pre: ``saved`` was returned by ``apply_condition``.
    Post: for each key in saved, os.environ is restored to its pre-apply state.
    """
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def heat_for(condition: str, default: float = 1.0) -> float:
    """Heat for inserted memories under ``condition``.

    cortex_flat forces heat=0.5 so the flat-importance condition is
    observable even when downstream code does not yet read CORTEX_HEAT_CONSTANT.
    source: tasks/verification-protocol.md §E2 flat-baseline definition.
    """
    return 0.5 if condition == "cortex_flat" else default
