# Draft reply to darval — issue #13

**Instructions**: review and edit tone / word choice before posting. Post as
a comment on
https://github.com/cdeust/Cortex/issues/13#issuecomment-4255035704

---

Thanks for the rigorous methodology — the `pg_dump` into two independent
DBs, `pg_stat_statements` per-DB scoped with `VACUUM ANALYZE` +
autovacuum disabled, the JSON-RPC stdio driver, and the clean
decomposition of the decay shortfall into HNSW index maintenance + WAL
volume + network RTT. That methodology is now being adopted as the Phase
0.2 baseline standard for the scalability program — will be codified
verbatim at `benchmarks/scalability/methodology.md`. The
[ADR](../adr/ADR-0045-scalability-governance-rules.md) that formalizes
measurement discipline for the project cites your approach as the
reference.

Your hypothesis that HNSW maintenance is the real carrier of the 539 s
residual was right, and testing it properly changed the plan.

## What the controlled experiment showed

Ran an isolation matrix on a synthetic 66,064-row table replicating
Cortex's HNSW config (`m=16, ef_construction=64`, 384-dim), N≥3 replicates
per condition, server-side timing via PL/pgSQL `clock_timestamp()`:

| Condition | HNSW | UPDATE kind | mean |
|---|---|---|---|
| A | present | per-row (single txn) | 115.4 s |
| B | present | batched UNNEST | **208.7 s** |
| C | dropped | per-row | 4.3 s |
| D | dropped | batched UNNEST | 1.6 s |
| E | present | batched + `IS DISTINCT FROM` (all rows change) | 169.9 s |

`A − C = 111 s` of pure HNSW maintenance cost on the per-row path. `B − D =
207 s` on the batched path. On HNSW-indexed tables, **batching is not a
speedup** — a single UNNEST UPDATE touching 66 K rows still triggers full
HNSW graph maintenance because the row width (embedding = 1.5 KB) forces
non-HOT MVCC, and pgvector's HNSW doesn't participate in HOT
(pgvector [#875](https://github.com/pgvector/pgvector/issues/875)).

The per-row → batched patch I shipped after your report reduces total time
~2× in production (removes the 65 K fsync amplification) but leaves HNSW
as the dominant stage carrier. That patch has been reverted; a measurement-
discipline rule (R7) is being added so future speedup claims require
before/after numbers with an explicit fsync / index / compute / network
decomposition, not an implicit single-factor model.

## Fragility audit — memory_entities coverage is the next blocker

A follow-up completeness audit found the `memory_entities` join table is
at **0.49 %** coverage on the cortex DB (required: 99 % for the planned
JOIN-replacement to be safe). The mechanism is exactly what your report
would predict in a different form: `persist_entities` runs synchronously
at memory write time, but never back-fills old memories when a new entity
is extracted from a later write. Result: every memory older than ~one week
has zero links, and the substring-scan stages (`plasticity`,
`synaptic_tagging`) are silently more permissive than any JOIN would be.

Named this `retroactive-entity-orphans` in the audit. Going to land a
trigram-prefiltered backfill (exploiting the existing `pg_trgm` GIN on
`memories.content`) + a windowed `reconcile_memory_entities` job that runs
inside consolidate on a daily schedule. A secondary finding — 111
case-variant entity duplicate groups (`Output`/`OUTPUT`, `String`/`STRING`,
…) — is filed as a Phase 1 knowledge-graph extraction bug. Not blocking
Phase 2 directly but feeds the dictionary bloat.

## What actually needs to happen — the plan

Your report seeded a multi-agent audit (Thompson scaling laws, Erlang
queuing, Carnot efficiency floors, Taleb fragility, Meadows leverage,
Simon decomposability, Curie measurement, Lamport invariants). 34
findings total, collapsed into one coupled core + sequential chain +
three parallel peripheries. Plan lives at
`docs/program/scalability-plan.md`; abbreviated:

1. **`memory_entities` JOIN replacement (Phase 2, blocked on backfill).**
   `plasticity` and `synaptic_tagging` today do Python-side substring
   scans. The join table already exists, populated synchronously on every
   `remember`. One JOIN each replaces O(N×E) with O(E_links). Predicted
   plasticity drop from ~200 s to < 30 s on your store. Phase 2 PR must
   include a parity test asserting co-accessed-pair count within 1 %
   between substring and JOIN — two independent implementations agreeing
   is the confirmation standard.

2. **Atomic `effective_heat()` migration (Phase 3).** `heat` becomes a
   PL/pgSQL function of `(heat_base, heat_base_set_at, last_accessed,
   stage, stage_entered_at, valence, homeostatic_state.factor)` — no
   stored mutable heat column, no per-row writes for decay or homeostatic
   scaling. Decay and homeostatic stages are deleted, not optimized, per
   Feynman's first-principles rederivation of Tetzlaff 2011 Eq. 3.
   Per-domain partitioning of `memories` lands in the same migration so
   the HNSW surface per partition stays bounded. Enforces a single heat
   writer (invariant I2) — today 5 sites write `heat` raw; post-A3 only
   `store.bump_heat_raw` exists.

3. **Chunked consolidate + streaming homeostatic (Phase 4).** Server-side
   cursor instead of `SELECT *` materialization. Welford streaming moments
   for homeostatic health (replaces the current 4-pass loop). Peak Python
   memory during consolidate drops from ~2 GB to < 500 MB on 66 K;
   consolidate wall-clock target < 2 min on 66 K, < 20 min on 660 K.

4. **Connection pool + admission control (Phase 5).** The single `_conn`
   singleton today is accidentally an admission controller at c=1.
   Replacing it with `psycopg_pool(min=2, max=8)` without adding admission
   control would make P99 worse under burst, not better — so the pool
   change is gated on `to_thread`-wrapping all sync calls, admission
   middleware, and a separate connection for `consolidate` vs
   interactive. Bundled atomic change, measured load-test gate.

5. **Fragility sweep (Phase 1, parallel).** Via-negativa removals for
   the black-swan paths at larger scale: delete `full_read=True` from
   `import_sessions`, SHA-keyed embedding cache, tighten content / tag
   envelope, `itertools.islice` before `sorted(root.rglob("*"))`,
   one-pass Welford moments in `homeostatic_health`, case-variant entity
   canonicalization in the knowledge-graph extractor.

## Two specific points from your report

- **`emergence_tracker` AttributeError** — real import bug introduced when
  `emergence_tracker` was split into `emergence_metrics` to stay under the
  300-line file cap. `generate_emergence_report` moved to the new module;
  the caller in `consolidate.py` wasn't updated. Fixed in the same commit
  that reverts the homeostatic patch. Thank you for catching it.

- **Cascade `stage_transitions` batching on real workloads** — valid
  point; your dataset only produced ~500 transitions so the batching
  never got exercised. Phase 4 adds a production-scale workload generator
  (10 K+ transitions) to CI so the batching is verified under realistic
  loads, not just unit-test workloads.

## Request

Can I get the `run_a.json` / `run_b.json` dumps you offered? Those become
the ground-truth baseline for Phase 0.2 — the before-numbers every later
phase is validated against, rather than re-synthesizing on a smaller
local store. If it's easier to share via gist or S3 link, either works.

The plan assumes production-scale Cortex, not just current darval-scale —
your timeline of re-running benchmarks on your 66 K store would be the
empirical close-out for each phase. If you're open to it, we'd rather
ship each phase with confirmation on your data than ship blind and
retro-fit.

Cheers.

---

*Signed-off by the zetetic audit team:
Thompson (scaling laws), Erlang (queuing), Carnot (efficiency floors),
Taleb (fragility), Meadows (leverage ranking), Simon (decomposability),
Curie (isolation measurement + I4 completeness audit), Lamport
(invariants I1–I10), Feynman (first-principles rederivation of
homeostatic).*
