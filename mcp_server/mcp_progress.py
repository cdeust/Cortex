"""Infrastructure adapter: MCP progress reporting via MCP Context.

source: ADR-0635"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from mcp.server.mcpserver import Context


class McpProgress:
    """ProgressReporter that forwards to MCP Context from any thread.

    Precondition (constructor):
      ctx  is a live MCP Context bound to the main event loop.
      loop is the main asyncio event loop (get_running_loop() from the
           tool registration coroutine, before asyncio.to_thread hands off).

    source: ADR-0635

    Overall progress fraction:
      fraction = (stage_index + within_fraction) / stage_total
      where within_fraction = done / total when total > 0, else 0.0.
    """

    # source: ADR-0635

    _ADVANCE_MIN_INTERVAL_S: float = 0.5

    def __init__(self, ctx: "Context", loop: asyncio.AbstractEventLoop) -> None:
        self._ctx = ctx
        self._loop = loop
        self._stage_index: int = 0
        self._stage_total: int = 1
        self._within_fraction: float = 0.0
        self._last_advance_ts: float = 0.0

    # -- helpers --

    def _overall(self) -> float:
        """Compute overall fraction in [0.0, 1.0]."""
        if self._stage_total <= 0:
            return 0.0
        return (self._stage_index + self._within_fraction) / self._stage_total

    def _dispatch(self, coro) -> None:
        """Fire-and-forget coroutine on the main loop; swallow all errors."""
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            # Loop already closed (server shutting down mid-operation) —
            # progress updates are cosmetic and safe to drop.
            coro.close()

    # -- ProgressReporter interface --

    def stage(self, name: str, index: int, total: int) -> None:
        """Signal entry into a named pipeline stage."""
        self._stage_index = index
        self._stage_total = max(1, total)
        self._within_fraction = 0.0
        overall = self._overall()
        self._dispatch(self._ctx.report_progress(progress=overall, total=1.0))
        self._dispatch(self._ctx.info(f"[{index + 1}/{total}] {name}"))

    def advance(self, done: int, total: int | None = None) -> None:
        """Update within-stage progress; throttled to ~2 Hz.

        source: ADR-0635"""
        now = time.monotonic()
        if now - self._last_advance_ts < self._ADVANCE_MIN_INTERVAL_S:
            return
        self._last_advance_ts = now
        if total and total > 0:
            self._within_fraction = min(1.0, done / total)
        else:
            self._within_fraction = 0.0
        overall = self._overall()
        self._dispatch(self._ctx.report_progress(progress=overall, total=1.0))
        if not (total and total > 0):
            # source: ADR-0635

            self._dispatch(self._ctx.info(f"ingested {done:,} symbols…"))

    def log(self, message: str) -> None:
        """Emit a human-readable log line via ctx.info."""
        self._dispatch(self._ctx.info(message))

    def close(self) -> None:
        """No resources to release for the MCP adapter."""
        pass
