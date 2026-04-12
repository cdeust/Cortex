---
name: replication-assessment
description: >
  Assess replicability of a published result: check availability of code, data, and
  hyperparameters; attempt replication if feasible; grade replicability.
category: research
trigger: >
  When implementing a technique from a paper and the results seem too good; when a
  published result drives a critical decision and hasn't been independently confirmed;
  when "as reported in [paper]" is doing load-bearing work.
agents:
  - fisher
  - curie
  - ibnalhaytham
  - wu
shapes: [reproducibility-check, untested-assumptions, replication-grade]
input: The paper and specific result to assess, plus the context in which it will be used.
output: Replicability grade (full/partial/failed/insufficient-info) with evidence.
zetetic_gate:
  logical: "Replication must use the same conditions as the original — differences must be noted"
  critical: "Grades must be based on actual evidence, not reputation or citation count"
  rational: "Replication effort must be proportional to how much weight the result carries"
  essential: "A failed replication is a finding, not a failure — report it honestly"
composes: [verify-claim, literature-review]
aliases: [replicate, replication-check, reproducibility]
hand_off:
  replication_fails: "/verify-claim — check if others have reported the same failure"
  conditions_differ: "/translation-across-systems — the result may hold under different conditions"
  missing_details: "(stop) — insufficient information to replicate; contact authors or downgrade confidence"
---

## Procedure

### Phase 1: Availability Check (ibnalhaytham)
1. ibnalhaytham: is the code available? (public repo, supplementary materials, on request)
2. ibnalhaytham: is the data available? (public dataset, described sufficiently to reconstruct)
3. ibnalhaytham: are hyperparameters, random seeds, and compute specifications reported?
4. **Gate:** if code + data + hyperparameters are all missing, grade as "insufficient-info" and stop.

### Phase 2: Identify Untested Assumptions (wu)
5. wu: what assumptions does the paper make that it does not test?
6. wu: which of these assumptions might not hold in our setting?
7. Note each assumption as a potential divergence point.

### Phase 3: Attempt Replication (fisher, curie)
8. fisher: set up the replication with matched conditions. Document every deviation from the original.
9. curie: instrument the replication. Measure the same quantities the paper reports.
10. Run the replication. Compare results to the paper's reported results.
11. **Gate:** results within the paper's reported confidence intervals = partial or full replication. Outside = failed.

### Phase 4: Grade
12. Grade the replicability:
    - **Full**: code + data available, results reproduced within reported bounds.
    - **Partial**: results partially reproduced, or reproduced with minor deviations.
    - **Failed**: results not reproduced under matched conditions.
    - **Insufficient-info**: cannot attempt replication due to missing information.
13. Document what was attempted, what matched, and what diverged.

## Output Format

```
## Replication Assessment: [paper citation]
### Result assessed: [specific claim/result]

### Availability (ibnalhaytham):
| Item | Available? | Source |
|------|-----------|--------|
| Code | [yes/no] | [...] |
| Data | [yes/no] | [...] |
| Hyperparameters | [yes/no] | [...] |
| Seeds | [yes/no] | [...] |

### Untested assumptions (wu):
| Assumption | Tested? | Holds in our setting? |
|-----------|---------|---------------------|

### Replication results:
| Metric | Paper reports | Our result | Within bounds? |
|--------|-------------|-----------|---------------|

### Grade: [Full / Partial / Failed / Insufficient-info]
### Evidence: [what was attempted and what was found]
```
