#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook — automatic memory recall.

When the user sends a message, this hook automatically retrieves relevant
memories and injects them into Claude's context. No explicit recall calls
needed — memory just works.

This is the core of the "seamless memory" experience: if Cortex is
installed, every conversation has memory context automatically.

Paper backing:
  - Smith & Vela 2001: context reinstatement produces ~15-20% recall
    boost (d=0.28). Injecting memories matching the current query
    implements automatic context reinstatement.
  - Bar 2007: proactive brain generates predictions from context
    BEFORE conscious retrieval request.
  - Collins & Loftus 1975: query text activates related memory nodes
    via spreading activation.

Source backing:
  - Claude Code auto-memory (lesson 40): "findRelevantMemories" selects
    up to 5 relevant files before the main agent responds. Same pattern.
  - Claude Code hooks (lesson 10): UserPromptSubmit exit 0 injects
    stdout into model context.

Strategy:
  1. Receive user message text from stdin JSON
  2. Run a fast FTS query — PG plainto_tsquery, or SQLite FTS5 through
     the store abstraction on the zero-config backend — plus heat filter
     (no embedding load either way)
  3. If relevant memories found, format as compact context block
  4. Exit 0 → stdout injected into Claude's context
  5. If nothing found, exit 1 → no injection, no noise

Performance constraints:
  - Must complete within 3s (hook timeout)
  - No embedding model load (takes 5-8s)
  - FTS-only query (PG plainto_tsquery / SQLite FTS5, sub-100ms)
  - Max 3 memories injected (keep context compact)
  - Skip very short queries (<10 chars) to avoid noise

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "UserPromptSubmit": [{
                "type": "command",
                "command": "python3 -m mcp_server.hooks.auto_recall",
                "timeout": 3
            }]
        }
    }

Invariants
----------
- Exit 0: stdout injected into model context (relevant memories found)
- Exit 1: no injection (nothing relevant or query too short)
- Must complete within 3s
- Logs to stderr only
- Never blocks user input (exit 2 reserved for validation hooks)
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from mcp_server.handlers.injection_receipts import (
    emit_hook_receipt,
    emit_injection_receipt,
    receipt_marker,
    session_id_from_transcript,
)

_LOG_PREFIX = "[cortex-auto-recall]"
_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
_MAX_MEMORIES = 3
_MIN_HEAT = 0.15
_MIN_QUERY_LENGTH = 10
_MAX_INJECTION_CHARS = 800  # Keep compact — don't flood context
# source: pre-existing tuned values, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
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
    """Open the hook's PG connection; None when PG is unreachable."""
    try:
        import psycopg  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        from psycopg.rows import dict_row  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return None
    try:
        return psycopg.connect(_DATABASE_URL, row_factory=dict_row, autocommit=True)
    except psycopg.Error:
        return None


def _recall_memories(conn, query: str) -> list[dict]:
    """Fast FTS-based recall against PG. No embedding model needed.

    Uses plainto_tsquery for natural language matching against the
    content_tsv tsvector column. Combined with heat filter to surface
    important memories.

    Each result keeps the memory ``id`` — the injection receipt (T2)
    records exactly which memories entered the context.
    """
    results = []

    # Pass 1: FTS match with heat filter.
    #
    # `memories.heat` does NOT exist as a stored column — heat is computed
    # via the effective_heat(m, NOW()) PL/pgSQL function which applies
    # lazy A3 decay over heat_base + heat_base_set_at + stage + valence.
    # Using effective_heat() here keeps this hook semantically aligned
    # with production recall_memories() — same lazy-decay read path,
    # just without the WRRF fusion (we only need a fast FTS prefilter).
    # Source: pg_schema.py EFFECTIVE_HEAT_FN (lines 586-682).
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.content,
                   effective_heat(m, NOW()) AS heat,
                   m.domain, m.agent_context, m.is_protected,
                   ts_rank_cd(m.content_tsv, q) AS rank
            -- JOIN current_memories: auto-recall injects content into the
            -- session context — supersession chain heads only. The join
            -- (not FROM the view) keeps m table-typed for effective_heat().
            FROM memories m
                 JOIN current_memories cm ON cm.id = m.id,
                 plainto_tsquery('english', %s) q
            WHERE m.content_tsv @@ q
              AND effective_heat(m, NOW()) >= %s
              AND NOT m.is_benchmark
              -- Never re-inject a corrected (superseded) fact —
              -- decision 4255039 correction 8.
              AND m.superseded_by_id IS NULL
            ORDER BY m.is_protected DESC, rank DESC, effective_heat(m, NOW()) DESC
            LIMIT %s
            """,
            (query[:200], _MIN_HEAT, _MAX_MEMORIES + 2),
        ).fetchall()

        for r in rows:
            results.append(
                {
                    "id": r["id"],
                    "content": r.get("content", ""),
                    "heat": r.get("heat", 0),
                    "domain": r.get("domain", ""),
                    "agent": r.get("agent_context", ""),
                    "protected": bool(r.get("is_protected")),
                }
            )
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"FTS query failed: {exc}")

    return results[:_MAX_MEMORIES]


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

    PG's ``plainto_tsquery`` strips stopwords and stems before matching;
    SQLite FTS5's default unicode61 tokenizer does neither, so MATCHing
    the raw prompt ANDs every token ("why is the deploy script...") and
    almost never hits. Mirror the stopword strip with the shared
    ``STOPWORDS`` list, then OR the remaining terms: FTS5 has no
    stemming, so exact-token AND would drop the whole injection on one
    morphological miss ("scripts" vs "script"); bm25 rank still sorts
    multi-term matches first. Each term is double-quoted (FTS5 string
    syntax) so user text can never inject FTS5 operators. Term count is
    bounded upstream by the existing ``query[:200]`` cap — no new
    constant introduced.
    """
    from mcp_server.shared.text import STOPWORDS  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

    # \W+ split mirrors shared.text._SPLIT_RE (kept private there).
    terms = [
        w
        for w in re.split(r"\W+", query.lower())
        if len(w) >= _MIN_FTS_TERM_CHARS and w not in STOPWORDS
    ]
    return " OR ".join(f'"{t}"' for t in terms)


def _recall_memories_sqlite(store, query: str) -> list[dict]:
    """FTS-based recall through the SQLite store — no embedding load.

    Mirror of the PG ``_recall_memories`` contract: FTS prefilter +
    heat floor, protected-first ordering, benchmark rows excluded.
    ``search_fts`` already restricts to supersession chain heads and
    non-stale rows (current_memories join) and returns [] on any FTS5
    error.
    """
    fts_query = _fts_query_from_prompt(query[:200])
    if not fts_query:
        return []
    results = []
    for memory_id, _score in store.search_fts(fts_query, limit=_MAX_MEMORIES + 2):
        m = store.get_memory(memory_id)
        if not m or m.get("is_benchmark"):
            continue
        heat = float(m.get("heat") or 0.0)
        if heat < _MIN_HEAT:
            continue
        results.append(
            {
                "id": memory_id,
                "content": m.get("content", ""),
                "heat": heat,
                "domain": m.get("domain", "") or "",
                "agent": m.get("agent_context", "") or "",
                "protected": bool(m.get("is_protected")),
            }
        )
    # Protected (decision) memories first; stable sort keeps FTS rank
    # order within each group — same ordering contract as the PG query.
    results.sort(key=lambda m: not m["protected"])
    return results[:_MAX_MEMORIES]


def _process_event_sqlite(event: dict[str, Any], query: str) -> None:
    """Inject relevant memories from the SQLite store; exit 0 always."""
    try:
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        store = get_shared_store()
        memories = _recall_memories_sqlite(store, query)
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


def _format_injection(memories: list[dict]) -> tuple[str, list[dict]]:
    """Format memories as a compact context block for injection.

    Keeps total injection under _MAX_INJECTION_CHARS to avoid flooding
    the context window. Returns the block AND the memories that actually
    fit — the injection receipt must mirror what is printed, never what
    was fetched (parity invariant, decision 4255039 correction 11):
    entries dropped by the budget were never in context; entries printed
    truncated keep their id and ARE in context.
    """
    lines = ["**Cortex context:**"]
    total_chars = len(lines[0])
    included: list[dict] = []

    for m in memories:
        content = m["content"].replace("\n", " ").strip()
        # Truncate individual memories
        if len(content) > _MAX_MEMORY_CHARS:
            content = content[: _MAX_MEMORY_CHARS - 3] + "..."

        agent = m.get("agent", "")
        prefix = f"[{agent}] " if agent else ""
        protected = " (decision)" if m.get("protected") else ""

        line = f"- {prefix}{content}{protected}"

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

    try:
        memories = _recall_memories(conn, query)
        if not memories:
            sys.exit(0)

        injection, included = _format_injection(memories)
        if not injection:
            sys.exit(0)

        # Receipt for exactly the memories that fit the injection budget
        # (blame path T2, decision 4255039). Emitted before printing so
        # the header line can carry the ⟦rcpt:id⟧ marker (correction 2);
        # a failed write degrades to a marker-less injection.
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


def main() -> None:
    """Entry point — read JSON event from stdin."""
    if sys.stdin.isatty():
        sys.exit(0)

    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

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
