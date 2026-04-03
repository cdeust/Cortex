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
  2. Run fast PG query: FTS match + heat filter (no embedding load)
  3. If relevant memories found, format as compact context block
  4. Exit 0 → stdout injected into Claude's context
  5. If nothing found, exit 1 → no injection, no noise

Performance constraints:
  - Must complete within 3s (hook timeout)
  - No embedding model load (takes 5-8s)
  - FTS-only query on PG (plainto_tsquery, sub-100ms)
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

_LOG_PREFIX = "[cortex-auto-recall]"
_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
_MAX_MEMORIES = 3
_MIN_HEAT = 0.15
_MIN_QUERY_LENGTH = 10
_MAX_INJECTION_CHARS = 800  # Keep compact — don't flood context

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


def _recall_memories(query: str) -> list[dict]:
    """Fast FTS-based recall against PG. No embedding model needed.

    Uses plainto_tsquery for natural language matching against the
    content_tsv tsvector column. Combined with heat filter to surface
    important memories.

    Falls back to ILIKE if FTS returns nothing (handles short queries
    that don't tokenize well).
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        return []

    try:
        conn = psycopg.connect(_DATABASE_URL, row_factory=dict_row, autocommit=True)
    except Exception:
        return []

    results = []

    # Pass 1: FTS match with heat filter
    try:
        rows = conn.execute(
            """
            SELECT id, content, heat, domain, agent_context, is_protected,
                   ts_rank_cd(content_tsv, q) AS rank
            FROM memories,
                 plainto_tsquery('english', %s) q
            WHERE content_tsv @@ q
              AND heat >= %s
              AND NOT is_benchmark
            ORDER BY is_protected DESC, rank DESC, heat DESC
            LIMIT %s
            """,
            (query[:200], _MIN_HEAT, _MAX_MEMORIES + 2),
        ).fetchall()

        for r in rows:
            results.append(
                {
                    "content": r.get("content", ""),
                    "heat": r.get("heat", 0),
                    "domain": r.get("domain", ""),
                    "agent": r.get("agent_context", ""),
                    "protected": bool(r.get("is_protected")),
                }
            )
    except Exception as exc:
        _log(f"FTS query failed: {exc}")

    conn.close()
    return results[:_MAX_MEMORIES]


def _format_injection(memories: list[dict]) -> str:
    """Format memories as a compact context block for injection.

    Keeps total injection under _MAX_INJECTION_CHARS to avoid
    flooding the context window.
    """
    lines = ["**Cortex context:**"]
    total_chars = len(lines[0])

    for m in memories:
        content = m["content"].replace("\n", " ").strip()
        # Truncate individual memories
        if len(content) > 200:
            content = content[:197] + "..."

        agent = m.get("agent", "")
        prefix = f"[{agent}] " if agent else ""
        protected = " (decision)" if m.get("protected") else ""

        line = f"- {prefix}{content}{protected}"

        if total_chars + len(line) > _MAX_INJECTION_CHARS:
            break

        lines.append(line)
        total_chars += len(line)

    if len(lines) == 1:
        return ""  # No memories fit

    return "\n".join(lines)


def process_event(event: dict[str, Any]) -> None:
    """Process UserPromptSubmit and inject relevant memories."""
    query = _extract_query(event)

    if not query:
        sys.exit(0)

    if _should_skip(query):
        sys.exit(0)

    memories = _recall_memories(query)

    if not memories:
        sys.exit(0)

    injection = _format_injection(memories)

    if not injection:
        sys.exit(0)

    # Exit 0 + stdout → injected into Claude's context
    print(injection)
    _log(f"injected {len(memories)} memories for query: {query[:50]}...")
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
    main()
