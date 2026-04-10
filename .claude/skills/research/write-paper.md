---
name: write-paper
description: >
  Draft a scientific paper with claim-evidence chains, proper structure, and venue-appropriate formatting.
category: research
trigger: >
  When research results need to be written up; when a paper draft needs structuring;
  when claim-evidence chains need to be made explicit.
agents:
  - paper-writer
  - latex-engineer
shapes: []
input: Research results, data, and the target venue.
output: Paper draft with explicit claim-evidence chains and venue-appropriate structure.
zetetic_gate:
  logical: "Every claim in the paper must have cited evidence"
  critical: "The limitations section lists high-impact potential invalidators, not boilerplate"
  rational: "Structure matches the target venue's expectations"
  essential: "The paper says what is true, what is uncertain, and what is not known"
composes: [verify-claim, difficulty-book]
aliases: [draft-paper, paper]
hand_off:
  needs_review: "/pre-submit-review — simulate peer review"
  needs_more_evidence: "/literature-review or /experiment"
---

## Procedure

1. **paper-writer: structure.** Identify the contribution, the claim-evidence chains, and the narrative arc.
2. **paper-writer: draft.** Abstract → intro → related work → method → results → discussion → conclusion. Every claim has a citation or experimental evidence.
3. **difficulty-book: limitations.** darwin: catalog every known weakness, negative result, and open question. The limitations section is not boilerplate; it is the difficulty book.
4. **latex-engineer: format.** Venue-appropriate template, figures, tables, bibliography.

## Output Format

```
## Paper Draft: [title]
### Contribution: [one sentence]
### Claim-evidence chains:
| Claim | Evidence | Type (experimental/cited/derived) |
|-------|---------|-----------------------------------|
### Limitations (from difficulty book):
| Limitation | Damage if true | Status |
|-----------|---------------|--------|
### Structure: [sections with status]
```
