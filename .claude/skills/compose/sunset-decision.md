---
name: sunset-decision
description: >
  Decide whether to sunset a system, feature, or practice. Weigh transaction costs (Coase),
  question the metrics keeping it alive (Zhuangzi), name what is honestly lost (Le Guin),
  and debias for sunk cost (Kahneman).
category: compose
trigger: >
  When a system or feature is expensive to maintain but "still has users"; when nobody
  can articulate why it exists but nobody wants to kill it; when sunk cost or loss
  aversion may be distorting the decision.
agents:
  - coase
  - zhuangzi
  - leguin
  - kahneman
shapes: [transaction-cost, wrong-metric, honest-loss, sunk-cost-check]
input: The system/feature/practice under consideration, its maintenance cost, and its claimed justification.
output: Sunset recommendation with conditions, or a justified case for keeping it alive.
zetetic_gate:
  logical: "Maintenance costs and replacement costs must be enumerable, not vague"
  critical: "The metrics justifying its existence must be audited for validity"
  rational: "Decision must survive the sunk-cost and loss-aversion debiasing"
  essential: "Name what is honestly lost — do not pretend sunsetting is costless"
composes: [verify-claim, difficulty-book]
aliases: [sunset, deprecate, kill-decision, end-of-life]
hand_off:
  cost_unclear: "/estimate — fermi bounds the maintenance and replacement costs"
  metric_suspicious: "/cargo-cult-check — is the metric measuring the right thing?"
  replacement_needed: "/migrate-system — plan the migration to the replacement"
---

## Procedure

### Phase 1: Enumerate Costs (coase)
1. coase: quantify the ongoing transaction cost of maintaining the system (engineering hours, infrastructure, cognitive load, opportunity cost).
2. coase: quantify the transaction cost of sunsetting (migration, communication, replacement, user disruption).
3. **Gate:** costs must be specific numbers or ranges, not "it's expensive."

### Phase 2: Audit the Justifying Metrics (zhuangzi)
4. zhuangzi: what metric keeps this system alive? Is it the right metric?
5. zhuangzi: would the system survive if measured by a different, more honest metric?
6. **Gate:** if the metric is invalid, the justification collapses. Flag this explicitly.

### Phase 3: Name What Is Lost (leguin)
7. leguin: name what will be honestly lost if this is sunsetted. Not in euphemisms — in concrete terms.
8. leguin: who bears the cost of the loss? Is it the people making the decision or someone else?
9. **Gate:** losses must be acknowledged, not hidden behind "minimal impact" language.

### Phase 4: Debias (kahneman)
10. kahneman: sunk cost check — would you build this today, knowing what you know? If no, sunk cost is distorting.
11. kahneman: loss aversion check — is the pain of losing it larger than the gain of freeing the resources?
12. kahneman: status quo bias check — is "keep it" the default because change is uncomfortable?

### Phase 5: Recommend
13. Synthesize into a recommendation: sunset (with conditions and timeline) or keep (with justification and review date).

## Output Format

```
## Sunset Decision: [system/feature/practice]

### Maintenance cost (coase): [quantified]
### Sunset cost (coase): [quantified]

### Metric audit (zhuangzi):
Claimed justification: [...]
Metric validity: [valid / invalid / misleading]
Under honest metric: [survives / collapses]

### Honest losses (leguin):
| What is lost | Who bears it | Severity |
|-------------|-------------|----------|

### Bias check (kahneman):
| Bias | Present? | Evidence |
|------|---------|----------|
| Sunk cost | [yes/no] | [...] |
| Loss aversion | [yes/no] | [...] |
| Status quo | [yes/no] | [...] |

### Recommendation: [sunset with conditions / keep with review date]
### Conditions: [what must be true for this recommendation to hold]
```
