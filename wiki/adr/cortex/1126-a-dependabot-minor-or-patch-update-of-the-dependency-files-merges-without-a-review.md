---
created: 2026-11-09T22:30:00Z
kind: adr
number: 1126
status: accepted
tags: [ci, review, merge, dependabot, risk-tier, amends-adr-1121]
title: A Dependabot minor or patch update of the dependency files merges without a review
---
# ADR-1126: A Dependabot minor or patch update of the dependency files merges without a review

## Status

accepted. Amends ADR-1121 (the Claude review verdict decides the merge): one class of change no longer needs a verdict.

## Context

ADR-1121 makes the resolver of `pipeline-post-merge.yml` merge a pull request only on a `Verdict: approve` bound to the review run of its head. `claude-review.yml` does not review a pull request whose actor is `dependabot[bot]` (GitHub gives those runs no secrets). So no Dependabot pull request could ever merge without the owner: on 2026-11-09, #931, #933, #934, #935 and #949 were green, mergeable and held, the oldest for two days.

Anthropic describes the same problem and its answer in "Solving code review at Anthropic" (https://claude.dev/blog/solving-code-review-at-anthropic/): a risk tier is set from the change, not from the author's word; a low-risk change needs no human once the automated and security checks pass; some paths, CI workflow files among them, always need a person.

## Decision

1. The resolver computes a tier from the change itself. A pull request is low risk when all of these hold:
   - its author is `dependabot[bot]`, it has exactly one commit, and every commit is authored by `dependabot[bot]`, committed by GitHub (`web-flow`) and carries a verified signature. The author alone is a declared e-mail and `verified` vouches for the committer's key, so a commit a person signs under Dependabot's name is refused;
   - every `update-type` its commit messages declare is `version-update:semver-minor` or `version-update:semver-patch`, and every dependency the commit names declares one;
   - every file it changes is `uv.lock` or `pyproject.toml`, a renamed file counting under both of its names.
2. A low-risk pull request merges without a Claude verdict. Everything else of the merge path is unchanged: the `Pipeline` run of the head succeeded, the branch protection still requires `merge` and `CodeQL`, and a `hold` or `do-not-merge` label or a "do not merge" title still holds it.
3. Any other pull request keeps ADR-1121. That includes a Dependabot major update, a Dependabot update of a workflow or a Dockerfile, and a Dependabot branch someone else pushed to.
4. The rule lives in the resolver, which runs from `main` through `workflow_run`: a pull request cannot change its own tier.

## Consequences

Positive: minor and patch dependency updates no longer wait for the owner; the supply-chain gate stays where it was (required tests on three OS, CodeQL, the lock diff only).

Negative: a minor or patch release that breaks behaviour the tests do not cover reaches main unreviewed. Reverts and incidents after such merges are the guardrail to watch; if they appear, the tier is narrowed here.

Tests: `tests_py/scripts/test_ci_low_risk_tier.py` (each condition alone refuses the tier; a low-risk pull request merges with no review run; any other is held with "no Claude review ran on this head"; a hold label still holds).
