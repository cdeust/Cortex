"""The one process-liveness probe (``pid_alive``) for every caller.

Layer: shared (stdlib only), so the infrastructure modules and the launcher
bootstrap (``scripts/launcher_deps_fs.py``) share one definition. ``os.kill``
with signal 0 is the POSIX existence check; it is NOT one on Windows (see
``win32_process`` for the CPython source and docs), where this module uses
``OpenProcess`` + ``GetExitCodeProcess`` instead.

source: ADR-1096"""

from __future__ import annotations

import os

from mcp_server.shared import platform as host_platform


def pid_alive(pid: int) -> bool:
    """True iff ``pid`` currently identifies a live process.

    precondition: none. postcondition: False for ``pid <= 0``; on POSIX a
    permission error (pid exists, other user) counts as alive; on Windows
    see ``win32_process.pid_alive_with``. No signal is ever delivered to the
    target on any platform. Windows raises ``OSError`` on an undocumented
    failure rather than answering "dead".

    source: ADR-1096"""
    if pid <= 0:
        return False
    if host_platform.IS_WINDOWS:
        # ctypes loads only here: the POSIX launcher bootstrap never imports it
        from mcp_server.shared import win32_process  # noqa: PLC0415

        return win32_process.pid_alive(pid)
    return _posix_pid_alive(pid)


def _posix_pid_alive(pid: int) -> bool:
    """POSIX: signal 0 performs the existence and permission checks only."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
