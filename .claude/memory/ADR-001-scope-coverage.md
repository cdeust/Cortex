# ADR-001: Memory Scope Coverage and Polycentric Governance

## Status
Accepted — 2026-04-24

## Context

The Ostrom audit of `memory/scope-registry.json` v1 returned the verdict:
**"convention relying on agent politeness, not a polycentric commons."**

Concrete defects flagged:

1. **Coverage gap.** 19 team agents and 97 genius agents — 116 total — but only 3 named per-agent scopes (`engineer`, `architect`, `research`). The other 114 agents had no home scope, so any write fell back to `defaults` (owners=`["_user"]`) which they cannot write. In practice agents wrote wherever they liked because `strict_unknown_scope: false` permitted it.
2. **Curator unwired.** The registry referenced `_curator` but the `curator_agents` list contained only `["_user"]`. The `_curator` token resolved to nothing. `lessons` (owners `_user` + `_curator`) was therefore write-dead for any agent.
3. **Permissive mode.** `strict_unknown_scope: false` meant unknown-scope writes silently succeeded against `defaults`, defeating the ACL.

A commons without enforced boundaries (Ostrom design principle 1) and without a credible monitor (principle 4) is not a commons. It is a tragedy waiting for a contributor.

## Decision

Adopt a **per-team-scope + shared-genius-scope** split, wire the curator, and turn on strict mode.

### 1. Per-team-agent scopes (1:1)
Every team agent under `agents/*.md` (excluding `genius/`) owns exactly one named scope whose key matches the agent slug. Owners list is `[<slug>, "_user"]`. Readers are `["*"]` (cross-team learning is desirable; cross-team writes are not).

Exception: `research-scientist` and `experiment-runner` continue to share the `research` scope. Both are research-pipeline agents whose memories are co-authored hypotheses and experiment logs; splitting them would force constant cross-scope reads.

`orchestrator` gets its own scope **and** is added to `curator_agents`. The dual role is documented in the scope description.

### 2. Single shared `genius` scope (1:98)
All 97 genius agents share one scope. Per-agent isolation is enforced by **subpath convention**, not ACL:
- Each genius MUST write under `/memories/genius/<agent-slug>/`.
- Reads across subpaths are permitted by design — cross-pollination is the entire point of the genius pool (Lamport reading Ostrom reading Taleb).
- TTL 60 days, `max_file_kb` 100, owners `["*"]`, readers `["*"]`.

### 3. Curator wired
`curator_agents: ["_user", "orchestrator"]`. The `_curator` token in any `owners` or `readers` list now resolves to this set. `lessons` and `global` become writable under curator review without the user being in the loop on every entry.

### 4. Strict mode
`strict_unknown_scope: true`. Any write to an unregistered scope fails loudly. Combined with 100% agent coverage, this closes the silent-fallback hole.

## Alternatives considered

### (a) One scope per genius agent (98 scopes)
**Rejected.** 97 scopes plus 17 team scopes plus 6 systemic = 120 entries. Registry becomes unreadable. Genius agents are designed for cross-pollination — siloing them by ACL would defeat the design. The subpath convention gives the same isolation at 1/97 the registry cost.

### (b) Pure defaults-fallback (no per-agent scopes)
**Rejected.** Defeats the ACL entirely. If every agent writes to `defaults` (owners=`["_user"]`), either (i) writes fail because no agent owns defaults, or (ii) defaults gets opened to `["*"]` and the registry collapses to a free-for-all. Either outcome is worse than v1.

### (c) Per-team scopes + per-genius scopes via wildcard pattern (e.g. `genius:*`)
**Rejected.** Adds registry-loader complexity (pattern matching) for a benefit (per-agent ACL isolation) that the genius pool does not actually want. Cross-pollination is a feature, not a bug.

### (d) Keep `strict_unknown_scope: false` until coverage is "really really" complete
**Rejected.** Permissive mode is the tragedy-of-the-commons enabler. Strict mode is the only forcing function that surfaces missed agents. Roll out strict mode the same day coverage hits 100%, not later.

## Consequences

### Positive
- Every agent has a named home scope. Quota and audit trail attach to the slug.
- `lessons` is writable (under curator review) — corrections from sessions can flow into durable rules.
- `strict_unknown_scope: true` makes unknown-scope writes a loud error, catching agent mis-configuration immediately.
- Genius-pool subpath convention preserves cross-pollination while giving per-genius audit boundaries.

### Negative
- **Agent slugs MUST match scope keys exactly.** Renaming an agent now requires a registry migration. Mitigation: agent rename is a refactorer-driven operation that already touches the frontmatter; add scope-registry as part of the checklist.
- **Adding a new team agent requires a registry entry.** Without one, strict mode rejects all its writes. Mitigation: documented in `memory/scope-coverage.md` and in the new-agent template.
- **Genius-pool subpath convention is enforced in description text, not in code.** A misbehaving genius could write outside its subpath. Mitigation: the `memory-tool.sh` validator (Lamport's territory) can be extended to enforce the convention if observed violations exceed threshold; add to backlog.

### Risks
1. **Slug drift.** If an agent's frontmatter `name:` diverges from its filename slug, the wrong scope gets matched. Mitigation: refactorer audit pass.
2. **Curator concentration.** `orchestrator` is now a curator. If orchestrator is compromised or buggy, `lessons` and `global` are at risk. Mitigation: audit log on every write to those scopes; quarterly review.
3. **Genius cross-writes.** Subpath convention is honor-system. Mitigation per "Negative" above.

## Reversibility
**Type-1 (one-way door)** for the strict-mode flip — once agents adapt to strict mode and start failing loudly on misconfig, reverting to permissive would silently re-enable the v1 hole. The other parts (per-team scopes, genius shared scope, curator wiring) are Type-2 (registry edit, no data migration).

## Rollout

1. Land registry v2 (this ADR's companion file).
2. Land `memory/scope-coverage.md` mapping every agent to its scope.
3. Refactorer pass to set `memory_scope:` frontmatter on each agent.
4. Verify 100% agent coverage by spawning each agent in a smoke test and checking the audit log for own-scope writes.
5. **Only after step 4 passes**, the `strict_unknown_scope: true` flip is observed in production. (Registry already ships with `true` — step 4 is the verification gate before relying on it.)
6. Monitor `.audit.log` for one week; any `denied_unknown_scope` entries trigger an immediate registry patch.

## Sources

- Ostrom, E. (1990). *Governing the Commons.* Cambridge University Press. (Design principles 1, 2, 4 are the load-bearing references for this ADR.)
- Conway, M. (1968). "How Do Committees Invent?" *Datamation* 14(5). (Inverse Conway: scope topology should mirror agent topology.)
- `memory/contract.md` §5 (substitutability), §7 (security invariants).
