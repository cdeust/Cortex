#!/usr/bin/env python3
"""Claude Code PostToolUse hook — pipeline-driven heat bump on file edits.

When an agent edits or writes a file, this hook asks the upstream
ai-architect-mcp-codebase's ``detect_changes`` tool which symbols are
impacted by the edit, then boosts heat on memories tagged with those
symbol names. This is a targeted version of ``preemptive_context`` —
instead of substring-matching file path in ALL memories, we query the
codebase graph for the precise impact set.

Why both hooks coexist
----------------------
  * ``preemptive_context``: path-based, works without the pipeline, fires
    on every edit. Cheap, broad, sometimes imprecise.
  * ``pipeline_impact_bump``: graph-based, requires the pipeline MCP
    server, fires on every edit with a cooldown. Precise, narrower, skips
    cleanly when the pipeline isn't installed.

They compose: run ``preemptive_context`` for the baseline boost; this
hook then adds a *focused* boost on the pipeline-resolved impact set.

Cooldown
--------
Per-file 30s cooldown (shared file with ``preemptive_context`` via a
different lockfile). On a quick sequence of edits to the same file we
fire once per window, not per keystroke.

Paper backing
-------------
  * Collins & Loftus 1975 — spreading activation on a structured graph.
  * Smith & Vela 2001 — context reinstatement benefit (d=0.28).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import LiteralString

import asyncio
import json
import os
import sys
import time
from typing import Any, cast

from mcp_server.shared.hook_state_paths import cooldown_path

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


# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
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
    """Boost heat_base on memories that mention any of these symbols.

    Uses the canonical A3 writer path. Returns number of memories bumped.
    """
    if not symbol_names:
        return 0
    try:
        import psycopg  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return 0

    db_url = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
    try:
        conn = psycopg.connect(db_url, autocommit=True)
    except psycopg.Error:
        return 0

    # Build an ILIKE OR clause with bounded params. Match any qualified name.
    try:
        like_clauses = " OR ".join(["content ILIKE %s"] * len(symbol_names))
        params = [f"%{name}%" for name in symbol_names]
        sql = (
            "UPDATE memories "
            "SET heat_base = LEAST(heat_base + %s, 1.0), "
            "    heat_base_set_at = NOW(), "
            "    last_accessed = NOW() "
            "WHERE NOT is_benchmark "
            "  AND NOT is_stale "
            "  AND heat_base < 1.0 "
            "  AND (" + like_clauses + ")"
        )
        result = conn.execute(cast("LiteralString", sql), [_IMPACT_BOOST, *params])
        count = result.rowcount if result else 0
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"heat bump failed: {exc}")
        count = 0
    finally:
        conn.close()
    return int(count)


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

    project_root = os.environ.get("CLAUDE_PROJECT_ROOT") or os.getcwd()
    try:
        from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit  # noqa: PLC0415 — rejected events must not import the store teardown path

        # issue #398: close cached stores on success, exception and SystemExit.
        with close_shared_store_on_exit():
            symbols = asyncio.run(_pipeline_detect_changes(project_root, file_path))
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"pipeline call failed: {exc}")
        return
    finally:
        _update_cooldown(file_path)

    if not symbols:
        return

    count = _bump_heat_for_symbols(symbols)
    if count > 0:
        _log(f"bumped {count} memories for {len(symbols)} impacted symbols")


def main() -> None:
    if sys.stdin.isatty():
        return
    raw = sys.stdin.read().strip()
    if not raw:
        return
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return
    process_event(event)


if __name__ == "__main__":
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    main()
