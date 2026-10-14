"""SessionStart hook banner rendering: the context block and the cold-start message.

source: ADR-0498"""

from __future__ import annotations

from datetime import datetime as _dt, timezone as _tz

from mcp_server.handlers.injection_receipts import (
    emit_hook_receipt,
    MEMORY_MARKER_PREFIX,
    memory_marker,
    receipt_marker,
    session_id_from_transcript,
)
from mcp_server.hooks.session_start_common import _log
from mcp_server.hooks.session_start_sources import _auto_backfill
from mcp_server.shared.freshness import provenance_suffix


def _short(text: str, max_len: int = 120) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 1] + "..."


def _body(memory: dict, max_len: int = 120) -> str:
    """Render one memory's content for a banner line, keeping a fetch key
        when — and only when — the line is actually truncated.

        Truncation itself is byte-identical to ``_short`` — this changes what
        a cut line CARRIES, not where it is cut.

    source: ADR-0498"""
    content = memory["content"].strip().replace("\n", " ")
    if len(content) <= max_len:
        return content
    return f"{content[: max_len - 1]}... {memory_marker(memory['id'])}"


def _format_checkpoint_section(checkpoint: dict) -> list[str]:
    """Format the checkpoint into markdown lines.

    Every field is passed through ``_short()`` — the same per-item cap
    already applied to anchors/team-decisions/hot memories below. Before
    this, checkpoint fields were the one banner section written raw: a
    long ``current_task`` or a verbose ``next_steps``/``active_errors``/
    ``open_questions`` entry could inflate this per-turn-repeated banner
    with no bound, unlike every other section in this file.
    """
    lines = ["### Last Session State"]
    lines.append(f"**Task:** {_short(str(checkpoint['current_task']))}")
    if checkpoint.get("directory"):
        lines.append(f"**Directory:** `{checkpoint['directory']}`")
    if checkpoint.get("next_steps"):
        lines.append("**Next steps:**")
        for step in checkpoint["next_steps"][:3]:
            lines.append(f"- {_short(str(step))}")
    if checkpoint.get("active_errors"):
        lines.append("**Active errors:**")
        for err in checkpoint["active_errors"][:2]:
            lines.append(f"- {_short(str(err))}")
    if checkpoint.get("open_questions"):
        lines.append("**Open questions:**")
        for q in checkpoint["open_questions"][:2]:
            lines.append(f"- {_short(str(q))}")
    lines.append("")
    return lines


def _emit_banner_receipt(
    conn, event: dict, anchors: list[dict], team_decisions: list[dict], hot: list[dict]
) -> int | None:
    """Emit the session_start injection receipt for the banner (T2).

    source: ADR-0498"""
    payload = [{"memory_id": m["id"]} for m in (*anchors, *team_decisions, *hot)]
    return emit_hook_receipt(
        conn,
        payload,
        channel="session_start",
        session_id=session_id_from_transcript(event.get("transcript_path")),
    )


def _freshness(memory: dict, now: _dt) -> str:
    """Rendered freshness suffix (age · grade · stale; fleet-watch #110), or ""
    for memories that carry none of those signals."""
    suffix = provenance_suffix(memory, now)
    return f"  ·  {suffix}" if suffix else ""


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

    source: ADR-0498"""
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
    now = _dt.now(_tz.utc)

    if checkpoint and checkpoint.get("current_task"):
        lines.extend(_format_checkpoint_section(checkpoint))

    if anchors:
        lines.append("### Anchored Memories (critical)")
        for a in anchors:
            lines.append(f"- {_body(a)}{_freshness(a, now)}")
        lines.append("")

    # Team decisions from other agents (TMS directory layer, Wegner 1987)
    if team_decisions:
        lines.append("### Team Decisions")
        for d in team_decisions:
            agent = d.get("agent", "")
            prefix = f"[{agent}] " if agent else ""
            lines.append(f"- {prefix}{_body(d)}{_freshness(d, now)}")
        lines.append("")

    if hot:
        lines.append("### Hot Memories")
        for m in hot:
            heat_bar = "+" * min(5, int(m["heat"] * 5))
            domain_hint = f" [{m['domain']}]" if m.get("domain") else ""
            bullet = f"- [{heat_bar}]{domain_hint} {_body(m)}"
            lines.append(f"{bullet}{_freshness(m, now)}")
        lines.append("")

    # source: ADR-0498
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

    # source: ADR-0498
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
    # Only explain the key when at least one line actually carries one —
    # a legend for a notation absent from the text above is pure noise.
    if any(MEMORY_MARKER_PREFIX in line for line in lines):
        lines.append(
            f"*Lines ending in `{MEMORY_MARKER_PREFIX}id\u27e7` are truncated; "
            "read the full memory with `recall(memory_id=id)`.*"
        )

    return "\n".join(lines)


def _build_cold_start_message(setup_result: dict | None) -> str:
    """Build a friendly message for first-time users."""
    lines = ["## Cortex — First Run\n"]

    if setup_result and setup_result.get("status") == "needs_install":
        # source: ADR-1104 -- the configured server's own error, no install recipe
        lines.append(
            "The PostgreSQL server configured for Cortex is not reachable: "
            f"{setup_result.get('message', 'no detail')}\n"
        )
        lines.append(
            "Start that server, or clear the plugin's database URL option "
            "(/plugin, Configure options) to use the local SQLite store."
        )
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
