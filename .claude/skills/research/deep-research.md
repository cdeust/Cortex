---
name: deep-research
description: >
  Master research orchestration: formulate question, plan search strategy, delegate to
  parallel researchers, synthesize across sources, verify claims, write findings with
  inline citations, and produce a provenance sidecar with lab notebook entry.
category: research
trigger: >
  When a research question requires end-to-end investigation; when multiple source types
  or angles are needed; when shallow search has failed; when the answer requires synthesis
  across disparate sources rather than a single lookup.
agents:
  - peirce
  - popper
  - shannon
  - cochrane
  - mendeleev
  - feynman
  - wu
  - toulmin
shapes: [abductive-hypothesis, falsifiability-gate, define-the-measure-first, evidence-pooling]
input: A research question. Context on why it matters and what decisions depend on the answer.
output: Cited research brief, provenance sidecar (sources consulted/accepted/rejected), lab notebook entry.
zetetic_gate:
  logical: "Research question must be well-formed and falsifiable before search begins"
  critical: "Every claim in the output is cited to a verifiable source; no unsourced assertions"
  rational: "Depth is proportional to stakes — a design decision gets hours, not weeks"
  essential: "Must produce at minimum: cited brief + provenance file"
composes: [literature-review, verify-claim]
aliases: [research, investigate, deep-dive]
hand_off:
  technique_found: "/implement — engineer implements the verified technique"
  claims_unverifiable: "(stop) — insufficient evidence; report what is known and what is not"
  needs_systematic_review: "/systematic-review — question requires formal meta-analysis"
---

## Procedure

### Phase 1: Formulate (peirce + popper + shannon)
1. **peirce: abductive hypothesis.** From the raw question, generate candidate hypotheses. What would explain the observations? What would be surprising?
2. **popper: falsifiability gate.** For each hypothesis: what evidence would refute it? If nothing could refute it, it is not a research question — restate it.
3. **shannon: define the measure.** What information resolves the question? Define the output quantity before searching for it.

### Phase 2: Plan search strategy
4. Decompose the question into 3-5 sub-questions, each targeting a disjoint dimension (source type, time period, disciplinary angle, geographic scope).
5. For each sub-question: specify evidence types needed (empirical data, theoretical framework, case study, meta-analysis).

### Phase 3: Delegate to parallel researchers
6. Assign each sub-question to a parallel research thread. Each thread searches independently — no shared state until synthesis.
7. Each thread produces: sources found, sources rejected (with reason), key claims extracted, confidence assessment.

### Phase 4: Synthesize (cochrane + mendeleev)
8. **cochrane: evidence pooling.** Aggregate findings across threads. Weight by evidence quality. Identify convergence and divergence.
9. **mendeleev: taxonomy of findings.** Classify findings into a structured taxonomy. Identify gaps — what was expected but not found?

### Phase 5: Verify (feynman + wu)
10. **feynman: integrity audit.** For each key claim: does the cited source actually say this? Are experimental conditions reported accurately? Flag any claim that fails verification.
11. **wu: untested assumptions.** What assumptions are the findings resting on? Which have never been tested? Flag these explicitly.
12. **Citation verification.** Every [N] reference resolves to an actual source. No orphan citations.

### Phase 6: Write findings (toulmin)
13. **toulmin: argument structure.** Write the findings as: claim, grounds, warrant, backing, qualifier, rebuttal. Every claim has inline citations.
14. Produce the research brief with explicit confidence levels (high / moderate / low / insufficient).

### Phase 7: Provenance sidecar
15. Generate provenance file listing every source: consulted, accepted (with reason), rejected (with reason), unresolvable.

### Phase 8: Lab notebook entry
16. Record: what was investigated, what was found, what remains unknown, what should be investigated next.

## Output Format

```
## Research Brief: [question]

### Summary
[2-3 sentence answer with confidence level]

### Findings
| # | Claim | Evidence | Confidence | Citations |
|---|-------|----------|------------|-----------|

### Untested assumptions
- [assumption]: never tested because [reason]

### Gaps
- [what was expected but not found]

### Recommendation
[what to do with these findings]
```

```
## Provenance Sidecar
| # | Source | Status | Reason |
|---|--------|--------|--------|
| 1 | [citation] | accepted / rejected / unresolvable | [why] |
```

```
## Lab Notebook
Date: [date]
Question: [question]
Found: [summary]
Unknown: [what remains]
Next: [recommended follow-up]
```
