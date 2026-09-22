---
created: 2026-09-22
kind: adr
number: 1085
status: accepted
tags: [codex, hooks, briefing]
title: Codex task and project briefings
---
# ADR-1085: Codex task and project briefings

## Evidence

The Codex hooks reference (https://developers.openai.com/codex/hooks,
read 2026-09-22) documents `spawn_agent` as a local function tool matching
`Agent`. Its PreToolUse arguments include the task message; `updatedInput`
with `permissionDecision: allow` replaces the entire arguments object.
SubagentStart includes `agent_type`, but no task prompt. Reproducing the
existing hook with `agent_type: worker` yields no context: the Claude
specialist roster rejects that role, and the missing prompt also exits.

## Decision

Brief each spawn from its own exact message in PreToolUse. Preserve every
argument and append delimited context to the message; never reconstruct a
task from the parent transcript or shared mutable state. Native roles do
not use the Claude specialist roster. Promptless native starts receive
project/global team decisions first, then scoped role priors within the existing
three-memory budget, through additionalContext. Label these as role/project
context because the host did not expose a task. Keep the
legacy specialist/prompt path.

Retain ADR-0481/ADR-0484's keyword extraction, two query passes, heat order,
and content budgets. Preserve ADR-1083's project scope, current-row and
nonbenchmark predicates before limiting. SQLite uses its existing FTS5
index and heat_base convention; PostgreSQL keeps effective_heat and English
FTS. Backend selection honors the saved backend and explicit environment.
Both backends record receipts containing exactly the injected memory IDs.

## Verification

The native-start and spawn-preservation regression tests fail against
4400d7ab and exercise the new paths. Backend tests cover project isolation,
current rows, benchmarks, global decisions, FTS quoting and receipts.
Native Codex child delivery remains a separate host verification gate.

## Native collaboration boundary

A Codex CLI 0.154.0 capture on 2026-09-22 showed the orchestration tool as
`collaborationspawn_agent`, with an encrypted `message` in PreToolUse.
The corresponding child's NEW_TASK was appended after SubagentStart and
also carried encrypted content. Reading that child's transcript therefore
cannot recover a task for the start hook. Preserve the opaque call unchanged;
do not inspect sibling or parent transcripts to guess its task.
The plaintext `spawn_agent`/`Agent` path remains supported independently.
Role priors use the existing heat order and role/project visibility. Team
decisions take priority because their project applicability is explicit;
remaining budget goes to non-team role memories, avoiding duplicates.

## Configured database identity

Raw briefing connections use the shared settings precedence at call time:
`DATABASE_URL`, then `get_memory_settings().DATABASE_URL` (including
`CORTEX_MEMORY_DATABASE_URL`). The wheel hook entry point promotes the
namespaced URL when the canonical URL is absent, before installing a local
default. Import-time URL capture and a default that masks an explicit alias
can redirect hook reads to a different store than the configured MCP server.
Regression tests use mocked connections to prove destination selection without
contacting a production database.
