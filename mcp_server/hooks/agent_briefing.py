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
    - Agent type must be a known specialist (engineer, tester, etc.)
    - Task description must be non-empty
    - At least 1 relevant memory found
    - Max 3 memories injected (keep context compact)

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
import os
import re
import sys
from pathlib import Path
from typing import Any

_LOG_PREFIX = "[cortex-agent-briefing]"
_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
_MAX_MEMORIES = 3
_MIN_HEAT = 0.2

# Fallback set used when ~/.claude/agents/ is missing (e.g., CI without install).
_FALLBACK_AGENTS: frozenset[str] = frozenset({
    "engineer", "tester", "reviewer", "architect", "dba", "devops",
    "frontend", "security", "researcher", "ux",
})

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
    `name:` frontmatter field of each, and returns the frozen set. Falls back
    to _FALLBACK_AGENTS if the directory is absent. Result is cached for the
    process lifetime — agents added after import are not picked up until
    restart (acceptable for a hook process).

    Each zetetic agent declares `memory_scope:` in frontmatter; that scope
    equals the name used as `agent_context` in Cortex memory rows. When the
    /session:memory-sync drainer sets `agent_topic=<scope>`, the briefing
    hook can filter by `agent_context = %s` and inject the right memories.
    """
    root = Path.home() / ".claude" / "agents"
    if not root.is_dir():
        return _FALLBACK_AGENTS
    names: set[str] = set()
    for pattern in ("*.md", "genius/*.md"):
        for md in root.glob(pattern):
            if md.name == "INDEX.md":
                continue
            name = _parse_frontmatter_name(md)
            if name:
                names.add(name)
    return frozenset(names) if names else _FALLBACK_AGENTS


# Known specialist agents that benefit from briefing — dynamic load from
# ~/.claude/agents/ (116+ zetetic agents when installed).
_SPECIALIST_AGENTS = _load_specialist_agents()


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _extract_task_keywords(prompt: str) -> list[str]:
    """Extract key terms from the agent prompt for FTS query.

    Takes the first 500 chars of the prompt and extracts words
    longer than 3 chars, excluding common stop words.
    """
    stops = {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "your",
        "have",
        "will",
        "been",
        "they",
        "what",
        "when",
        "where",
        "which",
        "there",
        "their",
        "about",
        "would",
        "could",
        "should",
        "into",
        "more",
        "some",
        "than",
        "them",
        "then",
        "these",
        "those",
        "each",
        "make",
        "like",
        "just",
        "over",
        "such",
        "take",
        "also",
        "back",
        "after",
        "only",
        "come",
        "made",
        "find",
        "here",
        "thing",
        "many",
        "well",
        "work",
        "need",
        "using",
        "used",
        "code",
        "file",
        "please",
        "ensure",
    }
    words = prompt[:500].lower().split()
    keywords = [
        w.strip(".,;:!?\"'()[]{}")
        for w in words
        if len(w) > 3 and w.lower().strip(".,;:!?\"'()[]{}") not in stops
    ]
    # Return unique keywords, max 8
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen and k:
            seen.add(k)
            unique.append(k)
    return unique[:8]


def _fetch_agent_context(agent_name: str, keywords: list[str]) -> list[dict]:
    """Fetch relevant memories for agent briefing.

    Two-pass query:
    1. Agent-scoped memories (agent_context matches) — prior work by this specialist
    2. Team decisions (is_protected + is_global) — cross-agent knowledge (TMS directory)

    Uses FTS plainto_tsquery for speed (no embedding model needed).
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

    # Pass 1: Agent-scoped memories matching keywords
    if keywords:
        try:
            rows = conn.execute(
                """
                SELECT id, content, heat, agent_context
                FROM memories
                WHERE agent_context = %s
                  AND heat >= %s
                  AND NOT is_benchmark
                  AND content_tsv @@ plainto_tsquery('english', %s)
                ORDER BY heat DESC
                LIMIT %s
                """,
                (agent_name, _MIN_HEAT, " ".join(keywords[:5]), _MAX_MEMORIES),
            ).fetchall()
            for r in rows:
                results.append(
                    {
                        "content": r.get("content", "")[:300],
                        "heat": r.get("heat", 0),
                        "source": "agent-prior",
                    }
                )
        except Exception as exc:
            _log(f"agent-scoped query failed: {exc}")

    # Pass 2: Team decisions (protected + global)
    remaining = _MAX_MEMORIES - len(results)
    if remaining > 0:
        try:
            rows = conn.execute(
                """
                SELECT id, content, heat, agent_context
                FROM memories
                WHERE is_protected = TRUE
                  AND is_global = TRUE
                  AND agent_context != %s
                  AND NOT is_benchmark
                ORDER BY heat DESC
                LIMIT %s
                """,
                (agent_name, remaining),
            ).fetchall()
            for r in rows:
                results.append(
                    {
                        "content": r.get("content", "")[:300],
                        "heat": r.get("heat", 0),
                        "source": f"team:{r.get('agent_context', '')}",
                    }
                )
        except Exception as exc:
            _log(f"team decisions query failed: {exc}")

    conn.close()
    return results


def process_event(event: dict[str, Any]) -> None:
    """Process SubagentStart event and inject briefing context."""
    agent_name = (event.get("agent_name") or "").lower()
    prompt = event.get("prompt", "")

    if agent_name not in _SPECIALIST_AGENTS:
        _log(f"skip: agent '{agent_name}' not a specialist")
        sys.exit(0)

    if not prompt or len(prompt) < 20:
        _log("skip: prompt too short")
        sys.exit(0)

    keywords = _extract_task_keywords(prompt)
    if not keywords:
        _log("skip: no keywords extracted")
        sys.exit(0)

    memories = _fetch_agent_context(agent_name, keywords)
    if not memories:
        _log(f"skip: no relevant memories for {agent_name}")
        sys.exit(0)

    # Build injection
    lines = [f"## Cortex Briefing ({agent_name})\n"]
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
    main()
