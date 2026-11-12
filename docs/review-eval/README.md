# Evaluation set of the pull request review

Pull requests whose defects are known. A change to `/review-pr`, to one of its reviewers, to
their tools or to the model is measured against them before it is proposed (ADR-1135).

Source: Anthropic, "How the Claude Code team does code review" (claude.dev, 15 October 2026):
"Turn incidents and reverts into an eval set, and rescore the reviewer whenever its prompts,
tools or model change."

## Protocol

- One agent per brief and per draw, of the type the case names, with the tools that type has
  in `.claude/agents/`: it reads and searches, it runs no command. That is what a reviewer of
  `/review-pr` has in `claude-review.yml`.
- The model is the one `claude-review.yml` pins, asked for by the alias the session's
  harness has for it (see the limits). The reviewers' definitions say
  `model: inherit`, so an agent started from an interactive session runs on that session's
  model unless the model is given: the first series below was drawn that way and is kept
  apart.
- The agent is given the pull request as one file (its description, then its diff) and a
  worktree of the commit before it. It is told to read nothing else, and on the web only
  what the pull request cites, nothing created after the pull request.
- The agent reports its findings, each tagged Blocker or Note, and every file and URL it
  read. A source outside the two paths voids the draw.
- The grid (the known defects) and the decision criterion are written before a report is
  read.
- Score: the number of known defects the report names, in any words. A finding the source
  contradicts is counted apart.
- A draw is asked to tag as Blocker "a defect that makes CI, security or a rule of the
  repository wrong, or a statement that is false" (the refutation brief adds "or
  unsupported"). That is wider than the definition of `claude-review.yml`, so a tag in a
  draw does not predict the hosted verdict.

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

## Case C: a control, with no known defect

- Pull request: `case-c-pull-request.md`, Cortex 998 as merged (commit `d4df0ab`,
  documentation only): its title and body, then its diff. A read outside CI, whose one
  blocker was corrected before the pull request was opened, and the hosted review had left
  it with no known false statement.
- Commit before it: `7183492`.
- Agent: `documentation-accuracy-reviewer`.
- What it measures: whether a brief reports Blockers where there are none.
- The file was first built with the squash commit message as its description: twelve commit
  messages, most of them of commits merged earlier, and none of the body's test plan. Two
  draws were made on that file and are reported apart. Cases A and B have a commit message
  as their description and say so above.

## Results of 12 November 2026

### On the model `claude-review.yml` pins: three draws per brief and per case

| Case | Known defects | Current brief | Refutation brief |
|---|---|---|---|
| A | 7 | 0, 0 and 0 named. | 2, 2 and 3 named: defects 2 and 4 in the three draws, defect 1 in one. Defect 4 tagged Blocker in two draws. |
| B | 1 | Not named in any of the three draws. | Named and tagged Blocker in two draws of three; one gives the remedy, the validator first. Not named in the third: it checked the job matrix the earlier resolver expects and did not read the earlier validator's keys. |
| C | 0 | No Blocker in any of the three draws. | No Blocker in any of the three draws. |

Criteria. The grid of known defects and the criterion (at least three more known defects
named on case A, and the defect of case B named when the current brief does not name it)
were written before any report was read. Their form for three draws was written after the
first draw of each cell of cases A and B on this model had been read, and before the two
others and the draws of case C were launched: on the medians, at least three more on case
A; the defect of case B named in at least two draws of three by the refutation brief and
in at most one by the current brief; and, for harm, a Blocker the source contradicts on
case C from the refutation brief while the current brief reports none.

- Case A: medians 2 and 0, two more. **Not met.**
- Case B: two draws of three against none. Met.
- Case C: no Blocker under either brief. No harm found.

Blockers of another kind, on cases with defects:

- Current brief: one on case A that the source contradicts (it said the run names
  `pipeline-after-merge.yml`; the run's API record names
  `pipeline-post-merge.yml@f7a7690`, as the pull request says, and the run's page shows the
  caller). One on case B: the two workflows are generated files edited by hand.
- Refutation brief: three in the draw of case B that did not name the known defect (rule 8
  against rule 6, a sentence of ADR-1133 on a copy "word for word", a commit message that
  contradicts itself). None was checked against the source here.

| Cell | Tokens, mean of three draws | Seconds, mean |
|---|---|---|
| A, current brief | 67 301 | 87 |
| A, refutation brief | 79 487 | 128 |
| B, current brief | 98 325 | 128 |
| B, refutation brief | 124 716 | 214 |
| C, current brief | 64 538 | 75 |
| C, refutation brief | 71 757 | 115 |

The refutation brief used 18 % more tokens on case A, 27 % more on case B and 11 % more on
case C.

Each draw listed what it read: no file outside its two paths, and on the web only runs,
commits and pull requests its case cites. Requests to `api.github.com` were refused (403) in
every draw that tried one; the draws that verified a run read its page on github.com.

On the first file of case C (the squash commit message as description), one draw of the
refutation brief on this model reported one Blocker: the description gives no counts for its
commands, against rule 8. The body of pull request 998 has the table of commands and names
the two it did not run, so the source contradicts it. The file was rebuilt before the three
draws above.

### First series, on the model of the interactive session: one draw per brief and per case

Drawn before the model was controlled. Kept because the brief was written from it.

| Case | Known defects | Current brief | Refutation brief |
|---|---|---|---|
| A | 7 | 0 named. "No BLOCKER", four Notes. | 4 named (1 to 4), each tagged Note. "No BLOCKER". |
| B | 1 | Not named. One Blocker of another kind: a false sentence of ADR-1133. | Named, tagged Blocker, with the remedy: the validator first. |
| C, first file | 0 | not drawn | "No BLOCKER found", six Notes. |

| Draw | Tokens | Seconds |
|---|---|---|
| A, current brief | 188 871 | 564 |
| A, refutation brief | 198 473 | 608 |
| B, current brief | 285 616 | 1 036 |
| B, refutation brief | 249 170 | 818 |
| C, refutation brief | 213 676 | 761 |

Criterion of that series, written before its reports were read: at least three more known
defects named on case A, and the defect of case B named when the current brief does not.
Met on that model: four more on A; B named by the refutation brief alone.

Four of the six Notes of its draw on case C named defects of rules 8 and 9 and of ADR-1134
that the reviews of 998 had let through: a clean copy that left out a fresh clone and the
Codex worktree; a required key whose removal the rule allowed while the resolver still
refused its absence; a replay that, after a conflict merge, used a validator older than the
main branch's; and "the run after it" for two runs that are not consecutive. The pull
request that adds this set corrects them. Draws on the model of CI named the first and the
third again.

## What this does not show

- Three draws per cell on the model of CI: the spread on case A is one defect, and case B
  was missed once in three. No interval is given on three draws.
- The model was given by the alias the session's harness has for the family
  `claude-review.yml` pins. The identifier that served the draws was not read.
- The third instruction of the refutation brief was written from the incident of case B, so
  B is not a held-out case for it. Case A was not used to write the brief.
- Finding is not blocking, and a draw's tag is not the hosted verdict (see Protocol).
- Only the reviewer's own report is measured. In CI the top-level reviewer then keeps what
  it deems noteworthy and writes the verdict; that step was not run.
- The three other reviewers of `/review-pr` were not measured.
- Three cases, all documentation and CI changes of one repository on one day. No case
  changes product code.
