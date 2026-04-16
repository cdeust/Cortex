# ADR-0045: Scalability Governance Rules (R1–R6)

- **Status**: Accepted
- **Date**: 2026-04-16
- **Context**: Phase 0.1 of the Cortex Scalability Program
- **Supersedes**: none
- **Superseded by**: none

## Context

A multi-agent zetetic audit (Thompson, Erlang, Carnot, Taleb, Meadows, Simon) of
Cortex's scalability profile on darval's 66K-memory reference store
(issue [#13](https://github.com/cdeust/Cortex/issues/13)) identified 34 distinct
bottleneck findings. Meadows' leverage-point analysis classified 3 of them at
LP2–3 (paradigm / goal), 3 at LP5–6 (rules / information), ~20 at LP8–10
(structure / loops), 4 at LP11 (buffers), 1 at LP12 (parameters).

The paradigm-level finding is that Cortex treats Python as the owner of
bulk data and Postgres as passive storage. Every Python-side whole-store
iteration scales linearly: 489 MB at 66K memories, ~5 GB at 660K, ~50 GB at
6.6M. At 100× the current scale, several consolidation stages cannot physically
complete regardless of optimization — the form of the architecture has to
change (Thompson 1917).

Most future regressions will come not from removing the existing bottlenecks,
but from quietly re-introducing the paradigm that produced them: new
contributors writing code that loads full stores into Python, new ingestion
paths materializing whole files in memory, new N+1 query patterns over
`memory_entities`. Rules enforced at review time cost near-zero and prevent
the entire class of regressions.

Meadows: *"Power over the rules is real power."*

## Decision

Adopt six governance rules that apply to every change merged to `main`.
Each rule is enforceable at code review AND by a CI lint check.

### R1 — No `SELECT *` on the `memories` table (or any vector-indexed table)

Every query on `memories`, `wiki.pages`, `wiki.claim_events`, `entities`,
`relationships`, `memory_entities` must list the specific columns it consumes.
In particular, `SELECT * FROM memories` is forbidden because it transfers
the 1.5 KB `embedding` column per row — catastrophic on any row count
over a few thousand.

**Rationale** (Thompson, Carnot): the `embedding` column is the dominant
per-row payload. Transferring it to Python when Python doesn't use it is
pure waste, scales linearly with store size, and is the mechanism by which
`consolidate` becomes infeasible at 100×.

**CI check**: grep for `SELECT \*` in any file under `mcp_server/` returns zero
matches except test fixtures. Exception marker: `# noqa: R1 — <justification>`.

**Refactor target**: `get_all_memories_for_decay` (`pg_store_queries.py:107-109`)
must be replaced with a column-limited scan that omits `embedding`.

### R2 — No ingestion path reads a whole file or store into Python memory

Every ingestion path — `import_sessions`, `backfill_memories`, `seed_project`,
`codebase_analyze`, `wiki_seed_codebase` — must stream line-by-line or chunk
via bounded buffers. No accumulator lists whose size is proportional to the
input size.

**Rationale** (Taleb): `import_sessions` with `full_read=True` on a 10 GB
JSONL fills Python memory and crashes the server; `codebase_analyze` with
`sorted(root.rglob("*"))` materializes every Path object on a 10M-file tree.
Both fail catastrophically. Bounded streaming is the via-negativa fix.

**CI check**: grep for `full_read=True`, `records = []` + `records.append`,
`sorted(.*rglob`, and equivalent patterns returns zero new occurrences.

**Refactor target**: delete the `full_read` code path in
`handlers/import_sessions.py`; replace `sorted(root.rglob(*))` with
`itertools.islice` in `handlers/codebase_analyze_helpers.py:34`.

### R3 — No analyzer materializes the full graph

`codebase_analyze`, knowledge-graph walkers, fractal clusterers, and similar
must operate chunk-by-chunk. No `file_contents: dict[str, str] = {}` that
grows with the corpus; no `all_analyses: list[Any] = []` accumulator.

**Rationale** (Taleb): `codebase_analyze` on a monorepo OOMs at mid-size
even without reaching its `max_files` cap because the per-file analyses
accumulate in Python memory. The fractal uncapped no-domain fallback
(`recall_hierarchical.py:112-113`) is already broken at 66K memories because
it calls O(N²) single-linkage on the full store.

**CI check**: review-time only — any new analyzer handler must declare a
bounded memory footprint in its docstring.

**Refactor target**: replace in-memory accumulators in `codebase_analyze` with
streaming writes to the PG store; delete the fractal no-domain fallback.

### R4 — No raw `SET heat = X` writes (post-Phase 3)

Every mutation of the `heat` column goes through the canonical
`effective_heat()` PL/pgSQL API that will exist after Phase 3 of the
Scalability Program. Callers express intent — anchor, boost on citation,
mark stale — and the API translates into the correct update of
`heat_base`, `heat_base_set_at`, `no_decay`, or the global
`homeostatic_state.factor`.

**Rationale** (Carnot, Simon): there are currently 5 sites that write raw
heat (`pg_store.py:237, 255`; `pg_store_wiki.py:448`; `anchor.py:134`;
`preemptive_context.py:135`; `pg_schema.py:739`). The atomic A3 migration
requires all five to speak the same language; R4 keeps that language
canonical going forward.

**CI check**: grep for `SET heat =` OR `UPDATE memories` adjacent to `heat`
assignment returns only hits inside the canonical API module
(`mcp_server/infrastructure/heat_store.py`, to be created in Phase 3).

### R5 — No text-keyed dicts or caches on user content

Any memoization layer over user-provided strings must use
`hashlib.sha256(text.encode()).hexdigest()[:16]` as the cache key.
Raw text keys are forbidden.

**Rationale** (Taleb, fragility): `embedding_engine._cache[text]` with a
100 KB text key stored verbatim wastes 12.8 MB of key bytes at
cache-size = 128, and makes the cache unserializable for cross-process
sharing.

**CI check**: grep for `_cache\[.*text.*\]`, `cache\[text\]`, and equivalents
returns zero matches outside approved sites.

**Refactor target**: `infrastructure/embedding_engine.py:258, 271`.

### R7 — No multiplicative speedup claim without measurement + decomposition

Any claim of the form "this change gives X× improvement" must be accompanied
by:

1. **Before / after wall-clock measurement on the target workload** (N ≥ 3
   replicates, mean ± stddev reported).
2. **A decomposition of the predicted speedup** into at least four components:
   fsync (WAL flush), index maintenance (HNSW / B-tree / GIN), compute
   (Python or PL/pgSQL), and network (round-trip time). Each component
   must have a measured or derived cost; hand-wavy estimates are refused.
3. **A reproducibility note**: the exact `pg_stat_statements` queries,
   the DB setup (`VACUUM ANALYZE` state, autovacuum setting, extensions
   installed), and the driver (JSON-RPC stdio vs HTTP) so another engineer
   can reproduce the measurement.

**Rationale**: the v3.11 release notes predicted "100–500×" decay speedup
based on an implicit model that fsync dominated the cost. Actual measured
speedup on darval's 66K-memory store was **6.3×** (issue
[#13 comment](https://github.com/cdeust/Cortex/issues/13#issuecomment-4255035704)).
The shortfall was explained by HNSW index maintenance per-row-touched
(~30 ms per row even in batched UNNEST), WAL record per row, and RTT —
all components the fsync-only model ignored. No-one benefited from the
over-promise. Measurement discipline prevents the recurrence.

**CI check**: review-time only — any PR description or CHANGELOG entry
containing `\b\d+x\b` or `\b\d+-\d+x\b` multiplicative claims must
reference a committed benchmark artifact under `benchmarks/scalability/`.

**Reference methodology**: darval's two-DB `pg_dump`-restore +
`pg_stat_statements` per-DB + `VACUUM ANALYZE` + autovacuum-disabled
harness, as codified in `benchmarks/scalability/methodology.md` (to be
authored in Phase 0.2).

### R6 — Every handler declares a latency class

Every handler docstring under `mcp_server/handlers/` includes one of:

- `latency_class: interactive` (expected p99 < 500 ms; uses interactive pool)
- `latency_class: batch` (expected p99 < 30 s; uses interactive pool)
- `latency_class: long_running` (expected p99 unbounded; uses batch pool)

After Phase 5 lands `psycopg_pool.ConnectionPool`, the pool a handler can
acquire is determined by its declared class. Interactive handlers cannot
acquire the batch pool; long-running handlers cannot acquire the
interactive pool. This prevents a long `consolidate` from starving
`recall`.

**Rationale** (Erlang): without latency classes the single connection
singleton serializes all work. With them, interactive and batch streams
are isolated and their queueing behavior is predictable (bounded-buffer
M/M/c/K instead of M/D/1 with c=1).

**CI check**: every file under `mcp_server/handlers/` matching
`handler\s*=\s*|async\s+def\s+handler` must contain `latency_class:`
in its module docstring or its tool schema.

## Consequences

### Positive

- Prevents regression of every bottleneck class identified in the audit.
  Future engineers adding a new ingestion path, a new analyzer, or a new
  handler cannot quietly re-introduce the paradigm without an ADR documenting
  the exception.
- Gives reviewers a short, citable checklist.
- Makes the Phase 3 A3 migration enforceable — post-A3, any raw heat write
  is a CI failure.
- Sets the precondition for Phase 5 connection pooling to be safe.

### Negative

- Six new CI lint rules and three new docstring checks. Small maintenance
  burden.
- Some existing code is out of compliance today. R1/R2/R3/R5 each require
  a small refactor in the Fragility Sweep (Phase 1) before CI can enforce
  them strictly.
- R6 (latency classes) is purely advisory until Phase 5. Before then the
  pool distinction is a docstring convention with no enforcement.

### Neutral

- The rules are framed as prohibitions, not prescriptions. They do not
  mandate a specific implementation; they forbid the class of pattern
  known to break.
- Exceptions are allowed via `# noqa: Rk — <justification>`. Every
  exception must be justified at use-site and is visible to code review.

## Alternatives considered

1. **No rules — rely on code review alone.** Rejected: reviewers change; the
   paradigm re-enters quietly; Meadows specifically warned against leaving
   LP5 implicit.
2. **Rules as descriptive guidelines without CI enforcement.** Rejected:
   enforced rules produce ~99% compliance; unenforced ones drift to 0 within
   one quarter (Cochrane meta-analyses on software-engineering governance).
3. **One giant "no anti-patterns" rule.** Rejected: the six rules target
   distinct mechanisms (Taleb: information-flow, structure, rules). Conflating
   them makes the CI check untargeted and the exception markers unclear.

## Compliance plan

| Phase | R1 | R2 | R3 | R4 | R5 | R6 | R7 |
|---|---|---|---|---|---|---|---|
| 0 | Lint deployed (warning) | Lint deployed | Review only | Pending A3 | Lint deployed | Review only | Review only |
| 1 (Fragility) | Existing violations fixed | Violations fixed | Analyzer pass | — | Violations fixed | Docstrings added | — |
| 3 (A3 lands) | Lint promoted to error | — | — | Enforced | — | — | — |
| 5 (Pools land) | — | — | — | — | — | Enforced | Promoted to CI-gated |

## References

- Meadows, D. (1999). *"Leverage Points: Places to Intervene in a System"*,
  Sustainability Institute.
- Thompson, D'A. W. (1917). *On Growth and Form*, Cambridge University Press.
- Taleb, N. N. (2012). *Antifragile: Things That Gain from Disorder*, Random
  House.
- Simon, H. A. (1962). *"The Architecture of Complexity"*, Proc. Am. Philos.
  Soc. 106(6): 467–482.
- Erlang, A. K. (1917). *"Solution of some Problems in the Theory of
  Probabilities of Significance in Automatic Telephone Exchanges"*,
  Elektroteknikeren 13: 5–13.
- Cortex Scalability Program, Phases 0–7 (this repository, `docs/program/`).
- pgvector issue
  [#875](https://github.com/pgvector/pgvector/issues/875) — HNSW UPDATE
  maintenance on non-vector columns.
- Cortex issue
  [#13](https://github.com/cdeust/Cortex/issues/13) — the darval benchmark
  that triggered this work.
