#!/usr/bin/env python3
"""Hook: wiki_distill — opt-in session-end reminder of undocumented decisions.

This hook is intentionally *deterministic* — it runs as a subprocess in
the session-end path and has no direct access to the conversation model.
It cannot author pages itself. Instead, it surfaces a list of hot
"decision-shaped" memories that the user may want to promote into ADRs
or specs next session.

Enable::

    export CORTEX_WIKI_DISTILL=1

Wire it up (optional) in ``plugin.json`` or ``~/.claude/settings.json``::

    {
      "hooks": {
        "SessionEnd": [{
          "hooks": [{
            "type": "command",
            "command": "python -m mcp_server.hooks.wiki_distill",
            "timeout": 5
          }]
        }]
      }
    }

The hook never blocks and never raises.
"""

from __future__ import annotations

import os
import sys

_DECISION_TAGS = {"decision", "architecture", "spec", "design", "adr"}
_MAX_ITEMS = 5
_MIN_HEAT = 0.4


def _enabled() -> bool:
    return os.environ.get("CORTEX_WIKI_DISTILL", "").strip() not in ("", "0", "false")


def _load_candidates() -> list[dict]:
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import MemoryStore

    settings = get_memory_settings()
    store = MemoryStore(settings.SQLITE_FALLBACK_PATH, settings.EMBEDDING_DIM)
    if not hasattr(store, "get_hot_memories"):
        return []
    try:
        hot = store.get_hot_memories(min_heat=_MIN_HEAT, limit=100) or []
    except Exception:
        return []

    filtered: list[dict] = []
    for mem in hot:
        tags = mem.get("tags") or []
        if not tags:
            continue
        if any(t in _DECISION_TAGS for t in tags):
            source = str(mem.get("source") or "")
            if source.startswith("wiki://"):
                continue  # already documented
            filtered.append(mem)
    filtered.sort(key=lambda m: float(m.get("heat") or 0.0), reverse=True)
    return filtered[:_MAX_ITEMS]


def _format(items: list[dict]) -> str:
    if not items:
        return ""
    lines = ["[wiki_distill] decision-shaped memories you could promote to ADRs:"]
    for m in items:
        heat = float(m.get("heat") or 0.0)
        content = (m.get("content") or "")[:80].replace("\n", " ").strip()
        lines.append(f"  - #{m.get('id')} heat={heat:.2f} — {content}")
    return "\n".join(lines)


def main() -> int:
    if not _enabled():
        return 0
    try:
        items = _load_candidates()
    except Exception as exc:  # noqa: BLE001 — hook must never raise
        print(f"[wiki_distill] skipped: {exc}", file=sys.stderr)
        return 0
    msg = _format(items)
    if msg:
        print(msg, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
