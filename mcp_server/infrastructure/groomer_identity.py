"""Layer: infrastructure. Identity and failure types of the groomer coordinator:
the pid that keys a window's session, and the two conditions under which a hook
fails hard instead of degrading (split from ``groomer_coordinator.py`` for size).

source: ADR-1097 (coordinator: ADR-0527; window identity: ADR-0597)"""

from __future__ import annotations

from mcp_server.infrastructure import session_registry


class WindowIdentityUnavailableError(RuntimeError):
    """The window's ``claude`` process could not be resolved.

    source: ADR-1097"""


class LivenessProbeUnavailableError(RuntimeError):
    """The liveness probe could not read the process table (``OSError``).

    Distinct from an I/O failure on the coordinator's own files, which keeps
    the legacy degrade path.

    source: ADR-1097 (point 3)"""


def window_pid() -> int:
    """Pid of the ``claude`` process that owns the calling hook.

    precondition: called from a hook process, a descendant of the window's
        ``claude`` process. postcondition: returns that pid. SessionStart and
        SessionEnd of one window resolve the same pid, and it stays alive for
        the whole session; the hook's own pid does not (it exits within a
        second, so ``live_session_count`` reclaims it). Raises
        ``WindowIdentityUnavailableError`` when the ancestor walk finds no
        ``claude`` process; no other pid stands in for it.

    source: ADR-1097 (coordinator: ADR-0527; window identity: ADR-0597)"""
    pid = session_registry.find_claude_ancestor()
    if pid is None:
        raise WindowIdentityUnavailableError(
            "no claude ancestor process found; cannot key the session registration"
        )
    return pid
