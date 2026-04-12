---
name: provenance-tracking
description: >
  Generate and maintain .provenance.md sidecar files that trace every implementation
  decision back to its source. Every algorithm, constant, and design choice links to
  a verifiable reference. Rejected sources are logged with reasons. Staleness is
  monitored. Revisit conditions are explicit.
category: zetetic
trigger: >
  When implementing an algorithm from a paper; when hardcoding constants that need
  justification; when "where did this come from?" has no answer; when a codebase
  needs an audit trail of its intellectual provenance.
agents:
  - feynman
  - wu
  - darwin
shapes: [no-source-no-implementation, multiple-sources-required, verify-before-accepting]
input: Target file or directory. Research context. Sources consulted so far.
output: .provenance.md sidecar file with full source lineage, acceptance/rejection log, staleness status.
zetetic_gate:
  logical: "Every accepted source has a verifiable citation — URL, DOI, or page reference"
  critical: "No source is accepted on authority alone; claims must be independently checkable"
  rational: "Provenance depth is proportional to the decision's impact — critical constants get full lineage"
  essential: "Rejected sources are as important as accepted ones; the rejection log prevents revisiting dead ends"
composes: []
aliases: [provenance, source-tracking, audit-trail]
hand_off:
  source_contradicts: "/seek-disconfirmation — resolve conflicting sources"
  source_unverifiable: "/verify-claim — attempt independent verification"
  needs_literature: "/literature-review — systematic search for additional sources"
---

## Procedure

### Phase 1: Identify and Initialize (feynman)

1. **feynman: identify the target.** Which file, directory, or decision needs provenance tracking?
   What is the scope — a single function, a module, an architecture decision?
2. **Initialize .provenance.md sidecar.** Place it adjacent to the target:
   - For a file `foo.py`: create `foo.provenance.md`
   - For a directory `lib/`: create `lib/.provenance.md`
3. **Write header metadata.** Target path, creation date, author, purpose statement.

### Phase 2: Source Inventory (wu)

4. **wu: inventory all claims.** For each implementation decision in the target, identify
   the underlying claim: "this algorithm works because...", "this constant is correct
   because...", "this design was chosen because...".
5. **For each claim, log all sources consulted.** A source entry contains:
   - Type: paper / documentation / benchmark / empirical measurement / expert opinion
   - Reference: DOI, URL, book + page, commit SHA (for empirical results)
   - Date consulted
   - Status: consulted / accepted / rejected
   - Relevance note: one sentence on what this source contributes

### Phase 3: Acceptance Criteria (feynman)

6. **feynman: evaluate each source.** A source is accepted if ALL of:
   - (a) It is a primary source (original paper, official documentation) or peer-reviewed
   - (b) Its claims are verifiable — equations can be checked, experiments can be replicated
   - (c) It is directly relevant to the implementation decision (not tangential)
   - (d) It is not contradicted by a stronger source
7. **Multiple sources required for critical decisions.** A single paper is a hypothesis.
   Cross-reference with at least one independent source before marking "accepted" for
   any constant, threshold, or algorithm choice.

### Phase 4: Rejection Logging (wu + feynman)

8. **Log every rejected source with a reason.** Categories:
   - Unreliable: blog post without citations, unverified claims, known errors
   - Irrelevant: does not apply to this context (e.g., different scale, domain, conditions)
   - Contradicted: a stronger source disagrees (cite the stronger source)
   - Unverifiable: behind paywall with no preprint, no equations shown, results not reproducible
   - Superseded: a newer publication updates or corrects this source
9. **Rejection is not deletion.** Rejected sources stay in the provenance file permanently.
   They prevent future re-investigation of dead ends.

### Phase 5: Staleness and Revisit (darwin)

10. **darwin: define staleness criteria.** For each accepted source:
    - Is it still accessible? (URL check, DOI resolution)
    - Has the content changed? (for web sources)
    - Has the field moved on? (newer publications in the same area)
11. **darwin: define revisit conditions.** Under what circumstances should this decision
    be reopened? Examples:
    - "Revisit if paper X's results are independently replicated"
    - "Revisit if performance drops below threshold Y"
    - "Revisit if dependency Z releases a major version"
    - "Revisit after 12 months regardless — field moves fast"
12. **Schedule staleness checks.** Use `provenance-manager.sh` for mechanical URL checks
    and date-based reminders.

### Phase 6: Maintenance

13. **Update on every relevant change.** When the target file is modified, review the
    provenance file: are the sources still applicable? Do new claims need new sources?
14. **Periodic review.** At project milestones, review all .provenance.md files for staleness.

## Output Format

```
## Provenance: [target path]
### Created: [date] | Author: [who] | Purpose: [why this exists]

### Sources:
| # | Type | Reference | Date | Status | Note |
|---|------|-----------|------|--------|------|

### Accepted sources (full detail):
#### [Source #]: [short name]
- Reference: [full citation]
- Claims used: [what we took from this source]
- Verification: [how we checked it]

### Rejected sources:
#### [Source #]: [short name]
- Reference: [full citation]
- Reason: [unreliable / irrelevant / contradicted / unverifiable / superseded]
- Detail: [explanation]

### Revisit conditions:
- [ ] [condition 1]
- [ ] [condition 2]

### Staleness check: [last checked date, next check date]
```
