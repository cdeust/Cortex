---
name: review
description: >
  Code review enforcing Clean Architecture, SOLID principles, layer boundary integrity,
  and the zetetic standard — every violation cites the specific principle and code location.
category: engineering
trigger: >
  When a PR needs review; when code has changed and nobody has checked architectural integrity;
  when "it works in tests" is the only defense for a merge.
agents:
  - code-reviewer
  - architect
shapes: []
input: A PR, a diff, or a set of changed files to review.
output: >
  Review report: violations by category (layer, SOLID, anti-pattern, security), each with
  file:line, principle violated, and suggested fix.
zetetic_gate:
  logical: "Every violation must cite the specific principle"
  critical: "Review the actual code, not the description of the code"
  rational: "Severity proportional to consequence — critical-path bugs > style nits"
  essential: "Flag only what matters; do not generate noise"
composes: []
aliases: [code-review, pr-review]
hand_off:
  security_finding: "/secure — security-auditor does a deep dive"
  architecture_violation: "/decompose — architect proposes restructuring"
  correctness_doubt: "/prove-correct — dijkstra verifies the logic"
---

## Purpose

Review code changes for Clean Architecture violations (wrong dependency direction, core importing infrastructure), SOLID violations (god classes, LSP breaks, leaky abstractions), anti-patterns (swallowed errors, untyped dicts, dead code), and security issues. Every finding cites the principle and the exact code location.

## Procedure

1. **code-reviewer reads the diff.** Identifies all changed files and their architectural layer.
2. **Layer audit.** For each changed file: does it import only from allowed layers? (Core → shared only; infrastructure → shared only; handlers → core + infrastructure.)
3. **SOLID audit.** For each changed class/module: SRP (one reason to change?), OCP (extension over modification?), LSP (subtypes substitutable?), ISP (focused interfaces?), DIP (core defines, infrastructure implements?).
4. **Anti-pattern scan.** Swallowed errors, magic numbers, grab-bag utils, dead code, backward-compat shims.
5. **Security scan.** Input validation at boundaries, injection vectors, secret exposure.
6. **architect reviews** structural changes (new modules, moved files, changed boundaries).
7. **Report.** Each finding: file:line, category, principle violated, severity, suggested fix.

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Every finding cites the principle | Remove findings without a principle |
| Critical | Review the actual diff, not the PR description | Re-read the code if review was summary-based |
| Rational | Critical-path findings before style nits | Reorder by severity |
| Essential | No noise — only actionable findings | Cut findings that don't affect correctness or maintainability |

## Output Format

```
## Code Review: [PR/files]

### Critical (blocks merge)
| # | File:Line | Category | Principle | Issue | Fix |
|---|-----------|----------|-----------|-------|-----|

### Important (should fix before merge)
| # | File:Line | Category | Principle | Issue | Fix |
|---|-----------|----------|-----------|-------|-----|

### Minor (optional, improve later)
| # | File:Line | Category | Principle | Issue | Fix |
|---|-----------|----------|-----------|-------|-----|

### Architecture assessment
[Does this change respect layer boundaries? Any structural concerns?]
```

## Anti-patterns

- Reviewing the PR description instead of the code.
- "LGTM" without reading the diff.
- Style nits drowning out real issues.
- Findings without a cited principle ("this feels wrong" is not a review).
