"""Doctor input for the auto-capture check: reads the telemetry log and the spool.

The judgement is ``core.capture_health.assess``; this module only gathers the
evidence. It creates nothing (a doctor must not leave state behind) and reads the
rotated generation of the telemetry log before the live one, so a window that
straddles a rotation is not cut in half.

source: ADR-1095
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from mcp_server.core.capture_health import CaptureVerdict, assess
from mcp_server.infrastructure import capture_spool


class UndecodableLogError(OSError):
    """A telemetry generation holds bytes that are not UTF-8 (a damaged file)."""


def _lines(path: Path) -> Iterator[str]:
    """A missing generation is no evidence, not an error; anything else raises:
    ``OSError`` for an unreadable file, ``UndecodableLogError`` (an ``OSError`` that
    names the file) for one that is not valid UTF-8 (ADR-1095)."""
    try:
        with open(path, encoding="utf-8") as stream:
            yield from stream
    except FileNotFoundError:
        return
    except UnicodeDecodeError as exc:
        raise UndecodableLogError(f"{path} is not valid UTF-8 ({exc.reason})") from exc


def read_events(telemetry_log: Path) -> tuple[list[tuple[float, str]], int]:
    """postcondition: every well-formed sample of the rotated then the live log as
    ``(ts, op)``, and how many lines were not one (counted, never hidden)."""
    events: list[tuple[float, str]] = []
    malformed = 0
    for path in (telemetry_log.with_name(telemetry_log.name + ".1"), telemetry_log):
        for line in _lines(path):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
                events.append((float(sample["ts"]), str(sample["op"])))
            except (ValueError, TypeError, KeyError):
                malformed += 1
    return events, malformed


def capture_verdict(claude_dir: Path, now: float) -> CaptureVerdict:
    """precondition: ``claude_dir`` is the Cortex root (``~/.claude`` by default).
    postcondition: the verdict of ``assess`` over the telemetry log and the spool
    under that root; an unreadable or undecodable log raises ``OSError`` naming
    the file to the caller, which reports it as a failed check."""
    if os.environ.get("CORTEX_TELEMETRY_DISABLED") == "1":
        return CaptureVerdict(
            True,
            "unverifiable: telemetry is disabled (CORTEX_TELEMETRY_DISABLED=1), "
            "so capture outcomes are not recorded",
            "",
        )
    events, malformed = read_events(claude_dir / "methodology" / "telemetry.jsonl")
    spool = capture_spool.spool_path(claude_dir)
    verdict = assess(
        events,
        oldest_pending_age=capture_spool.oldest_pending_age(spool, now),
        stall_seconds=capture_spool.STALL_SECONDS,
        rejected=capture_spool.rejected_count(spool),
        now=now,
    )
    if not malformed:
        return verdict
    note = f"; {malformed} unreadable telemetry line(s) ignored"
    return CaptureVerdict(verdict.ok, verdict.detail + note, verdict.fix)
