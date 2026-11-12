---
created: 2026-11-12T02:18:00Z
kind: adr
number: 1133
status: accepted
tags: [ci, pipeline, selection, resolver, merge-gate, fleet, ci-json]
title: A documentation-only pull request runs environment and install on Linux alone
---
# ADR-1133: A documentation-only pull request runs environment and install on Linux alone

## Status

accepted. Amends, for one case, the receipt the resolver requires before a merge (owner rule 2026-10-29: the exact `environment` and `install` matrices).

## Context

Owner request 2026-11-12: select what the Pipeline runs from the change, as Meta describes.

Every push to a pull request starts the same eleven jobs: seven on Linux, two on macOS, two on Windows (`contract`, `unit`, `regression`, `e2e`, `merge`, and `environment` and `install` on the three systems). Read on Pipeline run 43117402215 of `cdeust/ci-autonome`. On Cortex each `install` leg also waits its 1500 s settle (`ci.json`).

Source: Meta, "Predictive test selection" (engineering.fb.com, 2018; arXiv 1810.05286). Selecting tests by build dependencies ran up to a quarter of all tests per change on their mobile code base. Their learned selection runs a third of the dependent tests and still reports over 99.9 % of faulty changes; every change is tested exhaustively before it is deployed from the trunk. The conditions differ here: that selection is learned from a large history of test outcomes, which this repository does not have. Only the part that needs no data is taken: do not run before the merge what the change cannot reach, and keep the exhaustive run after it.

The resolver required the three legs of both jobs by name (`_validate_jobs`), and `scripts/ci_pipeline_source_contract.py` pinned that text.

## Decision

1. `ci.json` takes an optional key `docs_paths`: directories (ending in `/`) and files whose change cannot alter what a test job runs. An entry stays inside the repository, cannot start with a dot or a slash, and cannot be `ci.json`. The validator embedded in both workflows checks it.
2. The `contract` job of the Pipeline gains the step "Select the platforms". On a pull request whose every changed path lies under `docs_paths`, a rename counting under both of its names, `environment` and `install` run on Linux alone. Any other event or change, an unreadable file list, or a list of 3000 paths or more (GitHub lists 3000 files at most) keeps the three systems. A path whose name Windows cannot hold (a reserved character or device name, a trailing dot or space) is never documentation: it would fail only there, after the merge.
3. The resolver accepts the three systems, or Linux alone on both jobs. For Linux alone it reads `docs_paths` from the default branch's `ci.json` and the files of the pull request, and merges only when it finds the pull request documentation-only itself. Otherwise the merge is refused, and the run ends red.
4. The Pipeline after merge is unchanged: the three systems run on the merge commit.
5. Cortex lists `docs/`, `wiki/` and `CHANGELOG.md`. Neither `scripts/ci_environment.py` nor `scripts/ci_install.py` reads them. What checks them does not depend on the system: the tests of `check_doc_claims.py` run in the `unit` job, and `check_project_wiki.py` runs in workflows of its own (`supersession-delete-parity.yml`, `memory-exact-review.yml`), not in the Pipeline.

## Consequences

- A documentation-only pull request starts seven jobs instead of eleven before the merge. Measure: jobs started per Pipeline run on such pull requests, and macOS and Windows job minutes per merged pull request.
- A pull request cannot widen its own selection: changing `ci.json` is never a documentation change, and the resolver decides from the default branch.
- A path wrongly listed under `docs_paths` shows after the merge, when the three systems run. The remedy is to remove the entry.
- A pull request tested on Linux alone while the default branch no longer lists its paths is refused by the resolver; a new push runs the three systems.
- The validator is embedded word for word in both workflows (pinned by a test) and in `tools/ci_contract.py` of `zetetic-team-subagents`. That copy, and the workflows of the other repositories, follow in their own pull requests.
- The selector and the resolver count the same thing, paths, so that a pull request the selector sends to Linux alone is not refused for its size by the resolver.
- `scripts/ci_pipeline_source_contract.py` pins the text of the resolver, not its behaviour. In review, ten hand changes to the resolver went past it; the tests caught nine, and the tenth now has a pinned clause and a mutation case.
- Two scripts still name the six legs (`scripts/ci_codex_review_resume.py`, `scripts/ci_autopilot_queue.py`). No job of the Pipeline calls them (read, not run).
- Not proven before the merge: the job names GitHub gives a one-element `fromJSON` matrix. Shown since on pull request 997, the first documentation-only one. Its two Pipeline runs (43154988108 as a draft, 43157084794 once ready) started `environment (ubuntu-latest)` and `install (ubuntu-latest)` and no macOS or Windows job, six machines for the draft and seven once ready, and the resolver merged it on that matrix (run 43158939841).

## Alternatives considered

- Keep the three legs and skip their steps: each leg still starts a machine, which is what the selection is meant to avoid.
- Select on a label or on the title: that is the author's word, not the change (ADR-1126 takes the tier from the change).
- A learned selection as Meta's: there is no history of test outcomes per change to learn from.
