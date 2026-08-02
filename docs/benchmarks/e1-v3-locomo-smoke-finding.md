# E1 v3 LoCoMo — STOP gate triggered on smoke

**Status:** STOPPED at smoke per task validation gate. Awaiting human decision on
which design path to pursue. Harness wiring committed; full sweep NOT launched.

**Date:** 2026-05-02
**Code base SHA at smoke:** ca7f9d40888065bb3b30f17e0d56bd3e68417490 (tree dirty
with concurrent agent's `mcp_server/handlers/remember*.py` and tests — those
files do NOT touch the benchmark code path; benchmark uses
`benchmarks.lib.bench_db.BenchmarkDB` → `core.memory_ingest.ingest_memories_batch`
+ `core.pg_recall.recall`, never the `remember` handler).

## Pre-registered validation gate

From task #55 spec:
> BASELINE LoCoMo MRR: historical April 2026 clean-DB Cortex comparator is 0.794, R@10=0.926 (n=1982; first published in commit `b4057a`; original per-query artefact not committed; superseded by the [post-fix re-run](e1-v3-locomo-results-post-fix.md)).
> With `--with-consolidation` enabled, this should be APPROXIMATELY similar
> (consolidation may shift it slightly, but should be within ±0.05 MRR). If
> WAY off — STOP and diagnose.

## Smoke result (n=1 conversation, 197 questions)

| Run | MRR | R@10 | Wall (s) |
|---|---|---|---|
| `--limit 1` (no consolidation) | **0.866** | **99.0%** | 221.7 |
| `--limit 1 --with-consolidation` | **0.222** | **54.8%** | 176.3 (incl. 127.7s consol) |

Δ MRR = **−0.644** vs the no-consolidation anchor.
Δ MRR = **−0.572** vs the superseded historical 0.794 comparator.

This is **WAY off** the ±0.05 tolerance. Stop-and-diagnose triggered.

## Diagnosis

**Root cause: compression cycle fires on LoCoMo's old timestamps.**

LoCoMo session dates are from May–November 2023 (real conversation timestamps
preserved by the dataset). Current wall date is 2026-05-02, so loaded memories
have `created_at` ≈ 3 years old.

Consolidation defaults
(`mcp_server/infrastructure/memory_config.py`):
- `COMPRESSION_GIST_AGE_HOURS = 168.0` (7 days) → memories older than 7d get
  full-text → gist replacement.
- `COMPRESSION_TAG_AGE_HOURS = 720.0` (30 days) → memories older than 30d get
  gist → tag replacement.

LoCoMo memories are 3 years old at ingest time, so compression IMMEDIATELY
collapses them to tags after one consolidation pass. Recall against the verbatim
question text then misses, because the original session content has been
replaced by terse tag form.

This is a real architectural collision between:
- Production cadence assumption: memories accumulate over wall-clock time,
  consolidation gradually compresses old ones.
- Benchmark loading pattern: load N sessions instantly, run consolidation, query.
  If session timestamps are old, consolidation treats them as fully aged.

This is the SAME shape of architectural mismatch the LME-S audit identified, but
in the opposite direction: LME-S exercised consolidation-only mechanisms not at
all (so they showed Δ=0); LoCoMo exercises them so aggressively at first contact
that they destroy the retrieval signal. Neither benchmark, as currently
instrumented, isolates per-mechanism effects honestly.

## Why pre-spec'd "single BASELINE_WITH_CONSOLIDATION" design is unsafe

If we take the 0.222 anchor as baseline, then any ablation that disables a stage
contributing to the destruction (e.g., MICROGLIAL_PRUNING, compression-adjacent
parts of CASCADE) will show a LARGE POSITIVE ΔMRR — but that signal will
conflate two distinct effects:

1. "Mechanism X contributes to retrieval" (the desired ablation reading).
2. "Mechanism X is the proximate cause of LoCoMo-timestamp-driven destruction"
   (a benchmark-instrumentation artifact).

Reporting these as 1-row mechanism contributions in §6.3 of the paper would
overstate the case. The corresponding LME-S rows for the same mechanisms showed
Δ=0 because consolidation never fired; reporting Δ ≈ +0.4 on LoCoMo without the
context "the ablation rescued recall from a benchmark-induced collapse" is
not honest evidence for the paper claim.

## Decision matrix (FOR HUMAN REVIEW BEFORE SWEEP LAUNCH)

### Option A — Single BASELINE_WITH_CONSOLIDATION (as spec'd) — 13 rows
- Honors task spec literally.
- Anchor MRR ≈ 0.22.
- Risk: ablation deltas conflate mechanism contribution with destruction-rescue.
  Each row's writeup MUST disclose this confound; paper §6.3 cannot use these
  numbers as standalone evidence for "mechanism X contributes Y MRR."
- Useful if the goal is documentation of LoCoMo+consolidation interaction
  rather than per-mechanism contribution claim.

### Option B — Two baselines — 14 rows (RECOMMENDED)
- BASELINE_NO_CONSOLIDATION (≈0.866 anchor): used for all longitudinal
  read-path mechanisms (RECONSOLIDATION, CO_ACTIVATION, ADAPTIVE_DECAY) since
  these mechanisms do NOT depend on a consolidation pass — they accumulate
  state via cross-question reads.
- BASELINE_WITH_CONSOLIDATION (≈0.22 anchor): used for the 8 consolidation-only
  mechanisms (CASCADE, INTERFERENCE, HOMEOSTATIC_PLASTICITY, SYNAPTIC_PLASTICITY,
  MICROGLIAL_PRUNING, TWO_STAGE_MODEL, EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE) and
  SCHEMA_ENGINE — these can only fire if consolidation fires.
- Ablation deltas reported against the relevant baseline, with the architectural
  finding stated alongside. Honest per-mechanism evidence preserved.
- Sweep cost: 14 rows × ~30 min/row = ~7 hours.

### Option C — Decouple consolidation cadence from wall-clock age
- Change `COMPRESSION_GIST_AGE_HOURS`/`COMPRESSION_TAG_AGE_HOURS` to gate on
  access-count or relative recency rather than absolute timestamp diff.
- Or: in benchmark mode, override `created_at` to be relative to the benchmark
  start so memories appear "fresh" to consolidation.
- Out of scope for task #55 — task explicitly says "DO NOT modify
  recall_pipeline.py constants — Phase A+B calibration locked." Same prohibition
  reasonably extends to consolidation cadence constants without a separate task.

### Option D — Drop the LoCoMo half — keep LME-S only
- Reverts to the 17-row evidence base from `de1d316`.
- Honest: "we couldn't isolate consolidation-only mechanism contributions on
  any benchmark currently in our suite without confound."
- The mechanisms remain in the codebase, but unsupported by ablation evidence
  in §6.3. The paper would say so.

## Wall-budget data (pre-recorded in case we proceed)

- Per-conversation wall (with consolidation): 176.3s
  - Of which consolidation: 127.7s
  - Of which ingest+QA: 48.6s
- Per-conversation wall (no consolidation): 221.7s (more time spent in QA loop
  presumably because no compressed records — denser candidate set).
- Full LoCoMo (10 conversations) per row, with consolidation: ≈30 min.
- Full LoCoMo (10 conversations) per row, no consolidation: ≈37 min.
- Option A (13 rows × 30 min) ≈ 6.5 h.
- Option B (1 NO + 1 WITH baseline + 3 longitudinal vs NO + 9 consol vs WITH =
  14 rows: 4 × 37 min + 10 × 30 min) ≈ 7.5 h.

## Smoke artifacts

- `benchmarks/results/ablation/locomo_v3_smoke/SMOKE_NO_CONSOLIDATION.json`
- `benchmarks/results/ablation/locomo_v3_smoke/SMOKE_WITH_CONSOLIDATION.json`

## Harness wiring committed (independent of sweep decision)

`benchmarks/locomo/run_benchmark.py` now supports `--with-consolidation`,
`--ablate MECH`, `--results-out PATH`, mirroring the LME-S harness signature.
Manifest block in `--results-out` JSON includes `with_consolidation`,
`ablate_mechanism`, `ablate_env_var`, `n_conversations`, `n_questions`,
`consolidation_call_count`, `consolidation_total_wall_s`.

## What I have NOT done

- Have not launched the 13-row sweep.
- Have not written `benchmarks/lib/run_e1_v3_locomo.py` driver yet (depends on
  baseline-design decision).
- Have not modified retrieval constants or consolidation-cadence constants
  (per task constraint and Zetetic standard — no source for arbitrary
  constant change).
- Have not committed any code from the dirty tree (concurrent agent's work).

## Recommendation

Option B (two baselines, 14 rows). Strongest scientific design that respects
the architectural finding and the task constraint not to mutate constants. The
extra row is honest acknowledgment that LoCoMo+consolidation has a confound,
not a workaround.

If the human reviewer prefers Option A for §6.3 page-budget reasons, document
the confound in every consolidation-only row's writeup explicitly.

If Option D, document why the LME-S evidence stands alone.
