#!/usr/bin/env python3
"""Automatic child briefing for Claude Code and Codex.

Claude specialists use their task prompt. Codex PreToolUse appends context to
exact spawn arguments; promptless SubagentStart supplies scoped project/role context.
Queries and receipt writes honor the configured SQLite/PostgreSQL backend.

source: ADR-0481
source: ADR-1085
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from mcp_server.handlers.injection_receipts import (
    emit_hook_receipt,
    emit_injection_receipt,
    receipt_marker,
    session_id_from_transcript,
)
from mcp_server.hooks.agent_briefing_keywords import _extract_task_keywords
from mcp_server.hooks.agent_briefing_log import _log
from mcp_server.hooks.agent_briefing_native import emit_native, native_request
from mcp_server.hooks.agent_briefing_role import (
    fetch_role_context as _fetch_role_context,
)
from mcp_server.hooks.agent_briefing_sqlite import SqliteBriefingConnection
from mcp_server.hooks.agent_briefing_query import (
    _MAX_MEMORIES,
    _MIN_HEAT,
    _connect,
    _fetch_agent_context,
)
from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.shared.project_scope import resolve_project_root

__all__ = [
    "_MAX_MEMORIES",
    "_MIN_HEAT",
    "_connect",
    "_fetch_agent_context",
    "_extract_task_keywords",
    "_log",
]

# Fallback set used when the discovered roster is unusable — see
# _load_specialist_agents for what "unusable" means.
_FALLBACK_AGENTS: frozenset[str] = frozenset(
    {
        "engineer",
        "tester",
        "reviewer",
        "architect",
        "dba",
        "devops",
        "frontend",
        "security",
        "researcher",
        "ux",
    }
)

# source: ADR-0481
_NON_SPECIALIST_META_AGENTS: frozenset[str] = frozenset({"dispatch"})

# Matches `name: <slug>` or `name: "<slug>"` in agent-file YAML frontmatter.
_YAML_NAME_RE = re.compile(r"^name:\s*['\"]?([A-Za-z0-9_.-]+)['\"]?\s*$", re.MULTILINE)


def _parse_frontmatter_name(path: Path) -> str | None:
    """Extract the `name:` field from an agent file's YAML frontmatter.

    Reads up to 4 KB (frontmatter always fits) and regex-matches the first
    top-level `name:` line. Returns None if the file is unreadable or has
    no name field. No side effects.
    """
    try:
        head = path.read_text(errors="ignore")[:4096]
    except OSError:
        return None
    m = _YAML_NAME_RE.search(head)
    return m.group(1).strip() if m else None


def _load_specialist_agents() -> frozenset[str]:
    """Dynamically load agent slugs from ~/.claude/agents/ at module import.

        Scans ~/.claude/agents/*.md and ~/.claude/agents/genius/*.md, parses the
        `name:` frontmatter field of each, drops known non-specialist meta-agents
        (_NON_SPECIALIST_META_AGENTS), and returns the frozen set. Falls back to
        _FALLBACK_AGENTS whenever the resulting roster is empty — directory
        absent (e.g., CI without install) and directory-present-but-degenerate
        (e.g., plugin-only-dispatch, holding only dispatch.md) are the same
        failure mode: no specialist to scope memories to. Cached for the process
        lifetime — agents added after import need a restart to be picked up.

    source: ADR-0481"""
    root = CLAUDE_DIR / "agents"
    names: set[str] = set()
    if root.is_dir():
        paths = (md for pattern in ("*.md", "genius/*.md") for md in root.glob(pattern))
        for md in paths:
            if md.name == "INDEX.md":
                continue
            name = _parse_frontmatter_name(md)
            if name:
                names.add(name)
    usable = names - _NON_SPECIALIST_META_AGENTS
    dropped = names & _NON_SPECIALIST_META_AGENTS
    if dropped:
        _log(f"reserved meta-agent name(s) not briefed: {sorted(dropped)}")
    return frozenset(usable) if usable else _FALLBACK_AGENTS


# Known specialist agents that benefit from briefing — dynamic load from
# ~/.claude/agents/ (116+ zetetic agents when installed).
_SPECIALIST_AGENTS = _load_specialist_agents()

# source: ADR-0481
_MIN_PROMPT_CHARS = 20


def _request(event: dict) -> tuple[str, list[str] | None, bool] | None:
    """Native roles do not belong to the Claude specialist roster."""
    try:
        native = native_request(event)
    except ValueError as exc:
        _log(f"skip: {exc}")
        return None
    if native is not None:
        agent, prompt = native
        keywords = _extract_task_keywords(prompt) if prompt else None
        return agent, keywords, True
    agent = (event.get("agent_name") or "").lower()
    prompt = event.get("prompt", "")
    if agent not in _SPECIALIST_AGENTS:
        _log(f"skip: agent '{agent}' not a specialist")
    elif not prompt or len(prompt) < _MIN_PROMPT_CHARS:
        _log("skip: prompt too short")
    elif not (keywords := _extract_task_keywords(prompt)):
        _log("skip: no keywords extracted")
    else:
        return agent, keywords, False
    return None


def _briefing(event, agent, keywords):
    """Fetch bounded context and record exactly those injected memories."""
    try:
        conn = _connect()
    except Exception as exc:  # noqa: BLE001 — hook boundary; visible degradation
        _log(f"skip: briefing store unavailable: {exc}")
        return ""
    if conn is None:
        _log("skip: PostgreSQL unavailable")
        return ""
    try:
        project_root = resolve_project_root(event, os.environ)
        memories = (
            _fetch_role_context(conn, agent, project_root)
            if keywords is None
            else _fetch_agent_context(conn, agent, keywords, project_root)
        )
        if not memories:
            _log(f"skip: no relevant memories for {agent}")
            return ""
        emitter = (
            emit_injection_receipt
            if isinstance(conn, SqliteBriefingConnection)
            else emit_hook_receipt
        )
        target = conn.store if isinstance(conn, SqliteBriefingConnection) else conn
        receipt_id = emitter(
            target,
            [{"memory_id": m["id"]} for m in memories],
            channel="agent_briefing",
            session_id=session_id_from_transcript(event.get("transcript_path"))
            or event.get("session_id"),
        )
    except Exception as exc:  # noqa: BLE001 — hook boundary; visible degradation
        _log(f"skip: briefing query failed: {exc}")
        return ""
    finally:
        conn.close()
    _log(f"briefed {agent} with {len(memories)} memories")
    return _render_briefing(agent, memories, receipt_id, keywords is None)


def _render_briefing(agent, memories, receipt_id, role_only=False):
    """The bounded ADR-0481 banner shared by both hosts."""
    header = f"## Cortex Briefing ({agent})"
    if receipt_id is not None:
        header += f" {receipt_marker(receipt_id)}"
    lines = [header + "\n"]
    if role_only:
        lines.append("Role and project context; the host did not expose the task.\n")
    for m in memories:
        source = m.get("source", "")
        prefix = f"[{source}] " if source else ""
        first_line = m["content"].split("\n")[0][:200]
        lines.append(f"- {prefix}{first_line}")
    lines.append("\n*Auto-injected by Cortex. Use `recall` for deeper context.*")
    return "\n".join(lines)


def process_event(event: dict[str, Any]) -> None:
    """Brief native spawn tasks, native project starts, or legacy specialists."""
    request = _request(event)
    if request is not None:
        agent, keywords, native = request
        text = _briefing(event, agent, keywords)
        if text:
            if native:
                emit_native(event, text)
            else:
                print(text)
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

    if isinstance(event, dict):
        process_event(event)


if __name__ == "__main__":
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
