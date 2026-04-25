# ADR-0049 — Cortex stays local on main; server-side Cortex deferred to `feat/server-side-cortex`

**Status:** Accepted
**Date:** 2026-04-25
**Decision-makers:** cdeust
**Related:** ADR-0048 (Zetetic memory bridge), Anthropic `memory_20250818` contract

## Context

`zetetic-team-subagents` now ships a local replica of the Anthropic `memory_20250818` managed-agent memory tool with scope-based ACL, async Cortex replica queue, native MCP server, and PII scrubbing. Cortex bridges into this system via `mcp_server/hooks/agent_briefing.py` and the `agent_topic`→`agent_context` mapping.

A migration to Claude.ai Managed Agents (Anthropic-hosted) was considered. Honest readiness audit (this session, 2026-04-25):

| Layer | Migration verdict |
|---|---|
| `memory_20250818` contract conformance | Transfers — already Anthropic's contract |
| Agent bodies (system prompts, methodology) | Transfers — text is text |
| Scope concept | Transfers — maps to Anthropic memory stores |
| `memory-tool.sh` + `memory-mcp-server.py` | Becomes dead code in managed-agents land — Anthropic runs the backend |
| Local hooks (pre-commit, secret-shield, session-start) | Dev-loop only; out of scope for runtime migration |
| `MEMORY_AGENT_ID` env var ACL | Doesn't apply — managed agents enforce via memory store assignment |
| `.pending-sync` queue + `/session:memory-sync` drainer | Irrelevant — Anthropic stores natively |
| **Cortex MCP server (PostgreSQL + pgvector)** | **Local-only. Choice: drop, or deploy publicly as HTTP MCP.** |

The Cortex deploy/drop choice is the biggest fork. Deploying publicly requires auth, scaling, ops cost, and a security model for cross-tenant memory isolation. Dropping forfeits thermodynamic memory, methodology profiles, and cognitive-style enrichment.

## Decision

**Cortex stays local on `main`.** No public deployment. No HTTP MCP exposure. The PostgreSQL + pgvector stack continues to run on the developer's machine, embedded into Claude Code via `~/.claude/methodology/` and the local MCP stdio interface.

**A separate branch `feat/server-side-cortex` is created** as the placeholder for any future server-side work. It carries no commits yet — the slot exists so that when (and if) public deployment is greenlit, the work lands there without contaminating `main`.

When the Claude.ai Managed Agents migration is executed, the migration code path will:

- Use Anthropic memory stores as the persistence layer
- Drop the Cortex bridge (no `agent_topic` → `agent_context` mapping in managed-agents flow)
- Lose: thermodynamic memory, heat decay, methodology profile pre-loading, cognitive-style calibration at session start, cross-domain bridges, neural graph visualization
- Gain: zero ops burden, Anthropic-hosted durability, native semantic recall via Anthropic's index

## Alternatives Considered

1. **Deploy Cortex publicly as HTTP MCP** — rejected for now: ops cost and tenant-isolation security model not yet justified by usage signal.
2. **Drop Cortex entirely** — rejected: methodology profiles + thermodynamic memory are load-bearing for the local Claude Code workflow; removing them on `main` regresses present capability.
3. **Hybrid (local Cortex for Claude Code, no Cortex for Claude.ai)** — accepted: this is the current decision. Two code paths, one with Cortex (local Claude Code), one without (Claude.ai migration when executed).

## Consequences

### Positive
- `main` keeps the full Cortex methodology layer for local Claude Code users
- No premature ops investment in Cortex deployment
- Clear branch separation if/when server-side Cortex is greenlit

### Negative
- Claude.ai Managed Agents migration (when executed) will not have Cortex enrichment. Memory recall on Claude.ai will be Anthropic-native only.
- Two code paths must be maintained if both Claude Code (local Cortex) and Claude.ai (no Cortex) are supported simultaneously.

### Migration code-path implications

When the migration script (`scripts/migrate-to-managed-agents.py`) is built, it MUST:

1. Read agent `.md` files (frontmatter + body) and POST to Anthropic's Managed Agents API
2. Map `scope-registry.json` entries to Anthropic memory store creation
3. **Skip the Cortex bridge entirely** — no `agent_topic` parameter, no replica queue, no `/session:memory-sync` drainer
4. **Skip `MEMORY_AGENT_ID` propagation** — managed agents identify via session config + store ACL
5. Move PII scrubbing client-side as a preflight on `messages.create` calls

## Hand-off

When the user decides to deploy Cortex server-side:

```bash
git checkout feat/server-side-cortex
# Implement HTTP MCP transport, multi-tenant store, auth, deployment infra
```

Until then, the branch is a placeholder; `main` is canonical.
