"""Shared queue-capacity sizing for the streaming pipeline.

Extract Function (TRY003, issue #239): ``compute_queue_cap`` was byte-for-
byte duplicated in ``adaptive_writer.py`` and ``backpressure_pipeline.py``
(the same signature, docstring formula, and validation), reached through
two different import paths (``calibrated.py`` imported the
``adaptive_writer`` copy; the package's own ``__init__.py`` re-exported
the ``backpressure_pipeline`` copy) — a real drift risk: a fix to one
copy would silently not apply to the other. This module is now the one
canonical definition; both siblings import it instead of each defining
their own, and neither gains a new dependency on the other (both depend
on this module instead, preserving their prior independence).

Pure business logic — no I/O.
"""

from __future__ import annotations


def compute_queue_cap(
    ram_budget_bytes: int, b_max: int, row_bytes: int, reserve: int = 1
) -> int:
    """``Q_cap = floor(RAM_budget / (b_max * row_bytes)) - reserve``.

    Pinned to ``b_max`` (NOT the live B): the controller ramps B up to b_max,
    so sizing from a smaller live B would let peak RAM overshoot the budget by
    ``b_max / B`` once it ramps. source: Little (1961), occupancy bound applied
    to memory rather than time. Floors at 1 so the pipeline always makes
    progress.
    """
    if b_max <= 0 or row_bytes <= 0:
        raise ValueError("b_max and row_bytes must be positive")  # noqa: TRY003 — one-off message, not reused (§3.3); this IS the single canonical site both siblings now share
    if ram_budget_bytes <= 0:
        raise ValueError("ram_budget_bytes must be positive")  # noqa: TRY003 — one-off message, not reused (§3.3); this IS the single canonical site both siblings now share
    return max(1, ram_budget_bytes // (b_max * row_bytes) - reserve)
