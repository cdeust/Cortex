---
name: verify-claim
description: >
  Verify a factual claim against multiple independent sources. No source = "I don't know";
  single source = hypothesis; multiple independent sources = provisional finding.
category: zetetic
trigger: >
  When a claim is made without a source; when a "fact" drives a decision but nobody has checked it;
  when a blog post is cited instead of the primary source; when "everyone knows" is the justification.
agents:
  - research-scientist
  - feynman
shapes: [two-independent-methods, cargo-cult-detector]
input: >
  A specific claim to verify, stated as a falsifiable proposition.
output: >
  Verification report: sources, quality, agreement, verdict (confirmed/contested/unsupported/refuted/unknown).
zetetic_gate:
  logical: "Claim must be falsifiable as stated"
  critical: "2+ independent primary sources required; read actual papers not summaries"
  rational: "Verification depth proportional to decision stakes"
  essential: "Answer the question asked; do not scope-creep into adjacent research"
composes: []
aliases: [verify, check-source]
hand_off:
  mechanism_unclear: "/rederive — feynman rederives to find understanding gaps"
  claim_about_quantity: "/estimate — fermi bounds it independently"
  claim_about_behavior: "/experiment — fisher designs an experiment"
---

## Purpose

Enforce the zetetic standard's core rule: no implementation without a source. Takes a claim, sharpens it into a falsifiable proposition, finds multiple independent sources, reads the actual sources (not summaries), checks that conditions match, and reports honestly — including "I don't know."

## When to Use

- A team member states a "fact" that will drive a design decision.
- An algorithm, threshold, or constant is cited without a source.
- A single blog post or StackOverflow answer is the basis for a technical choice.
- "Everyone knows that X" appears in a discussion.
- A number is hardcoded with no documented origin.

## Procedure

1. **Sharpen.** Restate as a specific, falsifiable proposition with conditions. Refuse vague claims.
2. **Search.** research-scientist finds 2+ independent primary sources (papers, specs, benchmarks).
3. **Read.** Extract exact statements from each source, including conditions and caveats. No abstracts, no summaries.
4. **Cross-reference.** Do sources agree? Are they truly independent (different lab/dataset/methodology)?
5. **Mechanism check (if needed).** feynman rederives the claimed mechanism from first principles.
6. **Verdict.** Confirmed (2+ agree, conditions match) / Contested (disagree) / Unsupported (0-1 sources) / Refuted (2+ contradict) / Unknown ("I don't know").

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Claim is falsifiable | Refuse; ask user to sharpen |
| Critical | 2+ independent primary sources | Verdict = "unsupported" if only 0-1 |
| Critical | Actual papers read, not summaries | Reject blog-post-only evidence |
| Rational | Depth proportional to stakes | Quick check for low-stakes; full procedure for high-stakes |
| Essential | Answer the question asked | Stop at verdict; no scope-creep |

## Output Format

```
## Claim (sharpened): [falsifiable proposition]

## Sources
| # | Source | Type | Year | Finding | Conditions match? |
|---|--------|------|------|---------|-------------------|

## Independence: [truly independent? same lab/dataset?]
## Mechanism: [rederivable? understanding gap?]
## Verdict: [Confirmed / Contested / Unsupported / Refuted / Unknown]
## Confidence: [why this verdict; what would change it]
```

## Hand-offs

| Condition | Next skill | Reason |
|-----------|------------|--------|
| Mechanism unclear | `/rederive` | Find understanding gaps |
| Claim involves a quantity | `/estimate` | Bound independently |
| Claim about behavior | `/experiment` | Design a test |
| Claim about code | `/prove-correct` | Prove, don't cite |

## Anti-patterns

- Accepting a single source as proof.
- Reading abstracts instead of papers.
- Blog post as primary source.
- Ignoring a negative verdict because the claim is convenient.
- Over-verifying low-stakes claims at the cost of high-stakes ones.
