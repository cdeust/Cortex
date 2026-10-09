"""Hook-side worker composition and observable skip policy; no inference imports."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any

from mcp_server.hooks.launcher_command import child_command
from mcp_server.hooks.capture_worker_policy import limits, validate_payload
from mcp_server.infrastructure import capture_spool
from mcp_server.infrastructure.capture_client import deliver
from mcp_server.infrastructure.capture_peer import is_supported
from mcp_server.infrastructure.capture_transport import CaptureTransportError
from mcp_server.infrastructure.config import CLAUDE_DIR

logger = logging.getLogger(__name__)


def report_failure(
    message: str, elapsed: float, operation: str = "capture_skipped"
) -> None:
    """Log and record a failed capture step.

    postcondition: a ``capture_skipped`` report is a declined capture, recorded as
    skipped; any other operation (worker lifecycle, a stalled spool) is an error.
    The two are counted apart so a skip cannot hide among real errors (issue #660)."""
    logger.error("[cortex-capture-worker] %s", message)
    from mcp_server.core import telemetry  # noqa: PLC0415 — hook composition emits telemetry only on failure, no store/model import
    from mcp_server.core.capture_health import CAPTURE_SKIPPED  # noqa: PLC0415 — same: nothing under mcp_server.core loads at hook import

    # source: ADR-0486
    telemetry.record(
        operation,
        latency_ms=elapsed * 1000.0,
        ok=False,
        skipped=operation == CAPTURE_SKIPPED,
    )


# source: https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
# (DETACHED_PROCESS: no console of the parent; CREATE_NEW_PROCESS_GROUP: not
# signalled with the parent's group). The ``subprocess.*`` names of these flags
# exist only on Windows, so the documented values are spelled out to keep
# ``popen_options`` a pure function that macOS and Linux can test.
_WINDOWS_DETACHED = 0x00000008 | 0x00000200


def popen_options(platform: str, stream: IO[Any]) -> dict[str, Any]:
    """Options that start the drainer fully detached from the hook process.

    postcondition: stdin is closed, stdout and stderr go to ``stream``
    (the drainer's one log, so a crash before its logging exists is not lost), and
    the child does not die with the hook. Windows has no ``start_new_session``
    (``subprocess`` ignores it there) and no ``pass_fds``; it detaches through
    ``creationflags``."""
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": stream,
        "stderr": stream,
        "close_fds": True,
        "cwd": Path(__file__).resolve().parents[2],
        "env": dict(os.environ),
    }
    if platform == "win32":
        options["creationflags"] = _WINDOWS_DETACHED
    else:
        options["start_new_session"] = True
    return options


def spawn_drainer(stream: IO[Any]) -> subprocess.Popen[Any]:
    """Start ``capture_drain`` and do not wait for it. source: ADR-1094"""
    command = child_command("mcp_server.hooks.capture_drain")
    return subprocess.Popen(command, **popen_options(sys.platform, stream))


def _spool(payload: dict[str, object]) -> None:
    """Platform without the resident worker: durable file, then a detached drainer.

    The file is written before the drainer starts, so a spawn failure loses
    nothing: the next capture's drainer stores it."""
    spool = capture_spool.spool_directory(CLAUDE_DIR)
    age = capture_spool.oldest_pending_age(spool, time.time())
    if age is not None and age > capture_spool.STALL_SECONDS:
        # a drainer that is hung or cannot start leaves a growing backlog and, until
        # now, said nothing: surface it through telemetry on every capture (ADR-1094)
        report_failure(
            f"capture spool stalled: oldest pending file is {age:.0f}s old",
            age,
            operation="capture_spool_stalled",
        )
    capture_spool.write(spool, payload)
    with capture_spool.open_log(spool) as stream:
        spawn_drainer(stream)


def _spawn(listener: socket.socket, lease: int) -> None:
    command = child_command(
        "mcp_server.hooks.capture_worker",
        "--listener-fd",
        str(listener.fileno()),
        "--lease-fd",
        str(lease),
    )
    # source: ADR-0486
    subprocess.Popen(
        command,
        pass_fds=(listener.fileno(), lease),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=Path(__file__).resolve().parents[2],
        env=dict(os.environ),
    )


def dispatch(payload: dict[str, object]) -> bool:
    started = time.monotonic()
    try:
        validate_payload(payload)
        if is_supported():
            deliver(CLAUDE_DIR, payload, limits(), _spawn)
        else:
            _spool(payload)
    except (OSError, ValueError, CaptureTransportError) as exc:
        elapsed = time.monotonic() - started
        report_failure(
            f"capture skipped after {elapsed:.3f}s: {type(exc).__name__}: {exc}",
            elapsed,
        )
        return False
    return True
