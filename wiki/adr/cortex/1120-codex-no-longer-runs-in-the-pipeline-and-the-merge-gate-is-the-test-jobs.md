---
created: 2026-11-04T22:30:00Z
kind: adr
number: 1120
status: accepted
tags: [ci, codex, claude, review, amends-adr-1116]
title: Codex no longer runs in the pipeline and the merge gate is the test jobs
---
# ADR-1120: Codex no longer runs in the pipeline and the merge gate is the test jobs

## Status

accepted. Supersedes the Codex parts of ADR-1116 (the `review` job of `pipeline.yml` and `Codex.yml`). The Codex product plugin (ADR-1081, ADR-1085) is unaffected.

## Context

Owner directive 2026-11-04: Codex stays out of the CI while it does not work autonomously there; a PR must pass the tests, the e2e tests and the mutation testing; the Claude review bot (Anthropic's `claude-code-action`) is the reviewer.

Measured on main on 2026-11-04, before this change:

- `pipeline.yml` was 1690 lines, 891 of them the `review` job, which embedded the Codex reader scripts as heredocs and reported a pending Codex review as a failed job.
- 11 of the last 18 Pipeline runs showed a red `review` although every test job was green.
- `Codex.yml` ran on a five-minute cron plus `issue_comment` and `workflow_run` events only to resume that waiting job.
- The review needs the ChatGPT Codex GitHub App to answer in time; nothing in the repository can make it do so, so the gate depended on an external actor.

## Decision

1. Delete the `review` job from `pipeline.yml` and delete `.github/workflows/Codex.yml`. The Pipeline jobs are `contract`, `unit`, `regression`, `e2e`, `environment`, `install`, `merge`, `tag`.
2. `merge` stays the aggregate of the test jobs only. `scripts/ci_pipeline_profiles.py` no longer lists a `review` job, so `check_ci_gate_complete.py` rejects its reintroduction.
3. The only automatic reviewer is the Claude workflow (`claude-review.yml`, capped at three reviews by ADR-1119).
4. The `scripts/ci_codex_*` modules stay: the local autopilot (`ci_autopilot_*`) still imports them. Removing the autopilot is a separate decision of the owner.

## Consequences

- Metric: `pipeline.yml` 1690 to 799 lines; Pipeline runs with a red review job 11 of 18 to 0; scheduled runs of the Codex completion workflow (every five minutes) to 0.
- Codex findings no longer block or delay a merge. A Codex review can still be run locally by the author before pushing.
- Mutation testing on PRs and a bot-driven merge are separate changes (next PRs); until the first lands, mutation is not part of the PR gate.
