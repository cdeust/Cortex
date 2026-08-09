#!/usr/bin/env python3
"""Claude Code SubagentStart hook — automatic agent briefing.

When the orchestrator or any parent agent spawns a subagent, this hook
retrieves relevant memories for the spawned agent's task context.

NOTE: SubagentStart hook context injection behavior is not fully documented
in Claude Code. If exit 0 stdout is injected (like SessionStart), the
briefing appears in the agent's context. If not, this hook still warms
related memories via access timestamps, improving subsequent recall.
Needs validation against Claude Code source.

Paper backing:
  - Smith & Vela 2001 "Environmental context-dependent memory" (meta-analysis):
    context reinstatement at retrieval produces reliable memory benefit
    (d=0.28, ~15-20% boost). Injecting task-relevant memories at agent
    start implements context reinstatement.
  - Wegner 1987 Transactive Memory Systems: directory knowledge — each
    agent knows what the team knows. The briefing injects team decisions
    plus agent-scoped prior work.
  - Collins & Loftus 1975: spreading activation — task description
    activates related memory nodes.

Source backing:
  - Claude Code agent-system (lesson 05): agents start with "a separate
    LLM turn with its own tool pool, system prompt, model." Our briefing
    augments that system prompt with memory context.
  - Claude Code coordinator-mode (lesson 21): "Never delegate understanding.
    Include file paths, line numbers, what specifically to change." Our
    briefing automates this by recalling past context for the task.
  - Zetetic team agents (cdeust/zetetic-team-subagents): orchestrator.md
    already documents manual briefing via recall/get_causal_chain. This
    hook automates that pattern.

Strategy:
  Extracts the task description from the agent prompt, runs a lightweight
  PG recall (FTS + heat, no embedding to avoid latency), and injects
  matching memories as a context prefix.

  Gated by:
    - Agent type must be a known, usable specialist (engineer, tester, etc.)
    - Task description must be non-empty
    - At least 1 relevant memory found
    - Max 3 memories injected (keep context compact)

Module split (issue #401, 300-line cap): keyword extraction lives in
``agent_briefing_keywords.py``, the PG connect + query in
``agent_briefing_query.py`` (both re-exported via ``__all__``). Event
gating and the specialist-roster loader stay here — the latter reads the
``CLAUDE_DIR`` attribute the test suite monkeypatches on this module.

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "SubagentStart": [{
                "type": "command",
                "command": "python3 -m mcp_server.hooks.agent_briefing",
                "timeout": 5
            }]
        }
    }

Note: SubagentStart is available in Claude Code. The hook receives:
{
    "session_id": "...",
    "agent_name": "engineer",
    "agent_type": "custom",
    "prompt": "Fix the reranker score normalization...",
    "cwd": "/path/to/project"
}

Invariants
----------
- Exit 0: stdout injected into agent's context
- Exit 1: skip (no relevant context)
- Must complete within 5s
- Logs to stderr only
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from mcp_server.handlers.injection_receipts import (
    emit_hook_receipt,
    receipt_marker,
    session_id_from_transcript,
)
from mcp_server.hooks.agent_briefing_keywords import _extract_task_keywords
from mcp_server.hooks.agent_briefing_log import _log
from mcp_server.hooks.agent_briefing_query import (
    _DATABASE_URL,
    _MAX_MEMORIES,
    _MIN_HEAT,
    _connect,
    _fetch_agent_context,
)
from mcp_server.infrastructure.config import CLAUDE_DIR

__all__ = [
    "_DATABASE_URL",
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

# Reserved meta-agent names: agents whose declared job is to ROUTE work to
# other agents rather than perform it, so a roster reduced to only them is
# not a specialist set a briefing can scope memories to (treated as empty).
#
# A convention of the *consumer* environment, not a fact about this repo —
# `dispatch.md` lives under the reader's own ~/.claude/agents/, not in this
# repository, so no path/commit/digest here would be independently
# verifiable. What IS verifiable and pinned by tests: agent_briefing falls
# back when the discovered roster reduces to a router (see
# test_agents_dir_with_only_dispatch_falls_back_to_builtin_set and the
# end-to-end reproduction in test_hook_receipts.py). A reader without that
# setup loses nothing — the name is filtered only when present, and logged.
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

    Root is CLAUDE_DIR (default ~/.claude, overridable via CORTEX_CLAUDE_DIR
    — mcp_server/infrastructure/config.py), the project's test-isolation
    seam (issue #219). Each zetetic agent declares `memory_scope:` in
    frontmatter, equal to the `agent_context` used in Cortex memory rows —
    the briefing hook filters recall by it once agent_topic is set.
    """
    root = CLAUDE_DIR / "agents"
    names: set[str] = set()
    if root.is_dir():
        for pattern in ("*.md", "genius/*.md"):
            for md in root.glob(pattern):
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

# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_PROMPT_CHARS = 20


def process_event(event: dict[str, Any]) -> None:
    """Process SubagentStart event and inject briefing context."""
    agent_name = (event.get("agent_name") or "").lower()
    prompt = event.get("prompt", "")

    if agent_name not in _SPECIALIST_AGENTS:
        _log(f"skip: agent '{agent_name}' not a specialist")
        sys.exit(0)

    if not prompt or len(prompt) < _MIN_PROMPT_CHARS:
        _log("skip: prompt too short")
        sys.exit(0)

    keywords = _extract_task_keywords(prompt)
    if not keywords:
        _log("skip: no keywords extracted")
        sys.exit(0)

    conn = _connect()
    if conn is None:
        _log("skip: PostgreSQL unavailable")
        sys.exit(0)

    try:
        memories = _fetch_agent_context(conn, agent_name, keywords)
        if not memories:
            _log(f"skip: no relevant memories for {agent_name}")
            sys.exit(0)

        # Receipt for exactly the memories entering the agent's context
        # (blame path T2, decision 4255039 correction 3 — SubagentStart
        # is the fourth injecting channel). Emitted before rendering so
        # the header can carry the ⟦rcpt:id⟧ marker (correction 2); a
        # failed write degrades to a marker-less briefing.
        receipt_id = emit_hook_receipt(
            conn,
            [{"memory_id": m["id"]} for m in memories],
            channel="agent_briefing",
            session_id=session_id_from_transcript(event.get("transcript_path")),
        )
    finally:
        conn.close()

    # Build injection
    header = f"## Cortex Briefing ({agent_name})"
    if receipt_id is not None:
        header += f" {receipt_marker(receipt_id)}"
    lines = [header + "\n"]
    for m in memories:
        source = m.get("source", "")
        prefix = f"[{source}] " if source else ""
        first_line = m["content"].split("\n")[0][:200]
        lines.append(f"- {prefix}{first_line}")
    lines.append("\n*Auto-injected by Cortex. Use `recall` for deeper context.*")

    print("\n".join(lines))
    _log(f"briefed {agent_name} with {len(memories)} memories")
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
