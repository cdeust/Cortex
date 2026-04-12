---
name: research-watch
description: >
  Set up recurring monitoring for a research area: define search terms, filter for
  relevance, produce periodic digests, and flag papers that might invalidate current
  assumptions.
category: research
trigger: >
  When a project depends on a fast-moving research area; when "we should keep up with
  the literature" has no concrete mechanism; when a prior decision might be invalidated
  by new findings.
agents:
  - cochrane
  - darwin
  - rogers
shapes: [search-protocol, assumption-invalidation, adoption-tracking]
input: The research area to monitor, current assumptions that could be invalidated, and desired monitoring frequency.
output: Monitoring protocol and first digest of current state.
zetetic_gate:
  logical: "Search terms must be specific enough to produce actionable results, not a firehose"
  critical: "Relevance criteria must be defined before filtering — no post-hoc selection"
  rational: "Monitoring frequency must match the pace of the field and the stakes"
  essential: "Flag assumption-invalidating papers immediately; routine updates can batch"
composes: [literature-review, verify-claim]
aliases: [watch-research, monitor-literature, research-radar]
hand_off:
  assumption_invalidated: "/verify-claim — verify the invalidating paper before acting on it"
  new_technique_found: "/literature-review — full review of the new technique"
  adoption_threshold: "/translation-across-systems — adapt the technique for our domain"
---

## Procedure

### Phase 1: Define the Watch (cochrane)
1. cochrane: define search terms and venues (arXiv categories, journals, conferences, preprint servers).
2. cochrane: specify relevance criteria — what makes a paper relevant to this project? Be concrete.
3. List the current assumptions that could be invalidated. For each, specify what kind of finding would invalidate it.
4. **Gate:** search terms tested against recent results. If they return noise, refine.

### Phase 2: Assess Current State
5. Run the initial search. Produce a baseline digest of the current landscape.
6. darwin: check against the difficulty book — are any of the current assumptions already under pressure from recent work?
7. rogers: track adoption status of techniques the project uses. Are they mainstream, early-adopter, or declining?

### Phase 3: Design the Monitoring Protocol
8. Set the monitoring frequency based on field pace: weekly for fast-moving areas, monthly for stable areas.
9. Define the digest format: brief summary per paper, relevance score, and whether it touches a flagged assumption.
10. Define the escalation rule: which findings trigger immediate review vs routine digest inclusion.

### Phase 4: Produce First Digest
11. Apply the protocol to the current search results. Produce the first digest as a template.

## Output Format

```
## Research Watch: [area]

### Search protocol (cochrane):
Terms: [...] | Venues: [...] | Frequency: [...]
Relevance criteria: [...]

### Flagged assumptions:
| Assumption | Invalidated by | Current status |
|-----------|---------------|---------------|

### Adoption status (rogers):
| Technique | Stage | Trend |
|-----------|-------|-------|

### Current digest:
| Paper | Summary | Relevance | Touches assumption? |
|-------|---------|-----------|-------------------|

### Escalation rules:
| Trigger | Action |
|---------|--------|
```
