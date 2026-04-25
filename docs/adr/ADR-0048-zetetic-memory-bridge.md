# ADR-0048: Zetetic memory_scope → Cortex agent_context bridge

**Date:** 2026-04-24
**Status:** Accepted
**Authors:** engineer (Claude Code)

---

## Context

Two systems were independently correct but structurally disconnected:

- **Zetetic** (`zetetic-team-subagents/commands/session/memory-sync.md`) drains
  the `~/.claude/memories/.pending-sync/` queue by calling `cortex:remember` with
  `tags=["memory-replica", "scope:<scope>", "agent:<agent_id>"]` — but it did NOT
  set `agent_topic`. As a result, `mcp_server/handlers/remember.py:351` wrote
  `agent_context=NULL` to every replicated memory row.

- **Cortex** (`mcp_server/hooks/agent_briefing.py:217`) filters memories with
  `WHERE agent_context = %s` at SubagentStart. With `agent_context=NULL` the
  filter matched nothing: agents received no prior-work briefings.

Additionally, `agent_briefing.py:90-101` hardcoded a 10-name `_SPECIALIST_AGENTS`
set, silently skipping all 116 zetetic agents not in that list.

---

## Decision

### 1. Drainer sets `agent_topic` (zetetic-team-subagents)

`commands/session/memory-sync.md` now instructs the agent to pass
`agent_topic: <scope>` (the job's `scope` field) on every `cortex:remember` call,
in addition to the existing `tags`.

- Code site: `zetetic-team-subagents/commands/session/memory-sync.md`, step 3
- Bridge: `scope` → `agent_topic` (MCP param) → `agent_context` (DB column,
  `Cortex/mcp_server/handlers/remember.py:351`)

### 2. Dynamic `_SPECIALIST_AGENTS` load (Cortex)

`mcp_server/hooks/agent_briefing.py` now calls `_load_specialist_agents()` at
module load time. It scans `~/.claude/agents/*.md` and
`~/.claude/agents/genius/*.md`, parses the `name:` YAML frontmatter field from
each file, and builds a `frozenset` from those names.

- Falls back to the original 10-name set if neither directory exists (CI compat).
- Cached for the process lifetime (load once; the file set rarely changes).
- Code site: `Cortex/mcp_server/hooks/agent_briefing.py`, `_load_specialist_agents()`

With agents installed, the set resolves to **122 names** (98 genius + 19 team
agents + 5 from frontmatter overlaps); all 116+ zetetic agents are covered.

---

## Consequences

- **Positive:** Cross-session memory continuity works for all zetetic agents.
  Prior-work memories stored via any agent are visible at SubagentStart for
  the same agent on the next spawn.
- **Positive:** No DB schema change required. `agent_context` column already
  existed (`Cortex/mcp_server/handlers/remember.py:351`,
  `agent_briefing.py:217`).
- **Positive:** Adding a new agent file in `~/.claude/agents/` automatically
  enrolls it without touching Python code (OCP satisfied).
- **Negative:** Module load scans the filesystem once per process start. For
  122 files this is < 10 ms; acceptable.

---

## Alternatives considered

**Cortex-side daemon polling memory-tool's pending-sync queue** — rejected.
This would duplicate the drainer mechanism already in zetetic, introduce
a second writer path, and add operational complexity (another process to
manage, monitor, and restart). The simpler fix — pass `agent_topic` in the
existing drainer call — achieves the same result with zero new infrastructure.

---

## Verification

```bash
# Dynamic load count
cd /Users/cdeust/Developments/Cortex
python3 -c "from mcp_server.hooks.agent_briefing import _SPECIALIST_AGENTS; print(len(_SPECIALIST_AGENTS))"
# Expected: 122

# Hook unit tests
python3 scripts/test-agent-briefing.py
# Expected: 2/2 PASS
```

---

## Primary sources

- Martin (2017) Clean Architecture §22: composition-root wiring.
- `Cortex/mcp_server/handlers/remember.py:351` — `agent_context=agent_topic` assignment.
- `Cortex/mcp_server/hooks/agent_briefing.py:217` — `WHERE agent_context = %s` filter.
- `zetetic-team-subagents/commands/session/memory-sync.md` — drainer instruction set.
