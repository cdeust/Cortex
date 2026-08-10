# E1 v3 LME-S per-category delta analysis

> [!WARNING]
> **BASELINE per-category numbers below are a stale, unreproducible snapshot —
> not the current per-category figures.** The BASELINE row (`Temporal reasoning`
> MRR 0.9256/R@10 98.5%, `Single-session (preference)` MRR 0.6678/R@10 93.3%)
> came from `benchmarks/results/ablation/longmemeval-s_v3/BASELINE.json`, a
> single May 2026 run with `manifest.repro = null` — no code SHA was captured,
> so it cannot be pinned to a commit or reproduced. Every dated, git-SHA-tracked
> `benchmarks/results/repro/*/longmemeval-s.json` run from 2026-07-08 through
> 2026-08-09 (30+ runs across dozens of commits, `with_consolidation=false` in
> every case, same `--variant s` harness) agrees instead on `Temporal reasoning`
> R@10 = 97.7% (MRR 0.917-0.919) and `Single-session (preference)` R@10 = 90.0%
> (MRR 0.685-0.694) — flat across a month of active development, i.e. these are
> the stable current values, not a regression from the BASELINE row above. See
> `docs/benchmarks/arxiv-figure-audit-2026-08-02.md` § Per-category provenance
> for the full evidence. Use `README.md`'s LongMemEval per-category table for
> current figures; this document's mechanism-specialization deltas (§ Per-mechanism,
> per-category Δ MRR below) remain a valid historical read-path finding computed
> against the BASELINE row's own per-mechanism ablation set, not a current baseline.

Re-analysis of existing 17-row E1 v3 LME-S dataset (no re-run); category_mrr fields
are present in every result JSON. Reveals mechanism specialization that is hidden in
the overall MRR average because category effects cancel.

**Convention:** Δ = BASELINE - ABLATED. Positive Δ means the mechanism CONTRIBUTES
to that category (disabling it costs MRR). Negative Δ means the mechanism is
COUNTERPRODUCTIVE on that category (disabling it improves MRR).

## BASELINE per-category

| Category | MRR | R@10 |
|---|---|---|
| Single-session (user) | 0.8140 | 0.9429 |
| Multi-session reasoning | 0.9622 | 1.0000 |
| Single-session (preference) | 0.6678 | 0.9333 |
| Temporal reasoning | 0.9256 | 0.9850 |
| Knowledge updates | 0.9246 | 1.0000 |
| Single-session (assistant) | 1.0000 | 1.0000 |

**Overall: MRR=0.9124, R@10=0.9840**

## Per-mechanism, per-category Δ MRR

| Mechanism | SS-User | M-Sess | SS-Pref | Temporal | KU | SS-Asst | Overall |
|---|---|---|---|---|---|---|---|
| HOPFIELD | +0.0042 | -0.0018 | +0.0306 | +0.0099 | -0.0249 | +0.0000 | +0.0007 |
| ADAPTIVE_DECAY | -0.0062 | -0.0003 | -0.0206 | +0.0035 | -0.0011 | +0.0000 | -0.0014 |
| HDC | +0.0135 | -0.0083 | -0.0085 | +0.0032 | -0.0009 | +0.0000 | -0.0001 |
| EMOTIONAL_RETRIEVAL | +0.0000 | +0.0000 | +0.0000 | -0.0038 | +0.0000 | +0.0000 | -0.0010 |
| DENDRITIC_CLUSTERS | -0.0012 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | -0.0002 |
| CO_ACTIVATION | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| EMOTIONAL_TAGGING | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| ENGRAM_ALLOCATION | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| NEUROMODULATION | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| OSCILLATORY_CLOCK | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| PATTERN_SEPARATION | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| PREDICTIVE_CODING | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| RECONSOLIDATION | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| SPREADING_ACTIVATION | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| SURPRISE_MOMENTUM | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| SYNAPTIC_TAGGING | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |

## Key findings (paper §6.3)

**Mechanism specialization is real and category-dependent:**

- **HDC** specializes for multi-session reasoning (Δ = -0.0083 means disabling HDC
  HURTS that category by +0.0083 MRR). Counterproductive on Single-session-user
  (Δ = +0.0135). Net overall +0 because effects cancel across categories.
- **HOPFIELD** is the strongest specialist: helps Knowledge updates (Δ = -0.0249)
  but is counterproductive on Single-session preference (Δ = +0.0306). Net overall
  is the only positive contribution: +0.0007.
- **ADAPTIVE_DECAY** correctly penalizes stable preferences (Δ = -0.0206 on Pref)
  but the decay-helps-temporal effect (Δ = +0.0035) is small. Architectural finding:
  decay is mis-calibrated for benchmarks where memories are loaded fresh per-question.
- The remaining 13 mechanisms show ±0.0000 across ALL categories. These are
  candidates for LoCoMo evaluation: write-path side effects (NEUROMODULATION,
  PATTERN_SEPARATION, EMOTIONAL_TAGGING, SYNAPTIC_TAGGING, ENGRAM_ALLOCATION,
  OSCILLATORY_CLOCK, PREDICTIVE_CODING, SURPRISE_MOMENTUM) and longitudinal
  read-path mechanisms (CO_ACTIVATION, DENDRITIC_CLUSTERS, RECONSOLIDATION,
  SPREADING_ACTIVATION, EMOTIONAL_RETRIEVAL).

**Implication for §6.3 narrative:**
The integrated +3.0% MRR over published baseline is NOT attributable to a single
dominant mechanism. It's the sum of category-specialized contributions: HOPFIELD
for KU, HDC for multi-session, others sub-noise on this benchmark. Cortex's value
is the calibrated stack at plateau equilibrium, where each mechanism contributes
to the categories where its mechanism-of-action applies.
