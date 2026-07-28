"""Session-counted shared groomer coordinator (issue #171).

Problem it fixes: ``session_start`` used to spawn the 6-hour consolidate
cycle PER session, gated only by a global ``.last_consolidate`` stamp whose
in-flight marker (``"...T... (in-flight)"``) is *unparseable* by
``read_stamp`` — so a second session opening while the first cycle is in
flight reads the stamp as ``None`` (never-run), judges it stale, and spawns
a DUPLICATE cycle against the same store.

This replaces that race with a session-counted, per-store coordinator (CBM's
session-coordination semantics, narrowed to Cortex's one-groomer-per-store
need — NOT a general service daemon):

* **first session ensures the groomer runs** — ``ensure_cycle`` spawns only
  when the period has elapsed AND no cycle is already running.
* **each session registers / deregisters** — ``register`` on SessionStart,
  ``deregister`` on SessionEnd; one liveness-validated file per session.
* **last exit stops it** — ``stop_if_last`` clears the active marker (and
  invokes an injected ``stop_fn``) when the final session deregisters.
* **exactly one cycle per period across N sessions** — the period stamp is
  written UNDER a per-store lock as a *valid parseable* timestamp, so a
  concurrent session that later takes the lock reads it fresh and skips. The
  lock serialises simultaneous decisions; the stamp serialises sequential.

Crash safety: a ``kill -9``'d session leaks its registration file but not its
liveness — ``live_session_count`` sweeps dead-pid registrations before
counting (mirroring ``session_registry.purge_dead_entries``), and the
single-instance guard is a pid file validated by liveness, never a bare flag.

Layer: infrastructure (all I/O). Policy half of the policy/mechanism split;
fs + lock primitives live in ``groomer_coordinator_io.py``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from mcp_server.infrastructure.groomer_coordinator_io import (
    atomic_write_json,
    atomic_write_text,
    decision_lock,
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

# Outcomes of ``ensure_cycle`` — a small closed set of strings so callers
# and tests can branch/observe without importing an Enum across the
# boundary. source: design #171 (this module).
STARTED = "started"
SKIPPED_FRESH = "skipped_fresh"  # period not yet elapsed
SKIPPED_RUNNING = "skipped_running"  # a cycle is already in flight (single-instance)
SKIPPED_LOCKED = "skipped_locked"  # another session holds the decision lock right now

_SCHEMA_VERSION = 1  # registration-file schema; unknown versions ignored on read.


def resolve_store_key(env: dict[str, str] | None = None) -> str:
    """Filesystem-safe key identifying the store this coordinator guards.

    precondition: none. postcondition: returns a stable 16-hex-char token
    derived from the resolved store identity — the SQLite DB path on the
    SQLite backend, the ``DATABASE_URL`` on PostgreSQL — so two windows
    against the SAME store share a coordinator dir and two windows against
    DIFFERENT stores never collide. Degrades to a fixed ``"default"`` key
    (never raises) when backend resolution fails, so coordination still
    happens (one shared coordinator) rather than silently splitting.
    """

    e = env if env is not None else dict(os.environ)
    try:
        settings = get_memory_settings()
        # str(...) coercion: MemorySettings is a pydantic BaseSettings whose
        # attributes the type checker resolves as Unknown; these values ARE
        # strings, and coercing makes ``identity`` a definite ``str`` (never
        # ``str | None``) so the hash below is well-typed. ``get(k) or dflt``
        # (not ``get(k, dflt)``) keeps the same narrowing for the env case.
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

    Construct with an explicit ``store_key`` (see ``resolve_store_key``);
    ``root`` is overridable for tests. All state lives under
    ``root/<store_key>/``: ``sessions/<pid>.json`` registrations, a
    ``groomer.lock`` decision lock, a ``groomer.pid`` single-instance
    guard, a ``.last_consolidate`` period stamp, and an append-only
    ``runs.log`` (NDJSON) for operational duplicate-run observability.
    """

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
        """
        payload = {
            "v": _SCHEMA_VERSION,
            "pid": int(session_pid),
            "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return atomic_write_json(
            self.sessions_dir / f"{int(session_pid)}.json", payload
        )

    def deregister(self, session_pid: int) -> None:
        """Remove a session's registration. Idempotent; never raises."""
        try:
            (self.sessions_dir / f"{int(session_pid)}.json").unlink()
        except OSError:
            pass

    def live_session_count(self) -> int:
        """Count live registrations, reclaiming dead-pid files first.

        postcondition: every ``sessions/<pid>.json`` whose ``pid`` is no
        longer alive (crash / kill -9) is unlinked; returns the count of
        the survivors. Never raises — an unreadable dir counts as zero.
        """
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
        """Yield ``(path, pid)`` for valid registration files. Never raises."""
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

    # ── single-instance guard ───────────────────────────────────────────

    def is_groomer_running(self) -> bool:
        """True iff ``groomer.pid`` names a live process (liveness-validated,
        not a bare flag). A stale pid file from a crashed cycle names a dead
        pid and reads as not-running. Never raises."""
        try:
            raw = self.pid_path.read_text(encoding="utf-8").strip()
            return pid_alive(int(raw))
        except (OSError, ValueError):
            return False

    # ── the exactly-one-per-period gate ─────────────────────────────────

    def ensure_cycle(
        self, *, period_hours: float, spawn_fn, now: datetime | None = None
    ) -> str:
        """Ensure at most one grooming cycle runs per ``period_hours``.

        precondition: ``spawn_fn()`` starts the consolidate cycle and
        returns its pid (or None). postcondition: returns exactly one of
        ``STARTED`` / ``SKIPPED_FRESH`` / ``SKIPPED_RUNNING`` /
        ``SKIPPED_LOCKED``. ``spawn_fn`` is called AT MOST once, and only on
        ``STARTED``. Under the per-store lock the period stamp is (re)written
        as a valid ISO timestamp BEFORE spawning, so any concurrent session
        that subsequently takes the lock observes a fresh stamp and returns
        ``SKIPPED_FRESH`` — the invariant guaranteeing one cycle per period
        across N sessions. invariant: no path both writes the stamp and
        returns a SKIPPED_*.
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        now = now or datetime.now(timezone.utc)
        with decision_lock(self.lock_path) as acquired:
            if not acquired:
                return SKIPPED_LOCKED
            if self.is_groomer_running():
                self._log_run(SKIPPED_RUNNING, now)
                return SKIPPED_RUNNING
            if not self._period_elapsed(period_hours, now):
                return SKIPPED_FRESH
            # Commit the period BEFORE spawning: the stamp is the barrier.
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
        stop path fired (this was the last session). Never raises.
        """
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

    # ── observability (24h zero-duplication evidence) ───────────────────

    def count_cycles_since(self, since: datetime) -> int:
        """Number of ``STARTED`` cycles logged at/after ``since``.

        Operational evidence for the issue's "zero duplicated consolidate
        runs over 24h" criterion: with coordination working, this returns at
        most one per period window. Never raises — a missing/corrupt log line
        is skipped, not fatal.
        """
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
        # Valid ISO only — NEVER an unparseable "(in-flight)" suffix (that
        # was exactly the #171 duplication bug: read-back returned None →
        # concurrent re-spawn). source: design #171 (this module).
        atomic_write_text(self.stamp_path, now.isoformat(timespec="seconds"))
