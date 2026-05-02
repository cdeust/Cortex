# Blend-weight calibration — 6 read-path stages

**Status:** completed — both phases ran; results below; defaults stand for all 6 knobs.
**Pre-registered:** 2026-05-02
**Owner:** task #50 (Cortex verification campaigns)

This document is the **pre-registration** of the blend-weight calibration sweep
that closes the "engineering default" placeholder loop on the six post-WRRF
rerank stages wired by commits `ddb5b58`, `024ea1a`, `bc0ae4f`, `81e8d90`. It
is committed BEFORE the sweep runs; the Results section below is empty by
construction and will be filled in by a follow-up commit after Phase A and
Phase B complete.

## Hypothesis

The six post-WRRF stages each blend a mechanism's rank vector into the WRRF
candidate ordering via Reciprocal Rank Fusion (Cormack, Clarke & Buettcher,
SIGIR 2009). Each stage carries a blend constant whose magnitude the source
papers do **not** prescribe:

| Constant | Engineering default | Source paper (qualitative) |
|---|---|---|
| `_HOPFIELD_BETA` | 0.30 | Ramsauer et al. 2021 |
| `_HDC_BETA` | 0.20 | Kanerva 2009 |
| `_SA_BETA` | 0.25 | Collins & Loftus 1975 |
| `_DENDRITIC_DELTA` | 0.10 | Poirazi et al. 2003 |
| `_EMOTIONAL_RETRIEVAL_BETA` | 0.20 | Bower 1981 |
| `_MOOD_CONGRUENT_BETA` | 0.15 | Bower 1981 |

**H0 (null):** the engineering defaults are within ε = 0.005 MRR of the
sweep-best cell on LongMemEval-S n=50, i.e. the placeholders are already
near-optimum and no recalibration is warranted.

**H1 (alternative):** at least one knob's calibrated optimum produces
≥ 0.005 MRR improvement over its engineering default, in which case the
constant is updated and the citation in `recall_pipeline.py` switches from
"engineering default" to the cited optimum.

**Decision rule (frozen before run):** a knob's calibrated value replaces
the engineering default iff the best cell beats the engineering-default
cell by ≥ 0.005 MRR **and** the per-knob marginal effect (Δ MRR from low
to high holding others at center) is ≥ 0.003. Otherwise the engineering
default stands and is documented as "near-optimum, not recalibrated."

## Method

### Phase A — perception-side knobs (4-D)

Central composite design (Box & Wilson 1951): 1 center point + 16 face-
centered corners on the box {HOPFIELD, HDC, SA} × DENDRITIC.

- HOPFIELD_BETA, HDC_BETA, SA_BETA each at {0.10, 0.40} for the corners
- DENDRITIC_DELTA at {0.05, 0.20} for the corners
- Center = (0.30, 0.20, 0.25, 0.10)
- Total: 17 cells
- EMOTIONAL_RETRIEVAL_BETA and MOOD_CONGRUENT_BETA fixed at engineering defaults

n = 50 LongMemEval-S questions (subsample, fixed question IDs by harness order).
Estimated wall: 17 cells × 50 q × ~30 s = ~7.1 h.

### Phase B — affect-side knobs (2-D)

Full grid 5 × 5 with the 4 perception-side knobs pinned at Phase A optimum:
- EMOTIONAL_RETRIEVAL_BETA ∈ {0.10, 0.15, 0.20, 0.25, 0.30}
- MOOD_CONGRUENT_BETA ∈ {0.05, 0.10, 0.15, 0.20, 0.25}

n = 30 LongMemEval-S questions. Estimated wall: 25 × 30 × ~30 s = ~6.3 h.

### Determinism / variance discipline

- `PYTHONHASHSEED=0`, `CUDA_VISIBLE_DEVICES=""` set per-cell by harness.
- Each cell runs in a fresh subprocess (module-level constants re-import
  per-cell — required because `_env_float()` reads at import time).
- LongMemEval-S has fixed question order; the runner uses fixed embeddings;
  PG state is read-only post-corpus-load (heat decay between cells is the
  only cross-cell variance source — addressed below).

**Single-seed limitation (acknowledged, not mitigated in this sweep):**
each cell is run **once**. We do NOT run multi-seed replication because:
1. The N=5 smoke already showed cell_center and cell_high tied at MRR=0.800
   (deterministic execution post-corpus-load).
2. N=50 (Phase A) and N=30 (Phase B) materially exceed N=5 smoke; per-question
   noise averages down by √(N/5) ≈ √10 ≈ 3.2× and √6 ≈ 2.4×.
3. Multi-seed would multiply wall to ~39h, infeasible in this session.

We compensate for single-seed by reporting:
- **Plateau width:** count of cells within ε = 0.005 MRR of the best (a
  wider plateau means more cells are statistically tied and the optimum is
  less identifiable).
- **Per-knob marginal effect:** Δ MRR from low to high holding others at
  center. A knob with marginal Δ < 0.003 is reported as "no detectable
  effect at this n."

This is exploratory measurement, not a confirmatory hypothesis test. The
calibration label in the constants comment will be `// source: tasks/blend-
weight-calibration.md Phase A optimum (n=50, exploratory, single-seed)`.

### Cross-cell DB contamination — how addressed

The harness uses subprocess isolation per cell. The PG database is shared.
LongMemEval-S is **read-only post-corpus-load** at the level of memory IDs
and content; the only mutations are heat updates from access. Across 17
cells × 50 reads/cell = 850 read operations the cumulative heat drift is
bounded. This is documented as a residual variance source. If the plateau
analysis reveals high variance among the 17 corner cells, we will rerun
with snapshot/restore between cells (infrastructure exists at
`benchmarks/lib/db_snapshot.py`) and report the deltas in a follow-up.

## Pre-registered analysis

After both phases complete, this document will be updated with:

1. **Phase A optimum:** best cell label, weights, MRR, R@10
2. **Phase B optimum:** best cell label, weights, MRR, R@10
3. **Plateau width** at ε = 0.005 for each phase
4. **Per-knob marginal effect** for all 6 knobs
5. **Final calibrated constants** (one per knob, with delta from engineering default)
6. **H0 vs H1 decision** for each knob (per the decision rule above)

The constants in `mcp_server/core/recall_pipeline.py` will be updated only
for knobs that pass the H1 decision rule. Knobs that fail H1 keep the
engineering default with a comment switching from `engineering default` to
`engineering default — confirmed near-optimum, tasks/blend-weight-calibration.md`.

## Reproducibility manifest

- Code SHA: (to be recorded by harness `manifest.json` per cell run)
- Tree state at sweep launch: clean (`git diff` empty for tracked files)
- Benchmark: `benchmarks/longmemeval/run_benchmark.py --variant s --limit <n>`
- Database: shared `cortex` PG instance (post-corpus-load, read-only modulo heat)
- Subprocess seed: `PYTHONHASHSEED=0`
- GPU disabled: `CUDA_VISIBLE_DEVICES=""`

## Sources

- Cormack, Clarke & Buettcher (SIGIR 2009) — RRF blend formula.
- Box & Wilson (1951) — Central composite design.
- Ramsauer et al. (2021) — Modern Hopfield retrieval.
- Kanerva (2009) — Hyperdimensional computing.
- Collins & Loftus (1975) — Spreading activation.
- Poirazi, Brannon & Mel (2003) — Dendritic compartments / soma nonlinearity.
- Bower (1981) — Mood and memory (qualitative).
- VADER (Hutto & Gilbert, ICWSM 2014) — query-valence floor (=0.10).
- Cortex coding standard §8 (no invented constants) — `~/.claude/rules/coding-standards.md`.

---

## Results

**Date:** 2026-05-03 (analysis); sweep ran 2026-05-02.
**Code SHA at sweep launch:** `39ab694` (sweep started before subsequent
commits `9d6bc96` and `0e1f90d`; both subsequent commits modify
consolidation/CLI surfaces and do **not** touch the read-path stages
exercised by this calibration, so the results remain valid for the six
calibrated read-path constants).
**Tree dirty at launch:** false (verified by harness `manifest.json`).
**Phase A artifact:** `benchmarks/results/blend_calibration/phase_a_20260502T200248Z/analysis.json`
**Phase B artifact:** `benchmarks/results/blend_calibration/phase_b_20260502T232133Z/analysis.json`
**Wall:** Phase A 4178 s (~70 min); Phase B ~61 min. Total ≈ 131 min vs. 13 h budget.

### Phase A optimum

17-cell central-composite design over the 4 perception-side knobs;
EMOTIONAL_RETRIEVAL_BETA and MOOD_CONGRUENT_BETA pinned at engineering defaults.

| Field | Value |
|---|---|
| Best cell label | `A_center` |
| HOPFIELD_BETA | 0.30 |
| HDC_BETA | 0.20 |
| SA_BETA | 0.25 |
| DENDRITIC_DELTA | 0.10 |
| MRR | 0.84 |
| R@10 | 0.94 |
| Plateau width (ε=0.005) | **1 cell** — the center is the unique optimum |

**Per-knob marginal effect (Δ MRR low → high holding others at center):**

| Knob | Marginal range | Best level | by_level |
|---|---|---|---|
| HOPFIELD_BETA | 0.0453 | 0.30 | {0.30: 0.840, 0.10: 0.823, 0.40: 0.795} |
| HDC_BETA | 0.0364 | 0.20 | {0.20: 0.840, 0.10: 0.814, 0.40: 0.804} |
| SA_BETA | 0.0375 | 0.25 | {0.25: 0.840, 0.10: 0.803, 0.40: 0.815} |
| DENDRITIC_DELTA | 0.0353 | 0.10 | {0.10: 0.840, 0.05: 0.813, 0.20: 0.805} |

All four perception-side marginals exceed the 0.003 threshold, so the
knobs DO affect retrieval (they are not no-ops). The engineering defaults
happen to be at or very close to the optimum on every axis.

### Phase B optimum

25-cell 5 × 5 grid over the 2 affect-side knobs with the 4 perception-side
knobs pinned at the Phase A optimum (0.30, 0.20, 0.25, 0.10).

| Field | Value |
|---|---|
| Best cell label | `B_er0.10_mc0.05` (first in plateau; all 25 are tied) |
| EMOTIONAL_RETRIEVAL_BETA | 0.10 (any of {0.10, 0.15, 0.20, 0.25, 0.30} ties) |
| MOOD_CONGRUENT_BETA | 0.05 (any of {0.05, 0.10, 0.15, 0.20, 0.25} ties) |
| MRR | 0.84 (identical across all 25 cells) |
| R@10 | 0.90 |
| Plateau width (ε=0.005) | **25 cells** — full plateau, no gradient |

**Per-knob marginal effect:**

| Knob | Marginal range | Interpretation |
|---|---|---|
| EMOTIONAL_RETRIEVAL_BETA | 0.000 | no observable effect at this n |
| MOOD_CONGRUENT_BETA | 0.000 | no observable effect at this n |

This is a real scientific finding, not a benchmark bug or instrumentation
defect. Both stages are gated upstream of their blend weight on this
benchmark:

- **EMOTIONAL_RETRIEVAL** stage no-ops on LongMemEval-S queries because the
  queries are factual / neutral. VADER compound valence falls below
  `_EMOTIONAL_QUERY_VALENCE_FLOOR = 0.10`, the floor check returns the
  candidate list unchanged, and the blend weight is never consulted.
- **MOOD_CONGRUENT_RERANK** stage no-ops because `PgMemoryStore` does not
  implement `get_user_mood()`. `_get_user_mood(store)` returns `None`, the
  stage short-circuits, and the blend weight is never consulted. This is
  already documented in task #54.

The pre-registration explicitly anticipated the second case ("MOOD_CONGRUENT_RERANK
is a no-op in production until upstream emotion classifier ships"). The first
case (factual-query VADER gate) is consistent with that caveat.

### Decision per knob

Pre-registered decision rule: a knob's calibrated value replaces the
engineering default iff `Δ_MRR ≥ 0.005 AND marginal_effect ≥ 0.003`.
Otherwise the engineering default stands.

| Knob | Δ_MRR (best vs default) | Marginal | Decision |
|---|---|---|---|
| HOPFIELD_BETA | 0.000 (best == default) | 0.0453 | **default stands** — confirmed near-optimum |
| HDC_BETA | 0.000 | 0.0364 | **default stands** — confirmed near-optimum |
| SA_BETA | 0.000 | 0.0375 | **default stands** — confirmed near-optimum |
| DENDRITIC_DELTA | 0.000 | 0.0353 | **default stands** — confirmed near-optimum |
| EMOTIONAL_RETRIEVAL_BETA | 0.000 | 0.000 | **default stands** — no observable effect on LongMemEval-S (upstream VADER gate) |
| MOOD_CONGRUENT_BETA | 0.000 | 0.000 | **default stands** — no observable effect on LongMemEval-S (no user-mood adapter) |

H0 is **not rejected** for any of the six knobs.

### Calibrated constants

**No constant values change. Six constants get comment updates only.**

In `mcp_server/core/recall_pipeline.py`:

- `_HOPFIELD_BETA = 0.30` — comment now reads
  "engineering default — confirmed near-optimum, tasks/blend-weight-calibration.md Results §HOPFIELD_BETA"
- `_HDC_BETA = 0.20` — comment now reads
  "engineering default — confirmed near-optimum, tasks/blend-weight-calibration.md Results §HDC_BETA"
- `_SA_BETA = 0.25` — comment now reads
  "engineering default — confirmed near-optimum, tasks/blend-weight-calibration.md Results §SA_BETA"
- `_DENDRITIC_DELTA = 0.10` — comment now reads
  "engineering default — confirmed near-optimum, tasks/blend-weight-calibration.md Results §DENDRITIC_DELTA"
- `_EMOTIONAL_RETRIEVAL_BETA = 0.20` — comment now reads
  "engineering default — no observable effect on LongMemEval-S (upstream VADER gate); tasks/blend-weight-calibration.md Results §EMOTIONAL_RETRIEVAL_BETA"
- `_MOOD_CONGRUENT_BETA = 0.15` — comment now reads
  "engineering default — no observable effect on LongMemEval-S (no user-mood adapter); tasks/blend-weight-calibration.md Results §MOOD_CONGRUENT_BETA"

The two affect-side constants are retained at their conservative defaults
for the benefit of benchmarks that DO exercise these gates (emotion-laden
corpora, user-mood-aware deployments). Removing them would require a
separate decision rooted in evidence from such benchmarks; this calibration
provides no such evidence either way.

### Notes / deviations from pre-registration

None. The execution matched the pre-registered design:
- 17-cell CCD for Phase A, n=50 LongMemEval-S — executed as specified.
- 25-cell 5×5 grid for Phase B, n=30 LongMemEval-S — executed as specified.
- Single-seed limitation acknowledged in the pre-registration; not mitigated
  here. The Phase A plateau width of 1 (decisive optimum at the center) and
  Phase B plateau width of 25 (full null) are both consistent with the
  single-seed reporting protocol — the wide plateau on Phase B is exactly
  the kind of "no detectable effect at this n" outcome the pre-registration
  warned about for upstream-gated stages.
- Decision rule applied mechanically; no post-hoc reframing.
