"""SessionStart hook banner rendering: the context block and the cold-start message.

source: ADR-0498"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime as _dt, timezone as _tz

from mcp_server.hooks.session_start_common import _log
from mcp_server.shared.freshness import provenance_suffix
from mcp_server.shared.injection_markers import (
    MEMORY_MARKER_PREFIX,
    memory_marker,
    receipt_marker,
)


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


def _freshness(memory: dict, now: _dt) -> str:
    """Rendered freshness suffix (age · grade · stale; fleet-watch #110), or ""
    for memories that carry none of those signals."""
    suffix = provenance_suffix(memory, now)
    return f"  ·  {suffix}" if suffix else ""


def _memory_sections(
    anchors: list[dict], team_decisions: list[dict] | None, hot: list[dict]
) -> list[str]:
    """Banner lines for the anchored, team-decision and hot memories."""
    lines: list[str] = []
    now = _dt.now(_tz.utc)
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
    return lines


def _maintenance_lines(
    pending_curations: int, stale_grooming: list[str] | None
) -> list[str]:
    """Banner lines asking the agent to run the queued curation/grooming.

    source: ADR-0498"""
    lines: list[str] = []
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
    if stale_grooming:
        kinds_str = "/".join(stale_grooming)
        lines.append(
            f"*Grooming overdue ({kinds_str}) -- call `get_grooming_health` "
            "for backlog counts and exact ages.*"
        )
    return lines


def _footer_lines(has_memory_marker: bool) -> list[str]:
    """The usage hints closing the banner."""
    lines = [
        "*Use `recall` to retrieve full memories. "
        "Use `anchor` to protect critical facts.*"
    ]
    # Only explain the key when at least one line actually carries one —
    # a legend for a notation absent from the text above is pure noise.
    if has_memory_marker:
        lines.append(
            f"*Lines ending in `{MEMORY_MARKER_PREFIX}id\u27e7` are truncated; "
            "read the full memory with `recall(memory_id=id)`.*"
        )
    return lines


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
    if not (
        anchors
        or hot
        or checkpoint
        or team_decisions
        or pending_curations
        or stale_grooming
    ):
        return ""
    header = "## Cortex Memory Context"
    if receipt_id is not None:
        header += f" {receipt_marker(receipt_id)}"
    lines = [header + "\n"]
    if checkpoint and checkpoint.get("current_task"):
        lines.extend(_format_checkpoint_section(checkpoint))
    lines.extend(_memory_sections(anchors, team_decisions, hot))
    lines.extend(_maintenance_lines(pending_curations, stale_grooming))
    has_marker = any(MEMORY_MARKER_PREFIX in line for line in lines)
    lines.extend(_footer_lines(has_marker))
    return "\n".join(lines)


def _setup_problem_message(setup_result: dict) -> str:
    """The banner for a database that is not ready, or "" when it is."""
    status = setup_result.get("status")
    if status == "needs_install":
        # source: ADR-1104 -- the configured server's own error, no install recipe
        return "\n".join(
            [
                "## Cortex — First Run\n",
                "The PostgreSQL server configured for Cortex is not reachable: "
                f"{setup_result.get('message', 'no detail')}\n",
                "Start that server, or clear the plugin's database URL option "
                "(/plugin, Configure options) to use the local SQLite store.",
            ]
        )
    if status == "auth_failed":
        msg = setup_result.get("message", "Authentication failed")
        return "## Cortex — Database Authentication\n\n" + msg
    if status != "ready":
        msg = setup_result.get("message", "Unknown setup error")
        return "\n".join(
            [
                "## Cortex — First Run\n",
                f"Setup issue: {msg}\n",
                "Check the [Cortex README](https://github.com/cdeust/Cortex) "
                "for installation help.",
            ]
        )
    return ""


def _backfill_lines(session_files: int, backfill: Callable[[], int]) -> list[str]:
    """Auto-import the conversation history into an empty store and say so."""
    _log(f"Empty DB with {session_files} session files — auto-backfilling...")
    imported = backfill()
    if imported > 0:
        return [
            f"Cortex auto-imported **{imported} memories** "
            f"from your conversation history.\n",
            "Memories will consolidate naturally as you use them "
            "(recall = replay = consolidation).",
        ]
    return [
        "Cortex is set up and ready. Auto-import found no memorable items.\n",
        "Start working normally — Cortex will automatically remember "
        "important decisions, fixes, and patterns as you go.",
    ]


def _build_cold_start_message(
    setup_result: dict | None, backfill: Callable[[], int]
) -> str:
    """Build a friendly message for first-time users.

    ``backfill`` imports the conversation history into an empty store and
    returns the number of memories imported; it runs only when the store
    is empty and session files exist.
    """
    if setup_result:
        problem = _setup_problem_message(setup_result)
        if problem:
            return problem
    memories = (setup_result or {}).get("memories", 0)
    session_files = (setup_result or {}).get("session_files", 0)
    if memories != 0:
        return ""
    lines = ["## Cortex — First Run\n"]
    if session_files > 0:
        lines.extend(_backfill_lines(session_files, backfill))
    else:
        lines.append("Cortex is set up and ready. No previous sessions found.\n")
        lines.append(
            "Start working normally — Cortex will automatically remember "
            "important decisions, fixes, and patterns as you go."
        )
    return "\n".join(lines)
