@~/.claude/rules/model-behavior.md
@~/.claude/rules/coding-standards.md

# Cortex — Persistent Memory MCP Server

Persistent memory and cognitive profiling MCP server for Claude Code.
Python 3.10+, FastMCP, Pydantic, numpy. Storage: SQLite by default
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
- Tests: `pytest` (full suite — current count: `assets/badge-tests.svg`, or run `pytest --collect-only -q`) · `pytest tests_py/core/` (one layer) · `pytest --cov=mcp_server --cov-report=term-missing`- Lint BEFORE every commit: `ruff check && ruff format --check` — the CI enforces **both**; passing only `ruff check` is not enough.
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

- @docs/adr/ — Architecture Decision Records (013 = thermodynamic memory
  model, 014 = biological mechanisms, 012 = Python migration from Node.js)
- @docs/module-inventory.md — per-layer module catalogue + dependency rules
- @docs/mcp-tools.md — the 52 standalone tools + 3 conditionally-registered
  MCP tools, by tier, with purpose and target latency
- @PRIVACY.md — storage truth by launch surface (lines 26–38): SQLite is
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
  by AST, on the files a diff touches — never the whole repository. The
  layer whitelist is *parsed* from `docs/module-inventory.md`'s own table
  at run time (`scripts/craftsmanship_layer_table.py`), never a second
  hardcoded copy that could silently diverge from it.
  The comparison baseline is read via `git show <base-ref>:.craftsmanship-baseline.json`
  — the PR's BASE ref, immutable to the PR's own commits — never the
  working tree: a working-tree-only baseline is self-service (add a
  violation, run `--write-baseline` in the same tree, the gate would pass
  on it — this exact exploit is reproduced and closed in
  `tests_py/scripts/test_check_craftsmanship.py::SneakyLimitExploitTests`).
  The gate fails the diff on: any violation absent from that base-ref
  baseline (new debt); any base-ref-baselined entry whose violation no
  longer reproduces (fixed but not pruned); or any entry present in the
  working-tree `.craftsmanship-baseline.json` but absent from the base
  ref's (the file may only SHRINK within a PR — an addition is refused
  outright, matched or not, because debt discovered mid-PR gets fixed at
  the source, not grandfathered). Regenerate with
  `python scripts/check_craftsmanship.py --write-baseline` only to prune
  entries whose violations you actually fixed. Previously "enforced by
  code review today; no automated pre-commit hook checks this yet" (issue
  #276 corrected an earlier, false claim of a "craftsmanship-checker"
  hook) — that gap is what this gate closes. Historical import-rule
  violations once tracked ad hoc in this section (`wiki_axis_registry.py`,
  `wiki_classifier.py`, `wiki_schema_loader.py`, found 2026-07-14 during
  #114) now live in the baseline like any other pre-existing debt, not as
  separate prose here.

## What NOT to do

- Do NOT gate a release benchmark against the live production database —
  use `benchmarks/reproduce.sh` (isolated container) instead; see Build & Test.
- Do NOT add silent fallbacks or backward-compat shims — explicit
  contracts, one-shot migrations.
- Do NOT write model caches under `/tmp` — the FlashRank incident (silently
  absent re-ranker, 6 benchmarks invalidated) came from exactly this.
  `HF_HOME`/`cache_dir` must be persistent.

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
