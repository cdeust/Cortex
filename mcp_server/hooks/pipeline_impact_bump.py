#!/usr/bin/env python3
"""Claude Code PostToolUse hook — pipeline-driven heat bump on file edits.

They compose: run ``preemptive_context`` for the baseline boost; this
hook then adds a *focused* boost on the pipeline-resolved impact set.

Cooldown
--------
Per-file 30s cooldown (shared file with ``preemptive_context`` via a
different lockfile). On a quick sequence of edits to the same file we
fire once per window, not per keystroke.

source: ADR-0493"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from mcp_server.hooks.output_streams import use_utf8_output
from mcp_server.hooks.stdin_event import read_event_text
from mcp_server.shared.hook_state_paths import cooldown_path
from mcp_server.shared.project_scope import resolve_project_root

_LOG_PREFIX = "[pipeline-impact-bump]"
_COOLDOWN_SECONDS = 30
_COOLDOWN_FILE = cooldown_path("cortex_pipeline_impact_cooldown.json")
_FILE_TOOLS = {"Edit", "Write", "MultiEdit"}
_IMPACT_BOOST = 0.15  # Slightly higher than preemptive — graph precision earns it.
_MAX_BUMPS = 20  # Don't over-boost on massive impact sets.


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _check_cooldown(file_path: str) -> bool:
    """Return True if this file was bumped recently (skip)."""
    try:
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
            last = data.get(file_path, 0)
            if time.time() - last < _COOLDOWN_SECONDS:
                return True
    except (OSError, ValueError, TypeError):
        # Cooldown cache is disposable: unreadable/corrupt state means
        # "no cooldown", and the next _update_cooldown rewrites the file.
        pass
    return False


# source: ADR-0493
_MAX_COOLDOWN_ENTRIES = 50


def _update_cooldown(file_path: str) -> None:
    try:
        data = {}
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
        data[file_path] = time.time()
        if len(data) > _MAX_COOLDOWN_ENTRIES:
            # Prune oldest entries.
            sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
            data = dict(sorted_items[:_MAX_COOLDOWN_ENTRIES])
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except (OSError, ValueError, TypeError):
        # Cooldown cache is disposable: a failed write only means the next
        # run skips the cooldown, which is safe.
        pass


async def _pipeline_detect_changes(project_root: str, file_path: str) -> list[str]:
    """Ask the pipeline's ``detect_changes`` tool for impacted symbols.

    Returns a list of qualified_name strings (e.g. ``src/main.rs::handle_tool_call``).
    Returns [] if the pipeline isn't configured, the tool errors, or no
    impact is detected (e.g., file isn't in the indexed graph).
    """
    try:
        from mcp_server.handlers.ingest_helpers import (  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
            call_upstream,
            find_cached_graph,
            normalise_mcp_payload,
        )
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return []

    try:
        store = get_shared_store()
        graph_path = find_cached_graph(store, project_root)
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"cached-graph lookup failed: {exc}")
        return []

    if not graph_path:
        return []

    # Build a minimal diff the pipeline can ingest. detect_changes accepts
    # either ``diff_text`` or ``base_ref``/``head_ref``. We pass the file
    # path as an "unstaged" diff marker — the pipeline's tool matches
    # paths against its graph regardless of the diff content shape.
    diff_text = f"diff --git a/{file_path} b/{file_path}\n"
    try:
        payload = await call_upstream(
            "codebase",
            "detect_changes",
            {"graph_path": graph_path, "diff_text": diff_text},
        )
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"detect_changes failed: {exc}")
        return []

    inner = normalise_mcp_payload(payload)
    if not isinstance(inner, dict):
        return []

    impacted = inner.get("impacted_symbols") or inner.get("impacted") or []
    names: list[str] = []
    for item in impacted:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("qualified_name") or item.get("name")
            if name:
                names.append(str(name))
        if len(names) >= _MAX_BUMPS:
            break
    return names


def _bump_heat_for_symbols(symbol_names: list[str]) -> int:
    """Boost heat_base on the current memories that mention any of these
    symbols, through the configured store (SQLite or PostgreSQL).

    A psycopg-only UPDATE did nothing on SQLite, the plugin default, after
    the hook had already paid for the graph lookup and the ``detect_changes``
    call (issue #750). Uses the canonical A3 writer (``bump_heat_raw``).
    Returns the number of memories bumped.
    """
    if not symbol_names:
        return 0
    from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: rejected events never import the store

    store = get_shared_store()
    bumped: set[int] = set()
    for name in symbol_names:
        for mem in store.get_memories_mentioning_entity(name, limit=_MAX_BUMPS):
            heat = float(mem.get("heat_base") or 0.0)
            if mem["id"] in bumped or heat >= 1.0:
                continue
            if mem.get("is_benchmark") or mem.get("is_stale"):
                continue
            store.bump_heat_raw(mem["id"], heat + _IMPACT_BOOST)
            bumped.add(mem["id"])
    return len(bumped)


def process_event(event: dict[str, Any]) -> None:
    tool_name = event.get("tool_name", "")
    if tool_name not in _FILE_TOOLS:
        return

    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        return

    if _check_cooldown(file_path):
        return

    # Never os.getcwd(): under scripts/launcher.py it is the plugin root.
    project_root = resolve_project_root(event, os.environ)
    if project_root is None:
        _log("impact bump skipped: project root unresolved (issue #604)")
        return
    try:
        from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit  # noqa: PLC0415 — rejected events must not import the store teardown path

        # source: ADR-0493
        with close_shared_store_on_exit():
            symbols = asyncio.run(_pipeline_detect_changes(project_root, file_path))
            count = _bump_heat_for_symbols(symbols) if symbols else 0
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"pipeline impact bump failed: {exc}")
        return
    finally:
        _update_cooldown(file_path)

    if count > 0:
        _log(f"bumped {count} memories for {len(symbols)} impacted symbols")


def main() -> None:
    if sys.stdin.isatty():
        return
    raw = read_event_text(_log).strip()
    if not raw:
        return
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return
    process_event(event)


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
