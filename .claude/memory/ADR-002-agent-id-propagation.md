# ADR-002: MEMORY_AGENT_ID Propagation at Agent Spawn Sites

**Status**: Accepted  
**Date**: 2026-04-25  
**Supersedes**: design document `MEMORY_AGENT_ID-wiring.md` (now implemented)

---

## Context

`tools/memory-tool.sh` records every memory operation in an audit log and
enforces ACL checks using the `MEMORY_AGENT_ID` environment variable. When
that variable is unset it falls back to `"unknown"`, making the audit trail
untrustworthy and causing ACL denials for any scope that does not list
`"unknown"` as an owner (see `memory/contract.md §7`).

---

## Decision

**Identity MUST be injected by the spawn site, not self-declared by the
subagent.** An agent cannot forge its own `MEMORY_AGENT_ID`; the invoker owns
the assignment.

---

## Invariant (binding on all agent-spawn scripts)

```
INVARIANT: export MEMORY_AGENT_ID="<slug>" immediately before exec'ing the
           agent process, where <slug> = basename of the agent definition
           file without the .md extension.
```

Corollary: when the orchestrator fans out work to a subagent, it MUST export
the subagent's slug, not its own — otherwise ACL for the subagent's scope
fails even for legitimate writes.

---

## Spawn sites inventory

| Script | Mechanism | Status after this ADR |
|---|---|---|
| `scripts/spawn-agent.sh` | `exec claude --append-system-prompt` | Fixed: `export MEMORY_AGENT_ID="$AGENT"` added before both `exec` branches |
| `tools/genius-invoker.sh` | Prints system prompt only; does not spawn claude | N/A |
| `tools/skill-runner.sh` | Prints skill procedure only; does not spawn claude | N/A |
| `tools/worktree-manager.sh` | `git` commands only; does not spawn claude | N/A |
| `hooks/session-start.sh` | Sets `MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-_user}"` inline | Verified correct |

---

## Regression contract

1. `scripts/test-spawn-agent.sh` must pass: includes assertion that
   `MEMORY_AGENT_ID=<slug>` reaches the shimmed `claude` process.
2. `scripts/test-agent-id-propagation.sh` must pass all 7 assertions across
   three call paths (team agent, genius agent, orchestrator-fan-out).
3. `scripts/test-memory-e2e.sh` must pass 10/10 (backend unchanged).
4. Any future script adding `exec claude` or `claude -p` MUST add
   `export MEMORY_AGENT_ID="$AGENT_SLUG"` immediately before the call and
   add a corresponding assertion to `test-agent-id-propagation.sh`.

---

## Detection of non-compliance

`memory-tool.sh audit` surfaces entries with `agent=unknown`. Any such entry
after this ADR is a spawn site that was added without following the invariant.
Run `grep -R "exec claude\|claude -p" tools/ scripts/ hooks/ commands/` and
verify every hit has a preceding `export MEMORY_AGENT_ID=` or `env
MEMORY_AGENT_ID=` assignment.
