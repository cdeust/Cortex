---
created: 2026-11-12T03:50:00Z
kind: adr
number: 1134
status: accepted
tags: [ci, pipeline, ci-json, validator, post-merge, contract, fleet, amends-adr-1131]
title: A pull request that changes the ci.json validator leaves a tree the earlier validator passes
---
# ADR-1134: A pull request that changes the ci.json validator leaves a tree the earlier validator passes

## Status

accepted. Adds rule 9 to the CI contract. Amends one sentence of ADR-1131: how another repository takes `low_risk_files`.

## Context

The Pipeline after merge is started by a `workflow_run` event and runs the workflow files of the default branch as they are when the event fires. Its first job, `resolve`, performs the merge. The jobs that follow therefore test the merge commit with the workflow of the commit before it. Read on the runs: run 43149580342 merged pull request 996 as `c84dfb5` and names `pipeline-post-merge.yml@f7a7690`, the tip of the main branch before that merge; run 42968565597 merged pull request 982 as `bbe537b` and names `pipeline-post-merge.yml@637f6aa`. GitHub's page on the event was not read in this session (its host is refused by the session's network); the two runs are the source.

The `contract` job of such a run validates the merge commit, its `ci.json` and the version file `ci.json` names, with the validator embedded in that earlier workflow. That validator refuses a key it does not know. A pull request that adds a key to `ci.json` together with the validator that accepts it passes its own Pipeline and fails the first job after its merge.

Measured in Cortex: the 2 pull requests that added a key to `ci.json`. GitHub lists seven commits on the file. The first creates it with six keys, the next four change command values and keep the six keys, the last two each add a key.

| Pull request | Key added | Run after merge | `resolve` | `contract`, step "Validate ci.json" |
|---|---|---|---|---|
| 982 (ADR-1131) | `low_risk_files` | 42968565597, 11 November 2026, 05:52 UTC | merged | failed: `low_risk_files: unknown key` |
| 996 (ADR-1133) | `docs_paths` | 43149580342, 12 November 2026, 03:38 UTC | merged | failed: `docs_paths: unknown key` |

In both runs `unit`, `regression`, `e2e`, `environment`, `install` and `tag` were skipped: the merge commit went through no test job, on any system.

In claude-mods, pull request 72 brought `low_risk_files` with its validator, as ADR-1131 told the other repositories to do, and its run after merge failed at the same step (run 42975150439, 11 November 2026, 06:49 UTC; the log line was not read). The runs after the same change in ai-architect-mcp-codebase (509), ai-architect-mcp-spec (207), zetetic-team-subagents (249), cortex-viz (238) and ci-autonome (32) were not read.

The step was replayed here as the workflow runs it, on a `git archive` of each tree, with the validator taken from `pipeline-post-merge.yml` at the commit named:

| Validator of | Tree of | Result |
|---|---|---|
| `637f6aa` | `bbe537b` (982 merged) | exit 1, `low_risk_files: unknown key` |
| `f7a7690` | `c84dfb5` (996 merged) | exit 1, `docs_paths: unknown key` |
| `c84dfb5` | `c84dfb5` | exit 0 |
| `c84dfb5` | `f7a7690` (996 reverted) | exit 0 |

The third line says the failure does not repeat: the next run after a merge takes its validator from `c84dfb5` or later. The fourth says a pull request may change `ci.json` and the validator together when the earlier validator passes the tree it leaves.

For 982 the next merge came two hours and thirty-five minutes later (pull request 981, run 42987212297). That run tested the three systems on a merge commit that contains `bbe537b` and ended green at 09:03 UTC.

Rule 8 arrived with 996 itself. It asks an author to run what a change needs beyond the `unit` and `regression` commands. The author of 996 did not replay this step before opening the pull request, and the reviews of the change, before and after it was opened, did not report it.

## Decision

1. Rule 9 of the CI contract: a pull request that changes the validator leaves a tree the earlier validator still passes. The validator is the script of the step "Validate ci.json", embedded in `pipeline.yml` and `pipeline-post-merge.yml`.
2. Such a pull request replays the step before it is opened: the validator as it was before the pull request's commits, on the tree after them. A pull request that leaves the validator alone needs no replay: its own `contract` job runs that validator.
3. For a key, it follows that the key enters `ci.json` in a pull request after the one that taught the validator to accept it. What fails without the key, a validator that requires it or a reader that refuses its absence, comes with the key or after it. A key the validator requires leaves `ci.json` after the validator stopped requiring it.
4. ADR-1131 said a repository that takes the two workflows "must add `low_risk_files` to its `ci.json` in the same pull request". That is the case measured on claude-mods. Such a repository first teaches its own validator to accept the keys it lacks, in a pull request of its own.

## Consequences

- A key added to `ci.json` takes two pull requests. Measure: runs of the Pipeline after merge whose `contract` job fails at "Validate ci.json". In Cortex before this rule: after 2 of the 2 pull requests that added a key.
- The rule does not forbid a pull request that changes `ci.json` and the validator when the earlier validator passes the result: a command value, or the revert of 996 in one commit.
- The replay uses the validator the branch started from. The Pipeline after merge uses the validator of the main branch at the merge. The two differ when the main branch changed its validator in between, which an author does not check (rule 4).
- Rule 9 names the validator because it is the case measured. Every other step of the Pipeline after merge also comes from the earlier commit. Whether one of them has failed for that reason was not looked for.
- `c84dfb5`, the merge commit of 996, has been through no test job after its merge. The next merge covers it: the Pipeline after merge runs the three systems on a merge commit that contains it.
- The rule is not enforced by a check.

## Alternatives considered

- The resolver validates the tree of the pull request's head with the validator of its own workflow, and refuses a merge that would fail after it. This is the check at the moment the rule speaks of. It needs the validator inside the resolver's script and adds code to the job that performs the merge. Not done here: it is a change to `pipeline-post-merge.yml`.
- The `contract` job of the Pipeline refuses a pull request whose files hold `ci.json` and one of the two workflows. Rejected: it refuses more than the defect, a command change and the one-commit revert among them, and misses a change to the version file.
- The validator accepts an unknown key after the merge. Rejected: a key that is read and ignored is a compatibility shim (CLAUDE.md, non-negotiables), and it covers the unknown key alone, not a required key that `ci.json` dropped or a version file the earlier validator cannot read.
