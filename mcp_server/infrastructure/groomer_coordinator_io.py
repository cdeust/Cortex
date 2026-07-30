"""Low-level I/O + lock primitives for the groomer coordinator (issue #171).

Mechanism half of the policy/mechanism split (coding-standards §1.1 SRP):
``groomer_coordinator.py`` owns the session-counting POLICY; this module
owns the filesystem + cross-platform locking MECHANISM it stands on —
pid-liveness, atomic replace, ISO parsing, and a non-blocking per-store
lock. Kept separate so the policy file reasons about coordination without
carrying the platform ``fcntl``/``msvcrt`` split inline.

Layer: infrastructure (all I/O). Imports shared/ + stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def pid_alive(pid: int) -> bool:
    """True iff ``pid`` currently names a live process. Never raises.

    A ``PermissionError`` (pid exists, owned by another user) counts as
    alive — same discipline as ``session_registry._pid_alive`` (a peer infra
    module); duplicated rather than importing a private symbol.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def parse_iso(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 stamp to an aware UTC datetime, or None. Never raises."""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def atomic_write_text(path: Path, text: str) -> bool:
    """Atomically replace ``path`` with ``text`` (tmp + ``os.replace``).

    postcondition: a concurrent reader observes either the old content or
    the new content in full, never a torn write. Returns False (never
    raises) on any I/O failure.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception:
            os.unlink(tmp)
            raise
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def atomic_write_json(path: Path, payload: dict) -> bool:
    """Atomically replace ``path`` with the JSON of ``payload``."""
    return atomic_write_text(path, json.dumps(payload))


class DecisionLock:
    """Non-blocking per-store lock context manager.

    ``with DecisionLock(path) as acquired:`` yields True when this holder
    won the lock and False when another holder already owns it (contended
    simultaneous decision). Advisory ``flock`` on POSIX, mandatory
    ``msvcrt.locking`` on Windows — same split as ``pipeline_install_lock``
    (source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.4). Never raises out
    of ``__enter__``: a lock-open failure degrades to "not acquired" so the
    caller skips rather than crashes.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> bool:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            self._fd = None
            return False
        if _try_lock(self._fd):
            return True
        os.close(self._fd)
        self._fd = None
        return False

    def __exit__(self, *exc) -> None:
        if self._fd is None:
            return
        _unlock(self._fd)
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None


# Direct ``sys.platform`` comparison (not the ``IS_WINDOWS`` alias): the type
# checker statically prunes the unreachable branch per its configured target
# platform, so ``msvcrt``/``fcntl`` are each only analysed where they exist —
# an imported bool alias would not enable that narrowing.
if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    def _unlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
