---
name: product-quality-audit
description: >
  Audit integrated product quality: experience spec (jobs), strip to essential (galileo),
  verify correctness (dijkstra). "It just works" as a falsifiable engineering claim.
category: compose
trigger: >
  When a product "works" per component metrics but the user experience is broken;
  when trade-offs between quality dimensions are being accepted as inevitable;
  when integration seams are visible to the user.
agents:
  - jobs
  - galileo
  - dijkstra
shapes: [integrated-experience-as-spec, no-seams, all-dimensions-simultaneously, idealize-away-friction, elegance-as-correctness]
input: A product, feature, or user flow to audit.
output: Quality audit: experience spec, seam map, dimension check, correctness verification.
zetetic_gate:
  logical: "Quality criteria stated at experience level, not component level"
  critical: "'It just works' tested at every user contact point"
  rational: "Trade-offs between dimensions are design failures, not laws of nature"
  essential: "Every element serves the integrated experience or is cut"
composes: [audit-experience, strip-to-essential, prove-correct]
aliases: [product-audit, ux-audit, quality-check]
hand_off:
  seam_found: "Fix the organizational boundary that causes it"
  dimension_fails: "Rethink the design — trade-off is not acceptable"
  complexity_found: "/refactor — strip to the essential"
---

## Procedure

### Phase 1: Experience spec (jobs)
1. jobs: define "it just works" criteria for each user contact point (setup, first use, daily use, edge case, error, update).
2. jobs: map integration boundaries. Identify seams visible to the user.
3. jobs: check all quality dimensions simultaneously (ergonomic, functional, robust, performant, beautiful, autonomous, accessible).

### Phase 2: Strip to essential (galileo)
4. galileo: for each feature/element/setting, ask: is this essential to the experience? If not, cut.
5. galileo: identify the minimal model that delivers the core experience.

### Phase 3: Verify (dijkstra)
6. dijkstra: for the remaining essential elements, verify correctness by local reasoning.
7. dijkstra: identify what testing can and cannot cover. Recommend stronger methods for the gaps.

## Output Format

```
## Product Quality Audit: [product/feature]

### Experience spec:
| Contact point | "It just works" criterion | Pass? |
|---|---|---|

### Seam map:
| Boundary | Visible to user? | Fix needed? |
|---|---|---|

### Quality dimensions: [all pass simultaneously? any trade-offs?]
### Edit audit: [elements that don't serve the experience → cut]
### Correctness: [verified by dijkstra? gaps where tests are insufficient?]
### Verdict: [ships / needs work — specific items]
```
