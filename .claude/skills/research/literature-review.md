---
name: literature-review
description: >
  Systematic literature search: find papers, read the actual papers (not summaries),
  extract methods, cross-reference, and assess applicability to the current problem.
category: research
trigger: >
  When implementing an algorithm and the source paper hasn't been read; when a technique
  is being used without understanding its assumptions; when "the literature" is cited
  without specific papers.
agents:
  - research-scientist
shapes: []
input: A topic, technique, or question to research. Context on why it matters.
output: Literature review with paper citations, key findings, applicability assessment, and recommendations.
zetetic_gate:
  logical: "Read the actual paper, not the abstract or a blog post"
  critical: "Cross-reference with independent sources; single paper = hypothesis"
  rational: "Assess applicability to YOUR setting, not the paper's setting"
  essential: "Answer the research question; do not produce an encyclopedia"
composes: [verify-claim]
aliases: [lit-review, find-papers, research]
hand_off:
  technique_found: "/implement — engineer implements the verified technique"
  assumptions_dont_match: "(stop) — the technique doesn't apply to your setting"
---

## Procedure

1. **State the question.** What do you need to know? Why does it matter for the current work?
2. **Search.** research-scientist finds 3-10 relevant papers from primary sources (arXiv, ACM, IEEE, journals).
3. **Read.** For each paper: read the actual paper. Extract the key method, the assumptions, the experimental conditions, and the results. Not the abstract.
4. **Cross-reference.** Do independent papers agree? Where do they disagree?
5. **Applicability.** Do the paper's assumptions match your setting? (Dataset size, hardware, domain, constraints.) If not, the technique may not transfer.
6. **Recommend.** Which technique(s) are applicable? With what caveats?

## Output Format

```
## Literature Review: [question]
### Papers:
| # | Citation | Key method | Assumptions | Applicable? |
|---|----------|-----------|-------------|-------------|
### Cross-reference: [agreement/disagreement between sources]
### Recommendation: [technique to use, with caveats]
### Inapplicable techniques: [and why — so nobody re-researches them]
```
