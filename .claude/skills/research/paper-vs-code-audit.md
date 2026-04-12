---
name: paper-vs-code-audit
description: >
  Compare a paper's claims against its implementation: extract every testable claim,
  locate corresponding code, verify alignment, flag mismatches, and produce a
  traceability matrix from paper claims to code locations.
category: research
trigger: >
  When implementing from a paper and wanting to verify fidelity; when a codebase claims
  to implement a paper but results don't match; when reviewing a reproduction; when
  auditing whether code matches published methodology.
agents:
  - feynman
  - dijkstra
  - wu
  - curie
  - alkhwarizmi
shapes: [rederive-from-scratch, program-correctness, untested-assumptions, canonical-form]
input: A paper (title, DOI, or PDF) and a codebase (path or repository URL).
output: Traceability matrix with alignment status for every testable claim.
zetetic_gate:
  logical: "Every claim is extracted from the paper text, not from memory or summaries"
  critical: "Code is read directly — no assumptions about what it 'probably' does"
  rational: "Focus on claims that affect results; cosmetic differences are low priority"
  essential: "The traceability matrix is the deliverable — every claim has a status"
composes: [verify-claim, literature-review]
aliases: [paper-audit, code-audit, reproduction-check, paper-code-diff]
hand_off:
  all_aligned: "(done) — implementation matches paper"
  mismatches_found: "/implement — engineer fixes mismatches to match paper"
  paper_has_errors: "/deep-research — investigate whether the paper itself is wrong"
---

## Procedure

### Phase 1: Extract claims (feynman + alkhwarizmi)
1. **Read the paper.** The actual paper — equations, algorithms, experimental setup, hyperparameters, constants. Not the abstract.
2. **feynman: rederive from scratch.** For each equation: rederive it from stated assumptions. Flag any step that doesn't follow.
3. **alkhwarizmi: canonical form.** Reduce each algorithm to its canonical computational steps. Remove notational sugar.
4. **Extract testable claims.** For each, record:
   - Claim ID (paper section + equation/algorithm/table number)
   - Claim type: equation, algorithm, constant, hyperparameter, experimental condition, architectural choice
   - Exact statement from paper

### Phase 2: Locate code (dijkstra)
5. **For each claim:** find the corresponding code location. File, function, line range.
6. **dijkstra: program correctness.** Read the code as written. What does it actually compute? Express it in the same notation as the paper.
7. If no corresponding code exists for a claim, mark it as MISSING.

### Phase 3: Verify alignment (feynman + curie)
8. **For each claim-code pair:** compare the paper's statement with the code's behavior.
9. **curie: measurement verification.** For constants and hyperparameters: does the code use the exact value from the paper? Where does the value come from?
10. **feynman: integrity check.** For equations: does the code implement the equation faithfully, including edge cases, normalization, and boundary conditions?
11. Classify each pair:
    - **ALIGNED** — code implements what the paper says
    - **DISAGREEMENT** — paper says X, code does Y (document both)
    - **OMISSION** — paper claims X but code doesn't implement it
    - **UNDOCUMENTED** — code does X but paper doesn't mention it
    - **INVENTED** — paper's constant/threshold has no cited source

### Phase 4: Flag untested assumptions (wu)
12. **wu: error archaeology.** For each disagreement or omission: is this a deliberate deviation or an error?
13. For each undocumented code behavior: is this a necessary implementation detail or a hidden assumption?
14. For each invented constant: what happens if the value changes by 10%? By 2x?

### Phase 5: Produce traceability matrix
15. Compile the full matrix. Sort by severity: disagreements first, then omissions, then undocumented, then invented, then aligned last.
16. For each non-aligned entry: recommend action (fix code, fix paper, investigate further, accept deviation with justification).

## Output Format

```
## Paper vs Code Audit: [paper title] -> [codebase]

### Summary
Claims extracted: [N] | Aligned: [N] | Disagreement: [N] | Omission: [N] | Undocumented: [N] | Invented: [N]

### Traceability Matrix
| # | Claim ID | Type | Paper says | Code does | File:Line | Status | Severity |
|---|----------|------|-----------|-----------|-----------|--------|----------|
| 1 | Eq. 3 | equation | sigma = sqrt(2/n) | sigma = 1/sqrt(n) | model.py:42 | DISAGREEMENT | HIGH |
| 2 | Table 2 | hyperparameter | lr = 0.001 | lr = 0.01 | config.py:8 | DISAGREEMENT | MEDIUM |
| 3 | Sec 3.2 | algorithm | dropout after norm | — | — | OMISSION | MEDIUM |
| 4 | — | — | — | warmup 500 steps | train.py:15 | UNDOCUMENTED | LOW |

### Untested Assumptions (wu)
- [assumption]: sensitivity = [what happens if changed]

### Recommended Actions
| # | Action | Rationale |
|---|--------|-----------|
| 1 | Fix code to match Eq. 3 | Off by factor of sqrt(2) |
| 2 | Verify which lr was used in experiments | Results may not reproduce |
```
