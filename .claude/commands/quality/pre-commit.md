# Pre-Commit Quality Check

Run zetetic pre-commit checks manually on staged files.

## Instructions

1. Run `tools/zetetic-checker.sh --staged`

2. Report all findings: magic numbers, unsourced claims, TODOs without difficulty-book references.

3. For each finding, suggest the fix (add `# source:` annotation, reference the difficulty book, etc.).

4. Run `tools/difficulty-book-manager.sh check` and report if any hardest case is unaddressed.

$ARGUMENTS
