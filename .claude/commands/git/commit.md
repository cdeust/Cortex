# Zetetic Commit

Create a git commit that meets the zetetic standard.

## Instructions

1. **Pre-commit checks.** Run `tools/zetetic-checker.sh --staged` on all staged files.
   If violations found, list them and ask the user to fix. Do NOT commit with violations.

2. **Difficulty book check.** Run `tools/difficulty-book-manager.sh check`.
   If hardest case is unaddressed AND staged files touch that area, warn the user.

3. **Generate commit message.** Analyze the staged diff:
   - Format: `<type>(<scope>): <description>`
   - Types: feat, fix, refactor, test, docs, perf, chore
   - Description states WHAT changed and WHY
   - If the change addresses a difficulty-book entry, add `Difficulty-Book: #N addressed` in the footer

4. Present the message for approval, then commit.

5. If the user provided a message in $ARGUMENTS, use it as description but still enforce format and checks.

$ARGUMENTS
