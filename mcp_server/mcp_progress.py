"""Infrastructure adapter: MCP progress reporting via FastMCP Context.

Lives outside shared/ because it imports fastmcp and asyncio — both
outer-layer concerns. Wired by tool_registry_ingest.py (the composition root).

Thread-bridging contract (CRITICAL):
  The ingest handler runs on a WORKER THREAD (via asyncio.to_thread in
  safe_handler). ctx.report_progress / ctx.info are async, bound to the
  MAIN event loop. Dispatching them from the worker thread requires
  run_coroutine_threadsafe. We fire-and-forget (never .result()) and swallow
  exceptions so a slow or dead MCP client never blocks the ingest.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from fastmcp import Context


class McpProgress:
    """ProgressReporter that forwards to FastMCP Context from any thread.

    Precondition (constructor):
      ctx  is a live FastMCP Context bound to the main event loop.
      loop is the main asyncio event loop (get_running_loop() from the
           tool registration coroutine, before asyncio.to_thread hands off).

    Postcondition (each public method):
      A fire-and-forget coroutine is scheduled on the main loop via
      run_coroutine_threadsafe; exceptions are silently swallowed so
      ingest is never blocked by progress delivery failures.

    Overall progress fraction:
      fraction = (stage_index + within_fraction) / stage_total
      where within_fraction = done / total when total > 0, else 0.0.
    """

    # UI refresh cadence: 0.5 s ≈ 2 Hz — below the ~10 Hz flicker-fusion
    # threshold for perceived smoothness (Wertheim 1994, "Motion perception
    # during self-motion") while bounding MCP notification volume to at most
    # 2 messages/s per stage. source: chosen UI cadence; not a measured
    # production benchmark.
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
        except Exception:
            pass

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

        When total is known the bar fraction advances determinately.
        When total is None (uncapped ingest — no cheap count is available)
        the fraction stays at 0 but a ctx.info() line with the running count
        is still dispatched so the user sees visible movement.
        """
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
            # Indeterminate total: emit running count as text so the user
            # sees activity even though the bar fraction cannot advance.
            self._dispatch(self._ctx.info(f"ingested {done:,} symbols…"))

    def log(self, message: str) -> None:
        """Emit a human-readable log line via ctx.info."""
        self._dispatch(self._ctx.info(message))

    def close(self) -> None:
        """No resources to release for the MCP adapter."""
        pass
