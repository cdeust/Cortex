# Evaluation set of the pull request review

Pull requests whose defects are known. A change to `/review-pr`, to one of its reviewers, to
their tools or to the model is measured against them before it is proposed (ADR-1135).

Source: Anthropic, "How the Claude Code team does code review" (claude.dev, 15 October 2026):
"Turn incidents and reverts into an eval set, and rescore the reviewer whenever its prompts,
tools or model change."

## Protocol

- One agent per brief and per case, of the type the case names, with the tools that type has
  in `.claude/agents/`: it reads and searches, it runs no command. That is what a reviewer of
  `/review-pr` has in `claude-review.yml`.
- The agent is given the pull request as one file (its description, then its diff) and a
  worktree of the commit before it. It is told to read nothing else, and on the web only
  what the pull request cites, nothing created after the pull request.
- The agent reports its findings, each tagged Blocker or Note, and every file and URL it
  read. A source outside the two paths voids the draw.
- The grid (the known defects) and the decision criterion are written before a report is
  read.
- Score: the number of known defects the report names, in any words. A finding the source
  contradicts is counted apart.

## Briefs

Both begin: "You are one of the reviewers that the command `/review-pr` of the repository
cdeust/Cortex starts for a pull request", then name the two paths and the constraints above.

**Current brief** (what `/review-pr` said before ADR-1135): "Review the pull request below
and only provide noteworthy feedback."

**Refutation brief**: "Your job is to try to REFUTE the pull request below, not to confirm
it", followed by the three instructions `/review-pr` now gives (factual statements against
their primary source; a case that follows each rule and fails, or a harmless case it
forbids; which commit's workflow runs each job before and after the merge).

## Case A: a record with false statements

- Pull request: `case-a-pull-request.md`, the first version pushed for pull request 997
  (commit `d5c8d42`, documentation only: ADR-1134 and rule 9 as first written).
- Commit before it: `31a780d`, whose tree is that of `c84dfb5`.
- Agent: `documentation-accuracy-reviewer`.
- Known defects, found before the pull request was opened by reads launched outside CI:
  1. The rule speaks of `ci.json` alone. The validator also reads the version file, so a
     pull request that changes the validator and that file fails after its merge and no
     replay is asked.
  2. "That first pull request changes the validator and nothing that reads the key" forbids
     a reader that accepts the key's absence, which is harmless.
  3. "It is a change to both workflows" is false: the resolver is in
     `pipeline-post-merge.yml` alone.
  4. "Their merge commit had no test after the merge" is false for pull request 982: the
     same text says a later run tested a commit that contains it.
  5. The list of runs not read leaves out ai-architect-mcp-codebase 509.
  6. "The two copies of the validator would differ" is unsupported.
  7. "No test after its merge" is false to the letter: the `contract` job ran its guard test
     before it failed.

## Case B: a defect that showed after the merge

- Pull request: Cortex 996 as merged, commit `c84dfb5` on the main branch. Its file is the
  commit message, then `git show c84dfb5`.
- Commit before it: `f7a7690`.
- Agent: `code-quality-reviewer`.
- Known defect: the pull request adds the key `docs_paths` to `ci.json` together with the
  validator that accepts it. The Pipeline after merge runs the workflow of the commit before
  the merge, whose validator refuses the key: run 43149580342 failed at "Validate ci.json"
  and its test jobs were skipped. The hosted review approved the pull request (review 1 of
  3) and the Codex review reported nothing.

## Results of 12 November 2026

| Case | Known defects | Current brief | Refutation brief |
|---|---|---|---|
| A | 7 | 0 named. "No BLOCKER", four Notes. | 4 named (1 to 4), each tagged Note. "No BLOCKER". |
| B | 1 | Not named. One Blocker of another kind: a false sentence of ADR-1133. | Named, tagged Blocker, with the remedy: the validator first. |

| Draw | Tokens | Seconds |
|---|---|---|
| A, current brief | 188 871 | 564 |
| A, refutation brief | 198 473 | 608 |
| B, current brief | 285 616 | 1 036 |
| B, refutation brief | 249 170 | 818 |

Each draw listed what it read: no file outside its two paths, and on the web only runs,
commits and pull requests its case cites.

Criterion, written before the reports were read: the refutation brief names at least three
more known defects on case A, and names the defect of case B when the current brief does
not. Met: four more on A; B named by the refutation brief alone.

## What this does not show

- One draw per brief and per case: no measure of the variation between draws.
- The third instruction of the refutation brief was written from the incident of case B, so
  B is not a held-out case for it. Case A was not used to write the brief.
- Finding is not blocking. On case A the four defects named were tagged Note and the verdict
  would have stayed "approve".
- Only the reviewer's own report is measured. In CI the top-level reviewer then keeps what
  it deems noteworthy and writes the verdict; that step was not run.
- The three other reviewers of `/review-pr` were not measured.
