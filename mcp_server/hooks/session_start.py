#!/usr/bin/env python3
"""Claude Code SessionStart hook — inject memory context.

Connects to PostgreSQL directly (no MCP roundtrip) and prints a compact
Markdown context block to stdout. Claude Code injects this into the
context window at the start of every session.

On cold start (no database, no memories), prints a friendly setup guide
instead. If memories exist, injects anchored + hot memories + checkpoint.
If the database is empty but session history exists, suggests backfill
with user consent.

Output format
-------------
Prints to stdout — captured by Claude Code and prepended to the session.
Errors go to stderr only and never surface to the user.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
_HOT_LIMIT = int(os.environ.get("CORTEX_SESSION_START_LIMIT", "8"))
_MIN_HEAT = float(os.environ.get("CORTEX_SESSION_START_MIN_HEAT", "0.4"))
_ANCHOR_LIMIT = int(os.environ.get("CORTEX_SESSION_START_ANCHOR_LIMIT", "5"))
_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "")


def _log(msg: str) -> None:
    print(f"[session-start-hook] {msg}", file=sys.stderr)


def _has_sentence_transformers() -> bool:
    """Check if sentence-transformers is importable."""
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


def _short(text: str, max_len: int = 120) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 1] + "..."


# ── Database checks ──────────────────────────────────────────────────────


def _try_setup_db() -> dict | None:
    """Run setup_db.py and return its result, or None on failure."""
    setup_script = (
        Path(__file__).resolve().parent.parent.parent / "scripts" / "setup_db.py"
    )
    if not setup_script.exists():
        # Try relative to CLAUDE_PLUGIN_ROOT
        if _PLUGIN_ROOT:
            setup_script = Path(_PLUGIN_ROOT) / "scripts" / "setup_db.py"
        if not setup_script.exists():
            return None
    try:
        r = subprocess.run(
            [sys.executable, str(setup_script)],
            capture_output=True,
            timeout=15,
            text=True,
            env={**os.environ, "DATABASE_URL": _DATABASE_URL},
        )
        if r.stdout.strip():
            return json.loads(r.stdout.strip())
        return None
    except Exception as exc:
        _log(f"setup_db failed: {exc}")
        return None


def _connect_pg():
    """Try to connect to PostgreSQL. Returns connection or None."""
    try:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(_DATABASE_URL, row_factory=dict_row, autocommit=True)
        return conn
    except Exception as exc:
        _log(f"PostgreSQL connect failed: {exc}")
        return None


# ── Memory fetching ──────────────────────────────────────────────────────


def _fetch_anchors(conn) -> list[dict]:
    """Fetch anchored memories (is_protected with _anchor tag)."""
    try:
        rows = conn.execute(
            "SELECT id, content, tags, domain, is_global FROM memories "
            "WHERE is_protected = TRUE "
            "ORDER BY heat DESC LIMIT %s",
            (int(_ANCHOR_LIMIT),),
        ).fetchall()
    except Exception:
        return []

    anchors = []
    for r in rows:
        tags = r.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        if "_anchor" in tags or any(
            isinstance(t, str) and t.startswith("_anchor:") for t in tags
        ):
            anchors.append(
                {
                    "id": r["id"],
                    "content": r.get("content", ""),
                    "domain": r.get("domain", ""),
                    "is_global": bool(r.get("is_global", False)),
                }
            )
    return anchors


def _fetch_team_decisions(conn, exclude_ids: set) -> list[dict]:
    """Fetch auto-protected decision memories visible across agents.

    Implements the directory layer of Transactive Memory Systems
    (Wegner 1987): team members know WHAT was decided, regardless
    of WHO decided it. Decisions auto-propagate via is_global=TRUE
    set during ingestion (memory_ingest.py).

    Only fetches decisions not already in anchors to avoid duplicates.
    """
    try:
        rows = conn.execute(
            "SELECT id, content, domain, agent_context, heat FROM memories "
            "WHERE is_protected = TRUE AND is_global = TRUE "
            "AND agent_context != '' "
            "ORDER BY heat DESC LIMIT 5",
        ).fetchall()
    except Exception:
        return []

    decisions = []
    for r in rows:
        if r["id"] not in exclude_ids:
            decisions.append(
                {
                    "id": r["id"],
                    "content": r.get("content", ""),
                    "domain": r.get("domain", ""),
                    "agent": r.get("agent_context", ""),
                    "heat": r.get("heat", 0.0),
                }
            )
    return decisions[:3]  # Keep injection compact


def _fetch_hot_memories(conn, exclude_ids: set) -> list[dict]:
    """Fetch high-heat memories, excluding anchors."""
    try:
        rows = conn.execute(
            "SELECT id, content, domain, heat, tags, is_global FROM memories "
            "WHERE heat >= %s "
            "ORDER BY heat DESC LIMIT %s",
            (float(_MIN_HEAT), int(_HOT_LIMIT + len(exclude_ids))),
        ).fetchall()
    except Exception:
        return []

    hot = []
    for r in rows:
        if r["id"] not in exclude_ids:
            hot.append(
                {
                    "id": r["id"],
                    "content": r.get("content", ""),
                    "domain": r.get("domain", ""),
                    "heat": r.get("heat", 0.0),
                    "is_global": bool(r.get("is_global", False)),
                }
            )
    return hot[:_HOT_LIMIT]


def _fetch_checkpoint(conn) -> dict | None:
    """Fetch the latest active checkpoint."""
    try:
        row = conn.execute(
            "SELECT current_task, next_steps, open_questions, active_errors, "
            "key_decisions, directory_context "
            "FROM checkpoints WHERE is_active = TRUE "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return None

    if not row:
        return None

    def _parse_json_list(val) -> list:
        if not val:
            return []
        if isinstance(val, list):
            return val
        try:
            return json.loads(val) or []
        except Exception:
            return [val] if isinstance(val, str) and val.strip() else []

    return {
        "current_task": row.get("current_task", ""),
        "next_steps": _parse_json_list(row.get("next_steps")),
        "open_questions": _parse_json_list(row.get("open_questions")),
        "active_errors": _parse_json_list(row.get("active_errors")),
        "key_decisions": _parse_json_list(row.get("key_decisions")),
        "directory": row.get("directory_context", ""),
    }


def _count_memories(conn) -> int:
    """Count total memories."""
    try:
        row = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()
        return row["c"] if row else 0
    except Exception:
        return 0


def _count_session_files() -> int:
    """Count JSONL session files in ~/.claude/projects/."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return 0
    count = 0
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            count += len(list(project_dir.glob("*.jsonl")))
    return count


# ── Auto-backfill ────────────────────────────────────────────────────────


def _auto_backfill() -> int:
    """Run backfill + cascade automatically on first install.

    Returns number of memories imported.
    """
    try:
        import asyncio

        from mcp_server.handlers.backfill_memories import handler as backfill_handler

        result = asyncio.run(
            backfill_handler(
                {
                    "max_files": 100,
                    "min_importance": 0.35,
                    "force_reprocess": False,
                }
            )
        )
        imported = result.get("backfilled", 0)
        cascade_advanced = result.get("cascade_advanced", 0)
        _log(f"Auto-backfill: {imported} imported, {cascade_advanced} cascaded")
        return imported
    except Exception as exc:
        _log(f"Auto-backfill failed (non-fatal): {exc}")
        return 0


# ── Context building ─────────────────────────────────────────────────────


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
            lines.append(f"- {err}")
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
    team_decisions: list[dict] | None = None,
) -> str:
    """Build the Markdown context block injected into the session."""
    if not anchors and not hot and not checkpoint and not team_decisions:
        return ""

    lines = ["## Cortex Memory Context\n"]

    if checkpoint and checkpoint.get("current_task"):
        lines.extend(_format_checkpoint_section(checkpoint))

    if anchors:
        lines.append("### Anchored Memories (critical)")
        for a in anchors:
            lines.append(f"- {_short(a['content'])}")
        lines.append("")

    # Team decisions from other agents (TMS directory layer, Wegner 1987)
    if team_decisions:
        lines.append("### Team Decisions")
        for d in team_decisions:
            agent = d.get("agent", "")
            prefix = f"[{agent}] " if agent else ""
            lines.append(f"- {prefix}{_short(d['content'])}")
        lines.append("")

    if hot:
        lines.append("### Hot Memories")
        for m in hot:
            heat_bar = "+" * min(5, int(m["heat"] * 5))
            domain_hint = f" [{m['domain']}]" if m.get("domain") else ""
            lines.append(f"- [{heat_bar}]{domain_hint} {_short(m['content'])}")
        lines.append("")

    lines.append(
        "*Use `recall` to retrieve full memories. "
        "Use `anchor` to protect critical facts.*"
    )

    # Warn if semantic search is degraded
    if not _has_sentence_transformers():
        lines.append("")
        lines.append(
            "*Note: sentence-transformers is installing in the background. "
            "Semantic search will improve next session. "
            "Run `pip install sentence-transformers` to install immediately.*"
        )

    return "\n".join(lines)


def _build_cold_start_message(setup_result: dict | None) -> str:
    """Build a friendly message for first-time users."""
    lines = ["## Cortex — First Run\n"]

    if setup_result and setup_result.get("status") == "needs_install":
        lines.append(
            "Cortex needs PostgreSQL to store memories. Here's how to set it up:\n"
        )
        lines.append("```bash")
        lines.append("# macOS")
        lines.append("brew install postgresql@17 pgvector")
        lines.append("brew services start postgresql@17")
        lines.append("")
        lines.append("# Then restart Claude Code")
        lines.append("```\n")
        lines.append("Cortex will auto-create the database and schema on next start.")
        return "\n".join(lines)

    if setup_result and setup_result.get("status") != "ready":
        msg = setup_result.get("message", "Unknown setup error")
        lines.append(f"Setup issue: {msg}\n")
        lines.append(
            "Check the [Cortex README](https://github.com/cdeust/Cortex) "
            "for installation help."
        )
        return "\n".join(lines)

    # DB is ready but empty — offer backfill
    memories = (setup_result or {}).get("memories", 0)
    session_files = (setup_result or {}).get("session_files", 0)

    if memories == 0 and session_files > 0:
        # Auto-backfill on first run — no user interaction needed
        _log(f"Empty DB with {session_files} session files — auto-backfilling...")
        imported = _auto_backfill()
        if imported > 0:
            lines.append(f"Cortex auto-imported **{imported} memories** from your conversation history.\n")
            lines.append(
                "Memories will consolidate naturally as you use them "
                "(recall = replay = consolidation)."
            )
        else:
            lines.append("Cortex is set up and ready. Auto-import found no memorable items.\n")
            lines.append(
                "Start working normally — Cortex will automatically remember "
                "important decisions, fixes, and patterns as you go."
            )
        return "\n".join(lines)

    if memories == 0:
        lines.append("Cortex is set up and ready. No previous sessions found.\n")
        lines.append(
            "Start working normally — Cortex will automatically remember "
            "important decisions, fixes, and patterns as you go."
        )
        return "\n".join(lines)

    return ""


# ── Main ─────────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point — print context block to stdout."""

    # Try connecting to PostgreSQL directly first
    conn = _connect_pg()

    if conn is None:
        # Can't connect — try auto-setup
        _log("No PostgreSQL connection, attempting setup...")
        setup_result = _try_setup_db()

        if setup_result and setup_result.get("status") == "ready":
            # Setup succeeded, try connecting again
            conn = _connect_pg()
            if conn is None:
                _log("Setup reported ready but still can't connect")
                msg = _build_cold_start_message(setup_result)
                if msg:
                    print(msg)
                return
        else:
            # Setup failed or PostgreSQL not available
            msg = _build_cold_start_message(setup_result)
            if msg:
                print(msg)
            return

    # Connected — check memory count
    memory_count = _count_memories(conn)

    if memory_count == 0:
        # Empty database — first run with working DB
        session_files = _count_session_files()
        _log(f"Empty database, {session_files} session files found")
        conn.close()

        setup_result = {
            "status": "ready",
            "memories": 0,
            "session_files": session_files,
        }
        msg = _build_cold_start_message(setup_result)
        if msg:
            print(msg)
        return

    # Normal flow — fetch and inject context
    anchors = _fetch_anchors(conn)
    anchor_ids = {a["id"] for a in anchors}
    hot = _fetch_hot_memories(conn, anchor_ids)
    team_decisions = _fetch_team_decisions(conn, anchor_ids)
    checkpoint = _fetch_checkpoint(conn)
    conn.close()

    context = _build_context(anchors, hot, checkpoint, team_decisions)

    if context:
        print(context)
        _log(
            f"Injected {len(anchors)} anchors + {len(hot)} hot memories "
            f"(total: {memory_count})"
        )
    else:
        _log("No memories above threshold")


if __name__ == "__main__":
    main()
