---
name: migrate-system
description: >
  System migration planning: assess risk (Hamilton), audit reversibility (Carnot),
  weigh transaction costs (Coase), and execute via incremental PDSA cycles (Deming).
category: compose
trigger: >
  When moving from one system to another (database, platform, API, infrastructure);
  when a migration has been attempted without a rollback plan; when the cost of
  migrating vs staying has not been quantified.
agents:
  - hamilton
  - carnot
  - coase
  - deming
  - lavoisier
shapes: [criticality-tiers, reversibility-audit, transaction-cost, pdsa-cycle]
input: Current system, target system, motivation for migration, and constraints.
output: Migration plan with risk tiers, irreversible steps, rollback points, and incremental cutover schedule.
zetetic_gate:
  logical: "Every migration step must have a defined pre-condition and post-condition"
  critical: "Irreversible steps identified by two independent methods; data conservation verified"
  rational: "Transaction cost of migrating must exceed cost of staying — quantify both"
  essential: "Plan the smallest migration that delivers the stated motivation"
composes: [failure-resilient-design, verify-claim]
aliases: [migration-plan, system-migration, cutover-plan]
hand_off:
  cost_unclear: "/estimate — fermi bounds migration cost vs maintenance cost"
  risk_too_high: "/failure-resilient-design — redesign for safer incremental cutover"
  data_conservation_fails: "/verify-claim — check that no data is lost across the boundary"
---

## Procedure

### Phase 1: Assess Current State (hamilton, coase)
1. hamilton: enumerate what can fail. Classify components into criticality tiers (critical / important / cosmetic).
2. coase: quantify the transaction cost of the current system (maintenance burden, opportunity cost, technical debt interest).

### Phase 2: Define Target State and Audit Reversibility (carnot, coase)
3. coase: quantify the transaction cost of migration (engineering time, downtime, retraining, data transformation).
4. **Gate:** migration cost < maintenance cost over a defined horizon. If not, recommend staying.
5. carnot: reversibility audit. For each migration step, classify as reversible or irreversible.
6. **Gate:** every irreversible step must have explicit sign-off criteria and a point-of-no-return marker.

### Phase 3: Plan Incremental Cutover (deming, lavoisier)
7. deming: design PDSA cycles for incremental migration. Each cycle migrates one component or data subset.
8. lavoisier: verify data conservation at each cycle boundary — nothing created, nothing destroyed, everything accounted for.
9. Define rollback points after each reversible step. Define verification checks after each irreversible step.

### Phase 4: Execute with Monitoring
10. Execute cycle-by-cycle. Each cycle: Plan (pre-conditions) → Do (migrate) → Study (verify conservation) → Act (proceed or rollback).
11. **Gate:** no cycle proceeds until the previous cycle's conservation check passes.

## Output Format

```
## Migration Plan: [current system] → [target system]

### Motivation: [why migrate]
### Cost comparison:
| | Current system (stay) | Migration (move) |
|---|----------------------|-----------------|
| 12-month cost | [...] | [...] |

### Criticality tiers (hamilton):
| Tier | Components | Failure impact |
|------|-----------|---------------|

### Reversibility audit (carnot):
| Step | Reversible? | Rollback method | Point-of-no-return? |
|------|------------|----------------|-------------------|

### PDSA cutover schedule (deming):
| Cycle | Component | Plan | Do | Study | Act |
|-------|-----------|------|-----|-------|-----|

### Data conservation checks (lavoisier):
| Cycle | Input count | Output count | Delta | Status |
|-------|------------|-------------|-------|--------|
```
