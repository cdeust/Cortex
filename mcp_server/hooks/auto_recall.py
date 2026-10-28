#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook — automatic memory recall.

When the user sends a message, this hook automatically retrieves relevant
memories and injects them into Claude's context. No explicit recall calls
needed — memory just works.

This is the core of the "seamless memory" experience: if Cortex is
installed, every conversation has memory context automatically.

Strategy:
  1. Receive user message text from stdin JSON
  2. Merge project-scoped FTS and hot candidate pools, then reuse recall's
     cached FlashRank reranker (no embedding load or network fetch).
     Missing cached weights retain lexical retrieval with a degradation log.
  3. If relevant memories found, format as compact context block
  4. Exit 0 → stdout injected into Claude's context
  5. If nothing found, exit 1 → no injection, no noise

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "UserPromptSubmit": [{
                "type": "command",
                "command": "python3 -m mcp_server.hooks.auto_recall",
                "timeout": 5
            }]
        }
    }

source: ADR-0485"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from mcp_server.hooks.auto_recall_ranking import candidate_limit, rank_memories
from mcp_server.hooks.output_streams import use_utf8_output
from mcp_server.hooks.stdin_event import read_event_text
from mcp_server.handlers.injection_receipts import (
    emit_hook_receipt,
    emit_injection_receipt,
)
from mcp_server.shared.injection_markers import (
    receipt_marker,
    session_id_from_transcript,
)
from mcp_server.hooks._telemetry import observe_hook
from mcp_server.shared.freshness import provenance_suffix
from mcp_server.shared.project_scope import project_ancestors, resolve_project_root

_LOG_PREFIX = "[cortex-auto-recall]"
# source: issues #703/#704 -- only shared resolution supplies a PostgreSQL URL.
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_MAX_MEMORIES = 3
_MIN_HEAT = 0.15
_MIN_QUERY_LENGTH = 10
_MAX_INJECTION_CHARS = 800  # Keep compact — don't flood context
# source: ADR-0485
_MIN_FTS_TERM_CHARS = 2
_MAX_MEMORY_CHARS = 200

# Skip recall for meta/system messages
_SKIP_PATTERNS = re.compile(
    r"^(/|yes$|no$|ok$|sure$|thanks|continue|go ahead|y$|n$)",
    re.IGNORECASE,
)


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _extract_query(event: dict[str, Any]) -> str | None:
    """Extract the user's message text from the hook event.

    The UserPromptSubmit event contains the user's prompt. The exact
    field name may vary — try common candidates.
    """
    # Try known field names
    for field in ("content", "prompt", "message", "text", "query"):
        val = event.get(field)
        if val and isinstance(val, str) and len(val) >= _MIN_QUERY_LENGTH:
            return val.strip()

    # Try nested structures
    if isinstance(event.get("messages"), list):
        for msg in reversed(event["messages"]):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) >= _MIN_QUERY_LENGTH:
                    return content.strip()

    return None


def _should_skip(query: str) -> bool:
    """Skip recall for trivial/meta messages."""
    if len(query) < _MIN_QUERY_LENGTH:
        return True
    if _SKIP_PATTERNS.match(query):
        return True
    return False


def _connect():
    """Open a configured PG connection; None when absent or unreachable."""
    if not _DATABASE_URL:
        return None
    try:
        import psycopg  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return None
    from mcp_server.infrastructure.db_connect import pg_connect  # noqa: PLC0415 — after the optional-extra probe

    try:
        # source: ADR-1110 — gated: this connection also writes receipts
        return pg_connect(_DATABASE_URL, autocommit=True)
    except psycopg.Error:
        return None


def _recall_memories(conn, query: str, project_root: str | None = None) -> list[dict]:
    """Scoped lexical discovery, then cached cross-encoder reranking.

    The project predicate precedes LIMIT so foreign rows cannot starve
    the eligible pool (issue #604). The hot pool adds paraphrase candidates.
    """
    results = []
    ancestors = project_ancestors(project_root)

    # source: ADR-0485
    try:
        rows = conn.execute(
            (
                # source: ADR-0485
                """
            SELECT m.id, m.content,
                   effective_heat(m, NOW()) AS heat,
                   m.domain, m.agent_context, m.is_protected,
                   m.created_at, m.source_attribution, m.is_stale,
                   m.capture_origin, m.source,
                   ts_rank_cd(m.content_tsv, q) AS rank
            FROM memories m
                 JOIN current_memories cm ON cm.id = m.id,
                 plainto_tsquery('english', %s) q
            WHERE m.content_tsv @@ q
              AND effective_heat(m, NOW()) >= %s
              AND NOT m.is_stale
              AND (m.capture_origin = 'deliberate' OR
                   (COALESCE(m.capture_origin, '') NOT IN ('local_action', 'network')
                    AND COALESCE(m.source, '') <> 'post_tool_capture'))
              AND NOT m.is_benchmark
              AND m.superseded_by_id IS NULL
              AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[]))
            -- source: ADR-1106 -- exact ties go to the newer memory.
            ORDER BY m.is_protected DESC, rank DESC, effective_heat(m, NOW()) DESC,
                     m.created_at DESC, m.id DESC
            LIMIT %s
            """
            ),
            (query, _MIN_HEAT, ancestors, candidate_limit(_MAX_MEMORIES)),
        ).fetchall()

        results = [_sqlite_result_entry(r["id"], r, r.get("heat", 0)) for r in rows]
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"FTS query failed: {exc}")

    return rank_memories(query, results, lambda: _pg_hot_candidates(conn, ancestors))[
        :_MAX_MEMORIES
    ]


def _pg_hot_candidates(conn, ancestors: list[str]) -> list[dict]:
    """Scoped discovery without lexical overlap; predicates precede LIMIT."""
    rows = conn.execute(
        """
        SELECT m.id, m.content, m.domain, m.agent_context, m.is_protected,
               m.created_at, m.source_attribution, m.is_stale,
               m.capture_origin, m.source, effective_heat(m, NOW()) AS heat
        FROM memories m JOIN current_memories cm ON cm.id = m.id
        WHERE effective_heat(m, NOW()) >= %s AND NOT m.is_benchmark
          AND (m.capture_origin = 'deliberate' OR
               (COALESCE(m.capture_origin, '') NOT IN ('local_action', 'network')
                AND COALESCE(m.source, '') <> 'post_tool_capture'))
          AND NOT m.is_stale
          AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[]))
        ORDER BY heat DESC, m.created_at DESC, m.id DESC LIMIT %s
        """,
        (_MIN_HEAT, ancestors, candidate_limit(_MAX_MEMORIES)),
    ).fetchall()
    return [_sqlite_result_entry(m["id"], m, m["heat"]) for m in rows]


# ── SQLite backend path (zero-config plugin default) ─────────────────────


def _backend_is_sqlite() -> bool:
    """True when the resolved store backend is the SQLite store."""
    try:
        from mcp_server.infrastructure.backend_marker import effective_backend  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode

        return effective_backend(os.environ) == "sqlite"
    except ImportError:
        return False


def _fts_query_from_prompt(query: str) -> str:
    """Build a defensive FTS5 OR-query from the prompt's content words.

    source: ADR-0485"""
    from mcp_server.shared.text import STOPWORDS  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

    # \W+ split mirrors shared.text._SPLIT_RE (kept private there).
    terms = [
        w
        for w in re.split(r"\W+", query.lower())
        if len(w) >= _MIN_FTS_TERM_CHARS and w not in STOPWORDS
    ]
    return " OR ".join(f'"{t}"' for t in terms)


def _sqlite_result_entry(memory_id: int, m: dict, heat: float) -> dict:
    """One ``_recall_memories_sqlite`` result row, in the PG-path shape."""
    return {
        "id": memory_id,
        "content": m.get("content", ""),
        "heat": heat,
        "domain": m.get("domain", "") or "",
        "agent": m.get("agent_context", "") or "",
        "protected": bool(m.get("is_protected")),
        "created_at": m.get("created_at"),
        "source_attribution": m.get("source_attribution", ""),
        "is_stale": bool(m.get("is_stale")),
        "capture_origin": m.get("capture_origin"),
        "source": m.get("source"),
    }


def _recall_memories_sqlite(
    store, query: str, project_root: str | None = None
) -> list[dict]:
    """Scoped FTS and hot discovery before cached semantic ranking.
    Store predicates exclude captures, stale rows and benchmarks before LIMIT.
    Model failures retain protected-first lexical behavior (issue #706).
    """
    fts_query = _fts_query_from_prompt(query)
    if not fts_query:
        return []
    ancestors = project_ancestors(project_root)
    hits = store.search_fts(
        fts_query,
        limit=candidate_limit(_MAX_MEMORIES),
        directory_ancestors=ancestors,
        hook_only=True,
        min_heat=_MIN_HEAT,
    )
    results = []
    for memory_id, _score in hits:
        m = store.get_memory(memory_id)
        if not m or m.get("is_benchmark"):
            continue
        heat = float(m.get("heat") or 0.0)
        if heat < _MIN_HEAT:
            continue
        results.append(_sqlite_result_entry(memory_id, m, heat))
    return rank_memories(
        query,
        results,
        lambda: [
            _sqlite_result_entry(m["id"], m, float(m.get("heat") or 0.0))
            for m in store.get_hot_memories(
                min_heat=_MIN_HEAT,
                limit=candidate_limit(_MAX_MEMORIES),
                directory_ancestors=ancestors,
                hook_only=True,
            )
            if not m.get("is_stale")
        ],
    )[:_MAX_MEMORIES]


def _process_event_sqlite(event: dict[str, Any], query: str) -> None:
    """Inject relevant memories from the SQLite store; exit 0 always."""
    project_root = resolve_project_root(event, os.environ)
    if project_root is None:
        _log(
            "project root unresolved (no CLAUDE_PROJECT_ROOT, no event cwd), "
            "restricting to global memories"
        )
    try:
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        store = get_shared_store()
        memories = _recall_memories_sqlite(store, query, project_root)
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"sqlite recall failed (non-fatal): {exc}")
        sys.exit(0)

    injection, included = _format_injection(memories)
    if not injection:
        sys.exit(0)

    receipt_id = emit_injection_receipt(
        store,
        [{"memory_id": m["id"]} for m in included],
        channel="auto_recall",
        session_id=session_id_from_transcript(event.get("transcript_path")),
    )
    if receipt_id is not None:
        first, _, rest = injection.partition("\n")
        injection = f"{first} {receipt_marker(receipt_id)}"
        if rest:
            injection += "\n" + rest

    print(injection)
    _log(f"injected {len(included)} memories (sqlite) for query: {query[:50]}...")
    sys.exit(0)


def _render_memory_line(m: dict, now: datetime) -> str:
    """Render one memory as a bullet with a freshness suffix.

    source: ADR-0485"""
    content = m["content"].replace("\n", " ").strip()
    if len(content) > _MAX_MEMORY_CHARS:
        content = content[: _MAX_MEMORY_CHARS - 3] + "..."
    agent = m.get("agent", "")
    prefix = f"[{agent}] " if agent else ""
    protected = " (decision)" if m.get("protected") else ""
    suffix = provenance_suffix(m, now)
    freshness = f"  ·  {suffix}" if suffix else ""
    return f"- {prefix}{content}{protected}{freshness}"


def _format_injection(
    memories: list[dict], now: datetime | None = None
) -> tuple[str, list[dict]]:
    """Format memories as a compact context block for injection.

    source: ADR-0485"""
    now = now or datetime.now(timezone.utc)
    lines = ["**Cortex context:**"]
    total_chars = len(lines[0])
    included: list[dict] = []

    for m in memories:
        line = _render_memory_line(m, now)
        if total_chars + len(line) > _MAX_INJECTION_CHARS:
            break
        lines.append(line)
        total_chars += len(line)
        included.append(m)

    if len(lines) == 1:
        return "", []  # No memories fit

    return "\n".join(lines), included


def _refresh_session_registry(event: dict[str, Any]) -> None:
    """Best-effort refresh of this window's registry entry on every
    prompt (T2-D6: "rafraîchir write_session à chaque prompt").

    precondition: ``event`` is the parsed UserPromptSubmit JSON — may
    lack ``transcript_path``. postcondition: on success, this window's
    registry entry is refreshed to the current transcript stem. Any
    failure degrades to a stderr log line and never raises or exits —
    a registry hiccup must never block the recall injection this hook
    exists for (same degradation contract as the emitted receipt).

    Called unconditionally at the top of every UserPromptSubmit turn,
    before the skip/relevance logic — the registry must stay fresh
    every prompt regardless of whether THIS prompt triggers a recall.
    """
    try:
        from mcp_server.infrastructure.session_registry import write_session  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        write_session(session_id_from_transcript(event.get("transcript_path")))
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"session registry refresh skipped (non-fatal): {exc}")


def process_event(event: dict[str, Any]) -> None:
    """Process UserPromptSubmit and inject relevant memories."""
    _refresh_session_registry(event)
    query = _extract_query(event)

    if not query:
        sys.exit(0)

    if _should_skip(query):
        sys.exit(0)

    # SQLite backend (zero-config plugin default): recall through the
    # store abstraction — no psycopg connection to attempt.
    if _backend_is_sqlite():
        _process_event_sqlite(event, query)
        return

    conn = _connect()
    if conn is None:
        sys.exit(0)

    project_root = resolve_project_root(event, os.environ)
    if project_root is None:
        _log(
            "project root unresolved (no CLAUDE_PROJECT_ROOT, no event cwd), "
            "restricting to global memories"
        )

    try:
        memories = _recall_memories(conn, query, project_root)
        if not memories:
            sys.exit(0)

        injection, included = _format_injection(memories)
        if not injection:
            sys.exit(0)

        # source: ADR-0485
        receipt_id = emit_hook_receipt(
            conn,
            [{"memory_id": m["id"]} for m in included],
            channel="auto_recall",
            session_id=session_id_from_transcript(event.get("transcript_path")),
        )
    finally:
        conn.close()

    if receipt_id is not None:
        first, _, rest = injection.partition("\n")
        injection = f"{first} {receipt_marker(receipt_id)}"
        if rest:
            injection += "\n" + rest

    # Exit 0 + stdout → injected into Claude's context
    print(injection)
    _log(f"injected {len(included)} memories for query: {query[:50]}...")
    sys.exit(0)


@observe_hook("auto_recall")
def main() -> None:
    """Entry point — read JSON event from stdin."""
    if sys.stdin.isatty():
        sys.exit(0)

    raw = read_event_text(_log).strip()
    if not raw:
        sys.exit(0)

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

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
