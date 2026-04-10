---
name: pre-submit-review
description: >
  Simulate peer review as a skeptical NeurIPS/CVPR/ICML reviewer before submission.
category: research
trigger: >
  When a paper is ready for submission and needs a quality check; when the authors want
  to anticipate reviewer objections.
agents:
  - reviewer-academic
  - feynman
shapes: [integrity-audit, hardest-case-first]
input: A paper draft (or sections of it) and the target venue.
output: Simulated review with scores, strengths, weaknesses, questions, and suggestions.
zetetic_gate:
  logical: "Review must address the claims actually made, not strawmen"
  critical: "Weaknesses must be specific and actionable, not vague"
  rational: "Review standards matched to the target venue"
  essential: "The review catches the objections reviewers WILL raise"
composes: [audit-integrity]
aliases: [peer-review, review-paper, simulate-review]
hand_off:
  weakness_found: "Revise the paper before submission"
  missing_experiment: "/experiment — fisher: design the missing experiment"
---

## Procedure

1. **reviewer-academic: full review.** Read the paper as a skeptical expert. Score novelty, clarity, significance, reproducibility (1-10 each).
2. **Strengths.** What is genuinely good?
3. **Weaknesses.** Specific, actionable, cited to the paper. "The evaluation on Dataset X doesn't control for Y" not "the evaluation is weak."
4. **Questions.** What would you ask the authors?
5. **feynman: integrity check.** Does the limitations section catch the real weaknesses? Or is it boilerplate?
6. **Suggestions.** Specific changes that would address the weaknesses.

## Output Format

```
## Pre-Submission Review: [paper title]
### Venue: [target]
### Scores: Novelty [/10] | Clarity [/10] | Significance [/10] | Reproducibility [/10]
### Strengths: [bulleted]
### Weaknesses: [bulleted, specific, actionable]
### Questions for authors: [bulleted]
### Integrity check: [does the limitations section match the real weaknesses?]
### Suggestions: [specific changes]
### Verdict: [accept / revise / reject — with reasoning]
```
