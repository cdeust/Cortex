#!/usr/bin/env python3
"""Claude Code SessionStart hook — inject memory context.

Reads the hottest memories from SQLite directly (no MCP roundtrip) and
prints a compact Markdown context block to stdout. Claude Code injects
this into the context window at the start of every session.

Uses only stdlib — no mcp_server imports, no external packages.
This keeps startup latency under 100 ms even on cold SQLite.

Installation
------------
Add to ~/.claude/settings.json under hooks::

    {
        "hooks": {
            "SessionStart": [{
                "hooks": [{
                    "type": "command",
                    "command": "python3 -m mcp_server.hooks.session_start",
                    "timeout": 5
                }]
            }]
        }
    }

Output format
-------------
Prints to stdout — captured by Claude Code and prepended to the session.
Errors go to stderr only and never surface to the user.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path


# ── Config (mirrors memory_config defaults) ────────────────────────────────────

_DB_PATH = os.environ.get(
    "CORTEX_MEMORY_DB_PATH",
    str(Path.home() / ".claude" / "methodology" / "memory.db"),
)
_HOT_LIMIT = int(os.environ.get("CORTEX_SESSION_START_LIMIT", "8"))
_MIN_HEAT = float(os.environ.get("CORTEX_SESSION_START_MIN_HEAT", "0.4"))
_ANCHOR_LIMIT = int(os.environ.get("CORTEX_SESSION_START_ANCHOR_LIMIT", "5"))


def _log(msg: str) -> None:
    print(f"[session-start-hook] {msg}", file=sys.stderr)


def _short(text: str, max_len: int = 120) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _parse_json_list(val: str | None) -> list:
    """Parse a JSON string into a list, falling back to a single-element list."""
    if not val:
        return []
    try:
        return json.loads(val) or []
    except Exception:
        return [val] if val.strip() else []


def _fetch_anchors(conn: sqlite3.Connection) -> list[dict]:
    """Fetch anchored memories (is_protected=1 with _anchor tag)."""
    rows = conn.execute(
        "SELECT id, content, tags, domain FROM memories "
        "WHERE is_protected = 1 AND archived = 0 "
        "ORDER BY heat DESC LIMIT ?",
        (_ANCHOR_LIMIT,),
    ).fetchall()

    anchors = []
    for r in rows:
        try:
            tags = json.loads(r["tags"] or "[]")
        except Exception:
            tags = []
        if "_anchor" in tags or any(t.startswith("_anchor:") for t in tags):
            anchors.append(
                {
                    "id": r["id"],
                    "content": r["content"] or "",
                    "domain": r["domain"] or "",
                }
            )
    return anchors


def _fetch_hot_memories(
    conn: sqlite3.Connection,
    anchor_ids: set,
) -> list[dict]:
    """Fetch high-heat memories, excluding anchors."""
    rows = conn.execute(
        "SELECT id, content, domain, heat, tags FROM memories "
        "WHERE archived = 0 AND heat >= ? "
        "ORDER BY heat DESC LIMIT ?",
        (_MIN_HEAT, _HOT_LIMIT + len(anchor_ids)),
    ).fetchall()

    hot = []
    for r in rows:
        if r["id"] not in anchor_ids:
            hot.append(
                {
                    "id": r["id"],
                    "content": r["content"] or "",
                    "domain": r["domain"] or "",
                    "heat": r["heat"] or 0.0,
                }
            )
    return hot[:_HOT_LIMIT]


def _fetch_checkpoint(conn: sqlite3.Connection) -> dict | None:
    """Fetch the latest active checkpoint."""
    row = conn.execute(
        "SELECT current_task, next_steps, open_questions, active_errors, "
        "key_decisions, directory_context "
        "FROM checkpoints WHERE is_active = 1 "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None

    return {
        "current_task": row["current_task"] or "",
        "next_steps": _parse_json_list(row["next_steps"]),
        "open_questions": _parse_json_list(row["open_questions"]),
        "active_errors": _parse_json_list(row["active_errors"]),
        "key_decisions": _parse_json_list(row["key_decisions"]),
        "directory": row["directory_context"] or "",
    }


def _read_db(db_path: str) -> tuple[list[dict], list[dict], dict | None]:
    """Read anchored memories, hot memories, and latest checkpoint from SQLite."""
    try:
        conn = sqlite3.connect(db_path, timeout=3)
        conn.row_factory = sqlite3.Row

        anchors = _fetch_anchors(conn)
        anchor_ids = {a["id"] for a in anchors}
        hot = _fetch_hot_memories(conn, anchor_ids)
        checkpoint = _fetch_checkpoint(conn)

        conn.close()
    except Exception as exc:
        _log(f"DB read failed (non-fatal): {exc}")
        return [], [], None

    return anchors, hot, checkpoint


def _format_checkpoint_section(checkpoint: dict) -> list[str]:
    """Format the checkpoint into markdown lines."""
    lines = ["### Last Session State"]
    lines.append(f"**Task:** {checkpoint['current_task']}")
    if checkpoint.get("directory"):
        lines.append(f"**Directory:** `{checkpoint['directory']}`")
    if checkpoint.get("next_steps"):
        lines.append("**Next steps:**")
        for step in checkpoint["next_steps"][:3]:
            lines.append(f"- {step}")
    if checkpoint.get("active_errors"):
        lines.append("**Active errors:**")
        for err in checkpoint["active_errors"][:2]:
            lines.append(f"- ⚠️ {err}")
    if checkpoint.get("open_questions"):
        lines.append("**Open questions:**")
        for q in checkpoint["open_questions"][:2]:
            lines.append(f"- {q}")
    lines.append("")
    return lines


def _build_context(
    anchors: list[dict],
    hot: list[dict],
    checkpoint: dict | None,
) -> str:
    """Build the Markdown context block injected into the session."""
    if not anchors and not hot and not checkpoint:
        return ""

    lines = ["## 🧠 Cortex Memory Context\n"]

    if checkpoint and checkpoint.get("current_task"):
        lines.extend(_format_checkpoint_section(checkpoint))

    if anchors:
        lines.append("### 📌 Anchored Memories (critical — do not forget)")
        for a in anchors:
            lines.append(f"- {_short(a['content'])}")
        lines.append("")

    if hot:
        lines.append("### 🔥 Hot Memories")
        for m in hot:
            heat_bar = "█" * min(5, int(m["heat"] * 5))
            domain_hint = f" [{m['domain']}]" if m.get("domain") else ""
            lines.append(f"- {heat_bar}{domain_hint} {_short(m['content'])}")
        lines.append("")

    lines.append(
        "*Use `recall` to retrieve full memories. Use `anchor <id>` to protect critical facts.*"
    )
    return "\n".join(lines)


_AUTO_BACKFILL_THRESHOLD = int(os.environ.get("CORTEX_AUTO_BACKFILL_THRESHOLD", "20"))


def _count_memories(db_path: str) -> int:
    """Return total non-archived memories in the store."""
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        row = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE archived = 0"
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _trigger_backfill() -> None:
    """Run backfill in a subprocess so it doesn't block session start."""
    import subprocess

    try:
        subprocess.Popen(
            [
                "python3",
                "-c",
                "import asyncio; "
                "from mcp_server.handlers.backfill_memories import handler; "
                "asyncio.run(handler({'max_files': 30, 'min_importance': 0.35}))",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _log("Auto-backfill triggered in background")
    except Exception as exc:
        _log(f"Auto-backfill trigger failed (non-fatal): {exc}")


def main() -> None:
    """Entry point — print context block to stdout."""
    db = Path(_DB_PATH)
    if not db.exists():
        _log("No memory DB found, skipping context injection")
        return

    # Auto-backfill on fresh installs (fires once in background, non-blocking)
    total = _count_memories(_DB_PATH)
    if total < _AUTO_BACKFILL_THRESHOLD:
        _trigger_backfill()

    anchors, hot, checkpoint = _read_db(_DB_PATH)
    context = _build_context(anchors, hot, checkpoint)

    if context:
        print(context)
        _log(f"Injected {len(anchors)} anchors + {len(hot)} hot memories into session")
    else:
        _log("No memories above threshold — skipping injection")


if __name__ == "__main__":
    main()
