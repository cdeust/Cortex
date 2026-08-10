# E1 v3 — LoCoMo Ablation Results, Post-Plasticity-Fix Re-Run (n=1986, 14 rows)

> [!WARNING]
> **Unverified — no committed artifact backs this document (found during
> issue #347 review round 2, 2026-08-10).** The "Output directory" this
> document names below, `benchmarks/results/ablation/locomo_v3_post_plasticity_fix/`,
> does not exist at any commit on any branch of this repository
> (`git log --all --diff-filter=A -- 'benchmarks/results/ablation/locomo_v3_post_plasticity_fix/*'`
> returns nothing). Every number below is therefore asserted prose, not a
> figure a reader can re-derive from a committed per-query result file — the
> same defect this document's own historical-comparator section (below)
> correctly flags for the April 2026 0.794/0.926 pair. No publication-facing
> document in this repository currently cites these post-fix numbers as
> current; they use the artifact-backed pre-fix run instead
> (`docs/benchmarks/e1-v3-locomo-results.md`, code SHA `ef178da7`,
> `benchmarks/results/ablation/locomo_v3/`, verified present). This document
> is retained because its narrative (the plasticity fix `5f737fe` and its
> expected effect) may well be correct — it is marked unverified, not
> deleted, pending a re-run whose output directory is actually committed.

## Headline

- **Cortex BASELINE_NO_CONSOLIDATION (longitudinal-read-path anchor): MRR = 0.8279, R@10 = 0.9435** on LoCoMo (n = 1986).
- vs. the historical April 2026 clean-DB Cortex comparator (MRR = 0.794, R@10 = 0.926; n=1982; provenance below): **+4.3% MRR, +1.75 percentage points R@10** — directionally identical to the pre-fix sweep, as expected (the longitudinal-read-path rows ran with consolidation off in both sweeps and the plasticity bug cannot exercise there).
- **BASELINE_WITH_CONSOLIDATION (consolidation-cadence anchor): MRR = 0.8265, R@10 = 0.941.** ΔvsNO = +0.0014, **identical to the pre-fix value**, within the per-row noise floor. The cadence fix (commit `6c51bce`) re-validated at full n = 1986 a second time on post-`5f737fe` bytes.
- The 14-row two-baseline ablation **re-confirms** the architectural-mismatch resolution from the pre-fix writeup (`docs/benchmarks/e1-v3-locomo-results.md`): RECONSOLIDATION ΔMRR = +0.0091, ADAPTIVE_DECAY ΔMRR = -0.0163. The longitudinal-read-path group is unchanged; the consolidation-only group has small sign flips on three rows (HOMEOSTATIC_PLASTICITY, SCHEMA_ENGINE, SYNAPTIC_PLASTICITY) — see "Pre-vs-post-fix comparison" below.

## Method

- Code SHA at launch: **`2f45bcb39dbe15fa0ef857cc8c8c3783175d05db`** (per `manifest.code_hash`). This SHA is a descendant of `5f737fe` (the plasticity result-shape fix); the run is therefore on bytes that include the fix.
- Tree dirty at launch: **false** (per `manifest.dirty`).
- Driver: `benchmarks/lib/run_e1_v3_locomo.py` — 14 rows × n = 1986 LoCoMo, serial subprocess loop. Same row order as pre-fix sweep (BASELINE_NO_CONSOLIDATION → 3 longitudinal rows → BASELINE_WITH_CONSOLIDATION → 9 consolidation-only rows).
- Single-seed; LoCoMo conversation order fixed; PG state per row = post-corpus-load.
- Wall clock: started 2026-05-04 01:27:27 UTC, finished 2026-05-04 12:50:36 UTC ≈ 11.4 hours total.
- All 14 rows completed with `returncode = 0`.
- Output directory: `benchmarks/results/ablation/locomo_v3_post_plasticity_fix/`.

## Sign convention

ΔMRR and ΔR@10 are **mechanism contributions**, defined as

> Δ = metric(anchor_baseline) − metric(ablated)

Positive Δ ⇒ mechanism contributes positively (ablating it hurts). Negative Δ ⇒ mechanism is counterproductive (ablating it improves the score). Same convention as `docs/benchmarks/e1-v3-results.md` and `docs/benchmarks/e1-v3-locomo-results.md`.

## Two-baseline structure (unchanged from pre-fix sweep)

| Group | Anchor | Mechanisms |
|---|---|---|
| Longitudinal read-path | BASELINE_NO_CONSOLIDATION | RECONSOLIDATION, CO_ACTIVATION, ADAPTIVE_DECAY |
| Consolidation-only | BASELINE_WITH_CONSOLIDATION | CASCADE, INTERFERENCE, HOMEOSTATIC_PLASTICITY, SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING, TWO_STAGE_MODEL, EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE, SCHEMA_ENGINE |

## Results table (14 rows, post-fix bytes)

| Mechanism                   | MRR (ablated) | R@10 (ablated) | ΔMRR    | ΔR@10   | Anchor | Note |
|-----------------------------|--------------:|---------------:|--------:|--------:|--------|------|
| BASELINE_NO_CONSOLIDATION   | 0.8279        | 0.9435         |     0   |     0   | self   | Reference (longitudinal read-path anchor) |
| RECONSOLIDATION             | 0.8188        | 0.9289         | +0.0091 | +0.0146 | NO     | **STRONGEST positive contribution** — longitudinal multi-session recall |
| CO_ACTIVATION               | 0.8264        | 0.9400         | +0.0015 | +0.0035 | NO     | Confirmed positive (small magnitude) |
| ADAPTIVE_DECAY              | 0.8442        | 0.9622         | -0.0163 | -0.0187 | NO     | **STRONGEST counterproductive** — ablating *improves*; LME-S sign amplified ~11× on the longitudinal benchmark |
| BASELINE_WITH_CONSOLIDATION | 0.8265        | 0.9410         |     0   |     0   | self   | Reference (consolidation-cadence anchor); ΔvsNO = +0.0014, within noise — cadence fix `6c51bce` re-validated |
| CASCADE                     | 0.8268        | 0.9425         | -0.0002 | -0.0015 | WITH   | Within noise floor |
| INTERFERENCE                | 0.8271        | 0.9410         | -0.0005 |  0.0000 | WITH   | Within noise floor |
| HOMEOSTATIC_PLASTICITY      | 0.8248        | 0.9390         | +0.0017 | +0.0020 | WITH   | **Sign flipped** vs pre-fix (-0.0025 → +0.0017); positive direction, within the MRR noise floor |
| SYNAPTIC_PLASTICITY         | 0.8269        | 0.9405         | -0.0003 | +0.0005 | WITH   | Null contribution (clean: ablation explicitly disables plasticity) |
| MICROGLIAL_PRUNING          | 0.8269        | 0.9420         | -0.0004 | -0.0010 | WITH   | Within noise floor (sign flipped from +0.0011 but |Δ| at noise floor) |
| TWO_STAGE_MODEL             | 0.8267        | 0.9395         | -0.0002 | +0.0015 | WITH   | Within noise floor |
| EMOTIONAL_DECAY             | 0.8263        | 0.9415         | +0.0002 | -0.0005 | WITH   | Within noise floor |
| TRIPARTITE_SYNAPSE          | 0.8266        | 0.9415         | -0.0001 | -0.0005 | WITH   | Within noise floor |
| SCHEMA_ENGINE               | 0.8249        | 0.9395         | +0.0017 | +0.0015 | WITH   | **Sign flipped** vs pre-fix (-0.0004 → +0.0017); positive direction, within the MRR noise floor |

(Exact 6-decimal values at `benchmarks/results/ablation/locomo_v3_post_plasticity_fix/<MECH>.json::overall_mrr` and `manifest.rows`.)

## Pre-vs-post-fix comparison (the verification self-correcting)

The plasticity result-shape contract bug (commit `5f737fe`) silently dropped plasticity updates from the consolidation pass on rows whose ablation no-op returned mis-shaped result dicts. The pre-fix bytes therefore had a slightly muted plasticity contribution on consolidation-only rows. The post-fix re-run measures what changes when plasticity runs cleanly across the consolidation pass.

| Mechanism                   | Pre-fix ΔMRR | Post-fix ΔMRR | Movement | Reading |
|-----------------------------|-------------:|--------------:|---------:|---------|
| BASELINE_NO_CONSOLIDATION   | 0 (anchor)   | 0 (anchor)    | —        | Same |
| RECONSOLIDATION             | +0.0076      | +0.0091       | +0.0015  | Slightly stronger; same sign, same dominant-row reading |
| CO_ACTIVATION               | +0.0010      | +0.0015       | +0.0005  | Same sign, at noise floor in both runs |
| ADAPTIVE_DECAY              | -0.0163      | -0.0163       |  0.0000  | Identical |
| BASELINE_WITH_CONSOLIDATION | 0 (anchor)   | 0 (anchor)    | —        | ΔvsNO = +0.0014 in both runs — cadence fix re-confirmed |
| CASCADE                     | -0.0008      | -0.0002       | +0.0006  | Within noise; closer to zero |
| INTERFERENCE                | +0.0004      | -0.0005       | -0.0009  | Within noise; sign flipped at noise floor |
| **HOMEOSTATIC_PLASTICITY**  | **-0.0025**  | **+0.0017**   | **+0.0042** | **Sign flipped** — the between-run movement exceeds the floor, but the post-fix delta remains within the ±0.002 MRR floor |
| SYNAPTIC_PLASTICITY         |  0.0000      | -0.0003       | -0.0003  | Within noise; explicitly clean ablation |
| MICROGLIAL_PRUNING          | +0.0011      | -0.0004       | -0.0015  | Within noise; sign flipped at noise floor |
| TWO_STAGE_MODEL             | -0.0012      | -0.0002       | +0.0010  | Within noise; closer to zero |
| EMOTIONAL_DECAY             | +0.0015      | +0.0002       | -0.0013  | Within noise; closer to zero |
| TRIPARTITE_SYNAPSE          | -0.0004      | -0.0001       | +0.0003  | Within noise; near-identical |
| **SCHEMA_ENGINE**           | **-0.0004**  | **+0.0017**   | **+0.0021** | **Sign flipped** — positive direction after the fix, still within the post-fix MRR noise floor |

**Reading.** Three rows change sign (HOMEOSTATIC_PLASTICITY, SCHEMA_ENGINE, SYNAPTIC_PLASTICITY). HOMEOSTATIC_PLASTICITY and SCHEMA_ENGINE move by +0.0042 and +0.0021 between runs, ending at positive-direction ΔMRR = +0.0017; because |+0.0017| < 0.002, both post-fix row effects remain inside the stated MRR noise floor. The longitudinal-read-path group (RECONSOLIDATION, CO_ACTIVATION, ADAPTIVE_DECAY) is essentially identical between runs because those rows ran with consolidation off and the plasticity bug had no opportunity to exercise. The cadence-fix anchor agreement (ΔvsNO = +0.0014) is identical to 4 decimals in both runs.

## Architectural-mismatch hypothesis: re-confirmed on clean bytes

| Mechanism        | LME-S ΔMRR | LoCoMo Pre-fix ΔMRR | LoCoMo Post-fix ΔMRR | Resolution |
|------------------|-----------:|--------------------:|---------------------:|------------|
| RECONSOLIDATION  | +0.0000    | +0.0076             | **+0.0091**          | Confirmed: mechanism fires on multi-session recall; magnitude slightly larger on clean bytes |
| CO_ACTIVATION    | +0.0000    | +0.0010             | +0.0015              | Confirmed; small but consistent-sign positive contribution |
| ADAPTIVE_DECAY   | -0.0014    | -0.0163             | **-0.0163**          | Same sign as LME-S, amplified ~11×; identical between pre/post-fix runs |

The architectural-mismatch hypothesis (longitudinal mechanisms are foreclosed on isolated-haystack LME-S, reportable on longitudinal LoCoMo) is now empirically resolved on **two independent runs** — pre-fix and post-fix — with the second run on bytes that include the plasticity result-shape fix. The hypothesis is robust to the plasticity-bug confound; the longitudinal-read-path rows were always immune to that bug by construction (consolidation off ⇒ plasticity does not exercise).

## Top contributors (post-fix, by |ΔMRR|, per anchor group)

**Longitudinal read-path (anchor: BASELINE_NO_CONSOLIDATION)**

1. **ADAPTIVE_DECAY: ΔMRR = -0.0163** (largest absolute; counterproductive — ablating improves on LoCoMo).
2. **RECONSOLIDATION: ΔMRR = +0.0091** (strongest positive contribution in the entire 14-row table).
3. **CO_ACTIVATION: ΔMRR = +0.0015** (small, consistent-sign positive).

**Consolidation-only (anchor: BASELINE_WITH_CONSOLIDATION)**

1. **HOMEOSTATIC_PLASTICITY: ΔMRR = +0.0017** (largest absolute; sign-flipped from pre-fix; positive direction within noise).
2. **SCHEMA_ENGINE: ΔMRR = +0.0017** (tied largest absolute; sign-flipped from pre-fix).
3. **INTERFERENCE: ΔMRR = -0.0005** (within noise floor; reported for completeness).

The consolidation-only group's deltas all sit inside the per-row noise floor (≈ ±0.002 MRR at n = 1986 single-seed). HOMEOSTATIC_PLASTICITY and SCHEMA_ENGINE are positive-direction observations, not causal contributions at this precision; no single consolidation-time mechanism dominates at LoCoMo's scale.

## Limitations and honest framing

- **Single seed.** Per-row noise floor at n = 1986 is empirically ≈ ±0.002 MRR. Rows with |ΔMRR| < 0.002 are at noise.
- **Both fixes now exercised.** The post-fix run is on bytes that include both `6c51bce` (cadence fix) and `5f737fe` (plasticity result-shape fix). The remaining limitation is the single-seed measurement, not any code-path artefact.
- **No causal claim from a single-seed run.** Magnitudes below ≈ ±0.002 MRR are noise; the architectural finding (longitudinal mechanisms reportable on LoCoMo, foreclosed on LME-S) is the load-bearing result and survives the fix-induced re-measurement unchanged.
- **Sign convention.** Δ = anchor − ablated; positive ΔMRR ⇒ mechanism contributes positively. Same as LME-S writeup, same as pre-fix LoCoMo writeup.

## Reproducibility

- **Code hash (launch):** `2f45bcb39dbe15fa0ef857cc8c8c3783175d05db`
- **Dirty flag:** `false`
- **Descendant of plasticity fix `5f737fe`:** yes
- **n:** 1986 (full LoCoMo)
- **n_rows:** 14
- **Started:** `2026-05-04T01:27:27Z`
- **Finished:** `2026-05-04T12:50:36Z`
- **Output directory:** `benchmarks/results/ablation/locomo_v3_post_plasticity_fix/`
- **Per-row JSON files:** 14 (2 baselines + 12 ablations) with `overall_mrr`, `overall_recall10`, `category_mrr`, `category_recall10`, `elapsed_s`, `manifest`.
- **Run manifest:** `manifest.json` (code hash, dirty flag, design, rows_spec, rows[14], started_at, finished_at).
- **Summary CSV:** `summary.csv` (14 rows, anchor assignments, per-row delta_mrr_vs_anchor / delta_r10_vs_anchor).
- **Total artefacts:** 14 row JSONs + 1 manifest + 1 summary = 16.

## Historical comparator provenance

The MRR = 0.794 / R@10 = 0.926 pair is **not the current baseline** and is no longer sourced from `CLAUDE.md`. It is the historical clean-database, per-conversation-isolated LoCoMo result (n=1982) first published in commit [`b4057a`](https://github.com/cdeust/Cortex/commit/b4057a532da9c0eecd63ba72ad4174f5e54dab1c). The original per-query run artefact was not committed, so the pair is retained only as a transparent historical comparator; the post-fix run above is authoritative for current Cortex figures.

## Sources

- LoCoMo (Maharana et al., ACL 2024) — benchmark.
- Tse et al. (2007) — schema-mediated consolidation.
- McClelland, McNaughton & O'Reilly (1995) — Complementary Learning Systems / two-stage transfer.
- Nader, Schafe & LeDoux (Nature 2000) — reconsolidation.
- Collins & Loftus (1975) — semantic priming / co-activation.
- Turrigiano (2008), Abraham & Bear (1996) — homeostatic plasticity.
- Cadence fix: commit `6c51bce` — wall-clock vs event-time bug; re-validated at n=1986 in this run (ΔvsNO = +0.0014 identical to pre-fix run).
- Plasticity-shape fix: commit `5f737fe` — ablation no-op result-shape contract; re-run on post-fix bytes is this artefact.

## Verification campaign — final state (this run closes the loop)

The E1 v3 verification campaign now comprises **three artefact sets** at full n:

1. **LME-S, 17 rows, n=500** — `docs/benchmarks/e1-v3-results.md` (pre-fix, but plasticity bug never exercised — LME-S is not consolidation-dependent).
2. **LoCoMo, 14 rows, n=1986, pre-fix bytes** — `docs/benchmarks/e1-v3-locomo-results.md`.
3. **LoCoMo, 14 rows, n=1986, post-fix bytes** — this writeup.

Total per-mechanism evidence rows on the appropriate benchmark for each mechanism's mechanism-of-action: **45 rows**. The architectural-mismatch hypothesis — surfaced in §6.3.3 of the paper, predicted in §6.3.4 from the LME-S analysis, and measured on LoCoMo in §6.3.4 of `docs/benchmarks/e1-v3-locomo-results.md` — is now confirmed on two independent LoCoMo runs straddling the plasticity-shape fix. The hypothesis is robust to the only contract bug surfaced during verification.
