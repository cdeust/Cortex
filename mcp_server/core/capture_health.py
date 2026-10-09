"""Is auto-capture working? A verdict computed from the repository's own evidence.

Pure: the caller reads the telemetry log and the spool and hands the facts in.
The evidence is what the capture path itself recorded: ``capture_processed`` when
a payload went through the remember handler (stored or gated, either way the
pipeline worked) and ``capture_skipped`` when one was declined (hook, worker or
drainer). The host never surfaces the hook's stderr, so this record is the only
channel (issue #660).

source: ADR-1095
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

CAPTURE_SKIPPED = "capture_skipped"
CAPTURE_PROCESSED = "capture_processed"

# source: own choice, issue #660 (no published threshold exists for this signal).
# A skip is a hook the system declined to store; one or two in a row happen on a
# transient (a locked file, a full disk) and the next success clears them. Five
# in a row with no success between them is not a transient: at the capture rate
# of a working session (one per tool call) it is minutes of continuous failure.
FAILURE_RUN = 5
# source: own choice, issue #660. A failing run is current only if its latest skip
# is within a day: it spans an overnight idle period, so a session started in the
# morning still sees yesterday's outage, and a run that stopped long ago is
# reported in the detail as history instead of blocking readiness for ever.
WINDOW_SECONDS = 86400.0


_FIX = (
    "The host does not show the hook's stderr. Read the capture_skipped lines of "
    "<claude dir>/methodology/telemetry.jsonl, and the capture log: "
    "<claude dir>/.capture-worker/drain.log (platforms without the resident "
    "worker) or worker.log in the worker's runtime directory."
)


@dataclass(frozen=True)
class CaptureVerdict:
    ok: bool
    detail: str
    fix: str


def _age(now: float, then: float | None) -> str:
    return "never" if then is None else f"{max(now - then, 0.0):.0f}s ago"


def _evidence(
    counts: tuple[int, int],
    last: tuple[float | None, float | None],
    spool: tuple[float | None, int],
    now: float,
) -> str:
    """counts = (processed, skipped); last = their latest timestamps;
    spool = (oldest pending age, rejected files)."""
    pending = "none" if spool[0] is None else f"{spool[0]:.0f}s"
    return (
        f"{counts[0]} processed (last {_age(now, last[0])}), "
        f"{counts[1]} skipped (last {_age(now, last[1])}); "
        f"spool: oldest pending {pending}, {spool[1]} rejected"
    )


def _failing_capture(
    processed: list[float], skipped: list[float], now: float
) -> str | None:
    """The auto-capture problem, if the latest skip is recent and either nothing
    was ever processed or a run of ``FAILURE_RUN`` skips follows the last success."""
    if not skipped or now - skipped[-1] > WINDOW_SECONDS:
        return None
    run = sum(1 for ts in skipped if not processed or ts > processed[-1])
    if processed and run < FAILURE_RUN:
        return None
    since = (
        "and none ever processed" if not processed else "since the last processed one"
    )
    return f"auto-capture is failing: {run} captures skipped {since}"


def _stalled_spool(age: float | None, stall_seconds: float) -> str | None:
    if age is None or age <= stall_seconds:
        return None
    return (
        f"spooled captures are not being drained (oldest {age:.0f}s,"
        f" limit {stall_seconds:.0f}s)"
    )


def assess(
    events: Iterable[tuple[float, str]],
    *,
    oldest_pending_age: float | None,
    stall_seconds: float,
    rejected: int,
    now: float,
) -> CaptureVerdict:
    """precondition: ``events`` are ``(unix_ts, op)``; other ops are ignored.
    postcondition: ``ok`` is False iff (a) the latest skip is within
    ``WINDOW_SECONDS`` and either no capture was ever processed or at least
    ``FAILURE_RUN`` skips follow the last processed one, or (b) the oldest
    pending spool file is older than ``stall_seconds``. ``detail`` always carries
    the counts and ages the verdict was computed from."""
    ordered = sorted(e for e in events if e[1] in (CAPTURE_PROCESSED, CAPTURE_SKIPPED))
    processed = [ts for ts, op in ordered if op == CAPTURE_PROCESSED]
    skipped = [ts for ts, op in ordered if op == CAPTURE_SKIPPED]
    last = (processed[-1] if processed else None, skipped[-1] if skipped else None)
    evidence = _evidence(
        (len(processed), len(skipped)), last, (oldest_pending_age, rejected), now
    )
    problems = [
        p
        for p in (
            _failing_capture(processed, skipped, now),
            _stalled_spool(oldest_pending_age, stall_seconds),
        )
        if p
    ]
    if not problems:
        return CaptureVerdict(True, evidence, "")
    return CaptureVerdict(
        False,
        "; ".join(problems) + f" [{evidence}]",
        _FIX,
    )
