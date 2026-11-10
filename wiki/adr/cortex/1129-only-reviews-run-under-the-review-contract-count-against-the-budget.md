---
created: 2026-11-10T06:55:00Z
kind: adr
number: 1129
status: accepted
tags: [ci, review, budget, amends-adr-1119]
title: Only reviews run under the review contract count against the budget
---
# ADR-1129: Only reviews run under the review contract count against the budget

## Status

accepted. Amends ADR-1119 (three automatic Claude reviews per pull request).

## Context

The budget counted every successful run of `claude-review.yml` on a pull request whose `PR Review` step succeeded. A pull request opened before a repository received the review contract (the cap of ADR-1119, then the `Verdict:` line the merge waits for, ADR-1121) had been reviewed by the earlier workflow, sometimes more than four times, and none of those reviews posted a verdict. After the contract arrived its budget was already used: the review was skipped on every new head, no verdict could exist, and the resolver held the merge for ever. The label `claude-rereview` did not help, since it grants a fourth review and never a fifth. Measured on 2026-11-10: ai-architect-mcp-spec #182, #184, #181 and ai-architect-mcp-codebase #484, #481, #478, #476 were in that state; #182 had four earlier reviews (runs 42706154534, 42707023304, 42708329495, 42709055781) and its relabelled, reopened run 42769093930 still ended "3 of 3 reviews used".

## Decision

A run counts as a review only if it ran under the contract: it contains the `Claude review budget` job, which the earlier workflow did not have, and its `PR Review` step succeeded. The script still reads run metadata only.

## Consequences

Positive: a pull request older than the contract gets the same three reviews as a new one, and so can receive a verdict; no date, no per-repository switch, no label is needed.

Negative: in a repository that had the cap before the verdict line (Cortex, between ADR-1119 and ADR-1121), reviews of that interval count although they carry no verdict; such a pull request still needs the label for one more review.

Tests: `tests_py/scripts/test_ci_review_budget.py` (`test_a_review_of_the_workflow_before_the_contract_does_not_count`, `test_the_budget_job_name_is_the_workflow_s`).
