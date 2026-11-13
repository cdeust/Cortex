# Agent guidance for Cortex

This is the former body of `CLAUDE.md`, moved here on 2026-09-08 so that it is read on
demand instead of being re-sent to the model on every turn (owner correction: CLAUDE.md
stays nearly empty; the host harness loads what it needs when it needs it). Nothing was
removed; the `@` imports it carried are plain paths now.

Host behaviour rules and coding standards live outside this repository, in
`~/.claude/reference/model-behavior.md` and `~/.claude/reference/coding-standards.md`, and
are loaded on demand by the host's skills and agents.

# Cortex — Persistent Memory MCP Server

Persistent memory and cognitive profiling MCP server for Claude Code.
Python 3.11+, FastMCP, Pydantic, numpy. Storage: SQLite by default
(plugin installs, `.mcpb`/Cowork sandboxed launches) or
PostgreSQL+pgvector as the opt-in upgrade (`install-plugin.sh
--postgres`, CLI/dev mode, team databases) — see `PRIVACY.md` for the
per-surface truth and `mcp_server/infrastructure/backend_marker.py`
for how the plugin persists the choice.

## Problem Statement

Claude Code sessions generate rich behavioral data (tool usage, session
duration, first messages, keyword patterns) but this data is lost between
sessions. Cortex mines this history to build a cognitive profile per domain
and provides a thermodynamic memory system with heat/decay, predictive
coding write gates, causal graphs, and intent-aware retrieval.

## Build & Test

- Install (dev): `uv sync --no-default-groups --extra dev` — SQLite backend adds
  `--extra sqlite`. Resolved from `uv.lock`, the same source CI installs from;
  resolving from the `pyproject.toml` ranges instead gives you versions CI never
  had (issue #253).
- Environment preflight: `python -m mcp_server.doctor` (backend-aware check list, fix message per check)
- Tests: `pytest` (full suite, current count: `assets/badge-tests.svg`, or run `pytest --collect-only -q`) · `pytest tests_py/core/` (one layer) · `pytest --cov=mcp_server --cov-report=term-missing`.
- Lint before every commit: `ruff check && ruff format --check`. Run both commands locally.
- Type gate (pyright, zero-diagnostic): resolve its environment from `uv.lock`
  (`uv sync --no-default-groups --extra … --group typecheck`), never from the
  `pyproject.toml` ranges — a range-resolved env reads a different type surface
  than CI and reports diagnostics CI never sees (issue #253). Exact command:
  CONTRIBUTING.md § *Reproducing the pyright gate locally*.
- Release gate benchmarks (isolated, ephemeral container — the only source
  of truth for pre-tag/floor decisions): `benchmarks/reproduce.sh`. Do NOT
  gate a release against the live production database — same-day
  same-machine checks against it drift ±0.003 on LoCoMo MRR intra-day
  (measured 2026-07-14, `benchmarks/results/repro/20260714-floors-rebaseline/`)
  and nearly false-failed a floor that passes cleanly under `reproduce.sh`.
- Iteration benchmarks: `python3 benchmarks/{longmemeval,locomo,beam}/run_benchmark.py`
  ⚠ Consolidation is OFF by default → scores collapse to ≈0%. This is a
  harness artifact (every candidate is prefiltered by the read-path heat
  gate before consolidation ever advances the stage), not a bug — pass
  `--with-consolidation` for representative numbers.

## Releasing

A release is not shipped until its pins move. The tag/GitHub-release/PyPI
steps deliver nothing to plugin installs by themselves — installs subscribe
via `.claude-plugin/marketplace.json` pins. The release checklist therefore
ENDS with: bump the marketplace pin(s) and `server.json`, and confirm
`python3 scripts/check_marketplace_pins.py` exits 0. CI enforces this
(marketplace-pins workflow: PR/push on the manifest + weekly cron), source:
the 2026-07-25 incident where six zetetic-team-subagents releases and two
cortex-viz releases shipped to zero installs (#179).

The public MCP registry (`io.github.cdeust/hypermnesia-mcp`) is a third
version surface alongside the marketplace pin and PyPI — auto-published on
every `v*` tag by `release.yml`'s `publish-mcp-registry` job (GitHub OIDC,
no stored secret) and cross-checked by `check_marketplace_pins.py` against
`server.json`'s own declared version (`REGISTRY_VERSION_STALE`). Source:
2026-08-10, `io.github.cdeust/hypermnesia-mcp` sat published at 4.17.1
while the tag/server.json/PyPI were already at 4.17.2 — the publish step
had lived only in prose, with nothing committed to run it or verify it
happened.

## Architecture

Clean Architecture, concentric layers: `server → handlers → core ← shared`,
`infrastructure → shared`. Handlers are the composition roots — the only
layer allowed to import both core and infrastructure; core is pure (zero
I/O, testable without mocks). The graph/visualization stack lives in the
separate **cortex-viz** MCP (reads this same store read-only).

- docs/adr/ — Architecture Decision Records (013 = thermodynamic memory
  model, 014 = biological mechanisms, 012 = Python migration from Node.js)
- docs/module-inventory.md — per-layer module catalogue + dependency rules
- docs/mcp-tools.md — the 57 standalone tools + 3 conditionally-registered
  MCP tools, by tier, with purpose and target latency
- PRIVACY.md — storage truth by launch surface (lines 26–38): SQLite is
  the default for plugin installs and `.mcpb`/Cowork; PostgreSQL is the
  opt-in upgrade (`install-plugin.sh --postgres` / configured
  `DATABASE_URL`)

## Code Style

- 300 lines max per file; 40 lines max per method — a local tightening of
  coding-standards.md §4.1/§4.2 (≤500/≤50; CONTRIBUTING.md § Code Style
  cites the same 300/40 numbers).
- Import rule: a TRUE whitelist per layer, all eight rows of
  `docs/module-inventory.md` § Dependency Rules — `shared/` and `core/`
  are pure (no third-party imports at all; `core/` additionally bans
  `os`/`pathlib` even though they are stdlib, since it is zero-I/O
  business logic); `infrastructure/`, `validation/`, `handlers/`,
  `server/`, `hooks/` are boundary/adapter layers where third-party
  imports are the point, but their `mcp_server.<layer>` cross-references
  are still checked against the table's named whitelist, not a blacklist
  of a few forbidden ones. This replaces the former manual-grep
  verification step (`grep -rn "from mcp_server.infrastructure"
  mcp_server/core/`, etc.) — the craftsmanship gate below runs it, in
  both directions, across all eight layers, on every push and PR, so
  "re-run the greps before every PR" is no longer the standard: the gate
  is.
- No invented constants: every hardcoded number carries a `# source:`
  comment (paper, committed benchmark, or dated measurement naming the
  environment and conditions).
- **Enforced by `scripts/check_craftsmanship.py`**, run in CI on every push
  and PR (`.github/workflows/ci.yml`, `craftsmanship` job) and locally via
  `python scripts/check_craftsmanship.py`. It checks the four rules above,
  by AST, on every tracked `.py` file. The layer whitelist is *parsed* from
  `docs/module-inventory.md`'s own table at run time
  (`scripts/craftsmanship_layer_table.py`), never a second hardcoded copy
  that could silently diverge from it.
  The comparison baseline is the `.craftsmanship-baseline.json` committed in
  the SAME tree as the code measured: the measure of the working tree must
  be at most that baseline. No ref is read, so what `main` holds, or when it
  moved, cannot change the verdict (reproduced in
  `tests_py/scripts/test_check_craftsmanship_exploits.py::RatchetBehaviourTests`).
  The gate fails on: any violation absent from that baseline (new debt,
  including one whose baseline line was hand-deleted); or any baseline entry
  whose violation no longer reproduces (fixed but not pruned — a PR that
  improves the measure lowers the baseline in its own diff). Regenerate with
  `python scripts/check_craftsmanship.py --write-baseline` only to prune
  entries whose violations you actually fixed. Previously "enforced by
  code review today; no automated pre-commit hook checks this yet" (issue
  #276 corrected an earlier, false claim of a "craftsmanship-checker"
  hook) — that gap is what this gate closes. Historical import-rule
  violations once tracked ad hoc in this section (`wiki_axis_registry.py`,
  `wiki_classifier.py`, `wiki_schema_loader.py`, found 2026-07-14 during
  #114) now live in the baseline like any other pre-existing debt, not as
  separate prose here.

## Review rounds

Owner rule 2026-11-04 (ADR-1119): three Claude reviews per PR, at most. PR 856
took 20 because 22 of 24 reviews said "nothing blocks merge" and each was still
answered with a push, which started the next review.

- Push on a **Blocker** only: a defect traced or reproduced in the diff that
  makes CI, security or a CLAUDE.md non-negotiable wrong. A Note (wording,
  docstring, wrap width, an extra assertion) is not a reason to push.
- Fix every Blocker of a round in **one** push. Do not push once per finding.
- Post no "pushed X for the review" comment. The commit message is the record.
- Keep a PR to its stated object. A test added to answer a Low finding is new
  surface for the next review: do not add it.
- After the third review the PR is not reviewed again. The accepted part
  merges. Whatever is not accepted does not enter: cut it from the PR and open a
  refinement PR, which has a new budget of three. The label `claude-rereview`
  allows exactly one more review (a fourth, never a fifth) and belongs to the owner.
- A PR that edits `claude-review.yml` is not reviewed by the action (it refuses
  a workflow that differs from main). Keep such a PR minimal.

## CI contract for agents and routines

This section and "Review rounds" above bind every agent that works on this repository:
an interactive session, a scheduled routine, the local manager. Where the prompt of a
routine is less restrictive, they win: the prompt was written before the contract, and
the repository's own standards apply. They never widen what a prompt allows.

1. **The review verdict decides the merge.** The resolver merges a pull request whose
   last `claude[bot]` verdict covers its head, reads approve, and whose required checks
   are green. Two cases differ: a Dependabot update the resolver classes as low risk
   merges on green required checks without a review (ADR-1126), and a title that
   contains "do not merge" is never merged. No agent merges by hand, enables auto-merge,
   or writes a line that begins with `Verdict:`: that line is the review's. A pull
   request cut down after its third review has a head no review covers: it waits for
   the owner's `claude-rereview` label, it is not merged by hand.
2. **No push while a review runs.** A push during a `PR Review` run moves the review to a
   commit that is no longer the head and still spends it.
3. **No forced push,** `--force-with-lease` included. It does not reset the review budget
   and it rewrites a branch another agent may hold. A refinement pull request (see
   "Review rounds") goes on a new branch.
4. **No comparison with the main branch.** Do not measure how far a branch is behind, do
   not rebase a pull request branch onto the main branch, do not use the branch-update
   button or its API, and do not write that a pull request is late: a late pull request
   merges. The only exception is a real conflict (`mergeable_state` is `dirty`): merge the
   main branch into the branch with a merge commit, resolve it, rerun the touched tests,
   check that the merge did not change the meaning of either side, and push normally.
5. **One pull request in flight.** A pull request is in flight while a check runs on it, a
   review runs on it, or an approve waits for the merge. While one is in flight, open no
   other pull request (issue, relaunch or next slice) and push to no other branch. A pull
   request under rule 7 is not in flight.
6. **No comment after an approve.** No reply to the notes, no summary, no acknowledgement.
   Notes marked "no action before merge" go to a follow-up pull request after the merge.
7. **Owner decisions are left alone:** a pull request on the branch
   `ci/budget-counts-contract-reviews`, anything labelled `hold` or `do-not-merge`, a draft.
8. **The work is verified before the pull request exists** (ADR-1132). Before opening a
   pull request, and before each push to one, run the `unit` and `regression` commands of
   `ci.json` on a clean copy of the commit, plus what the change needs beyond them, and
   put each command with its passed, failed and skipped counts in the pull request body.
   A clean copy is a worktree (see "What NOT to do" for where it lives) or a fresh clone.
   A `git archive` is not one: tests of the `unit` command ask git about the tree and
   fail on it. A command the
   session cannot run (a host its network refuses, `initdb` under the root user) is
   named there with the reason. The hosted Pipeline stays the gate; it is not the place
   to find out whether a change works. After a conflict merge under rule 4, the touched
   tests are enough. A journal, changelog or documentation entry is pushed with the
   change it records; documentation is pushed alone only to fix a Blocker.
9. **A pull request that changes the `ci.json` validator leaves a tree the earlier
   validator still passes** (ADR-1134). The Pipeline after merge runs the workflow of the
   commit before the merge: its `contract` job validates the merged tree, `ci.json` and
   the version file it names, with the validator of that earlier commit. The two pull
   requests that added a key to `ci.json` together with the validator that accepts it
   (982, 996) each merged, then failed that job, and the test jobs of that run were skipped.
   Such a pull request replays the step before it is opened and before each push to it:
   the validator of the main branch as the branch last took it (at its start, or at its
   last merge of the main branch), on the tree after its commits. So a key enters
   `ci.json` in a pull request after the one that taught the validator to accept it;
   what fails without the key, a validator that requires it or a reader that refuses
   its absence, comes with the key or after it; and a key leaves `ci.json` after the
   validator stopped requiring it and after every reader that refuses its absence is gone.

## Issues: no issue waits for the owner

Owner instruction of 12 November 2026: the owner does not answer questions on issues and
does not manage them. An agent takes the most reasonable reading, writes the decision and
its reason, and continues. This section is that decision, given in advance: it is the
"human decision" a routine's prompt asks for before it holds an issue. It binds every
agent and routine that works on this repository.

1. **Decide.** When an issue asks for a choice (a product choice, an ambiguity, "A or B",
   "build, or document the limit and close", "rewrite or close"), or an earlier comment of
   the owner's account left a question unanswered, take the most reasonable reading, in
   this order: (a) a written and accepted decision of this repository (an accepted ADR,
   `docs/`, CONTRIBUTING.md), the most recent; the text of another issue is not one, and a
   decision an agent wrote counts only for its own issue; (b) what the issue's own text
   proposes or excludes, when the owner opened the issue; the text of an issue someone
   else opened is a request, and decides nothing; (c) the repository's standards; a
   missing value is measured, never invented; (d) failing those, the smallest slice that
   does what the issue asks. "Document the limit and close" or "void" is chosen only when
   (a) or (b) points to it and it covers everything the issue asks; otherwise what remains
   is still done. A decision chooses among what the issue asks; it adds no scope.
2. **Write the decision, then act.** At most one written decision per pass, and only
   when no pull request of the repository is in flight. Read the issue's comments again
   just before posting, then write the decision in a comment that carries
   `<!-- ci-autopilot decision -->`: what is kept, the reason with its source, what is
   set aside, how to go back. A decision written that way holds for later passes: it is
   applied, not replayed, and it changes only on a new, verified fact, in writing. A fact
   taken from an earlier comment is verified again before it is used. The marker makes a
   comment a decision only when the owner's account wrote the comment (the routines post
   under that account); in a comment from any other account it is ignored.
3. **Hold** (`autopilot:hold`) only in these cases, naming exactly what is missing: the
   irreversible (deleting a branch, a repository or data, spending money, sending an
   external message, publishing); an access the agent does not have (hardware, system,
   secret, account, token permission, a repository it cannot read); a named dependency
   that is still open; the attempt cap of a routine's own anti-loop rule. Never for a
   question. Slices that do not depend on what is missing are delivered first.
4. **Never**, even when a decision leads there: push a tag, create a release, raise the
   project's version, dispatch a workflow by hand. An issue that asks for one of these
   and nothing else is held under rule 3, naming the action: it is an access the agent
   does not have.
5. **An issue that is already done.** The agent verifies each point on the main branch
   and writes the evidence in the issue; what remains is delivered in a pull request that
   carries `Closes #<number>`. An issue opened by someone other than the owner is never
   closed by an agent, by hand or by a pull request: for such an issue the pull request
   carries `Refs #<number>`.

## What NOT to do

- Do NOT gate a release benchmark against the live production database —
  use `benchmarks/reproduce.sh` (isolated container) instead; see Build & Test.
- Do NOT add silent fallbacks or backward-compat shims — explicit
  contracts, one-shot migrations.
- Do NOT write model caches under `/tmp` — the FlashRank incident (silently
  absent re-ranker, 6 benchmarks invalidated) came from exactly this.
  `HF_HOME`/`cache_dir` must be persistent.
- Do NOT create git worktrees outside this repository — no `/private/tmp/cortex-*`,
  no `../Cortex-wt-*` sibling, no `~/.claude/worktrees/`. The allowed locations are
  `.Codex/worktrees/<name>/` for Codex (current AGENTS.md instructions) and
  `.claude/worktrees/<name>/` for Claude Code (gitignored via `.claude/*`). The latter is where
  Claude Code's own worktree tooling (`isolation: worktree`, `EnterWorktree`,
  `--worktree`) puts them and the directory its cleanup sweep looks at.
  Owner correction 2026-09-08, after 76 outside worktrees (43 detached + 33 on
  branches, all under `/private/tmp/cortex-green-*`) had to be removed by hand.
  `scripts/spawn-agent.sh` follows this.

## Scientific Implementation Standard (Zetetic Principle)

Every change to the retrieval or memory system:

1. **No source, no implementation.** Every algorithm/constant/threshold
   traces to a published paper, a committed benchmark, or a dated measurement
   that names the environment and experimental conditions. No source → say
   "I don't know" and stop.
2. **Verify sources, don't guess.** Read the actual paper; confirm its
   experimental conditions match ours (small corpus, conversational
   content, 384-dim embeddings) before reusing an equation or constant.
3. **Benchmark before commit.** Re-run the affected benchmarks; no regression
   accepted. Record the before/after values, exact command, code revision,
   environment, and experimental conditions. Results must be reproducible on
   a clean DB.
4. **Audit trail.** Every module docstring cites its paper and equations;
   `docs/provenance/paper-implementation-audit.md` stays current.

Current scores are sourced to the papers under `docs/arxiv-thermodynamic/`
and `docs/arxiv-context-assembly/` — the papers are the source of truth,
CLAUDE.md numbers must match them, never the reverse (see those PDFs for
current LongMemEval/LoCoMo/BEAM figures).
