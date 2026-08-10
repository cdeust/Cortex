# Contributing to Cortex

Thanks for considering a contribution. Cortex is a persistent memory
engine built on **36 neuroscience-grounded mechanisms** with a
**97-reference bibliography** ([`docs/papers/bibliography.md`](docs/papers/bibliography.md),
the canonical list) backing the algorithms. Every change is held to that bar.

---

## What this project is

A Python 3.10+ MCP server with **52 standalone tools** (55 with the optional
ai-architect-mcp-codebase + prd-spec-generator integrations) and **9 automatic
hooks**, persisting to a local SQLite store by default or to PostgreSQL +
pgvector when configured. Implements rate-distortion forgetting,
predictive-coding write gating, retrieval-induced reconsolidation, pattern
separation, sleep-cycle consolidation, emotional-valence weighting, and
more. See [README](README.md) for the full architecture and benchmark
results (LongMemEval Recall@10 = 98.2%, LoCoMo Recall@10 = 94.2%, BEAM-10M
+33.4% over the published baseline).

---

## Dev setup

**Prerequisites:** Python 3.10+ and `uvx` (`pip install uv` or `pipx install uv`).
The default store is a local SQLite file — nothing to provision. PostgreSQL 17
+ pgvector is only needed to run the PostgreSQL-backed integration tests.

```bash
git clone https://github.com/cdeust/Cortex.git
cd Cortex

# Install every extra CI installs. Missing extras do not fail — they SKIP, so
# a local run looks green while covering less than CI does. Measured
# 2026-07-28 on a tree without them, 12 tests skipped [not-a-count-claim: tests]
# locally that CI runs (8 tree-sitter, 1 leidenalg — both `codebase`;
# 3 sqlite-vec — `sqlite`).
# CI's SQLite job installs ".[dev,sqlite,codebase]"; its PG job adds
# `postgresql`. Install all of them so your run is the stricter one.
# `uv sync`, not `pip install -e`: sync resolves from uv.lock, which is what
# CI installs (as the hash-pinned requirements/ exported from it). Resolving
# from the pyproject.toml ranges instead lands you on versions CI never had —
# issue #253, where that gap cost a contributor a phantom type error.
uv sync --no-default-groups \
  --extra postgresql --extra sqlite --extra codebase --extra benchmarks --extra dev

# Optional: the setup script provisions PostgreSQL + pgvector and inits the DB
bash scripts/setup.sh        # macOS / Linux

# Verify everything is wired
uvx --python 3.13 --from "hypermnesia-mcp[postgresql]" cortex-doctor

# Run tests (under tests_py/; current count: assets/badge-tests.svg)
pytest
# Run a benchmark
python benchmarks/longmemeval/run_benchmark.py --variant s
```

### Reproducing the pyright gate locally

The gate is zero-diagnostic, so its answer only means something if your
environment is CI's. Build it from `uv.lock` — the same lock CI installs from,
via the hash-pinned `requirements/ci-typecheck.txt` that
`scripts/generate_pip_constraints.py` exports from it:

```bash
uv sync --no-default-groups \
  --extra dev --extra postgresql --extra sqlite --extra codebase --extra otel \
  --group typecheck
.venv/bin/python -m pyright mcp_server/
```

Do **not** resolve this environment from the `pyproject.toml` ranges
(`pip install -e ".[dev,...]"`): the ranges admit versions whose type surface
differs, so the gate reports one thing to you and another to CI. That is issue
#253 — a contributor chasing a `tree-sitter-language-pack` diagnostic CI never
saw. The extras above are not a hand-kept list: they are asserted equal to the
`ci-typecheck.txt` / `typecheck-tool.txt` entries of
`scripts/pip_constraint_sets.py` by
`tests_py/scripts/test_typecheck_env_parity.py`, which fails if this block and
CI's install ever drift apart.

---

## Branching + workflow

- `main` is the integration branch.
- Branch naming: `feature/<short-slug>`, `fix/<short-slug>`, `docs/<short-slug>`, `mechanism/<name>` (for new biological mechanisms), `benchmark/<name>` (for new benchmark integrations).
- One mechanism per PR when adding new biological mechanisms.
- Conventional commit messages preferred.

### The one required status check

Branch protection on `main` names a single `ci.yml` context, **`CI Green`**
(plus `CodeQL`, which GitHub reports from its own default setup). `CI Green`
is the `ci-green` job at the bottom of `.github/workflows/ci.yml`: it needs
every other job in that workflow and fails on any result other than
`success`, except for the jobs listed in its `ALLOWED_SKIPS` — which may
contain only jobs carrying a job-level `if:`, each with its reason.

Naming individual jobs in the protection settings instead put the contract
outside git, where no diff shows it and every rename breaks it: extracting
the test steps into a reusable workflow (issue #336) renamed the four matrix
legs to `Test (Python X.Y) / Test (Python X.Y)`, the four bare contexts
`main` required were never reported again, and a fully green PR sat BLOCKED
(#387). With one aggregate context, renaming a job, resizing the matrix, or
delegating steps costs nothing.

**Adding a job to `ci.yml` means adding it to `ci-green.needs`.**
`scripts/check_ci_gate_complete.py` (run by `lint`) fails the build
otherwise — an ungated job could fail without blocking a merge.

### Issue ownership

**Only the repository owner opens issues on this repo.** If you (human or
agent contributor) find a defect while working — including one outside the
blast radius of your current change — you do not file a ticket for it.

This is not a license to ignore it. The rule closes the exit, it does not
open one: a defect you can fix in the material you are already touching
gets fixed in the same PR (see the boy-scout discipline under Testing/What
NOT to do below); a defect outside that blast radius gets described plainly
in the PR description instead of being silently dropped or waved through
with a "pre-existing" / "unrelated" / "out of scope" label — those labels
are not a substitute for either fixing it or naming it where a reviewer can
see it. **A violation you declare in a commit message or a PR description
is still a violation** — enumerating it does not authorize leaving it in
place; it is triage information for the owner, who decides whether it
becomes its own issue, its own PR, or gets folded into the current one.

Concretely: don't invoke "no issues" as a reason to decline fixing or
reporting something you found. It is a rule about *who opens tickets*, not
about *what gets addressed*.

---

## Adding a biological mechanism

Cortex's mechanisms are not metaphors — each maps to a specific
neuroscience finding with a specific algorithmic implementation.
A new mechanism PR must include:

1. **Primary citation.** What published neuroscience or cognitive-science
   work motivates this mechanism? Include the paper's bibliographic
   reference in `docs/papers/bibliography.md`.
2. **The mathematical form.** Equations or pseudocode showing the exact
   computation. If you're adapting an algorithm from the literature,
   call out the divergence and justify it.
3. **The biological grounding.** Which brain region / circuit / molecular
   pathway does this mirror? A one-paragraph mapping is required.
4. **Empirical validation.** A benchmark or unit test demonstrating the
   mechanism behaves as predicted. Quantitative claims need numbers.
5. **Ablation.** A test showing the system's behavior with the mechanism
   disabled, so its contribution is observable.

A mechanism PR without these five elements does not pass review.

---

## Modifying retrieval signals

Cortex fuses five retrieval signals (vector similarity, full-text search,
trigram matching, thermodynamic heat, recency) plus a cross-encoder
reranker. Changes here:

1. **Run the full benchmark suite.** LongMemEval, LoCoMo, BEAM at both
   100K and 10M scales. A regression on any of those is blocking unless
   explicitly justified.
2. **Document the delta.** A markdown row in `benchmarks/results.md`
   showing before/after MRR + Recall@10 per category.
3. **Cite the source.** If you're adding a new signal, reference the IR
   literature (BM25 → Robertson; pgvector HNSW → Malkov et al.; trigram
   → Lehmann; etc.).
4. **Preserve the 22MB embedding-model footprint.** Cortex runs entirely
   on the user's machine; bringing in a 1GB model is out of scope.

---

## Coding standards (excerpt)

Standard Python style, enforced in CI by `ruff format --check .` and
`ruff check .` (ruff pinned at 0.15.20 in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)), plus
project-specific rules:

- **No `Any`** in production code. Use `Protocol` or generic typing.
- **§8 Source discipline.** Every numeric constant ≥3 significant digits
  needs a `# source:` annotation.
- **No mutable default arguments.** No globals except for read-once
  configuration objects.
- **No bare `except:`.** Catch the specific exception you mean.
- **Type-checked at zero.** `pyright` (pinned 1.1.410, `typeCheckingMode:
  "standard"`) runs over `mcp_server/` and ANY diagnostic fails the build —
  the 568-diagnostic ratchet backlog was burned to zero in issue #197
  (2026-07-28) and the ratchet retired. History:
  [`docs/provenance/pyright-remediation-plan.md`](docs/provenance/pyright-remediation-plan.md).
- **File ≤300 lines, function ≤40 lines** — this repo's local tightening of
  coding-standards.md §4.1/§4.2 (≤500/≤50); see CLAUDE.md § Code Style for
  the authoritative numbers (issue #276).

The full standard lives in
[zetetic coding standards](https://github.com/cdeust/zetetic-team-subagents/blob/main/rules/coding-standards.md).

---

## Testing

```bash
pytest                              # full suite (see assets/badge-tests.svg for the current count)
pytest tests_py/core                # core (pure business logic) onlypytest tests_py/integration         # PostgreSQL-backed integration
pytest tests_py/benchmarks -k locomo # subset
pytest -x --ff                      # stop on first fail, run failures first
```

The suite runs on the default SQLite store; `tests_py/integration` needs a
local PostgreSQL instance with pgvector. CI provisions a fresh database per
run and additionally runs the suite against the SQLite backend and on Windows.

### The testing policy (mandatory)

**Every change that adds or alters externally observable behaviour must arrive
with tests for that behaviour, in the same pull request.** Specifically:

- **New functionality** — major or minor — ships with tests in the automated
  suite. A new MCP tool carries a contract test; a new mechanism carries the
  empirical validation and the ablation described above.
- **A bug fix carries a regression test that fails on the pre-fix code.** If
  the test passes without the fix, it does not pin the bug.
- **Every failure path is tested like a happy path**: each error arm, fallback
  and degraded mode asserts its observable effect, including the signal it
  emits — not only a downstream side effect.
- Changes that alter no behaviour (formatting, comments, documentation) are
  exempt; say so in the PR description.

This is checked in review: a PR that adds behaviour without tests is sent back
rather than merged with a promise to follow up. Ask of each new test "what
mutation would this fail to catch?" — `scripts/mutation_check.sh` answers it
mechanically for the modules it is scoped to.

---

## Adding an MCP tool

52 standalone tools currently (55 with the optional upstream integrations). Adding a new one:

1. **Define the JSON schema** in the tool's module-level decorator.
2. **Implement the handler** following the `BaseTool` protocol.
3. **Add to the tool registry** at the canonical registration site.
4. **Document in [`docs/mcp-tools.md`](docs/mcp-tools.md)** with the tool's
   purpose, tier and target latency, and update the standalone tool count
   there — `tests_py/test_main.py::test_standalone_baseline_is_52_tools` pins
   it, and `scripts/check_doc_claims.py` fails the build if the docs disagree.
5. **Add a unit test** for the tool's contract.
6. **Add an integration test** if the tool touches the database.

---

## What NOT to do

- Don't claim a benchmark improvement without committing the actual
  benchmark output. Numbers without a reproducible run are unverified.
- Don't add a mechanism without academic grounding. "It seems brain-like"
  is not a citation.
- Don't introduce a heavy ML model dependency that breaks the
  runs-on-your-machine guarantee.
- Don't suppress a pyright diagnostic to make the build pass. The type
  system is the contract; the tree stays at zero diagnostics.
- Don't relax a test that fails on your branch. The test exists for a
  reason; understand the reason before changing it.

---

## Code of Conduct

This project follows [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

---

## Reporting security issues

See [`SECURITY.md`](SECURITY.md). The memory engine handles potentially
sensitive user data (PII in conversation transcripts); any data-exposure
or injection issue is high-priority. In-repo, the defence is
[`mcp_server/shared/redaction.py`](mcp_server/shared/redaction.py), which
masks credentials in URLs and scrubs well-known secret shapes before content
is stored — new code paths that capture or persist text must route through
it. (The `pre-tool-secret-shield` file gate some maintainers run is part of
their local agent tooling, not of Cortex; do not rely on it.) The security
argument, its trust boundaries and its limits are in
[`docs/ASSURANCE-CASE.md`](docs/ASSURANCE-CASE.md).

---

## License

MIT. Contributions are licensed under the same. See [`LICENSE`](LICENSE).
The neuroscience and IR algorithms remain attributable to the cited
sources; the MIT license covers this implementation.
