---
name: anomaly-to-explanation
description: >
  Full pipeline: notice the anomaly (mcclintock), isolate its carrier (curie),
  formalize the explanation (shannon or noether).
category: compose
trigger: >
  When a specific case is weird and the aggregate is smooth; when discarded data might
  contain a signal; when an anomaly has been noticed but nobody has isolated or explained it.
agents:
  - mcclintock
  - curie
  - shannon
  - noether
shapes: [anomaly-others-discarded, residual-with-a-carrier, define-the-measure-first, symmetry-first]
input: An anomaly — a specific observation that doesn't fit expectations.
output: Explanation report: the anomaly, the isolated carrier, and the formal explanation.
zetetic_gate:
  logical: "The explanation must be consistent with all observations, not just the anomaly"
  critical: "The carrier must be isolated by two independent methods"
  rational: "Route to shannon (if the explanation is a new quantity) or noether (if it's a symmetry)"
  essential: "The anomaly is data; the explanation is a testable hypothesis"
composes: [investigate-anomaly, isolate-signal, define-measure, find-symmetry]
aliases: [explain-anomaly, trace-anomaly]
hand_off:
  explanation_found: "/verify-claim — check the explanation against independent sources"
  anomaly_is_noise: "(stop) — after investigation, the anomaly is within measurement noise"
---

## Procedure

### Phase 1: Notice (mcclintock)
1. mcclintock: deep single-specimen observation. What is the anomaly? Reproduce it. Record in detail.
2. **Gate:** is the anomaly reproducible and specific? If not, it may be noise → stop or refine the observation.

### Phase 2: Isolate (curie)
3. curie: instrument the system. Name the anomaly. Chase the excess.
4. curie: isolate the carrier by enrichment (bisect, ablate, substitute) with a matched control.
5. **Gate:** two independent methods confirm the carrier.

### Phase 3: Explain (shannon or noether)
6. If the anomaly suggests a new quantity that needs definition → shannon: axiomatize, derive, operationalize.
7. If the anomaly suggests a broken or hidden symmetry → noether: find the group, classify, check conservation.
8. The explanation is a testable hypothesis, not a final theory.

## Output Format

```
## Anomaly → Explanation: [anomaly name]

### Phase 1 — Observation (mcclintock)
Specimen: [...] | Reproducible: [yes/no] | Specific: [yes/no]

### Phase 2 — Isolation (curie)
Instrument: [...] | Carrier: [...] | Confirmed by: [method 1, method 2]

### Phase 3 — Explanation
Route: [shannon / noether]
Explanation: [testable hypothesis]
Predictions: [what the explanation predicts that can be checked]
```
