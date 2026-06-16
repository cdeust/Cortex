"""Progress reporting protocol for long-running ingest operations.

Pure shared layer: stdlib + typing only. No I/O, no fastmcp, no rich.
Implementations live in infrastructure (McpProgress) or handler entry
points (CliProgress in scripts/).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressReporter(Protocol):
    """Contract for reporting ingest progress to any sink.

    All methods are synchronous. Implementations may fire-and-forget
    async dispatches internally, but callers see a plain sync interface
    so they can be used from both async handlers and worker threads.
    """

    def stage(self, name: str, index: int, total: int) -> None:
        """Signal entry into a named pipeline stage.

        Precondition:  0 <= index < total; name is non-empty.
        Postcondition: sink receives stage label + fraction (index / total).
        """
        ...

    def advance(self, done: int, total: int | None = None) -> None:
        """Update within-stage progress.

        Precondition:  done >= 0; total is None (indeterminate) or > 0.
        Postcondition: sink receives updated overall fraction; throttled
                       to ~2 Hz so callers may call on every loop iteration.
        """
        ...

    def log(self, message: str) -> None:
        """Emit a human-readable log line to the sink."""
        ...

    def close(self) -> None:
        """Release any resources held by this reporter (e.g., rich Live)."""
        ...


class NullProgress:
    """No-op implementation — default when no reporter is wired.

    Postcondition: all methods are no-ops; no state is mutated.
    This preserves backward compatibility for all existing callers.
    """

    def stage(self, name: str, index: int, total: int) -> None:
        pass

    def advance(self, done: int, total: int | None = None) -> None:
        pass

    def log(self, message: str) -> None:
        pass

    def close(self) -> None:
        pass
