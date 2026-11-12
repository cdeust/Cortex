---
created: 2026-11-12T07:25:00Z
kind: adr
number: 1135
status: accepted
tags: [ci, review, review-pr, evaluation, fleet]
title: Two reviewers of /review-pr are told to refute the pull request
---
# ADR-1135: Two reviewers of /review-pr are told to refute the pull request

## Status

accepted. Owner instruction 2026-11-12, after the measurement below was sent to him: correct it at once, without asking him anything. The branch it is written on has had its three reviews (ADR-1119); the session set the `claude-rereview` label on the pull request on that instruction, for the one more review the label allows.

## Context

Owner remark 2026-11-12: what was merged that day (ADR-1132, ADR-1133, ADR-1134) does not improve the review Claude does in CI.

Measured on the three pull requests of that day:

| Pull request | Errors found before it was opened, by reads launched outside CI | Blockers reported by the hosted review | Defect found after the merge |
|---|---|---|---|
| 996 | several, not counted | 0 | 1: run 43149580342 failed at "Validate ci.json" |
| 997 | 11 | 0 | 0: run 43158939841 green |
| 998 | 1 | 0 | 0: run 43169983700 green |

The hosted review approved each of them. What caught the errors ran outside CI, from an interactive session.

What the hosted review is given, read in the repository:

- `/review-pr` was twenty lines: five reviewers, each told "to only provide noteworthy feedback". Nothing asked a reviewer to check a statement against its source, or to look at what runs after the merge.
- `claude-review.yml` allows inline comments, `gh pr diff`, `gh pr view` and `gh pr comment`, on a checkout of the main branch at depth 1. The reviewers read and search; they run no command. The reviews say so themselves. On 997: "this checkout is shallow", "could not be run in this session". On pull request 521 of ai-architect-mcp-codebase: "I could not run the Python suites myself: running Python needs approval this session does not have."

Source: Anthropic, "How the Claude Code team does code review" (claude.dev, 15 October 2026). "Any incidents are now an eval. […] The reviewer runs against that set daily." "Turn incidents and reverts into an eval set, and rescore the reviewer whenever its prompts, tools or model change." "When a review misses something, we ask what the model didn't have in front of it and put the fix into a CLAUDE.md, a skill or a new check."

## Measurement

Two cases with known defects, two briefs, one agent per brief and per case, with the tools a reviewer of `/review-pr` has. The grid and the criterion were written before a report was read. Protocol, briefs, cases and limits: `docs/review-eval/README.md`.

| Case | Known defects | Current brief | Refutation brief |
|---|---|---|---|
| A: the first version pushed for 997, `documentation-accuracy-reviewer` | 7 | 0 named | 4 named, each tagged Note |
| B: 996 as merged, `code-quality-reviewer` | 1 | not named | named, tagged Blocker |
| C, a control: 998 as merged, `documentation-accuracy-reviewer` | 0 | not drawn | no Blocker, six Notes |

The refutation brief cost no more: 198 473 tokens against 188 871 on A, 249 170 against 285 616 on B.

On the control it reported no Blocker. Four of its six Notes named defects of rules 8 and 9 and of ADR-1134, merged that morning after the reviews of 998: the rules' clean copy left out a fresh clone and the Codex worktree; rule 9 let a required key leave `ci.json` while the resolver still refused its absence; after a conflict merge its replay used a validator older than the main branch's; and ADR-1134 called "the run after it" a run that was not the next one.

## Decision

1. `/review-pr` tells `code-quality-reviewer` and `documentation-accuracy-reviewer`, in addition, to try to refute the pull request: every factual statement against its primary source; for every rule, a case that follows it and fails or a harmless case it forbids; for every change to a workflow, a CI script or a file CI reads, which commit's workflow runs each job before and after the merge, and whether the tree the pull request leaves passes.
2. `docs/review-eval/` holds the evaluation set of the review. Its first two cases are those of the measurement. A change to `/review-pr`, to a reviewer, to their tools or to the model is measured against it before it is proposed, and a defect the review missed becomes a case.
3. `/review-pr` is the same file in every repository. The others take it from Cortex.
4. What a Blocker is does not change. `claude-review.yml` rates a documentation or wording gap above Note only when it states something false about security or behaviour (ADR-1119, written after pull request 856 took twenty reviews). The four defects named on case A stay Notes; the defect of case B, a run that fails after the merge, is a Blocker.
5. The four defects named on the control are corrected here, in rules 8 and 9 of `docs/agent-guidance.md` and in ADR-1134.
6. The reviewers still run no command. Whether they may run the repository's scripts is not decided here: the review job holds a token and the pull request's code would run under it.

## Consequences

- Measure: known defects named by each brief on the evaluation set, and defects found after a merge that the hosted review did not report. On 12 November 2026: 1 of 3 pull requests.
- Finding is not blocking. On case A the four defects named were tagged Note and the verdict would have stayed "approve" (decision 4). The gain on the verdict is for defects of CI, security or behaviour, as on case B.
- Not measured: the verdict the top-level reviewer writes from the reports; the variation between draws (one draw each); the three other reviewers.
- The third instruction was written from the incident of case B, which is therefore not a held-out case for it.

## Alternatives considered

- Let the reviewers run the repository's scripts, so that a step can be replayed. Not done (decision 6).
- Rate a false statement of a record as a Blocker. Not done (decision 4): it would undo the limit ADR-1119 set on review rounds.
- A sixth reviewer. Not proposed: what was measured is the two existing reviewers with another brief.
- The refutation brief for the five reviewers. Not proposed: three of them were not measured.
