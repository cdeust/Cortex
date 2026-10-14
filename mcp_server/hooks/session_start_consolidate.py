"""SessionStart hook background consolidate cycle: coordinator and spawn.

source: ADR-0498"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from mcp_server.hooks.launcher_command import child_command
from mcp_server.hooks.session_start_common import _log
from mcp_server.shared import detached_spawn
from mcp_server.shared.log_rotation import methodology_log_path, open_rotating_log


_CONSOLIDATE_TTL_HOURS: float = float(
    os.environ.get("CORTEX_CONSOLIDATE_TTL_HOURS", "6")
)


def _spawn_consolidate_cycle(spawn_options: dict[str, Any]) -> int | None:
    """Spawn the detached ``consolidate_background`` worker; return its pid.

    precondition: ``spawn_options`` came from ``detached_spawn.options()``,
    decided by the caller before it stamped the period (ADR-1102).
    postcondition: a fully-detached subprocess (own
    process group, stdio → ``consolidate.log``) is started and its pid
    returned, or None if the spawn itself failed. The worker runs decay,
    compression, CLS, memify, cascade, homeostatic, emergence cycles plus
    autonomous wiki maintenance — this is the SAME cycle as before; #171
    changes only WHO decides to start it, never what it does.
    """
    cmd = child_command("mcp_server.hooks.consolidate_background")

    log_path = methodology_log_path("consolidate.log")
    with open_rotating_log(log_path) as log:
        proc = subprocess.Popen(  # noqa: S603 — cmd built from trusted sources
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            **spawn_options,
        )
    _log(f"background consolidate spawned → {log_path}")
    return proc.pid


def _maybe_background_consolidate() -> None:
    """Ensure ONE consolidate cycle runs per period across N sessions (#171).

    The session is keyed by its window's ``claude`` pid. When that identity
    cannot be resolved (no ``claude`` ancestor, or the process table is
    unreadable, here or during the liveness probe) the hook fails hard: it
    logs an ERROR and starts no cycle. It does NOT take the legacy path,
    which bypasses the coordinator's lock and ``groomer.pid`` guard and would
    let overlapping windows spawn duplicate cycles (the race #171 removed).
    The legacy path remains for other coordinator failures (I/O).

    source: ADR-1097 (coordinator: ADR-0527; consolidate period: ADR-0498)"""
    try:
        from mcp_server.infrastructure.groomer_coordinator import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            GroomerCoordinator,
            resolve_store_key,
        )

        coord = GroomerCoordinator(resolve_store_key())
        outcome = _ensure_coordinated_cycle(coord)
        if outcome is not None:
            _log(f"groomer coordinator: {outcome}")
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(
            f"NOTICE: groomer coordinator unavailable ({exc}); falling back "
            "to legacy per-session consolidate spawn"
        )
        _legacy_background_consolidate()


def _consolidate_spawn_options() -> dict[str, Any] | None:
    """Decide the spawn options once, before the period is stamped.

    postcondition: the options, or None after logging ERROR when the job
    state cannot be read; the caller then stamps and spawns nothing, the
    window staying registered (a spawn failure, not a coordinator failure).

    source: ADR-1102"""
    try:
        return detached_spawn.options()
    except OSError as exc:
        _log(
            f"ERROR: consolidate spawn options unavailable ({exc}); "
            "no consolidate cycle started this session"
        )
        return None


def _ensure_coordinated_cycle(coord) -> str | None:
    """Register this window and ensure the cycle; None on a hard failure.

    postcondition: on an unresolved window identity, an unreadable process
    table (ADR-1097 points 2, 3) or an unreadable job state (ADR-1102) logs
    ERROR with the cause and returns None with nothing spawned or stamped;
    the window stays registered only in the job-state case.

    source: ADR-1097 and ADR-1102"""
    from mcp_server.infrastructure.groomer_identity import (  # noqa: PLC0415 — hook latency boundary: see _maybe_background_consolidate
        LivenessProbeUnavailableError,
        WindowIdentityUnavailableError,
        window_pid,
    )

    try:
        session_pid = window_pid()
    except (WindowIdentityUnavailableError, OSError) as exc:
        _log(
            f"ERROR: groomer coordinator: window identity unavailable ({exc}); "
            "no consolidate cycle started this session"
        )
        return None
    coord.register(session_pid)  # counted for last-exit stop (ADR-1102)
    spawn_options = _consolidate_spawn_options()
    if spawn_options is None:
        return None
    try:
        return coord.ensure_cycle(
            period_hours=_CONSOLIDATE_TTL_HOURS,
            spawn_fn=lambda: _spawn_consolidate_cycle(spawn_options),
        )
    except LivenessProbeUnavailableError as exc:
        coord.deregister(session_pid)
        _log(
            f"ERROR: groomer coordinator: liveness probe failed ({exc}); "
            "no consolidate cycle started this session"
        )
        return None


def _legacy_background_consolidate() -> None:
    """Pre-#171 per-session stamp spawn — the honest degrade path.

    Kept as the fallback the coordinator degrades to (never a silent skip).
    Spawns the cycle when the global ``.last_consolidate`` stamp is older
    than the TTL. Retains the crude ``"(in-flight)"`` marker: under this
    path (coordinator wholly unavailable) it is still strictly better than
    no guard at all.
    """
    try:
        from mcp_server.hooks.consolidate_background import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            STAMP_PATH,
            read_stamp,
        )

        last = read_stamp()
        if last is not None:
            age_hours = (_dt.now(_tz.utc) - last).total_seconds() / 3600.0
            if age_hours < _CONSOLIDATE_TTL_HOURS:
                return  # Fresh enough; skip.

        # decided before the in-flight stamp, like the coordinated path
        spawn_options = detached_spawn.options()
        try:
            STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
            STAMP_PATH.write_text(
                __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(timespec="seconds")
                + " (in-flight)",
                encoding="utf-8",
            )
        except OSError:
            pass
        _spawn_consolidate_cycle(spawn_options)
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"background consolidate skipped: {exc}")
