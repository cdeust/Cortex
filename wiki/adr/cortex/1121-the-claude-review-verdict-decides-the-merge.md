---
created: 2026-11-04T23:30:00Z
kind: adr
number: 1121
status: accepted
tags: [ci, claude, review, merge, amends-adr-1115]
title: The Claude review verdict decides the merge
---
# ADR-1121: The Claude review verdict decides the merge

## Status

accepted. Amends ADR-1115 and the owner rule of 2026-10-29 (the review never gates the merge), which this reverses for the Claude review only. Follows ADR-1119 (three reviews, `Verdict:` line) and ADR-1120 (Codex out of the CI).

## Context

Owner directive 2026-11-04, "comme le CI Anthropic": the Claude Code reviewer dictates the merge. Until now `pipeline-post-merge.yml` squash-merged any PR whose Pipeline was green, whatever the review said. PR 868 was merged by `github-actions[bot]` at 22:03:33Z while its review comments were still open for follow-up; a `Verdict: block` would not have stopped it.

## Decision

1. Before its merge call, the resolver of `pipeline-post-merge.yml` requires `_review_approves`: a successful `claude-review.yml` run of the exact head SHA whose `Claude review` job succeeded at the `PR Review` step, and a comment by `claude[bot]` (type Bot) that links that run id and whose last `Verdict:` line is `approve`. The latest such comment wins. The run link binds the verdict to the head: a late review of an older head links another run, and a run that skipped the review (past the cap) has no successful `PR Review` step. First version (timestamp binding) merged PR 870 over its own `Verdict: block`; a review finding showed the race, see Consequences.
2. No review run, a failed run, a verdict older than the head's review, a verdict by anyone else, or `Verdict: block` holds the merge: the resolver exits non-zero with a `merge held:` message. No fallback merge.
3. The test jobs remain required; this is an addition, not a replacement.
4. After the third review (ADR-1119) no review runs on a new head, so the PR is not merged by the bot: the owner merges the accepted part and the rest goes to a refinement PR.

## Consequences

- Metric: PRs merged by the bot without a `Verdict: approve` on their head: 0 (was every PR).
- The resolver runs once, when the Pipeline completes. If the review has not finished by then, the merge is held and `Pipeline after merge` must be re-run once the verdict is posted. The review takes about 4 minutes against about 25 for the Pipeline, so this is the exception.
- PR 870 introduced this gate and was merged at 23:00Z by the previous resolver while its review said `Verdict: block` (a late approve of an older head could merge a newer one). The binding to the run id and the `PR Review` step fixes it; the tests cover both traced scenarios.
- A PR that edits `claude-review.yml` or `claude.yml` is not reviewed by the action (it refuses a workflow that differs from main), so it is never merged by the bot.
