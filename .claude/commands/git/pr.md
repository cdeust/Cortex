# Zetetic Pull Request

Create a pull request with zetetic-standard review and documentation.

## Instructions

1. Run the `/review` skill (skills/engineering/review.md) on all changes vs the base branch.

2. Generate a PR description:
   ```
   ## Summary
   [1-3 bullet points of what changed and why]

   ## Zetetic Checklist
   - [ ] No invented constants (zetetic-checker passed)
   - [ ] Sources cited for non-trivial claims
   - [ ] Difficulty book updated (if applicable)
   - [ ] Tests cover new behavior
   - [ ] Layer boundaries respected

   ## Review findings
   [Summary of /review output — critical items must be resolved before merge]
   ```

3. Push the branch and create the PR with `gh pr create`.

4. Report the PR URL.

$ARGUMENTS
