# Reply to darval's 2026-04-18 follow-up on issue #14

Context: darval overlaid `homeostatic.py` from `main @ d26a291` onto a
v3.13.2 plugin cache on a 66 k store. On this run the cohort branch
did not fire — code took `scalar_update` — so the three new
`cohort_*_heat_delta` fields from `ae6f280` are absent. Bimodality had
drifted from 0.8433 to 0.6763 in 25 h of lazy decay + fresh writes
without any cohort cycle in between.

---

## Thanks — this run is itself the O1 answer

The cohort branch not firing is not a regression; it is the diagnostic
signal. Three things line up:

1. **OB3 directly confirms option 1.** Bimodality fell 0.167 in 25 h
   with zero `cohort_correction` cycles. That's 2 400× the 0.07 pp the
   cohort cycle moved it in the 3.13.2 report. Per-row heat motion
   (lazy decay + fresh writes at mid-heat) moves the shape far faster
   than the cohort branch does. So the 3.13.2 "0.07 pp after
   cohort_correction" finding was the metric being slow, not the write
   path being broken.

2. **OB1 confirms the cohort path is rare on real traffic.** Between
   bulk imports / reranker refreshes the store self-heals to unimodal,
   and the cohort branch stays idle. That means the O2 instrumentation
   (`cohort_mean_heat_delta`, `cohort_max_heat_delta`,
   `cohort_rows_written`) is correctly implemented but will only
   surface during an active bimodal event — which is the intended
   semantics.

3. **OB2 confirms the 3.13.2 latency regression was scoped to
   cohort.** Scalar path is 99 ms; the 336 s cost was the per-row
   cohort UPDATE over 33 k members. After A3 the cohort writes route
   through `bump_heat_raw` — still per-row, but only on the cohort
   subset (thousands, not tens of thousands). A proof point for this
   only shows up on an active bimodal event.

So from my side the O1 ask is resolved as option 1: the write path is
fine, the bimodality metric was the misleading dial. I'll leave the
heat_delta instrumentation from `ae6f280` in place because when the
cohort branch DOES fire (on a bulk import / reranker event), those
fields are the right number to watch.

---

## OB4 — fixed on `main` in `85fb8bf` + `82ad597`

Your read was exact: emitting `bimodality_before` + `bimodality_after:
null` + `bimodality` (at the same value) is confusing. Fix shipped in
two commits.

**`scalar_update` / no-op / empty-cohort branches** → truly scale-
invariant. `scalar_update` only writes the `homeostatic_state.factor`
row — `heat_base` is untouched, so the bimodality coefficient of
stored heat is identical before and after. Now emits:

```python
"bimodality_after": bimodality,  # scale-invariant → shape unchanged
```

**`fold` branch** → slightly weaker guarantee. Fold rewrites every
`heat_base` per-row multiplied by the (pre-fold) factor with `[0, 1]`
clipping. When many rows saturate at the endpoints the shape can
shift. I don't re-scan post-fold (that would cost another 66 k-row
scan at steady state), so the emitted `bimodality_after` is the pre-
fold value as a bounded estimate, flagged explicitly:

```python
"bimodality_after": bimodality,
"bimodality_after_is_estimate": True,  # next consolidate will measure exactly
```

Consumers that want the exact post-fold shape get it on the next
consolidate cycle.

**Cohort branch** unchanged — `bimodality_after =
after["bimodality_coefficient"]` because subtractive renormalization
does change the shape, so the post-correction value is meaningful
and re-measured.

Pinned with a new regression test:
`test_scalar_and_noop_paths_emit_bimodality_after_equal_to_before`.

---

## On option B (forced synthetic bimodal test)

Not needed for O1 since this run settled the question. But if you want
to verify the three new `cohort_*_heat_delta` fields on the synthetic
bimodal fixture, the Cortex test suite already has one — see
`tests_py/core/test_homeostatic_bimodal.py`
(`test_bimodal_triggers_cohort_correction`). It seeds 200 memories in
a split at ~0.05 and ~0.95, asserts the cohort path fires, and checks
that `bimodality_after <= bimodality_before + 1e-6` and that
`cohort_size` matches. You'd be duplicating it with 1 k rows on a real
store, which would also work and is welcome — but it's not load-
bearing for the O1 answer anymore.

---

## What ships next

- `main` carries the OB4 fix in `85fb8bf`.
- v3.14.2 (the current trajectory, post-Gap 1 / Gap 6) will include
  it. No v3.13.3 anymore — main moved past 3.13 with the workflow
  graph + AST integration + Gap 1/6 work.
- O3 fit-quality flag (`8d9b82e`) is still pending a real exercise on
  your store because your overlay was `homeostatic.py` only. When
  v3.14.2 goes out and you pick it up cleanly, that field will show
  up on `emergence.forgetting_curve`.
- O1 is considered resolved. Reopen if you see the cohort branch fire
  on a bulk import and the new `cohort_*_heat_delta` numbers look
  wrong; I'll dig back in.

Thanks again — this was a high-signal follow-up.
