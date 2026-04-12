---
name: architecture-review
description: >
  Holistic architecture review that goes beyond code diffs. Analyzes dependency structure,
  layer integrity, scaling characteristics, failure modes, pattern correctness, viable
  system completeness, boundary optimization, and technical debt accumulation. Findings
  ranked by structural impact.
category: architecture
trigger: >
  When a system has grown without architectural review; when "does this still make sense?"
  needs an honest answer; when scaling problems, coupling pain, or mysterious failures
  suggest structural issues; when preparing for a major feature or migration.
agents:
  - alexander
  - thompson
  - erlang
  - hamilton
  - maxwell
  - coase
  - simon
  - beer
  - dijkstra
  - feynman
  - meadows
shapes: [defensive-by-default, graceful-degradation, spec-first]
input: Codebase path. Architecture documentation (if any). Known pain points. Scale targets.
output: Architecture Assessment with findings ranked by structural impact.
zetetic_gate:
  logical: "Every finding traces to a specific code artifact — no vague 'it feels wrong'"
  critical: "Findings are verified against actual code, not assumed from diagrams"
  rational: "Recommendations are proportional to impact — do not prescribe a rewrite for a minor issue"
  essential: "Focus on structural issues that compound over time, not cosmetic complaints"
composes: [decompose, spec, contract]
aliases: [arch-review, system-review, architecture-audit]
hand_off:
  boundary_wrong: "/decompose — redesign module boundaries"
  spec_missing: "/spec — write the missing specification"
  failure_mode_found: "/design-for-failure — harden the identified failure path"
  debt_critical: "/adr — document the debt and the plan to address it"
---

## Procedure

### Phase 1: Dependency Structure (coase + dijkstra)

1. **dijkstra: map all dependencies.** Module-level dependency graph. Identify cycles,
   fan-out/fan-in hot spots, and orphan modules (dead code candidates).
2. **coase: boundary analysis.** For each boundary: is the transaction cost of crossing it
   justified? Missing boundaries where coupling is too tight?

### Phase 2: Layer Integrity (dijkstra)

3. **dijkstra: verify layer discipline.** Map the codebase to its declared architecture.
   Check: dependency rule violations, domain-to-infrastructure shortcuts, bypassed layers.
4. **Catalog violations.** Each violation: source file, target file, rule broken, severity.

### Phase 3: Scaling Characteristics (thompson + erlang)

5. **thompson: 10x analysis.** For each subsystem: what breaks at 10x load? Consider data
   volume, request rate, and team-size contention.
6. **erlang: queuing analysis.** Identify queues (explicit and implicit). For each: arrival
   rate, service rate, utilization. Where does utilization approach 1.0?

### Phase 4: Failure Modes (hamilton + maxwell)

7. **hamilton: priority under failure.** When degraded, what still works? Is there a
   criticality taxonomy? Are error paths tested or aspirational?
8. **maxwell: feedback stability.** Identify feedback loops (retries, cache invalidation,
   auto-scaling, circuit breakers). Do they have backoff? Can they cascade or oscillate?
9. **Failure cascade analysis.** If component X fails, what else fails? Blast radius? Isolation?

### Phase 5: Pattern Assessment (alexander + feynman)

10. **alexander: pattern language audit.** Which patterns are in use? For each: right context?
    Correctly applied (forces resolved, not just structure copied)? Missing patterns?
11. **feynman: cargo-cult detection.** Patterns applied without understanding: microservices
    where a monolith suffices, event sourcing without replay, CQRS without separate read
    models, DI frameworks where constructor injection suffices, abstractions with exactly
    one implementation and no test doubles.

### Phase 6: Viable System Check (beer)

12. **beer: VSM analysis.** Does the system have all five viable system functions?
    S1 (Operations), S2 (Coordination), S3 (Optimization), S4 (Intelligence), S5 (Policy).
13. **Missing functions.** Which are absent or vestigial? Consequences of each gap?

### Phase 7: Boundary Optimization (coase + simon)

14. **simon: near-decomposability.** Are the module boundaries aligned with natural
    clusters of high internal interaction and low external interaction? Or do they
    cut across natural boundaries, forcing excessive cross-module communication?
15. **coase: transaction cost optimization.** For each proposed boundary change:
    what is the cost of the current boundary (coupling, coordination overhead)?
    What would be the cost of the alternative? Is the change worth the migration cost?

### Phase 8: Technical Debt Assessment (meadows)

16. **meadows: system archetype identification.** What system dynamics are at play?
    - "Shifting the burden": are workarounds preventing root-cause fixes?
    - "Fixes that fail": are quick fixes creating new problems?
    - "Eroding goals": are quality standards being lowered to meet deadlines?
    - "Success to the successful": are popular modules getting all investment while others rot?
17. **Debt classification.** For each debt item: structural (wrong abstraction) vs.
    incidental (shortcuts under time pressure). Structural debt compounds; incidental
    debt is linear.

## Output Format

```
## Architecture Assessment: [system name]
### Date: [date] | Scope: [what was reviewed]
### Architecture style: [declared] | Actual: [observed]

### Findings:

#### Critical (structural, compounding, blocks scaling or reliability):
| # | Area | Finding | Evidence | Recommendation |
|---|------|---------|----------|----------------|

#### Major (significant impact, should be addressed in next cycle):
| # | Area | Finding | Evidence | Recommendation |
|---|------|---------|----------|----------------|

#### Minor (low impact, address opportunistically):
| # | Area | Finding | Evidence | Recommendation |
|---|------|---------|----------|----------------|

#### Observations (informational, no action required):
| # | Area | Finding |
|---|------|---------|

### VSM Status:
| Function | Status | Notes |
|----------|--------|-------|
| S1 Operations | [present/partial/absent] | |
| S2 Coordination | [present/partial/absent] | |
| S3 Optimization | [present/partial/absent] | |
| S4 Intelligence | [present/partial/absent] | |
| S5 Policy | [present/partial/absent] | |

### Scaling Bottlenecks (10x analysis):
| Subsystem | Breaks at | Reason | Mitigation |
|-----------|-----------|--------|------------|

### Technical Debt Summary:
| Category | Items | Compounding? | Priority |
|----------|-------|-------------|----------|
| Structural | | Yes | |
| Incidental | | No | |
```
