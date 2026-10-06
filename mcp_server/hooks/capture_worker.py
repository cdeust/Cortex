"""Resident capture composition root; imports inference only after admission.

The listener and lease are inherited from the launching hook. The handler's
existing store/model singletons remain alive on this one asyncio event loop.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import time
from pathlib import Path

from mcp_server.hooks.capture_store import remember
from mcp_server.hooks.capture_worker_policy import limits
from mcp_server.hooks.capture_worker_logging import configure
from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit
from mcp_server.infrastructure.capture_server import CaptureServer, ServerPolicy
from mcp_server.infrastructure.capture_socket import remove_socket, runtime_directory

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listener-fd", type=int, required=True)
    parser.add_argument("--lease-fd", type=int, required=True)
    args = parser.parse_args()
    from mcp_server.hooks.capture_dispatch import report_failure  # noqa: PLC0415 — composition root binds diagnostics
    from mcp_server.infrastructure.config import CLAUDE_DIR  # noqa: PLC0415 — composition resolves the configured root

    runtime = runtime_directory(CLAUDE_DIR)
    configure(runtime)
    listener = socket.socket(fileno=args.listener_fd)
    path = Path(listener.getsockname())
    if path != runtime / "socket":
        raise ValueError("inherited capture listener does not match configured root")
    try:
        with close_shared_store_on_exit():
            CaptureServer(
                listener, remember, ServerPolicy(limits(), report_failure)
            ).run()
    finally:
        _close_endpoint(path, args.lease_fd)


def _close_endpoint(path: Path, descriptor: int) -> None:
    from mcp_server.hooks.capture_dispatch import report_failure  # noqa: PLC0415 — lifecycle diagnostics stay in the hook composition

    started = time.monotonic()
    try:
        remove_socket(path)
    except OSError as exc:
        report_failure(
            f"capture socket cleanup failed: {exc}",
            time.monotonic() - started,
            "capture_worker_lifecycle",
        )
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    main()
