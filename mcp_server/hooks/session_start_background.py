"""SessionStart hook background work: pipeline wiring, re-analysis, registry.

source: ADR-0498"""

from __future__ import annotations

import subprocess

from mcp_server.handlers.injection_receipts import session_id_from_transcript
from mcp_server.hooks.launcher_command import launcher_child_command
from mcp_server.hooks.session_start_common import _log
from mcp_server.shared import detached_spawn
from mcp_server.shared.log_rotation import methodology_log_path, open_rotating_log


def _auto_wire_pipeline(project_root: str | None) -> None:
    """Best-effort: auto-add the ai-architect-mcp-codebase MCP server to
    mcp-connections.json when detected. Non-blocking; failures go to
    stderr only.

    Idempotent — once the ``codebase`` server entry exists, subsequent
    SessionStarts leave the config alone. Users who customized their
    config keep their customization.
    """
    try:
        from mcp_server.infrastructure.pipeline_discovery import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            ensure_pipeline_connection,
        )

        result = ensure_pipeline_connection(project_root)
        action = result.get("action", "unknown")
        if action in {"wrote_config", "added_codebase"}:
            _log(
                f"pipeline auto-wired ({result.get('binary')}) in {result.get('path')}"
            )
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"pipeline auto-wire skipped: {exc}")


def _maybe_background_reanalyze(project_root: str | None) -> None:
    """Spawn background ``ingest_codebase`` when the graph is stale.

    Runs detached (``subprocess.Popen`` with its own process group) so
    SessionStart returns immediately — the next session sees a fresh
    graph. Blocks NOTHING in the current session. Auto-stops if no
    pipeline is configured or graph is fresh.

    Gated by the TTL check in ``pipeline_graph_ttl.graph_is_stale``.
    ``project_root`` is ``resolve_project_root(event, os.environ)``, never
    ``os.getcwd()``: under ``scripts/launcher.py`` the cwd is the plugin
    root, and ingesting it is the leak the #679 guard reported. ``None``
    (no CLAUDE_PROJECT_ROOT, no event cwd) spawns nothing (issue #604).
    """
    if project_root is None:
        _log("background reanalysis skipped: project root unresolved")
        return
    try:
        from mcp_server.infrastructure.pipeline_discovery import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            discover_pipeline_command,
        )
        from mcp_server.infrastructure.pipeline_graph_ttl import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            claim_reanalysis_slot,
            graph_is_stale,
        )

        if discover_pipeline_command(project_root) is None:
            return  # Pipeline not installed — nothing to do.

        cached_path = _lookup_cached_graph_path(project_root)
        if not graph_is_stale(cached_path):
            return  # Fresh enough; skip.

        # Spawn background ingest. scripts/launcher.py handles PYTHONPATH
        # + deps, then runs the ingest_codebase handler as a one-shot CLI.
        cmd = launcher_child_command(
            "mcp_server.hooks.ingest_codebase_background", project_root
        )
        if cmd is None:
            return
        if not claim_reanalysis_slot(project_root):
            _log("background reanalysis skipped: one already started within the TTL")
            return

        # Rotate before spawn; the inherited fd stays open for the worker.
        log_path = methodology_log_path("pipeline_reanalyze.log")
        with open_rotating_log(log_path) as log:
            subprocess.Popen(  # noqa: S603 — cmd built from trusted sources
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **detached_spawn.options(),
            )
        _log(f"background pipeline reanalysis spawned → {log_path}")
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"background pipeline reanalysis skipped: {exc}")


def _lookup_cached_graph_path(project_root: str) -> str | None:
    """The newest materialised graph memoised for this project, or None.

    Reads through the configured store, SQLite or PostgreSQL alike: a
    psycopg-only read returned None on SQLite, so every SessionStart saw a
    stale graph and spawned a re-ingest (issue #751). A store failure
    propagates to ``_maybe_background_reanalyze``, which logs it and spawns
    nothing: an unknown cache never costs the user a background ingest.
    """
    from mcp_server.handlers.ingest_helpers import materialised_graph_paths  # noqa: PLC0415 — hook latency boundary: imported only once a pipeline is discoverable (store import ~0.1 s, measured 2026-10-14)
    from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: imported only once a pipeline is discoverable (store import ~0.1 s, measured 2026-10-14)

    paths = materialised_graph_paths(get_shared_store(), project_root)
    return paths[0] if paths else None


def _refresh_session_registry(event: dict) -> None:
    """Best-effort write of this window's current session into the
        per-window registry (T2-D6, T2-D11), plus an opportunistic purge of
        dead-pid entries.

        precondition: ``event`` is the tolerant ``_read_event()`` result —
        may be ``{}``. postcondition: on success, this window's registry
        entry (keyed by the ancestor ``claude`` pid) holds the transcript
        stem computed by ``session_id_from_transcript`` and stale entries
        for closed windows are removed. Any failure — resolution, I/O,
        import — degrades to a stderr log line and NEVER raises: the
        SessionStart banner is critical and must ship regardless of the
        registry's state (design §1 directing invariant).

    source: ADR-0498"""
    try:
        from mcp_server.infrastructure.session_registry import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            purge_dead_entries,
            write_session,
        )

        write_session(session_id_from_transcript(event.get("transcript_path")))
        purge_dead_entries()
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"session registry refresh skipped (non-fatal): {exc}")
