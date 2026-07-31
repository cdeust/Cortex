"""Adaptive batch-size controller — AIMD congestion control for batch writes.

Pure business logic — no I/O.

Grows the batch size additively while observed write latency stays within
target and shrinks it multiplicatively when latency exceeds target. AIMD is
the control law proven to converge to efficiency *and* fairness — additive
increase / multiplicative decrease is the unique combination that does
(Chiu & Jain 1989) — and is TCP's congestion-window algorithm (Jacobson 1988).
Using latency (not loss) as the congestion signal follows SEDA's adaptive
admission controller (Welsh et al. 2001).
"""

from __future__ import annotations

from dataclasses import dataclass

# source: Jacobson, V. (1988) "Congestion Avoidance and Control", SIGCOMM '88 —
# multiplicative decrease halves the window on congestion. Chiu & Jain (1989)
# prove multiplicative decrease is necessary for convergence. β = 0.5 is the
# TCP Reno value.
_MD_FACTOR = 0.5


@dataclass
class AdaptiveBatchController:
    """AIMD state machine; the SOLE owner of the live batch size ``B``.

    ``b_min``, ``b_max`` and ``w_target_s`` MUST come from the calibration
    sweep (benchmarks/streaming_calibration), never invented constants.

    ``b_max`` is a hard upper bound the controller can never exceed: the
    pipeline sizes its bounded queue from ``b_max`` (not the live B), so the
    RAM invariant ``(Q + c + 1)·b_max·row_bytes`` holds even after B ramps up.

    ``ai_step`` — additive-increase increment per control interval. Jacobson's
    unit is one MSS (the smallest sendable segment); the analog here is one
    minimum batch, so it defaults to ``b_min``. source: Jacobson 1988
    (one unit / interval).
    """

    b_min: int
    b_max: int
    w_target_s: float
    ai_step: int = 0  # resolved to b_min in __post_init__ when left 0
    _b: int = 0

    def __post_init__(self) -> None:
        if not 0 < self.b_min <= self.b_max:
            raise ValueError(
                f"require 0 < b_min <= b_max, got {self.b_min}, {self.b_max}"
            )
        if self.w_target_s <= 0:
            raise ValueError(f"w_target_s must be positive, got {self.w_target_s}")
        if self.ai_step <= 0:
            self.ai_step = self.b_min
        self._b = self.b_min


def adaptive_batch_controller_batch_size(controller: "AdaptiveBatchController") -> int:
    """The current batch size ``B`` (b_min <= B <= b_max).

    A free function, not a method: mutmut categorically excludes the body
    of any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:
    236`), so logic placed on `AdaptiveBatchController` methods (other than
    `__post_init__`, a dunder mutmut skips regardless) would carry zero
    mutation coverage no matter how the test loader names the module
    (issue #262 3rd pass; issue #282).
    """
    return controller._b


def adaptive_batch_controller_observe(
    controller: "AdaptiveBatchController", latency_s: float
) -> int:
    """Update B from one observed batch-write latency; return the new B.

    Within target → additive increase ``B += ai_step``; over target →
    multiplicative decrease ``B := max(b_min, floor(beta * B))``.
    Postcondition: ``b_min <= B <= b_max``. Mutates ``controller`` in place
    (it is the sole owner of the live batch size), matching the
    pre-extraction method's own behavior.
    """
    if latency_s <= controller.w_target_s:
        controller._b = min(controller.b_max, controller._b + controller.ai_step)
    else:
        controller._b = max(controller.b_min, int(controller._b * _MD_FACTOR))
    if not (controller.b_min <= controller._b <= controller.b_max):
        # invariant (precond 4) — explicit raise, not `assert` (S101), so
        # this postcondition is never silently stripped by `python -O`.
        b, lo, hi = controller._b, controller.b_min, controller.b_max
        raise AssertionError(f"batch size {b} out of [{lo}, {hi}]")
    return controller._b
