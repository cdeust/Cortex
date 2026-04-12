---
name: systematic-review
description: >
  Cochrane-style systematic review with full protocol: PICO question, pre-registered
  protocol, exhaustive search, screening, data extraction, heterogeneity assessment,
  publication bias checks, GRADE evidence grading, and meta-analysis when appropriate.
category: research
trigger: >
  When a question requires formal evidence synthesis; when decisions depend on the
  aggregate effect across multiple studies; when a narrative review is insufficient;
  when "what does the evidence say?" needs a rigorous answer.
agents:
  - cochrane
  - fisher
  - laplace
  - feynman
  - darwin
shapes: [evidence-pooling, bayesian-update, integrity-audit]
input: A research question suitable for systematic review. Ideally in PICO format.
output: Systematic review with protocol, search results, forest plot, GRADE assessment, and summary of findings.
zetetic_gate:
  logical: "Protocol must be written BEFORE searching — no post-hoc inclusion criteria"
  critical: "Every included study is independently screened; every excluded study has a documented reason"
  rational: "Pool only when heterogeneity is acceptable; otherwise report narratively"
  essential: "GRADE the evidence — the consumer must know how much to trust the conclusion"
composes: [literature-review, verify-claim]
aliases: [meta-analysis, systematic-search, evidence-synthesis]
hand_off:
  evidence_sufficient: "/implement — engineer implements the evidence-backed technique"
  evidence_insufficient: "(stop) — insufficient primary studies; report what exists and what is missing"
  high_heterogeneity: "/deep-research — investigate moderators before pooling"
---

## Procedure

### Phase 1: Define question (cochrane)
1. **Formulate in PICO.** Population: who/what? Intervention: the thing being evaluated. Comparison: the alternative. Outcome: what is measured and how.
2. If the question does not fit PICO, use an equivalent structured format (SPIDER, PEO) and justify the choice.

### Phase 2: Write protocol (cochrane)
3. **Pre-register the protocol BEFORE searching.** Specify:
   - Search terms (Boolean queries, MeSH terms or equivalents)
   - Databases to search (minimum 3: e.g., arXiv, ACM DL, PubMed, Scopus, IEEE Xplore)
   - Grey literature sources (preprints, theses, technical reports)
   - Inclusion criteria (study type, date range, language, domain)
   - Exclusion criteria (with justification for each)
   - Primary and secondary outcomes
4. **Gate:** protocol is locked. Any deviation is documented as a protocol amendment.

### Phase 3: Exhaustive search (cochrane)
5. Execute the search across all specified databases.
6. Reference chaining: forward and backward citation search on included studies.
7. Record total hits per database. Export all results with deduplication.

### Phase 4: Screen results (cochrane)
8. **Title/abstract screening.** Apply inclusion/exclusion to each result independently.
9. **Full-text screening.** For studies passing title/abstract, read in full and apply criteria.
10. Record: included (N), excluded (N, with reason breakdown). Produce a PRISMA flow diagram.

### Phase 5: Extract data (fisher)
11. For each included study: extract effect size, sample size, variance, confidence interval.
12. Standardize effect sizes across studies (Cohen's d, odds ratio, risk ratio — whichever fits the outcome).
13. Record study-level risk of bias (randomization, blinding, attrition, reporting, other).

### Phase 6: Assess heterogeneity (fisher)
14. Compute I-squared statistic and Cochran's Q test.
15. If I-squared > 50%: investigate moderators (subgroup analysis, meta-regression). Do NOT pool blindly.
16. If I-squared > 75%: report narratively unless moderators explain the variance.

### Phase 7: Check publication bias (fisher)
17. Funnel plot analysis: visual inspection for asymmetry.
18. Egger's test or equivalent statistical test for small-study effects.
19. If bias detected: apply trim-and-fill and report both adjusted and unadjusted estimates.

### Phase 8: Grade evidence (cochrane)
20. Apply GRADE framework to each outcome:
    - Start at high (RCTs) or low (observational)
    - Downgrade for: risk of bias, inconsistency, indirectness, imprecision, publication bias
    - Upgrade for: large effect, dose-response, confounders would reduce effect
21. Final rating: very low / low / moderate / high.

### Phase 9: Pool if appropriate (fisher + laplace)
22. **fisher: frequentist meta-analysis.** Fixed-effects (if homogeneous) or random-effects (if heterogeneous) model.
23. **laplace (optional): Bayesian meta-analysis.** Use when prior information is available or when the frequentist model is unstable with few studies.
24. Report: pooled effect size, confidence/credible interval, prediction interval.

### Phase 10: Report (cochrane + darwin)
25. **darwin: difficulty book.** Document every limitation, every assumption, every weakness. What could overturn this conclusion?
26. **feynman: integrity check.** Final audit — does the report honestly represent the evidence?
27. Produce: forest plot, summary of findings table, plain-language summary.

## Output Format

```
## Systematic Review: [PICO question]

### Protocol
Search terms: [Boolean query]
Databases: [list] | Date range: [range]
Inclusion: [criteria] | Exclusion: [criteria]

### PRISMA Flow
Identified: [N] | Screened: [N] | Eligible: [N] | Included: [N]
Exclusion reasons: [breakdown]

### Summary of Findings
| Outcome | Studies | Effect size (95% CI) | I-squared | GRADE |
|---------|---------|---------------------|-----------|-------|

### Forest Plot
[visual or tabular representation of individual and pooled effects]

### Publication Bias
Funnel plot: [symmetric / asymmetric]
Egger's test: p = [value]
Trim-and-fill adjustment: [if applicable]

### Limitations (darwin)
- [limitation 1]
- [limitation 2]

### Conclusion
[plain-language summary with GRADE-qualified confidence]
```
