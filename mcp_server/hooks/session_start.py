#!/usr/bin/env python3
"""Claude Code SessionStart hook — inject memory context.

Connects to PostgreSQL directly (no MCP roundtrip) and prints a compact
Markdown context block to stdout. Claude Code injects this into the
context window at the start of every session.

This module is the entry point (``main``) and the composition of the
``session_start_*`` sibling modules, each owning one responsibility:
``_common`` (config, logging, event), ``_db`` / ``_fetch`` / ``_curation``
(PostgreSQL), ``_sqlite`` (SQLite banner), ``_context`` (rendering),
``_sources`` (external sources, backfill), ``_consolidate`` and
``_background`` (detached work, session registry).

Output format
-------------
Prints to stdout — captured by Claude Code and prepended to the session.
Errors go to stderr only and never surface to the user.

source: ADR-0498"""

from __future__ import annotations

import os

from mcp_server.hooks import session_start_status as _status
from mcp_server.hooks._telemetry import observe_hook
from mcp_server.hooks.output_streams import use_utf8_output
from mcp_server.hooks.session_start_background import (
    _auto_wire_pipeline,
    _maybe_background_reanalyze,
    _refresh_session_registry,
)
from mcp_server.hooks.session_start_common import _log, _read_event
from mcp_server.hooks.session_start_consolidate import _maybe_background_consolidate
from mcp_server.hooks.session_start_context import (
    _build_cold_start_message,
    _build_context,
    _emit_banner_receipt,
)
from mcp_server.hooks.session_start_curation import (
    _count_pending_curations,
    _fetch_grooming_staleness,
)
from mcp_server.hooks.session_start_db import (
    _connect_pg,
    _count_memories,
    _count_session_files,
    _fetch_checkpoint,
    _try_setup_db,
)
from mcp_server.hooks.session_start_fetch import (
    _fetch_anchors,
    _fetch_hot_memories,
    _fetch_team_decisions,
)
from mcp_server.hooks.session_start_sources import _print_external_sources
from mcp_server.hooks.session_start_sqlite import _backend_is_sqlite, _sqlite_context
from mcp_server.shared.project_scope import resolve_project_root


@observe_hook("session_start")
def main() -> None:
    """Entry point — one JSON object: the context, and the status line shown
    to the user (``session_start_status``, ADR-1104)."""
    _status.run_and_report(_session_start)


def _session_start() -> str:
    """Print the context block; return the status line."""

    # source: ADR-0498
    event = _read_event()

    # source: ADR-0498
    _refresh_session_registry(event)

    # Auto-discovery runs before the PG path so users see it work even
    # on a fresh machine without a DB set up yet.
    project_root = resolve_project_root(event, os.environ)
    _auto_wire_pipeline(project_root)

    # source: ADR-0498
    _maybe_background_reanalyze(project_root)

    # source: ADR-0498
    _maybe_background_consolidate()

    # SQLite backend (zero-config plugin default): banner via the store
    # abstraction — no psycopg connection to attempt.
    if _backend_is_sqlite():
        return _sqlite_context(event)
    conn, failure = _pg_connection()
    if failure is not None:
        return failure
    memory_count = _count_memories(conn)
    if memory_count == 0:
        return _pg_empty_store(conn)
    return _pg_banner(event, conn, memory_count)


def _pg_connection():
    """``(conn, None)``, or ``(None, status)`` after printing the first-run text."""
    conn = _connect_pg()
    if conn is not None:
        return conn, None
    # Can't connect — try auto-setup
    _log("No PostgreSQL connection, attempting setup...")
    setup_result = _try_setup_db()
    if setup_result and setup_result.get("status") == "ready":
        # Setup succeeded, try connecting again
        conn = _connect_pg()
        if conn is not None:
            return conn, None
        _log("Setup reported ready but still can't connect")
        cause = "PostgreSQL setup reported ready, but no connection opened"
    else:
        cause = "the configured PostgreSQL store is unavailable: " + (
            (setup_result or {}).get("message", "setup_db.py gave no result")
        )
    msg = _build_cold_start_message(setup_result)
    if msg:
        print(msg)
    return None, _status.not_ready(cause)


def _pg_empty_store(conn) -> str:
    """Empty database — first run with a working PostgreSQL."""
    session_files = _count_session_files()
    _log(f"Empty database, {session_files} session files found")
    conn.close()
    msg = _build_cold_start_message(
        {"status": "ready", "memories": 0, "session_files": session_files}
    )
    if msg:
        print(msg)
    return _status.ready("PostgreSQL memory store", 0)


def _pg_banner(event: dict, conn, memory_count: int) -> str:
    """Normal flow — fetch and inject context."""
    project_root = resolve_project_root(event, os.environ)
    if project_root is None:
        _log(
            "project root unresolved (no CLAUDE_PROJECT_ROOT, no event cwd), "
            "restricting to global memories"
        )
    anchors = _fetch_anchors(conn, project_root)
    anchor_ids = {a["id"] for a in anchors}
    hot = _fetch_hot_memories(conn, anchor_ids, project_root)
    team_decisions = _fetch_team_decisions(conn, anchor_ids, project_root)
    # Receipt BEFORE rendering: the banner header carries the ⟦rcpt:id⟧
    # marker, so the id must exist when the context is built. A failed
    # write degrades to a marker-less banner (read path intact).
    context = _build_context(
        anchors,
        hot,
        _fetch_checkpoint(conn),
        team_decisions,
        pending_curations=_count_pending_curations(conn),
        stale_grooming=_fetch_grooming_staleness(conn),
        receipt_id=_emit_banner_receipt(conn, event, anchors, team_decisions, hot),
    )
    conn.close()
    if context:
        print(context)
        _log(
            f"Injected {len(anchors)} anchors + {len(hot)} hot memories "
            f"(total: {memory_count})"
        )
    else:
        _log("No memories above threshold")
    # Always check for external memory sources that can be imported
    _print_external_sources()
    return _status.ready("PostgreSQL memory store", memory_count)


if __name__ == "__main__":
    use_utf8_output()
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    main()
