"""Per-process store for Platt calibration of FlashRank reranker scores.

Collects (raw_score, label) training pairs from ``rate_memory`` feedback
and fits Platt parameters every N pairs. The fitted parameters are cached
and applied in the reranker blend step.

Persistence to a ``reranker_calibration`` table is deferred until the
Phase 3 A3 migration lands (pg_schema.py is currently owned by A3). The
in-process state is reset on restart, which is acceptable:

  - Calibration converges in O(MIN_SAMPLES) rate_memory calls.
  - Cold start returns raw scores (which is the current production
    behaviour), so restart is never worse than the pre-AF-2 baseline.

Pure business logic — module-level mutable state is explicit and
audited at the call site (engineer.md Move 3 §Construct 1 override for
write-once-at-startup / runtime-seed configuration).
"""

from __future__ import annotations

from mcp_server.core.platt_calibration import (
    MIN_SAMPLES,
    PlattParams,
    TrainingSample,
    fit_platt,
)

# ── Config ──────────────────────────────────────────────────────────────

REFIT_EVERY: int = 50  # Refit parameters every N new samples.
MAX_SAMPLES: int = 2000  # FIFO cap so memory doesn't grow unboundedly.


# ── State ───────────────────────────────────────────────────────────────

_SAMPLES: list[TrainingSample] = []
_PARAMS: PlattParams | None = None
_SAMPLES_AT_LAST_FIT: int = 0


# ── Public API ──────────────────────────────────────────────────────────


def record_rating(raw_score: float, useful: bool) -> None:
    """Add one (raw_score, useful) pair and possibly refit.

    Contract:
      pre:  raw_score is a finite float (the FlashRank CE score at
            surfacing time); useful is the user's rating (True/False).
      post: the global _SAMPLES list has one more pair (bounded at
            MAX_SAMPLES via FIFO trim). If the number of samples since
            the last fit crossed REFIT_EVERY AND the total size is
            >= MIN_SAMPLES, _PARAMS is refit via ``fit_platt``.
    """
    global _PARAMS, _SAMPLES_AT_LAST_FIT
    _SAMPLES.append(TrainingSample(raw_score=float(raw_score), label=1 if useful else 0))
    if len(_SAMPLES) > MAX_SAMPLES:
        # FIFO trim — keep the most recent MAX_SAMPLES pairs.
        del _SAMPLES[: len(_SAMPLES) - MAX_SAMPLES]

    samples_since_fit = len(_SAMPLES) - _SAMPLES_AT_LAST_FIT
    if samples_since_fit >= REFIT_EVERY and len(_SAMPLES) >= MIN_SAMPLES:
        fitted = fit_platt(list(_SAMPLES))
        if fitted is not None:
            _PARAMS = fitted
            _SAMPLES_AT_LAST_FIT = len(_SAMPLES)


def get_params() -> PlattParams | None:
    """Return the currently-fitted Platt parameters, or None if untrained."""
    return _PARAMS


def sample_count() -> int:
    """Return the number of collected (raw_score, useful) pairs."""
    return len(_SAMPLES)


def reset_for_tests() -> None:
    """Test-only hook: reset all in-process calibration state."""
    global _PARAMS, _SAMPLES_AT_LAST_FIT
    _SAMPLES.clear()
    _PARAMS = None
    _SAMPLES_AT_LAST_FIT = 0
