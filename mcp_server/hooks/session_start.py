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

from mcp_server.handlers.injection_receipts import (
    emit_hook_receipt,
    emit_injection_receipt,
    receipt_marker,
    session_id_from_transcript,
)
import sqlite3
import asyncio
from datetime import datetime as _dt, timezone as _tz

# ── Config ────────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://127.0.0.1:5432/cortex")
_HOT_LIMIT = int(os.environ.get("CORTEX_SESSION_START_LIMIT", "8"))
_MIN_HEAT = float(os.environ.get("CORTEX_SESSION_START_MIN_HEAT", "0.4"))
_ANCHOR_LIMIT = int(os.environ.get("CORTEX_SESSION_START_ANCHOR_LIMIT", "5"))
_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "")


def _log(msg: str) -> None:
    print(f"[session-start-hook] {msg}", file=sys.stderr)


def _read_event() -> dict:
    """Read the SessionStart hook event from stdin, tolerantly.

    Claude Code pipes the event JSON ({"session_id", "transcript_path",
    "cwd", ...}) to every hook. A manual/tty run, an empty pipe, or
    malformed JSON all degrade to {} — the banner never depends on the
    event; only the receipt's session identity does (correction 7).
    """
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read().strip()
        return json.loads(raw) if raw else {}
    except (OSError, ValueError):
        return {}


def _has_sentence_transformers() -> bool:
    """Check if sentence-transformers is importable."""
    try:
        import sentence_transformers  # noqa: PLC0415, F401 — optional-feature probe: ImportError here is a handled degraded mode

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
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"setup_db failed: {exc}")
        return None


def _connect_pg():
    """Try to connect to PostgreSQL. Returns connection or None."""
    try:
        import psycopg  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working
        from psycopg.rows import DictRow, dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

        return psycopg.Connection[DictRow].connect(
            _DATABASE_URL, row_factory=dict_row, autocommit=True
        )
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"PostgreSQL connect failed: {exc}")
        return None


# ── Memory fetching ──────────────────────────────────────────────────────


def _fetch_anchors(conn) -> list[dict]:
    """Fetch anchored memories (is_protected with _anchor tag).

    Defense-in-depth: also exclude auto-captured memories even when
    is_protected=TRUE (a protected auto-capture should not exist, but
    we guard against it to prevent poisoned banner injection).
    # contract: zetetic-team-subagents memory/contract.md §8b
    """
    try:
        rows = conn.execute(
            # `memories.heat` is not a stored column; use effective_heat()
            # to match production recall semantics (lazy A3 decay).
            # Source: pg_schema.py EFFECTIVE_HEAT_FN.
            "SELECT m.id, m.content, m.tags, m.domain, m.is_global "
            # JOIN current_memories (not FROM the view): effective_heat()
            # takes the `memories` composite type and a view row is not
            # coercible to it; the join keeps m table-typed while the
            # supersession invariant stays defined once, in the view.
            # Anchors follow the chain head at supersession (write-path
            # transfer in supersede_atomic), so the corrected anchor is
            # what gets injected here.
            "FROM memories m JOIN current_memories cm ON cm.id = m.id "
            "WHERE m.is_protected = TRUE "
            # Exclude auto-captured noise (defense-in-depth — they should never
            # be protected, but guard against misconfiguration).
            # contract: zetetic-team-subagents memory/contract.md §8b
            "AND NOT (m.tags @> '[\"auto-captured\"]'::jsonb) "
            # Never inject a corrected (superseded) fact into the banner —
            # decision 4255039 correction 8.
            "AND m.superseded_by_id IS NULL "
            "ORDER BY effective_heat(m, NOW()) DESC LIMIT %s",
            (int(_ANCHOR_LIMIT),),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"anchor fetch failed (non-fatal): {exc}")
        return []

    anchors = []
    for r in rows:
        tags = r.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except ValueError:
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
            # JOIN current_memories: same pattern as _fetch_anchors —
            # supersession exclusion via the view, m stays table-typed
            # for effective_heat().
            "effective_heat(m, NOW()) AS heat "
            "FROM memories m JOIN current_memories cm ON cm.id = m.id "
            "WHERE m.is_protected = TRUE AND m.is_global = TRUE "
            "AND m.agent_context != '' "
            # Superseded decisions are corrected facts — never re-inject
            # (decision 4255039 correction 8).
            "AND m.superseded_by_id IS NULL "
            "ORDER BY effective_heat(m, NOW()) DESC LIMIT 5",
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"team-decision fetch failed (non-fatal): {exc}")
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
    """Fetch high-heat memories, excluding anchors.

    Tier exclusion: auto-captured tool noise and block-replica snapshots
    must not appear in the session-start banner — they poison the injected
    context with raw "# Tool: Edit" captures.
    # contract: zetetic-team-subagents memory/contract.md §8b
    """
    try:
        rows = conn.execute(
            "SELECT id, content, domain, heat_base AS heat, tags, is_global "
            # current_memories: hot-pool content injected into the session
            # banner — supersession chain heads only.
            "FROM current_memories "
            "WHERE heat_base >= %s "
            # Exclude tier-1 noise: auto-captured tool outputs and block replicas.
            # JSONB containment: tags @> '[\"x\"]' is true when the array contains x.
            # contract: zetetic-team-subagents memory/contract.md §8b
            "AND NOT (tags @> '[\"auto-captured\"]'::jsonb "
            "         OR tags @> '[\"memory-replica\"]'::jsonb) "
            # Never re-inject a corrected (superseded) fact —
            # decision 4255039 correction 8.
            "AND superseded_by_id IS NULL "
            "ORDER BY heat_base DESC LIMIT %s",
            (float(_MIN_HEAT), int(_HOT_LIMIT + len(exclude_ids))),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"hot-memory fetch failed (non-fatal): {exc}")
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
        from mcp_server.core.auto_curator import count_pending_clusters  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

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
            from mcp_server.infrastructure.config import WIKI_ROOT  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode

            wiki_root = str(WIKI_ROOT)
        except ImportError:
            wiki_root = None
        return count_pending_clusters(memories, wiki_root=wiki_root)
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"pending-cluster count failed (non-fatal): {exc}")
        return 0


def _fetch_grooming_staleness(conn) -> list[str]:
    """Return the kinds ('wiki'/'distillation'/'promotion') of
    judgment-level grooming that are overdue for attention.

    Precondition: none.
    Postcondition: returns a subset of {'wiki', 'distillation',
    'promotion'} -- kinds whose last execution is older than
    ``core.grooming_health.GROOMING_STALENESS_THRESHOLD_DAYS`` days, or
    that have never executed. Read-only, three bounded aggregate
    queries (~30ms combined, EXPLAIN ANALYZE 2026-07-11 -- see
    ``PgStatsMixin.get_grooming_ages`` for the per-query cost
    breakdown; this hook queries directly rather than going through
    ``get_shared_store`` to avoid pulling the full store composition
    into the SessionStart hot path). Deliberately does NOT call the
    backlog-count planners (curate_wiki/curate_distill/
    lesson_promotion) -- those cost ~1s combined
    (get_grooming_health.py), too expensive for every session start.

    Failure here is non-fatal: a missing staleness signal must never
    break the SessionStart preamble. Returns [] on any error.
    """
    try:
        from mcp_server.core.grooming_health import is_stale  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        row = conn.execute(
            "SELECT "
            "  (SELECT MAX(tended) FROM wiki.pages) AS wiki_last, "
            "  (SELECT MAX(created_at) FROM memories m "
            "     WHERE m.tags @> '[\"lesson\"]'::jsonb "
            "     AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
            "                 WHERE tg LIKE 'distill-of:%')) AS distill_last, "
            "  (SELECT MAX(created_at) FROM memories m "
            "     WHERE m.tags @> '[\"lesson\"]'::jsonb "
            "     AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
            "                 WHERE tg LIKE 'promoted:%')) AS promo_last"
        ).fetchone()
        if not row:
            return []
        d = dict(row) if not isinstance(row, dict) else row
        stale = []
        for kind, col in (
            ("wiki", "wiki_last"),
            ("distillation", "distill_last"),
            ("promotion", "promo_last"),
        ):
            ts = d.get(col)
            last_iso = ts.isoformat() if ts else None
            if is_stale(last_iso):
                stale.append(kind)
        return stale
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"grooming-staleness fetch failed (non-fatal): {exc}")
        return []


def _parse_json_list(val) -> list:
    """Tolerant list coercion for checkpoint columns (JSON text or list)."""
    if not val:
        return []
    if isinstance(val, list):
        return val
    try:
        return json.loads(val) or []
    except (ValueError, TypeError):
        return [val] if isinstance(val, str) and val.strip() else []


def _checkpoint_from_row(row: dict | None) -> dict | None:
    """Map a checkpoint row (PG dict_row or SQLite normalized row) to the
    banner's checkpoint shape. Shared by both backend paths."""
    if not row:
        return None
    return {
        "current_task": row.get("current_task", ""),
        "next_steps": _parse_json_list(row.get("next_steps")),
        "open_questions": _parse_json_list(row.get("open_questions")),
        "active_errors": _parse_json_list(row.get("active_errors")),
        "key_decisions": _parse_json_list(row.get("key_decisions")),
        "directory": row.get("directory_context", ""),
    }


def _fetch_checkpoint(conn) -> dict | None:
    """Fetch the latest active checkpoint."""
    try:
        row = conn.execute(
            "SELECT current_task, next_steps, open_questions, active_errors, "
            "key_decisions, directory_context "
            "FROM checkpoints WHERE is_active = TRUE "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"checkpoint fetch failed (non-fatal): {exc}")
        return None

    return _checkpoint_from_row(row)


def _count_memories(conn) -> int:
    """Count total memories."""
    try:
        row = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()
        return row["c"] if row else 0
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"memory count failed (non-fatal): {exc}")
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
            conn = sqlite3.connect(str(claude_mem_db))
            count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            conn.close()
            if count > 0:
                sources.append(
                    {"name": "claude-mem", "count": count, "path": str(claude_mem_db)}
                )
        except Exception:  # noqa: BLE001 — external-source probe — failure is reported as a count-0 source entry in the banner
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
        from mcp_server.handlers.backfill_memories import handler as backfill_handler  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

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
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
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


def _emit_banner_receipt(
    conn, event: dict, anchors: list[dict], team_decisions: list[dict], hot: list[dict]
) -> int | None:
    """Emit the session_start injection receipt for the banner (T2).

    Payload order mirrors the banner exactly: anchors, then team
    decisions, then hot memories — rank = position in the injected
    context. Banner lines are printed truncated (_short) but the memory
    IS in context, so truncation never drops an item (same parity stance
    as recall's bound_payload, decision 4255039 correction 11).
    """
    payload = [{"memory_id": m["id"]} for m in (*anchors, *team_decisions, *hot)]
    return emit_hook_receipt(
        conn,
        payload,
        channel="session_start",
        session_id=session_id_from_transcript(event.get("transcript_path")),
    )


def _build_context(
    anchors: list[dict],
    hot: list[dict],
    checkpoint: dict | None,
    team_decisions: list[dict] | None = None,
    pending_curations: int = 0,
    stale_grooming: list[str] | None = None,
    receipt_id: int | None = None,
) -> str:
    """Build the Markdown context block injected into the session.

    ``receipt_id`` stamps the banner header with the ⟦rcpt:id⟧ marker
    (decision 4255039 correction 2) so the model can hand the id back
    to ``cortex:why(receipt_ids=[...])`` — the receipt travels in-context
    because server-side session-temporal resolution does not exist.
    """
    if (
        not anchors
        and not hot
        and not checkpoint
        and not team_decisions
        and not pending_curations
        and not stale_grooming
    ):
        return ""

    header = "## Cortex Memory Context"
    if receipt_id is not None:
        header += f" {receipt_marker(receipt_id)}"
    lines = [header + "\n"]

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

    # G-4: one-line staleness reminder -- never a section, per the
    # 76-day-silent-wiki lesson (a full pending-curations-style block per
    # session would just become the next ignored nudge). Fires only when
    # a kind has gone longer than the sourced threshold without a real
    # (judgment-level) run; call `get_grooming_health` for exact counts.
    if stale_grooming:
        kinds_str = "/".join(stale_grooming)
        lines.append(
            f"*Grooming overdue ({kinds_str}) -- call `get_grooming_health` "
            "for backlog counts and exact ages.*"
        )

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
                f"Cortex auto-imported **{imported} memories** "
                f"from your conversation history.\n"
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
        from mcp_server.infrastructure.pipeline_discovery import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            ensure_pipeline_connection,
        )

        result = ensure_pipeline_connection()
        action = result.get("action", "unknown")
        if action in {"wrote_config", "added_codebase"}:
            _log(
                f"pipeline auto-wired ({result.get('binary')}) in {result.get('path')}"
            )
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"pipeline auto-wire skipped: {exc}")


_CONSOLIDATE_TTL_HOURS: float = float(
    os.environ.get("CORTEX_CONSOLIDATE_TTL_HOURS", "6")
)


def _spawn_consolidate_cycle() -> int | None:
    """Spawn the detached ``consolidate_background`` worker; return its pid.

    precondition: none. postcondition: a fully-detached subprocess (own
    process group, stdio → ``consolidate.log``) is started and its pid
    returned, or None if the spawn itself failed. The worker runs decay,
    compression, CLS, memify, cascade, homeostatic, emergence cycles plus
    autonomous wiki maintenance — this is the SAME cycle as before; #171
    changes only WHO decides to start it, never what it does.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(
        Path(__file__).resolve().parents[2]
    )
    launcher = Path(plugin_root) / "scripts" / "launcher.py"
    py = (
        __import__("shutil").which("python3")
        or __import__("shutil").which("python")
        or sys.executable
    )
    if launcher.exists():
        cmd = [py, str(launcher), "mcp_server.hooks.consolidate_background"]
    else:
        # Fall back to direct -m invocation (dev source is the package root).
        cmd = [py, "-m", "mcp_server.hooks.consolidate_background"]

    log_path = Path.home() / ".claude" / "methodology" / "consolidate.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(  # noqa: S603 — cmd built from trusted sources
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=open(log_path, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _log(f"background consolidate spawned → {log_path}")
    return proc.pid


def _maybe_background_consolidate() -> None:
    """Ensure ONE consolidate cycle runs per period across N sessions (#171).

    The consolidate handler must NEVER be invoked manually by the user
    (directive 2026-05-18). SessionStart owns the trigger, but the trigger
    is now session-counted, not per-session: this window registers with the
    per-store ``GroomerCoordinator`` and asks it to ensure a cycle. The
    coordinator writes the period stamp under a per-store lock BEFORE
    spawning, so two concurrent sessions produce exactly one cycle per
    ``CORTEX_CONSOLIDATE_TTL_HOURS`` window (default 6h) — fixing the old
    ``"(in-flight)"``-marker race where a second session read the stamp as
    never-run and spawned a duplicate.

    Degrade honestly (#171): if the coordinator path raises for ANY reason,
    fall back to the legacy per-session stamp spawn with a logged NOTICE —
    never silently skip grooming entirely.
    """
    try:
        from mcp_server.infrastructure.groomer_coordinator import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            GroomerCoordinator,
            resolve_store_key,
        )

        coord = GroomerCoordinator(resolve_store_key())
        coord.register(os.getpid())
        outcome = coord.ensure_cycle(
            period_hours=_CONSOLIDATE_TTL_HOURS,
            spawn_fn=_spawn_consolidate_cycle,
        )
        _log(f"groomer coordinator: {outcome}")
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(
            f"NOTICE: groomer coordinator unavailable ({exc}); falling back "
            "to legacy per-session consolidate spawn"
        )
        _legacy_background_consolidate()


def _legacy_background_consolidate() -> None:
    """Pre-#171 per-session stamp spawn — the honest degrade path.

    Kept as the fallback the coordinator degrades to (never a silent skip).
    Spawns the cycle when the global ``.last_consolidate`` stamp is older
    than the TTL. Retains the crude ``"(in-flight)"`` marker: under this
    path (coordinator wholly unavailable) it is still strictly better than
    no guard at all.
    """
    try:
        from mcp_server.hooks.consolidate_background import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            STAMP_PATH,
            read_stamp,
        )

        last = read_stamp()
        if last is not None:
            age_hours = (_dt.now(_tz.utc) - last).total_seconds() / 3600.0
            if age_hours < _CONSOLIDATE_TTL_HOURS:
                return  # Fresh enough; skip.

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
        _spawn_consolidate_cycle()
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
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
        from mcp_server.infrastructure.pipeline_discovery import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            discover_pipeline_command,
        )
        from mcp_server.infrastructure.pipeline_graph_ttl import graph_is_stale  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

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
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"background pipeline reanalysis skipped: {exc}")


def _lookup_cached_graph_path(project_root: str) -> str | None:
    """Read the cached ``graph_path=...`` memo for this project, if any."""
    try:
        from mcp_server.handlers.ingest_helpers import (  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
            code_graph_tag,
        )
    except ImportError:
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
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"cached-graph lookup failed (non-fatal): {exc}")
        return None
    finally:
        try:
            conn.close()
        except Exception as exc:  # noqa: BLE001 — teardown must not mask the lookup result
            _log(f"pg connection close failed: {exc}")
    return None


def _refresh_session_registry(event: dict) -> None:
    """Best-effort write of this window's current session into the
    per-window registry (T2-D6, T2-D11), plus an opportunistic purge of
    dead-pid entries.

    precondition: ``event`` is the tolerant ``_read_event()`` result —
    may be ``{}``. postcondition: on success, this window's registry
    entry (keyed by the ancestor ``claude`` pid) holds the transcript
    stem computed by ``session_id_from_transcript`` and stale entries
    for closed windows are removed. Any failure — resolution, I/O,
    import — degrades to a stderr log line and NEVER raises: the
    SessionStart banner is critical and must ship regardless of the
    registry's state (design §1 directing invariant).

    Called unconditionally near the top of ``main()`` rather than after
    the last banner line: three of ``main()``'s branches return early
    (no PostgreSQL, setup failed, empty DB) and a real interactive
    window can legitimately hit any of them on first launch — the
    registry entry must exist for those windows too (T2-D9 case 3),
    not only on the "normal flow" happy path. This is a deliberate
    placement deviation from the design note's "dernière position du
    hook" — the design's binding requirement is best-effort
    non-interference with the banner, which top-of-main placement
    satisfies identically (produces no stdout, no exception escapes).
    """
    try:
        from mcp_server.infrastructure.session_registry import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            purge_dead_entries,
            write_session,
        )

        write_session(session_id_from_transcript(event.get("transcript_path")))
        purge_dead_entries()
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"session registry refresh skipped (non-fatal): {exc}")


# ── SQLite backend path (zero-config plugin default) ─────────────────────
#
# The plugin's default install provisions no PostgreSQL server; the
# launcher resolves CORTEX_MEMORY_STORE_BACKEND=sqlite from the install
# marker (mcp_server/infrastructure/backend_marker.py). This path builds
# the same banner (checkpoint + anchors + hot memories + injection
# receipt) through the store abstraction instead of raw psycopg SQL.
# PG-only banner extras — team decisions, pending wiki curation,
# grooming staleness — are skipped here; README "Install" discloses the
# difference.

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


def _partition_banner_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split hot rows into (anchors, hot) with the PG path's exclusions.

    Mirrors _fetch_anchors/_fetch_hot_memories: tier-1 noise tags are
    dropped, protected ``_anchor``-tagged rows become anchors, the rest
    are hot-pool entries. Supersession exclusion already happened
    upstream (``get_hot_memories(heads_only=True)`` routes through the
    ``current_memories`` view).
    """
    anchors: list[dict] = []
    hot: list[dict] = []
    for r in rows:
        tags = [t for t in (r.get("tags") or []) if isinstance(t, str)]
        if _SQLITE_NOISE_TAGS & set(tags):
            continue
        entry = {
            "id": r["id"],
            "content": r.get("content", ""),
            "domain": r.get("domain", "") or "",
            "heat": float(r.get("heat") or 0.0),
            "is_global": bool(r.get("is_global", False)),
        }
        is_anchor = bool(r.get("is_protected")) and any(
            t == "_anchor" or t.startswith("_anchor:") for t in tags
        )
        (anchors if is_anchor else hot).append(entry)
    return anchors[:_ANCHOR_LIMIT], hot[:_HOT_LIMIT]


def _sqlite_banner_rows(store) -> tuple[list[dict], list[dict], dict | None]:
    """Fetch (anchors, hot, checkpoint) from the SQLite store, tolerantly."""
    try:
        rows = store.get_hot_memories(
            min_heat=_MIN_HEAT, limit=_HOT_LIMIT + _ANCHOR_LIMIT, heads_only=True
        )
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"SQLite hot-memory fetch failed (non-fatal): {exc}")
        rows = []
    anchors, hot = _partition_banner_rows(rows)
    try:
        checkpoint = _checkpoint_from_row(store.get_active_checkpoint())
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"SQLite checkpoint fetch failed (non-fatal): {exc}")
        checkpoint = None
    return anchors, hot, checkpoint


def _sqlite_context(event: dict) -> None:
    """Build and print the SessionStart banner on the SQLite backend."""
    try:
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        store = get_shared_store()
        total = int(store.count_memories().get("total") or 0)
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"SQLite store unavailable (non-fatal): {exc}")
        return

    if total == 0:
        session_files = _count_session_files()
        _log(f"Empty SQLite store, {session_files} session files found")
        msg = _build_cold_start_message(
            {"status": "ready", "memories": 0, "session_files": session_files}
        )
        if msg:
            print(msg)
        return

    anchors, hot, checkpoint = _sqlite_banner_rows(store)
    receipt_id = None
    payload = [{"memory_id": m["id"]} for m in (*anchors, *hot)]
    if payload:
        receipt_id = emit_injection_receipt(
            store,
            payload,
            channel="session_start",
            session_id=session_id_from_transcript(event.get("transcript_path")),
        )

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


def main() -> None:
    """Entry point — print context block to stdout."""

    # Hook event first: stdin carries transcript_path, the stable session
    # identity for the injection receipt (decision 4255039 correction 7).
    event = _read_event()

    # Best-effort registry refresh (T2-H2) — see _refresh_session_registry
    # docstring for why this runs here rather than at the tail of main().
    _refresh_session_registry(event)

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

    # SQLite backend (zero-config plugin default): banner via the store
    # abstraction — no psycopg connection to attempt.
    if _backend_is_sqlite():
        _sqlite_context(event)
        return

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
    stale_grooming = _fetch_grooming_staleness(conn)
    # Receipt BEFORE rendering: the banner header carries the ⟦rcpt:id⟧
    # marker, so the id must exist when the context is built. A failed
    # write degrades to a marker-less banner (read path intact).
    receipt_id = _emit_banner_receipt(conn, event, anchors, team_decisions, hot)
    conn.close()

    context = _build_context(
        anchors,
        hot,
        checkpoint,
        team_decisions,
        pending_curations=pending_curations,
        stale_grooming=stale_grooming,
        receipt_id=receipt_id,
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
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"External source detection failed (non-fatal): {exc}")


if __name__ == "__main__":
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    main()
