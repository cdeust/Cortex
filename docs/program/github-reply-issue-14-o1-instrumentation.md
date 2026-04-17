# Draft reply to darval — issue #14 (O1 instrumentation ask)

**Instructions**: review before posting. Target comment at
https://github.com/cdeust/Cortex/issues/14

---

Quick update on **O1** from your 3.13.2 report — the one where
`cohort_correction` moved bimodality 0.07% in 336 s while recall
quality improved dramatically. I ran the diagnosis locally before
shipping a fix, and the answer is not obvious from in-process
simulation alone. I'd like to read your next `consolidate` output
with the new instrumentation I just merged to `main`.

## What I found so far

I simulated several distribution shapes that match your reported
stats (`mean=0.6487, std=0.3162, bimodality=0.8433, cohort_size=33604`):

| Simulated distribution | Δ bimodality per cycle |
|---|---|
| Wide two-peak (σ=0.08 around each mode) | −0.022 |
| Narrow hot peak at 0.98 + wide cold tail | −0.046 |
| Three-mode (0.98/0.5/0.2) | −0.014 |
| Saturated hot peak + uniform cold tail | −0.024 |

Every reasonable reconstruction of your numbers shows the correction
should move bimodality by **1.4–4.6 percentage points per cycle** at
the default `correction_strength=0.3`. You saw **0.07 pp** — at least
20× less than expected.

Two live hypotheses:

1. **The correction IS moving per-row heat** (which is what actually
   drives WRRF ranking), but the bimodality metric is a poor index of
   that — it measures global distribution shape, not per-row moves.
   This would explain why recall improved dramatically while the
   metric barely moved.

2. **Something is suppressing per-row writes** — e.g. protected/stale
   filter, pool-connection race, a silent fallback path I'm missing.
   This would be a real bug and the recall improvement came from
   somewhere else entirely (reranker, query dispatch, new heat-weight
   mix).

Without per-row movement data from your production distribution I
can't choose between them.

## What I shipped to `main` (not tagged yet)

Commit [`ae6f280`](https://github.com/cdeust/Cortex/commit/ae6f280)
adds three new fields to the homeostatic cycle output:

```json
"homeostatic": {
  "scaling_kind": "cohort_correction",
  "cohort_size": 33604,
  "bimodality_before": 0.8433,
  "bimodality_after":  0.8427,

  "cohort_mean_heat_delta": 0.1234,   // NEW
  "cohort_max_heat_delta":  0.1650,   // NEW
  "cohort_rows_written":    33600     // NEW
}
```

These let us see per-row movement directly without inferring it from
a shape metric.

**Expected values for hypothesis (1)**: your cohort members have
heat ≈ 0.93 pre-correction. With default `strength=0.3` and
`target=0.4`, each drops by `0.3 × (0.93 − 0.4) = 0.159`. So:

  * `cohort_mean_heat_delta` ≈ **0.13–0.17** (depending on the hot-peak
    shape)
  * `cohort_max_heat_delta` ≈ **0.18** (for memories near heat=1.0)
  * `cohort_rows_written` ≈ `cohort_size` (every cohort member > 0.001
    delta → every one writes)

**If these match your expected values**, cohort_correction is doing
its job on ranking — the fix is to add a better retrieval-relevant
health metric, not to change the correction behaviour.

**If `cohort_mean_heat_delta` is close to 0 or `cohort_rows_written`
is much less than `cohort_size`**, there's a real bug and I'll fix
the write path.

## What I'm NOT shipping yet

v3.13.3 is on deck but held until I have the numbers. The bundle
includes:

- Pipeline → wiki/memory/KG integration (auto-wire on SessionStart,
  incremental detect_changes on file edits, graph-TTL background
  re-analyze).
- Doc grooming: wiki templates per kind (ADR/specs/guides/…),
  naming-convention regex, deterministic auditor, and a
  `cortex-wiki-groomer` sub-agent that rewrites pages to template
  without deleting content.
- Plain-language `/wiki/README.md` generator (readable by non-tech
  stakeholders; tech detail stays in `.generated/INDEX.md` and the
  templated pages).
- O2 (`schema_acceleration.ratio_defined` + `reason_for_undefined`).
- O3 (`forgetting_curve.fit_quality` ∈ `poor/weak/good/insufficient/
  degenerate`).

All are orthogonal to O1 and test-green (2500+ passing), so the tag
is just waiting on the O1 write-path decision.

## Ask

When you next run `consolidate` on your 66 k store (whenever you'd
normally do so — no rush), please share the `homeostatic` block from
the output. The three new fields will tell me whether the fix is
observability (option 1) or the write path (option 2).

Cheers.
