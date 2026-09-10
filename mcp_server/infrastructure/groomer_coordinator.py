"""Layer: infrastructure (all I/O). Policy half of the policy/mechanism split;
fs + lock primitives live in ``groomer_coordinator_io.py``.

source: ADR-0527"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from mcp_server.infrastructure.groomer_coordinator_io import (
    atomic_write_json,
    atomic_write_text,
    DecisionLock,
    parse_iso,
    pid_alive,
)
from mcp_server.shared.platform import cache_dir
from mcp_server.observability import silent_failure
import hashlib
import os
from mcp_server.infrastructure.backend_marker import effective_backend
from mcp_server.infrastructure.memory_config import get_memory_settings

logger = logging.getLogger(__name__)

# source: ADR-0527
STARTED = "started"
SKIPPED_FRESH = "skipped_fresh"  # period not yet elapsed
SKIPPED_RUNNING = "skipped_running"  # a cycle is already in flight (single-instance)
SKIPPED_LOCKED = "skipped_locked"  # source: ADR-0527

_SCHEMA_VERSION = 1  # registration-file schema; unknown versions ignored on read.


def resolve_store_key(env: dict[str, str] | None = None) -> str:
    """precondition: none. postcondition: returns a stable 16-hex-char token
        derived from the resolved store identity — the SQLite DB path on the
        SQLite backend, the ``DATABASE_URL`` on PostgreSQL — so two windows
        against the SAME store share a coordinator dir and two windows against
        DIFFERENT stores never collide.

    source: ADR-0527"""

    e = env if env is not None else dict(os.environ)
    try:
        settings = get_memory_settings()
        # source: ADR-0527
        if effective_backend(e) == "sqlite":
            identity = str(settings.SQLITE_FALLBACK_PATH)
        else:
            identity = e.get("DATABASE_URL") or str(settings.DATABASE_URL)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("groomer_coordinator.store_identity", exc)
        return "default"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


class GroomerCoordinator:
    """Per-store session-counting coordinator for the consolidate cycle.

    source: ADR-0527"""

    def __init__(self, store_key: str, *, root: Path | None = None) -> None:
        base_root = (
            root if root is not None else cache_dir() / "cortex" / "groomer-coordinator"
        )
        self.base_dir = base_root / store_key
        self.sessions_dir = self.base_dir / "sessions"
        self.lock_path = self.base_dir / "groomer.lock"
        self.pid_path = self.base_dir / "groomer.pid"
        self.stamp_path = self.base_dir / ".last_consolidate"
        self.log_path = self.base_dir / "runs.log"

    # ── session registration (crash-safe counting) ──────────────────────

    def register(self, session_pid: int) -> bool:
        """Register a live session. Idempotent per pid.

        postcondition: ``sessions/<session_pid>.json`` exists holding
                ``{v, pid, registered_at}``, written atomically. Returns False
                (never raises) on I/O failure, so the caller can degrade to legacy
                per-session behaviour with a logged NOTICE.

        source: ADR-0527"""
        payload = {
            "v": _SCHEMA_VERSION,
            "pid": int(session_pid),
            "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return atomic_write_json(
            self.sessions_dir / f"{int(session_pid)}.json", payload
        )

    def deregister(self, session_pid: int) -> None:
        """Remove a session's registration.

        source: ADR-0527"""
        try:
            (self.sessions_dir / f"{int(session_pid)}.json").unlink()
        except OSError:
            pass

    def live_session_count(self) -> int:
        """Count live registrations, reclaiming dead-pid files first.

        postcondition: every ``sessions/<pid>.json`` whose ``pid`` is no
                longer alive (crash / kill -9) is unlinked; returns the count of
                the survivors.

        source: ADR-0527"""
        live = 0
        for path, pid in self._iter_session_files():
            if pid_alive(pid):
                live += 1
            else:
                try:
                    path.unlink()
                except OSError:
                    pass
        return live

    def _iter_session_files(self):
        """Yield ``(path, pid)`` for valid registration files.

        source: ADR-0527"""
        try:
            entries = list(self.sessions_dir.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.suffix != ".json":
                continue
            try:
                yield entry, int(entry.stem)
            except ValueError:
                continue

    # source: ADR-0527

    def is_groomer_running(self) -> bool:
        """True iff ``groomer.pid`` names a live process (liveness-validated, not
        a bare flag).

        source: ADR-0527"""
        try:
            raw = self.pid_path.read_text(encoding="utf-8").strip()
            return pid_alive(int(raw))
        except (OSError, ValueError):
            return False

    # ── the exactly-one-per-period gate ─────────────────────────────────

    def ensure_cycle(
        self, *, period_hours: float, spawn_fn, now: datetime | None = None
    ) -> str:
        """precondition: ``spawn_fn()`` starts the consolidate cycle and
                returns its pid (or None). postcondition: returns exactly one of
                ``STARTED`` / ``SKIPPED_FRESH`` / ``SKIPPED_RUNNING`` /
                ``SKIPPED_LOCKED``. ``spawn_fn`` is called AT MOST once, and only on
                ``STARTED``.

        source: ADR-0527"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        now = now or datetime.now(timezone.utc)
        with DecisionLock(self.lock_path) as acquired:
            if not acquired:
                return SKIPPED_LOCKED
            if self.is_groomer_running():
                self._log_run(SKIPPED_RUNNING, now)
                return SKIPPED_RUNNING
            if not self._period_elapsed(period_hours, now):
                return SKIPPED_FRESH
            # source: ADR-0527
            self._write_stamp(now)
            pid = spawn_fn()
            if pid is not None:
                atomic_write_text(self.pid_path, str(int(pid)))
            self._log_run(STARTED, now, session_pid=pid)
            return STARTED

    def _period_elapsed(self, period_hours: float, now: datetime) -> bool:
        last = self._read_stamp()
        if last is None:
            return True
        return (now - last).total_seconds() / 3600.0 >= period_hours

    # ── last-exit stop ──────────────────────────────────────────────────

    def stop_if_last(self, session_pid: int, *, stop_fn=None) -> bool:
        """Deregister ``session_pid``; if it was the last live session, stop.

        postcondition: the session's registration is removed; when no live
                session remains, the ``groomer.pid`` single-instance marker is
                cleared and ``stop_fn`` (if given) is invoked. Returns True iff the
                stop path fired (this was the last session).

        source: ADR-0527"""
        self.deregister(session_pid)
        if self.live_session_count() > 0:
            return False
        try:
            self.pid_path.unlink()
        except OSError:
            pass
        if stop_fn is not None:
            try:
                stop_fn()
            except Exception as exc:  # noqa: BLE001 — shutdown callback must not block exit
                logger.debug("groomer stop callback failed: %s", exc)
        self._log_run("stopped_last_exit", datetime.now(timezone.utc))
        return True

    # source: ADR-0527

    def count_cycles_since(self, since: datetime) -> int:
        """Number of ``STARTED`` cycles logged at/after ``since``.

        source: ADR-0527"""
        count = 0
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("outcome") != STARTED:
                continue
            ts = parse_iso(rec.get("ts"))
            if ts is not None and ts >= since:
                count += 1
        return count

    def _log_run(
        self, outcome: str, now: datetime, *, session_pid: int | None = None
    ) -> None:
        rec: dict[str, object] = {
            "ts": now.isoformat(timespec="seconds"),
            "outcome": outcome,
        }
        if session_pid is not None:
            rec["session_pid"] = int(session_pid)
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    # ── stamp primitives ────────────────────────────────────────────────

    def _read_stamp(self) -> datetime | None:
        try:
            raw = self.stamp_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return parse_iso(raw)

    def _write_stamp(self, now: datetime) -> None:
        # source: ADR-0527
        atomic_write_text(self.stamp_path, now.isoformat(timespec="seconds"))
