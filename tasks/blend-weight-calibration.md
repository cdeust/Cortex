# Blend-weight calibration — 6 read-path stages

**Status:** pre-registered (results pending Phase A + B execution)
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

(to be filled in after Phase A + Phase B complete)

### Phase A optimum
TBD

### Phase B optimum
TBD

### Decision per knob
TBD

### Calibrated constants
TBD

### Notes / deviations from pre-registration
TBD
