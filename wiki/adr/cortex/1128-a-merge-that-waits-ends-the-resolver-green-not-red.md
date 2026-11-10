---
created: 2026-11-10T06:30:00Z
kind: adr
number: 1128
status: accepted
tags: [ci, merge, resolver, amends-adr-1127]
title: A merge that waits ends the resolver green, not red
---
# ADR-1128: A merge that waits ends the resolver green, not red

## Status

accepted. Amends ADR-1127 (the review's completion wakes the resolver as the Pipeline's does).

## Context

Since ADR-1127 each pull request head wakes the resolver twice, and the wake-up that comes first is held: no verdict yet, or no Pipeline yet. The resolver ended those runs with exit code 1, so `Pipeline after merge` showed a failed run on the default branch for every head that merged normally, and one more for every head a later push replaced. On 2026-11-10 ai-architect-mcp-spec showed four failed runs of `Pipeline after merge` on `main` in 30 minutes (runs 42760396148, 42761592374, 42762089329, 42763216215: "PR head advanced after testing" and "merge held: no Claude review ran on this head") while nothing was broken. The owner read them as the CI being in error. ADR-1127 recorded this red run as "the expected trace of the order"; a trace that reads as a failure hides the real ones.

## Decision

1. A resolver that does not merge because the merge waits ends with exit code 0 and one notice, `Merge not made: <reason>`. The waiting reasons are every `merge held: ...` refusal and `PR head advanced after testing`.
2. It writes no output. `contract` already requires `run_tests == 'true'`, and `close-issues` now requires a `pr_number`, so no job runs after a waiting resolver and the run is green with skipped jobs.
3. Every other refusal still fails the run: a wrong source run, a red or missing required job, an owner hold (`hold`, `do-not-merge`, a "do not merge" title), a closed or draft pull request, a merge GitHub did not confirm, an API error.

## Consequences

Positive: a red `Pipeline after merge` on the default branch now means something is wrong. The reason a merge waits stays readable, as a notice on the run.

Negative: a pull request held by a `Verdict: block` no longer leaves a red resolver run; the verdict is on the pull request itself. A pull request that waits forever (its review budget is used and no verdict exists) shows no red run either; it is found by its age, not by a failure.

Tests: `tests_py/scripts/test_ci_held_merge_is_not_a_failure.py`, `tests_py/scripts/test_ci_pipeline_routes.py` (the `close-issues` condition).
