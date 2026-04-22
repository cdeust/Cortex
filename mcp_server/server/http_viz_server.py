"""Unified visualization HTTP server — legacy in-process entry point.

The in-process unified viz server was replaced by ``http_standalone.py``,
which runs as a detached subprocess launched via ``http_launcher``. The
only surviving public symbol from this module is
``shutdown_unified_viz_server``, which ``mcp_server.__main__`` calls
during SIGTERM/SIGINT to close the (always-absent) in-process server.

Since ``start_unified_viz_server`` has no callers anywhere in the code
base, the idle timer and HTTP handler never come into existence and
``shutdown_unified_viz_server`` is a guaranteed no-op. The stub is
retained so ``__main__`` keeps compiling until the import is removed.
"""

from __future__ import annotations


def shutdown_unified_viz_server() -> None:
    """No-op — the in-process unified viz server is never started.

    Kept as a stable import surface for ``mcp_server.__main__``; the
    real viz server lives in ``http_standalone.py`` and shuts itself
    down via its idle watchdog.
    """
    return None
