"""SessionStart hook banner on the SQLite backend: row partition, store reads, printing.

source: ADR-0498"""

from __future__ import annotations

import os
from collections.abc import Callable

from mcp_server.hooks import session_start_status as _status
from mcp_server.hooks.session_start_common import (
    _ANCHOR_LIMIT,
    _HOT_LIMIT,
    _MIN_HEAT,
    _log,
)
from mcp_server.hooks.session_start_context import (
    _build_cold_start_message,
    _build_context,
)
from mcp_server.hooks.session_start_db import _checkpoint_from_row, _count_session_files
from mcp_server.hooks.session_start_sources import _print_external_sources
from mcp_server.shared.project_scope import (
    memory_matches_project,
    project_ancestors,
    resolve_project_root,
)


# source: ADR-0498

# Tier-1 noise excluded from the banner on both backends.
# contract: zetetic-team-subagents memory/contract.md §8b
_SQLITE_NOISE_TAGS = frozenset({"auto-captured", "memory-replica"})


def _backend_is_sqlite() -> bool:
    """True when the resolved store backend is the SQLite store."""
    try:
        from mcp_server.infrastructure.backend_marker import effective_backend  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode

        return effective_backend(os.environ) == "sqlite"
    except ImportError:
        return False


def _partition_banner_rows(
    rows: list[dict], project_root: str | None = None
) -> tuple[list[dict], list[dict]]:
    """Split hot rows into (anchors, hot) with the PG path's exclusions.

    Mirrors _fetch_anchors/_fetch_hot_memories: tier-1 noise tags are
    dropped, rows outside project_root (and not global) are dropped
    (issue #604), protected ``_anchor``-tagged rows become anchors, the
    rest are hot-pool entries. Supersession exclusion already happened
    upstream (``get_hot_memories(heads_only=True)`` routes through the
    ``current_memories`` view).
    """
    anchors: list[dict] = []
    hot: list[dict] = []
    for r in rows:
        tags = [t for t in (r.get("tags") or []) if isinstance(t, str)]
        if _SQLITE_NOISE_TAGS & set(tags):
            continue
        if not memory_matches_project(
            r.get("directory_context"), bool(r.get("is_global")), project_root
        ):
            continue
        entry = {
            "id": r["id"],
            "content": r.get("content", ""),
            "domain": r.get("domain", "") or "",
            "heat": float(r.get("heat") or 0.0),
            "is_global": bool(r.get("is_global", False)),
            "created_at": r.get("created_at"),
            "source_attribution": r.get("source_attribution", ""),
            "is_stale": bool(r.get("is_stale")),
        }
        is_anchor = bool(r.get("is_protected")) and any(
            t == "_anchor" or t.startswith("_anchor:") for t in tags
        )
        (anchors if is_anchor else hot).append(entry)
    return anchors[:_ANCHOR_LIMIT], hot[:_HOT_LIMIT]


def _sqlite_banner_rows(
    store, project_root: str | None = None
) -> tuple[list[dict], list[dict], dict | None]:
    """Fetch (anchors, hot, checkpoint) from the SQLite store, tolerantly.

    The project predicate runs inside ``get_hot_memories`` itself, before
    its own LIMIT (issue #604 follow-up): a post-fetch filter would let
    foreign-project rows starve the project's own rows out of the
    already-truncated pool.
    """
    try:
        rows = store.get_hot_memories(
            min_heat=_MIN_HEAT,
            limit=_HOT_LIMIT + _ANCHOR_LIMIT,
            heads_only=True,
            directory_ancestors=project_ancestors(project_root),
        )
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"SQLite hot-memory fetch failed (non-fatal): {exc}")
        rows = []
    anchors, hot = _partition_banner_rows(rows, project_root)
    try:
        checkpoint = _checkpoint_from_row(store.get_active_checkpoint())
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"SQLite checkpoint fetch failed (non-fatal): {exc}")
        checkpoint = None
    return anchors, hot, checkpoint


def _open_sqlite_store() -> tuple[object, int, str] | str:
    """``(store, memory count, "Cortex ready" status)``, or the "not ready"
    status naming the cause when the store does not open (ADR-1104)."""
    try:
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: PLC0415 — same latency boundary

        store = get_shared_store()
        total = int(store.count_memories().get("total") or 0)
        where = _status.home_relative(get_memory_settings().SQLITE_FALLBACK_PATH)
    except Exception as exc:  # noqa: BLE001 — hook boundary: the cause reaches the user as "not ready"
        _log(f"SQLite store unavailable: {exc}")
        return _status.not_ready(f"the SQLite memory store did not open: {exc}")
    return store, total, _status.ready(f"SQLite memory at {where}", total)


def _print_sqlite_cold_start(backfill: Callable[[], int]) -> None:
    """Print the first-run banner for an empty SQLite store."""
    session_files = _count_session_files()
    _log(f"Empty SQLite store, {session_files} session files found")
    msg = _build_cold_start_message(
        {"status": "ready", "memories": 0, "session_files": session_files},
        backfill,
    )
    if msg:
        print(msg)


def _sqlite_context(
    event: dict,
    backfill: Callable[[], int],
    emit_receipt: Callable[[object, list[dict], dict], int | None],
) -> str:
    """Print the SessionStart banner on the SQLite backend; return the status line.

    ``backfill`` fills an empty store (see ``_build_cold_start_message``);
    ``emit_receipt(store, memories, event)`` records the injected memories
    and returns the receipt id the banner header carries.
    """
    project_root = resolve_project_root(event, os.environ)
    if project_root is None:
        _log(
            "project root unresolved (no CLAUDE_PROJECT_ROOT, no event cwd), "
            "restricting to global memories"
        )
    opened = _open_sqlite_store()
    if isinstance(opened, str):
        return opened
    store, total, ready = opened
    if total == 0:
        _print_sqlite_cold_start(backfill)
        return ready

    anchors, hot, checkpoint = _sqlite_banner_rows(store, project_root)
    receipt_id = emit_receipt(store, [*anchors, *hot], event)
    context = _build_context(anchors, hot, checkpoint, receipt_id=receipt_id)
    if context:
        print(context)
        _log(
            f"Injected {len(anchors)} anchors + {len(hot)} hot memories "
            f"(total: {total}, backend: sqlite)"
        )
    else:
        _log("No memories above threshold (backend: sqlite)")

    _print_external_sources()
    return ready
