"""Hook-side worker composition and observable skip policy; no inference imports."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp_server.hooks.capture_worker_policy import limits, validate_payload
from mcp_server.infrastructure.capture_client import deliver
from mcp_server.infrastructure.capture_transport import CaptureTransportError
from mcp_server.infrastructure.config import CLAUDE_DIR

logger = logging.getLogger(__name__)


def report_failure(
    message: str, elapsed: float, operation: str = "capture_skipped"
) -> None:
    logger.error("[cortex-capture-worker] %s", message)
    from mcp_server.core import telemetry  # noqa: PLC0415 — hook composition emits telemetry only on failure, no store/model import

    # source: ADR-0486
    telemetry.record(operation, latency_ms=elapsed * 1000.0, ok=False)


def _spawn(listener: socket.socket, lease: int) -> None:
    command = [
        sys.executable,
        "-m",
        "mcp_server.hooks.capture_worker",
        "--listener-fd",
        str(listener.fileno()),
        "--lease-fd",
        str(lease),
    ]
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
        deliver(CLAUDE_DIR, payload, limits(), _spawn)
    except (OSError, ValueError, CaptureTransportError) as exc:
        elapsed = time.monotonic() - started
        report_failure(
            f"capture skipped after {elapsed:.3f}s: {type(exc).__name__}: {exc}",
            elapsed,
        )
        return False
    return True
