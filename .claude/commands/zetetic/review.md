# Quick Review

Fast review of staged changes. Critical findings only — no style nits.

## Instructions

1. Get the staged diff: `git diff --cached`

2. Review for critical issues ONLY:
   - Layer boundary violations (core importing infrastructure)
   - Security vulnerabilities (injection, auth bypass, secret exposure)
   - Correctness bugs (wrong logic, missing error handling for real cases)
   - SOLID violations that affect correctness (LSP breaks, leaky abstractions)

3. Skip: style, naming, formatting, minor improvements. This is the fast pass.

4. For each finding: file:line, what's wrong, why it matters, suggested fix.

5. If no critical findings, say "No critical issues in staged changes."

$ARGUMENTS
