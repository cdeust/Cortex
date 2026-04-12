---
name: source-comparison-matrix
description: >
  Structured comparison across multiple sources: build a matrix of claims, methods,
  and results to identify agreements, disagreements, and gaps.
category: research
trigger: >
  When multiple sources exist on a topic and they haven't been systematically compared;
  when contradictory findings need resolution; when a decision depends on choosing
  between competing approaches with different evidence bases.
agents:
  - cochrane
  - mill
  - feynman
shapes: [matrix-comparison, agreement-disagreement-gap, most-reliable-finding]
input: A set of sources (papers, reports, benchmarks) or a topic to compare across sources.
output: Comparison matrix with agreements, disagreements, gaps, and most reliable finding per dimension.
zetetic_gate:
  logical: "Comparison dimensions must be defined before extraction — no post-hoc cherry-picking"
  critical: "Extract from actual sources, not summaries; note when sources are not independent"
  rational: "Disagreements are data, not noise — investigate them before resolving"
  essential: "Identify the most reliable finding per dimension, not the most cited"
composes: [verify-claim, literature-review]
aliases: [compare-sources, source-matrix, cross-reference]
hand_off:
  disagreement_unresolvable: "/experiment — design a test to discriminate between competing claims"
  gap_found: "/literature-review — search for sources that fill the gap"
  source_unreliable: "/verify-claim — verify the questionable source independently"
---

## Procedure

### Phase 1: Define Comparison Dimensions (cochrane)
1. cochrane: define the comparison dimensions before reading sources. What aspects will you compare? (Methods, datasets, results, assumptions, limitations.)
2. **Gate:** dimensions must be specified upfront. Adding dimensions after seeing the data is cherry-picking.

### Phase 2: Extract Data (cochrane, feynman)
3. cochrane: for each source, extract data along every dimension. Use the actual source, not abstracts or summaries.
4. feynman: for each source, note what the source does NOT report. Missing data is informative.
5. Build the matrix: sources as columns, dimensions as rows.

### Phase 3: Analyze (mill)
6. mill: method of agreement — which findings do all sources agree on?
7. mill: method of difference — where do sources disagree, and what differs in their conditions?
8. mill: identify gaps — which dimensions have no data from any source?
9. **Gate:** disagreements must be investigated. Do they stem from different conditions, different methods, or actual contradiction?

### Phase 4: Assess Reliability
10. For each dimension, identify the most reliable finding. Reliability criteria: independence of sources, sample size, reproducibility, methodological rigor.
11. **Gate:** "most cited" is not "most reliable." Assess on evidence quality, not popularity.

## Output Format

```
## Source Comparison: [topic]

### Dimensions: [list of comparison dimensions]

### Matrix:
| Dimension | Source 1 | Source 2 | Source 3 | ... |
|-----------|---------|---------|---------|-----|

### Agreements: [findings all sources confirm]
### Disagreements:
| Dimension | Source A says | Source B says | Likely reason |
|-----------|-------------|-------------|--------------|

### Gaps: [dimensions with no data]

### Most reliable finding per dimension:
| Dimension | Finding | Basis | Confidence |
|-----------|---------|-------|-----------|
```
