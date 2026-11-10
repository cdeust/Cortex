---
created: 2026-11-10T01:40:00Z
kind: adr
number: 1127
status: accepted
tags: [ci, review, merge, resolver, amends-adr-1121]
title: The review's completion wakes the resolver as the Pipeline's does
---
# ADR-1127: The review's completion wakes the resolver as the Pipeline's does

## Status

accepted. Amends ADR-1121 (the Claude review verdict decides the merge).

## Context

`pipeline-after-merge.yml` called the resolver on the completion of `Pipeline` only. The resolver reads the verdict once, without polling (ADR-1121). So the merge depended on an order: the review had to end before the Pipeline. In Cortex the Pipeline lasts about 30 minutes and the review 3 to 4, so the order held. It does not hold in a repository whose Pipeline is shorter than its review, nor when the review is queued behind runners: the Pipeline ends, the resolver finds no verdict and holds the merge, and nothing wakes it when the `Verdict: approve` arrives. The pull request stays open until someone re-runs the Pipeline or merges by hand. Codex reported it on the pull requests that replicate this CI (ai-architect-mcp-codebase #486, ai-architect-mcp-spec #185).

## Decision

1. `pipeline-after-merge.yml` listens to the completion of both `Pipeline` and `PR Review`.
2. Woken by a review, the resolver takes as its source the newest successful `pull_request` run of `pipeline.yml` on the review's head. That run then goes through every check the Pipeline's own completion goes through (run identity, exact job results, pull request identity, verdict or low-risk tier). Without such a run the merge is held: the Pipeline's completion will wake the resolver.
3. A pull request already merged when the review ends is left alone: the wake-up that merged it tests the merge commit.
4. The review run must itself be a completed, successful `pull_request` run of `claude-review.yml` from this repository; a review that was skipped by its budget wakes the resolver too and is held by ADR-1121 as before.

## Consequences

Positive: the merge no longer depends on which workflow finishes first; no polling is added.

Negative: each pull request head wakes the resolver twice. The wake-up that comes first is held and ends in failure (no verdict yet, or no Pipeline yet), which is the expected trace of the order, not a defect.

Tests: `tests_py/scripts/test_ci_review_wakes_resolver.py`, `tests_py/scripts/test_ci_pipeline_routes.py` (the caller's event contract).
