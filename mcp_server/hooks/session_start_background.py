"""SessionStart hook background work: pipeline wiring, re-analysis, registry.

source: ADR-0498"""

from __future__ import annotations

from collections.abc import Callable

from mcp_server.hooks.launcher_command import launcher_child_command
from mcp_server.hooks.session_start_common import _log
from mcp_server.shared import detached_spawn
from mcp_server.shared.injection_markers import session_id_from_transcript
from mcp_server.infrastructure.log_relay import spawn_logged
from mcp_server.shared.log_rotation import methodology_log_path


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


def _maybe_background_reanalyze(
    project_root: str | None, lookup_cached_graph: Callable[[str], str | None]
) -> None:
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
            graph_is_stale,
        )

        if discover_pipeline_command(project_root) is None:
            return  # Pipeline not installed — nothing to do.

        cached_path = lookup_cached_graph(project_root)
        if not graph_is_stale(cached_path):
            return  # Fresh enough; skip.
        _spawn_reanalysis(project_root)
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"background pipeline reanalysis skipped: {exc}")


def _spawn_reanalysis(project_root: str) -> None:
    """Start the detached ``ingest_codebase`` worker, once per project per TTL."""
    from mcp_server.infrastructure.pipeline_graph_ttl import (  # noqa: PLC0415 — hook latency boundary: imported by _maybe_background_reanalyze already, only once a pipeline is discoverable
        claim_reanalysis_slot,
    )

    # Spawn background ingest. scripts/launcher.py handles PYTHONPATH
    # + deps, then runs the ingest_codebase handler as a one-shot CLI.
    cmd = launcher_child_command(
        "mcp_server.hooks.ingest_codebase_background", project_root
    )
    if cmd is None:
        return
    if not claim_reanalysis_slot(project_root):
        _log("background reanalysis skipped: one already claimed this TTL window")
        return

    # Rotate before spawn; the inherited fd stays open for the worker.
    log_path = methodology_log_path("pipeline_reanalyze.log")
    # source: ADR-1110 — the child's output reaches the log only redacted
    spawn_logged(cmd, log_path, **detached_spawn.options())
    _log(f"background pipeline reanalysis spawned → {log_path}")


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
