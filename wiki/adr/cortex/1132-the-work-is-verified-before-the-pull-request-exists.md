---
created: 2026-11-12T01:54:00Z
kind: adr
number: 1132
status: accepted
tags: [ci, contract, review, pull-request, verification, rollback, fleet]
title: The work is verified before the pull request exists
---
# ADR-1132: The work is verified before the pull request exists

## Status

accepted. Adds rule 8 to the CI contract of `docs/agent-guidance.md` and a "Risk and rollback" section to the pull request template. It changes no workflow and no gate.

The number 1132 was first given, in the same session, to a decision that was withdrawn before it was pushed (a job that reverts a merge whose tests fail). Section 3 of the design journal of `cdeust/ci-autonome` cites "Cortex ADR-1132" with that earlier meaning.

## Context

Owner request 2026-11-12: bring the CI to the practice Anthropic and Meta describe.

The contract already holds the review side of that practice: three reviews per pull request (ADR-1119), one push per verdict, a verdict tied to the head. It says nothing about what an author does before the pull request exists, and the template asks for a test plan but not for the risk of the change or the way to undo it.

Two measurements show the cost of that gap.

- `cdeust/ci-autonome`, 11 November 2026, 22:59 to 23:45 UTC: one agent session caused 9 Pipeline runs for 6 commits. Three of the nine ran a commit a second time (the pull request was opened as a draft and marked ready once the first run had ended). Two more were for one-file journal entries pushed alone to an open pull request.
- `cdeust/Cortex`, 600 workflow runs from 10 November 04:56 to 12 November 00:13 UTC: 21 of the 69 Pipeline runs on pull requests were cancelled by a later push (30 %), 282 minutes in all.

Source: Anthropic, "How the Claude Code team does code review" (claude.dev, 15 October 2026). "Most review now happens before a PR exists. We give Claude something it can run [...] and ask it to show the output instead of saying it's done." Its adoption list asks to "add 'Testing', 'Risk' and 'How to revert' to your PR template".

## Decision

1. Rule 8 of the CI contract: before opening a pull request, and before each push to one, the author runs the `unit` and `regression` commands of `ci.json` on a clean copy of the commit, plus what the change needs beyond them, and puts each command with its passed, failed and skipped counts in the pull request body.
2. A command the session cannot run is named in the body with the reason. After a conflict merge under rule 4, the touched tests are enough.
3. A journal, changelog or documentation entry is pushed with the change it records. Documentation is pushed alone only to fix a Blocker.
4. The pull request template gains "Risk and rollback": what the change can break, and the command or step that undoes it.

## Consequences

- The hosted Pipeline stays the gate. It is no longer the first place a change is run.
- A pull request body carries evidence a reviewer can replay, and the way back if the merge is wrong.
- The rule binds authors; no workflow enforces it. The measurements above are the baseline: Pipeline runs per tested commit, and the share of Pipeline runs cancelled by a later push.
- Not every session can run `unit`. Measured in a cloud session on 12 November 2026: the dependency download of `uv sync` was refused by the session's network, and `scripts/ci_unit.sh` starts PostgreSQL with `initdb`, which refuses the root user. For such a session the rule asks for a statement, not a run.
- Not covered: a draft marked ready after its run has ended runs the whole Pipeline again on the same commit, because `ready_for_review` is one of its triggers.
- Running fewer jobs for a change that cannot affect them is decided in ADR-1133.
