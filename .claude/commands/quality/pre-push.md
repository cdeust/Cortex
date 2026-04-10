# Pre-Push Review

Run the full review skill on all changes since last push.

## Instructions

1. Determine the remote tracking branch.

2. Compute the diff: `git diff <tracking>...HEAD`

3. Run the `/review` skill (skills/engineering/review.md) on the diff.

4. If critical findings exist, list them and recommend fixing before push.

5. Run `tools/zetetic-checker.sh --files` on all changed files.

6. Report: review findings + zetetic violations + recommendation (push / fix first).

$ARGUMENTS
