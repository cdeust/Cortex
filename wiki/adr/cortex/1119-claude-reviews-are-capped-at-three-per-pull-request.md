---
created: 2026-11-04T20:00:00Z
kind: adr
number: 1119
status: accepted
tags: [ci, claude, review, amends-adr-1117]
title: Claude reviews are capped at three per pull request
---
# ADR-1119: Claude reviews are capped at three per pull request

## Status

accepted. Amends ADR-1117 (official Anthropic direct PR review workflow). The checked-in `review-pr` command and its five reviewer agents stay the verbatim upstream copy; this ADR adds only the documented `prompt` input and one read-only job.

## Context

PR 856 (a fix of the owner-mention workflow) received 20 automatic Claude review runs for 23 commits and 24 Claude comments, answered by 22 author comments, 47 issue comments in total plus 6 inline comments. Measured on 2026-11-04:

- 22 of the 24 Claude comments state "nothing blocks merge"; each was nevertheless followed by a push, and every push (`synchronize`) started a full new review.
- Codex reviewed the same PR three times and its three P1 findings were real defects that failed deterministically (the build backend `hatchling` absent when build isolation is disabled, the `null` and `{}` guard fixtures failing their own test, and the editable-build dependency `editables` missing from the locked install). Claude's reviews after the first rounds rated docstring wording, CHANGELOG wrap width and assertions about assertions as Medium or Low.
- The diff grew from the intended fix to +655/-141 lines; most of the growth is tests of the tests added in answer to earlier Low findings, which the next review then reviewed.
- `review-pr.md` asks for "noteworthy" feedback with no severity definition and no stopping rule, and each run re-audits the whole PR with no memory of earlier rounds.

A reviewer without a definition of "blocker" never converges, and an author who answers every finding with a push feeds it.

## Decision

1. At most three automatic Claude reviews per PR. A new read-only job `budget` in `claude-review.yml` runs `scripts/ci_review_budget.py` from trusted main: it counts earlier successful runs of the same PR whose step `PR Review` itself succeeded. At the cap the `review` job is skipped, with no PR comment, and a notice states what to do.
2. At the cap nothing further is reviewed. The accepted part merges. What is not accepted does not enter the PR: it is removed and sent to a new refinement PR, which has a new budget of three.
3. The label `claude-rereview` raises the cap from three to four while it is attached: one more review, never a fifth, so it cannot restore the loop. It is the owner's lever, not the author's default.
4. The `prompt` input carries a severity contract: findings only for Blockers (a defect traced or reproduced in the diff that makes CI, security or a CLAUDE.md non-negotiable wrong), at most three one-line Notes, no Medium for wording or test-coverage gaps, round 2 and 3 check earlier Blockers then review only the commits pushed since the previous review, the last review names the accepted part, and the review ends with `Verdict: approve` or `Verdict: block`.
5. Author protocol (`docs/agent-guidance.md`, "Review rounds"): push only on a Blocker, fix all Blockers of a round in one push, post no "pushed X" comment (the commit message is the record), and keep a PR that edits CI to its stated object.

## Consequences

- Metric: automatic Claude reviews per PR at most 3 (was 20 on PR 856); pushes caused by a non-Blocker 0.
- The review stays non-blocking for merge (owner rule 2026-10-29). The verdict line makes a later required check possible without changing the contract.
- A PR that edits `claude-review.yml` is not reviewed by the action (it refuses a workflow that differs from main), so this change itself carries the Codex reviews only.
- Two pushes in quick succession can both read a count of two and start four reviews in total. The budget is a bound on the steady state, not a lock.
- ADR-1117 asked for the official layout. The deviation is one job of about 25 lines and one script; the verbatim command, agents and action invocation are unchanged.
