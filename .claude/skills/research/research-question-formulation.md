---
name: research-question-formulation
description: >
  Structure a vague interest into a well-formed research question: abductive hypothesis
  generation (Peirce), falsifiability check (Popper), feasibility estimation (Fermi),
  and scope satisficing (Simon).
category: research
trigger: >
  When someone says "I'm interested in X" but hasn't formed a question; when a research
  direction is too broad to act on; when a question is interesting but unfalsifiable;
  when feasibility hasn't been assessed.
agents:
  - peirce
  - popper
  - fermi
  - simon
shapes: [abduction, falsifiability, feasibility-bound, satisficing-scope]
input: A vague interest, observation, or problem area to formulate into a research question.
output: Well-formed research question with type, falsifiability criteria, feasibility assessment, and sub-questions.
zetetic_gate:
  logical: "The question must be logically well-formed — not ambiguous, not compound"
  critical: "The question must be falsifiable — state what would count as a negative answer"
  rational: "The question must be feasible given available resources and time"
  essential: "One focused question is better than five vague ones — scope ruthlessly"
composes: [literature-review, verify-claim]
aliases: [formulate-question, research-question, refine-question]
hand_off:
  question_already_answered: "/literature-review — check the literature before investigating"
  question_too_broad: "(iterate) — decompose into sub-questions and formulate each"
  question_unfalsifiable: "(revise) — restate until a negative result is possible"
---

## Procedure

### Phase 1: Identify the Phenomenon (peirce)
1. peirce: what is the surprising observation or unexplained phenomenon?
2. peirce: generate candidate hypotheses by abduction — what would explain this if it were true?
3. **Gate:** the phenomenon must be specific and observable, not abstract.

### Phase 2: Formulate the Question
4. State what is known vs unknown about the phenomenon.
5. Formulate as a question. Classify its type:
   - **Descriptive**: what is X? (measurement, characterization)
   - **Relational**: is X associated with Y? (correlation, co-occurrence)
   - **Causal**: does X cause Y? (intervention, mechanism)
   - **Mechanistic**: how does X produce Y? (process, pathway)
6. **Gate:** the question must be a single, unambiguous question. Compound questions must be split.

### Phase 3: Falsifiability Check (popper)
7. popper: what would count as a negative answer to this question?
8. popper: is the negative answer empirically distinguishable from the positive answer?
9. **Gate:** if no observation could falsify the answer, the question is not scientific. Revise.

### Phase 4: Feasibility Assessment (fermi)
10. fermi: estimate the resources needed to answer the question (data, compute, time, expertise).
11. fermi: estimate the probability of getting a clear answer (signal-to-noise, sample size, measurement precision).
12. **Gate:** if feasibility is below threshold, narrow the scope or change the approach.

### Phase 5: Scope Satisficing (simon)
13. simon: is this question scoped to produce a satisfactory answer with available resources?
14. simon: decompose into sub-questions ordered by dependency and information value.
15. **Gate:** the first sub-question must be answerable independently and informative about the rest.

## Output Format

```
## Research Question: [well-formed question]

### Phenomenon (peirce): [what was observed]
### Known: [...] | Unknown: [...]
### Question type: [descriptive / relational / causal / mechanistic]

### Falsifiability (popper):
Negative answer: [what would count as falsification]
Distinguishable: [yes / no]

### Feasibility (fermi):
| Resource | Required | Available | Gap |
|----------|---------|-----------|-----|
Probability of clear answer: [estimate]

### Sub-questions (simon):
| # | Sub-question | Depends on | Information value |
|---|-------------|-----------|------------------|

### Recommended starting point: [first sub-question to pursue]
```
