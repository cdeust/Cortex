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

_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://127.0.0.1:5432/cortex")
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
            # `memories.heat` is not a stored column; use effective_heat()
            # to match production recall semantics (lazy A3 decay).
            # Source: pg_schema.py EFFECTIVE_HEAT_FN.
            "SELECT m.id, m.content, m.tags, m.domain, m.is_global "
            "FROM memories m "
            "WHERE m.is_protected = TRUE "
            "ORDER BY effective_heat(m, NOW()) DESC LIMIT %s",
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
            # `memories.heat` is not stored; effective_heat(m, NOW())
            # matches production lazy A3 decay semantics.
            # Source: pg_schema.py EFFECTIVE_HEAT_FN.
            "SELECT m.id, m.content, m.domain, m.agent_context, "
            "effective_heat(m, NOW()) AS heat FROM memories m "
            "WHERE m.is_protected = TRUE AND m.is_global = TRUE "
            "AND m.agent_context != '' "
            "ORDER BY effective_heat(m, NOW()) DESC LIMIT 5",
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
            "SELECT id, content, domain, heat_base AS heat, tags, is_global "
            "FROM memories "
            "WHERE heat_base >= %s "
            "ORDER BY heat_base DESC LIMIT %s",
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


def _count_pending_curations(conn) -> int:
    """Count topic clusters of PG memories that warrant a wiki page
    but don't have one yet.

    Surfaced in the SessionStart preamble so the in-session LLM
    (Opus 4.7) sees how much authoring work is queued. The full
    detection logic lives in ``mcp_server.core.auto_curator``; this
    helper just pulls a sample of recently-accessed memories and asks
    the curator to count.

    Failure here is non-fatal: a missing curation count must never
    break the SessionStart preamble. We return 0 and move on.
    """
    try:
        from mcp_server.core.auto_curator import count_pending_clusters

        # `effective_heat` is a PL/pgSQL function, not a column —
        # mirror the form used in _fetch_hot_memories above. Without
        # the (m, NOW()) call form, Postgres rejects with
        # `column "effective_heat" does not exist` and the schema
        # integrity test catches it.
        rows = conn.execute(
            "SELECT id, content, tags, "
            "effective_heat(m, NOW()) AS effective_heat, "
            "created_at, domain "
            "FROM memories m "
            "WHERE NOT is_stale "
            "ORDER BY last_accessed DESC NULLS LAST, created_at DESC "
            "LIMIT 500"
        ).fetchall()
        memories: list[dict] = []
        for r in rows:
            d = dict(r) if not isinstance(r, dict) else r
            memories.append(
                {
                    "id": d.get("id"),
                    "content": d.get("content") or "",
                    "tags": list(d.get("tags") or []),
                    "effective_heat": float(d.get("effective_heat") or 0.0),
                    "created_at": str(d.get("created_at") or ""),
                    "domain": d.get("domain") or "",
                }
            )
        if not memories:
            return 0
        # WIKI_ROOT lookup so the curator can skip already-authored
        # clusters by filesystem mtime.
        try:
            from mcp_server.infrastructure.config import WIKI_ROOT

            wiki_root = str(WIKI_ROOT)
        except Exception:
            wiki_root = None
        return count_pending_clusters(memories, wiki_root=wiki_root)
    except Exception:
        return 0


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


# ── External memory source detection ─────────────────────────────────────


def _detect_external_sources() -> list[dict]:
    """Detect other AI memory systems that can be imported into Cortex."""
    sources = []

    # claude-mem SQLite
    claude_mem_db = Path.home() / ".claude-mem" / "claude-mem.db"
    if claude_mem_db.exists():
        try:
            import sqlite3

            conn = sqlite3.connect(str(claude_mem_db))
            count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            conn.close()
            if count > 0:
                sources.append(
                    {"name": "claude-mem", "count": count, "path": str(claude_mem_db)}
                )
        except Exception:
            sources.append(
                {"name": "claude-mem", "count": 0, "path": str(claude_mem_db)}
            )

    # Cursor conversations
    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.exists():
        cursor_files = list(cursor_dir.glob("**/*.jsonl"))
        if cursor_files:
            sources.append(
                {"name": "Cursor", "count": len(cursor_files), "path": str(cursor_dir)}
            )

    # ChatGPT exports in Downloads
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        chatgpt_files = list(downloads.glob("**/conversations.json"))
        if chatgpt_files:
            sources.append(
                {
                    "name": "ChatGPT",
                    "count": len(chatgpt_files),
                    "path": str(chatgpt_files[0]),
                }
            )

    return sources


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
    pending_curations: int = 0,
) -> str:
    """Build the Markdown context block injected into the session."""
    if (
        not anchors
        and not hot
        and not checkpoint
        and not team_decisions
        and not pending_curations
    ):
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

    # 2026-05-17: surface pending wiki authoring work to the in-session
    # LLM. The auto-curator (handlers/curate_wiki.py) detects high-heat
    # topic clusters of PG memories that warrant a curated wiki page;
    # the in-session LLM (Opus 4.7) is the authoring agent. Without
    # this nudge the LLM has no way to know there's documentation
    # work waiting — surfacing it here lets it happen "without a human
    # asking", per the 2026-05-17 user directive.
    if pending_curations:
        lines.append("### Pending Wiki Curation")
        lines.append(
            f"Auto-curator detected **{pending_curations}** topic cluster"
            f"{'s' if pending_curations != 1 else ''} of PG memories "
            "warrant a curated wiki page. Call `curate_wiki` to fetch "
            "authoring jobs and write the pages via `wiki_write` — "
            "each job carries a structured prompt with the cluster's "
            "memories and the documentation conventions. No human "
            "needs to ask; the curator works queued."
        )
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

    if setup_result and setup_result.get("status") == "auth_failed":
        msg = setup_result.get("message", "Authentication failed")
        return "## Cortex — Database Authentication\n\n" + msg

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
            lines.append(
                f"Cortex auto-imported **{imported} memories** from your conversation history.\n"
            )
            lines.append(
                "Memories will consolidate naturally as you use them "
                "(recall = replay = consolidation)."
            )
        else:
            lines.append(
                "Cortex is set up and ready. Auto-import found no memorable items.\n"
            )
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


def _auto_wire_pipeline() -> None:
    """Best-effort: auto-add the ai-automatised-pipeline MCP server to
    mcp-connections.json when detected. Non-blocking; failures go to
    stderr only.

    Idempotent — once the ``codebase`` server entry exists, subsequent
    SessionStarts leave the config alone. Users who customized their
    config keep their customization.
    """
    try:
        from mcp_server.infrastructure.pipeline_discovery import (
            ensure_pipeline_connection,
        )

        result = ensure_pipeline_connection()
        action = result.get("action", "unknown")
        if action in {"wrote_config", "added_codebase"}:
            _log(
                f"pipeline auto-wired ({result.get('binary')}) in {result.get('path')}"
            )
    except Exception as exc:
        _log(f"pipeline auto-wire skipped: {exc}")


_CONSOLIDATE_TTL_HOURS: float = float(
    os.environ.get("CORTEX_CONSOLIDATE_TTL_HOURS", "6")
)


def _maybe_background_consolidate() -> None:
    """Spawn a detached ``consolidate`` cycle when the stamp is stale.

    The consolidate handler must NEVER be invoked manually by the user
    (directive 2026-05-18). SessionStart owns the trigger: if the last
    successful run was more than ``CORTEX_CONSOLIDATE_TTL_HOURS`` ago
    (default 6h), spawn a detached subprocess that:

      * Runs decay, compression, CLS, memify, cascade, homeostatic,
        emergence cycles.
      * Runs autonomous wiki maintenance (stub purge + classifier-reject
        purge + coverage / drift audit).
      * Updates the stamp at ``~/.claude/methodology/.last_consolidate``.
      * Logs to ``~/.claude/methodology/consolidate.log``.

    Spawn is fully detached (own process group, stdio redirected to the
    log) so SessionStart returns immediately. The user opens a session,
    Cortex catches up silently in the background. The next session sees
    the freshly-consolidated state.

    Failure is silent: a consolidate that crashes leaves the stamp
    untouched so the next session retries. A persistent failure surfaces
    in the log file (operators can `tail -f` it).
    """
    try:
        from mcp_server.hooks.consolidate_background import (
            STAMP_PATH,
            read_stamp,
        )

        last = read_stamp()
        if last is not None:
            from datetime import datetime as _dt, timezone as _tz

            age_hours = (_dt.now(_tz.utc) - last).total_seconds() / 3600.0
            if age_hours < _CONSOLIDATE_TTL_HOURS:
                return  # Fresh enough; skip.

        # Locate the launcher (same as background reanalyze).
        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(
            Path(__file__).resolve().parents[2]
        )
        launcher = Path(plugin_root) / "scripts" / "launcher.py"
        if not launcher.exists():
            # Fall back to direct python invocation with PYTHONPATH —
            # works when the dev source is the package root.
            launcher = None

        py = (
            __import__("shutil").which("python3")
            or __import__("shutil").which("python")
            or sys.executable
        )
        if launcher is not None:
            cmd = [
                py,
                str(launcher),
                "mcp_server.hooks.consolidate_background",
            ]
        else:
            cmd = [py, "-m", "mcp_server.hooks.consolidate_background"]

        log_path = Path.home() / ".claude" / "methodology" / "consolidate.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Touch the stamp so a *second* SessionStart racing this one
        # doesn't spawn a duplicate worker. The background worker
        # overwrites the stamp on its own completion.
        try:
            STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
            STAMP_PATH.write_text(
                __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(timespec="seconds")
                + " (in-flight)",
                encoding="utf-8",
            )
        except OSError:
            pass
        subprocess.Popen(  # noqa: S603 — cmd built from trusted sources
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _log(f"background consolidate spawned → {log_path}")
    except Exception as exc:
        _log(f"background consolidate skipped: {exc}")


def _maybe_background_reanalyze() -> None:
    """Spawn background ``ingest_codebase`` when the graph is stale.

    Runs detached (``subprocess.Popen`` with its own process group) so
    SessionStart returns immediately — the next session sees a fresh
    graph. Blocks NOTHING in the current session. Auto-stops if no
    pipeline is configured or graph is fresh.

    Gated by the TTL check in ``pipeline_graph_ttl.graph_is_stale``.
    Project root is the user's CWD — Claude Code sets this to the
    project Claude was started in.
    """
    try:
        from mcp_server.infrastructure.pipeline_discovery import (
            discover_pipeline_command,
        )
        from mcp_server.infrastructure.pipeline_graph_ttl import graph_is_stale

        if discover_pipeline_command() is None:
            return  # Pipeline not installed — nothing to do.

        project_root = os.environ.get("CLAUDE_PROJECT_ROOT") or os.getcwd()
        cached_path = _lookup_cached_graph_path(project_root)
        if not graph_is_stale(cached_path):
            return  # Fresh enough; skip.

        # Spawn background ingest. scripts/launcher.py handles PYTHONPATH
        # + deps, then runs the ingest_codebase handler as a one-shot CLI.
        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(
            Path(__file__).resolve().parents[2]
        )
        launcher = Path(plugin_root) / "scripts" / "launcher.py"
        if not launcher.exists():
            return

        py = (
            __import__("shutil").which("python3")
            or __import__("shutil").which("python")
            or sys.executable
        )
        cmd = [
            py,
            str(launcher),
            "mcp_server.hooks.ingest_codebase_background",
            project_root,
        ]
        # Detach: no stdin, redirect stdout/stderr to a log file so we
        # can diagnose later.
        log_path = Path.home() / ".claude" / "methodology" / "pipeline_reanalyze.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(  # noqa: S603 — cmd built from trusted sources
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _log(f"background pipeline reanalysis spawned → {log_path}")
    except Exception as exc:
        _log(f"background pipeline reanalysis skipped: {exc}")


def _lookup_cached_graph_path(project_root: str) -> str | None:
    """Read the cached ``graph_path=...`` memo for this project, if any."""
    try:
        from mcp_server.handlers.ingest_helpers import (
            code_graph_tag,
        )
    except Exception:
        return None
    conn = _connect_pg()
    if conn is None:
        return None
    try:
        tag = code_graph_tag(project_root)
        rows = conn.execute(
            "SELECT content FROM memories WHERE tags @> %s::jsonb "
            "AND NOT is_stale ORDER BY heat_base_set_at DESC LIMIT 1",
            (f'["{tag}"]',),
        ).fetchall()
        for row in rows:
            content = row.get("content") or ""
            if content.startswith("graph_path="):
                return content[len("graph_path=") :].strip()
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return None


def main() -> None:
    """Entry point — print context block to stdout."""

    # Auto-discovery runs before the PG path so users see it work even
    # on a fresh machine without a DB set up yet.
    _auto_wire_pipeline()

    # Background re-analysis: fire-and-forget when the graph is stale.
    # This happens BEFORE PG connection because the spawn itself doesn't
    # need the DB — the spawned process will connect independently. If
    # the pipeline isn't installed OR the graph is fresh, this is a no-op.
    _maybe_background_reanalyze()

    # Background consolidate: same pattern, different worker. Runs the
    # full maintenance cycle (decay / compression / CLS / wiki purge /
    # coverage audit) detached when the stamp is older than the TTL
    # (default 6h). The user never invokes consolidate manually — every
    # session opens against a freshly-consolidated store.
    _maybe_background_consolidate()

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
    pending_curations = _count_pending_curations(conn)
    conn.close()

    context = _build_context(
        anchors,
        hot,
        checkpoint,
        team_decisions,
        pending_curations=pending_curations,
    )

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


def _print_external_sources() -> None:
    """Detect and report importable external memory sources."""
    try:
        sources = _detect_external_sources()
        if not sources:
            return
        lines = ["\n### External Memory Sources Detected\n"]
        for s in sources:
            count_str = f" ({s['count']} items)" if s.get("count") else ""
            lines.append(f"- **{s['name']}**{count_str} — `{s['path']}`")
        lines.append("\nUse `/cortex-import` to import these into Cortex.")
        print("\n".join(lines))
        _log(f"Detected {len(sources)} external memory sources")
    except Exception as exc:
        _log(f"External source detection failed (non-fatal): {exc}")


if __name__ == "__main__":
    main()
