---
created: 2026-11-13T03:40:00Z
kind: adr
number: 1139
status: accepted
tags: [ci, review, claude-review, permissions, fleet]
title: The review command file carries no allowed-tools header
---
# ADR-1139: The review command file carries no allowed-tools header

## Status

accepted. Removes one line from the frontmatter of `.claude/commands/review-pr.md`. The workflow, its prompt and its `--allowedTools` are unchanged. It answers the third point of issue 1021. ADR-1138, which adds a step to the review workflow, is in pull request 1025 and not merged: the number is taken there.

## Context

In some runs the review does not load `/review-pr` and gives its verdict from one or two reviewers instead of the five the command lists: 3 reviews of 11 between 23:00 UTC on 12 November 2026 and 00:46 UTC on 13 November (zetetic-team-subagents run 43325391874, Cortex run 43332363652, ai-architect-mcp-spec run 43339174713), and review comments that say the same back to Cortex pull request 637 of 22 September.

The review workflow sets `track_progress: true`, which puts the pinned action in tag mode. In tag mode the prompt reaches the CLI inside a larger template and does not start with `/review-pr`, so the CLI does not expand the command: the model loads it with the `Skill` tool. The workflow's `--allowedTools` does not list `Skill`.

The job logs hide the transcript, so they do not show which call is refused. A probe does.

## Measurement

Probe of 13 November 2026, Claude Code 2.1.323, headless (`claude -p`, `--output-format json`), default permission mode, `--allowedTools "Bash(gh pr view:*)"`. Two directories that differ by one line of one file, a command `.claude/commands/probe.md` whose body asks for the word LOADED. The prompt asks the model to run that command with the `Skill` tool. One run per arm.

| Frontmatter of the command file | `permission_denials` of the result | Answer |
|---|---|---|
| `allowed-tools: Bash(gh pr comment:*),Bash(gh pr diff:*),Bash(gh pr view:*)` and `description` | `Skill`, input `{"skill": "probe"}` | REFUSED |
| `description` only | none | LOADED |

A command file that carries `allowed-tools` needs an approval when the model loads it; one that does not is loaded without one. The two arms differ by nothing else, and the decision is taken by the CLI, not sampled.

Not measured: the review job itself. It runs Claude Code 2.1.311 with `--permission-mode auto`, where a call that needs an approval is decided by Claude Code's safety review. The probe shows that the header is what sends the `Skill` call to that review; that the review then refused it in 3 runs of 11 is the reading that fits the logs (7 or 8 refused calls in those runs against 5 in the others), not an observation.

## Decision

The frontmatter of `.claude/commands/review-pr.md` keeps `description` and loses `allowed-tools`.

The three commands the header allowed, `gh pr comment`, `gh pr diff` and `gh pr view`, are allowed to the review by `--allowedTools` of `.github/workflows/claude-review.yml`, which lists the same three. `tests_py/scripts/test_ci_review_command_loads.py` holds both: no `allowed-tools` in the command file, the three commands in the workflow's list.

## Consequences

- The `Skill` call for `review-pr` no longer needs an approval, so there is nothing for the safety review to refuse.
- Someone who types `/review-pr` in an interactive session is asked before each `gh pr` command, where the header allowed them at once.
- The command file differs from the upstream one by this line, besides the brief ADR-1135 added. A later copy of the upstream file must leave the header out; the test fails if it comes back.
- The review of a pull request runs the command file of the main branch. The pull request that carries this change is reviewed with the header still in place.
- The other repositories copy this file. They take the change once it is measured here.

## What will show it worked

The share of review comments that say the command failed to load: 3 of 11 before. After the merge, the same count on the next reviews of this repository; one occurrence means the cause is elsewhere and this page is wrong.

## Rollback

`git revert` of the commit that removes the line.

## Sources

- Issue 1021 of this repository: the runs, the earlier occurrences, what the logs show and do not show.
- The probe above; its two directories and outputs are not committed.
- Pinned action `anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb`, `src/modes/detector.ts`: tag mode when `track_progress` is set on a pull request event.
- The same action, `src/entrypoints/run.ts`: `const claudeCodeVersion = "2.1.311"`, the version of Claude Code the review job installs.
- `.github/workflows/claude-review.yml`, `claude_args`.

## Corrections of 13 November 2026

Added after the review of pull request 1026.

- The version of Claude Code the review job runs, 2.1.311, had no source on this page. It is the constant of the pinned action, now listed under Sources.
- One more occurrence before the merge. The review of pull request 1026 itself (run 43357754247, 03:19 UTC) says that its `Skill` call for `/review-pr` was refused. It ran the command file of the main branch, header in place, as "Consequences" says a review of that pull request would. The reviews between 00:46 and 03:19 UTC were not counted, so the 3 of 11 above is not updated.
- `docs/verification/anthropic-workflow-source-parity-20261027.md` said that the command file matched the upstream blob byte for byte. It has not since ADR-1135; that page now lists both changes.
- `tests_py/scripts/test_ci_review_command_loads.py` compared the whole frontmatter with `{"description": ...}`, which refused any other key. It now holds what this decision needs: no `allowed-tools`, and the description.
