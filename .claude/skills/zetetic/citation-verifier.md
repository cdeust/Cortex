---
name: citation-verifier
description: >
  Mechanical citation verification: extract all citations from a document, verify URLs
  resolve, verify content matches the claim being cited, check DOIs, verify quotation
  accuracy, detect orphan citations, and produce a verification report.
category: zetetic
trigger: >
  When a document contains citations that haven't been verified; when reviewing a research
  brief or paper for citation accuracy; when "trust but verify" applies to referenced
  sources; before publishing anything with inline citations.
agents:
  - feynman
  - wu
shapes: [integrity-audit, error-archaeology]
input: A document containing citations (markdown, PDF, or plain text).
output: Citation verification report with resolution status, content match, and accuracy grade for each citation.
zetetic_gate:
  logical: "Every citation in the document is checked — no sampling, no skipping"
  critical: "Content match means the source actually says what the citing document claims — not just that the source exists"
  rational: "Grade by impact: a wrong citation supporting a key claim is FATAL; a wrong citation in background is MINOR"
  essential: "The verification report is the deliverable — each citation has a status and grade"
composes: [verify-claim]
aliases: [verify-citations, check-citations, citation-check, source-check]
hand_off:
  all_verified: "(done) — all citations verified"
  issues_found: "/deep-research — replace or fix broken citations"
  systematic_problems: "(escalate) — pattern of citation misuse suggests deeper issues"
---

## Procedure

### Phase 1: Extract citations
1. **Scan the document.** Find every citation: numbered references [N], URLs, DOIs, paper titles, author-year references.
2. Build a citation inventory: citation ID, citation text, location in document, the claim it supports.
3. Build a reference list inventory: every entry in the reference list or bibliography.
4. **Cross-check:** every citation ID in the text must have a reference list entry, and vice versa.

### Phase 2: Verify URL resolution
5. For each URL: HTTP HEAD request. Record status code.
6. Flag: 404 (broken), 301/302 to unrelated content (misleading redirect), 403/paywall (unverifiable), timeout.
7. For URLs that resolve: record the final destination URL and page title.

### Phase 3: Verify DOIs
8. For each DOI: resolve via doi.org. Record whether the paper exists.
9. Cross-check: does the DOI resolve to the paper cited (matching title and authors)?
10. Flag DOIs that resolve to a different paper than cited.

### Phase 4: Verify content matches claim (feynman)
11. **feynman: integrity audit.** For each citation: read the cited source. Does it actually say what the citing document claims?
12. Classify content match:
    - **YES** — source directly supports the claim as stated
    - **PARTIAL** — source is related but the claim overstates, understates, or mischaracterizes it
    - **NO** — source does not support the claim or says something different
    - **UNVERIFIABLE** — source behind paywall, unavailable, or in a language that cannot be verified
13. For PARTIAL and NO: document what the source actually says versus what is claimed.

### Phase 5: Verify quotation accuracy
14. For any direct quotes: compare the quote against the source text character by character.
15. Flag: misquotes, elisions that change meaning, quotes taken out of context.

### Phase 6: Detect orphan citations (wu)
16. **Orphan in text:** citation [N] appears in body but not in reference list.
17. **Orphan in references:** reference list entry has no corresponding citation in body.
18. **wu: error archaeology.** Are orphans the result of editing artifacts, copy-paste errors, or systematic sloppiness?

### Phase 7: Produce verification report
19. For each citation: assign a grade based on resolution + content match + accuracy:
    - **A** — resolves, content matches, quote accurate (if applicable)
    - **B** — resolves, content partially matches or minor discrepancy
    - **C** — resolves but content match is weak or unverifiable
    - **F** — does not resolve, content does not match, or quote is wrong
20. Classify issues by severity:
    - **FATAL** — citation supporting a key claim is wrong or broken
    - **MAJOR** — citation does not support the specific claim made
    - **MINOR** — cosmetic issue, paywall, or citation in non-critical context

## Output Format

```
## Citation Verification Report: [document title]

### Summary
Total citations: [N] | Verified: [N] | Issues: [N]
Grade distribution: A=[N] B=[N] C=[N] F=[N]

### Verification Matrix
| # | Citation | URL/DOI | Resolves? | Content matches claim? | Grade |
|---|----------|---------|-----------|----------------------|-------|
| 1 | [author, year] | [url] | yes | yes | A |
| 2 | [author, year] | [url] | yes | partial — overstates | B |
| 3 | [author, year] | [url] | no (404) | n/a | F |

### Issues Found
- [FATAL] Citation [3] URL returns 404 — supports key claim in Section 2.1
- [MAJOR] Citation [7] does not support the specific claim made — source discusses X, not Y
- [MINOR] Citation [12] is behind a paywall — content unverifiable

### Orphan Citations
- In text but not in references: [N]
- In references but not in text: [N]

### Quotation Accuracy
| # | Quote location | Accurate? | Issue |
|---|---------------|-----------|-------|
```
