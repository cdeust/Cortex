# Draft reply to darval — issue #14 (field report v3.12.0)

**Instructions**: review before posting. Target comment at
https://github.com/cdeust/Cortex/issues/14

---

Thanks for the field report — the JSON excerpts per stage plus the
user-level "`recall(hcrdashboard)` returns the wrong bucket" symptom made
diagnosis fast. Status per issue:

## Issue 1 — `emergence` AttributeError — **FIXED on `main`**

Root cause exactly as you suspected: `generate_emergence_report` moved
from `emergence_tracker` into `emergence_metrics` when the module was
split to satisfy the 300-line file cap, but the caller in `consolidate.py`
wasn't updated. Same class of bug as the `homeostatic_health` import
fixed in `69d81fb`.

Fix merged to `main`: [`c5a1862`](https://github.com/cdeust/Cortex/commit/c5a1862)
(import change). The regression guard via invariant I2 — spelled out in
[`docs/invariants/cortex-invariants.md`](https://github.com/cdeust/Cortex/blob/main/docs/invariants/cortex-invariants.md)
— lands as a pytest in `tests_py/invariants/test_I2_canonical_writer.py`
this weekend so the next rename/split can't reintroduce the same class
of bug.

**v3.12.1** release tag is not cut yet; planned this weekend as a hotfix
containing just this fix so you don't have to wait for the larger
refactor.

## Issue 4 — homeostatic scaling isn't rebalancing — **root cause found**

Your diagnosis ("`scaling_applied: true` but the distribution stays
bimodal") is correct and the fix isn't in the homeostatic cycle — it's
upstream, in the write path.

Found the real culprit in `mcp_server/handlers/remember.py:221-222`:

```python
heat = thermodynamics.apply_surprise_boost(
    1.0, gate["score"], get_memory_settings().SURPRISE_BOOST
)
```

**Every new memory starts at baseline heat = 1.0.** A backfill of 330+
memories in one minute all land in the `[0.9, 1.0]` bucket. That creates
the sharp peak you observed (`bimodality: 0.85`).

Turrigiano scaling (`homeostatic_plasticity.compute_scaling_factor`) is
**mathematically order-preserving** — its defining property per Tetzlaff
et al. 2011 Eq. 3. Multiplying every row by `factor = 1.03` shifts the
mean but cannot flatten two peaks into one. So `scaling_applied: true`
technically ran; it just mathematically cannot do what you reasonably
expected.

Two changes land this weekend:

1. **Backfill heat assignment fix**: `backfill_memories` and
   `import_sessions` will compute an initial heat that reflects the age
   of the original conversation (a 6-month-old imported memory starts at
   heat ≈ 0.3, not 1.0), so the bulk cohort doesn't form at the top of
   the distribution to begin with. Optional `initial_heat` parameter on
   `remember` for callers that know the memory is historical.

2. **Bimodality-aware homeostatic primitive**: when
   `bimodality_coefficient > 0.5`, switch from multiplicative scaling to
   cohort-aware subtractive renormalization. The `scaling_applied` flag
   becomes `scaling_applied: true/false + scaling_kind: "multiplicative" |
   "subtractive_cohort" | "none"` so the output reports what actually
   happened, not just that the function returned.

3. **Truth in reporting**: `scaling_applied` gets renamed
   `scaling_reduced_bimodality` with an explicit before/after metric, so
   "ran without raising" is no longer indistinguishable from "rebalanced
   the distribution". That fixes your "flag is misleading" complaint at
   the primitive.

## Issue 2 — `cls` all-zeros — **diagnostic gap confirmed**

Your read is right: with `episodic_scanned: 2000` and every output at 0
(including `skipped_inconsistent` and `skipped_duplicate`), the output is
indistinguishable from "early-returned silently" vs "ran and found
nothing meaningful". Neither answer is useful.

Weekend fix: add `reason_for_zero` to the cls stats when all counts are
0, one of:
- `below_min_confidence` (threshold gate rejected everything)
- `no_qualifying_entities` (the entity filter starved the sample)
- `insufficient_pairs` (clustering couldn't form groups)
- `passed_through` (actually ran all the work, genuinely nothing new)

This is part of a broader audit we're running on every consolidation
stage: if a stage exits with zero mutations, it must report WHY in a way
that's greppable and alertable.

## Issue 3 — `memify` `0 strengthened / 0 pruned / 2671 reweighted`

Less urgent, but filed. Likely intentional gating (a reweight-only cycle
when no stage-transition thresholds are crossed), but the report should
disambiguate the same way as cls.

## Performance — `homeostatic` 66% of wall time

Separate workstream you effectively kicked off in
[#13](https://github.com/cdeust/Cortex/issues/13). A multi-agent
scalability audit produced a structured plan to address this: the
homeostatic cycle stops touching rows at all, becoming an O(1) write to
a per-domain `homeostatic_state` row, with heat computed lazily at recall
time via a PL/pgSQL `effective_heat()` function. Plan in
[docs/program/](https://github.com/cdeust/Cortex/tree/main/docs/program);
invariants and governance in
[docs/invariants/](https://github.com/cdeust/Cortex/tree/main/docs/invariants/cortex-invariants.md)
and [ADR-0045](https://github.com/cdeust/Cortex/blob/main/docs/adr/ADR-0045-scalability-governance-rules.md).
Target: homeostatic wall-time < 100 ms on your 66 K store post-A3. That
migration is two weekends away, not this weekend.

## Weekend deliverable summary (not yet tagged)

- **v3.12.1 hotfix**: the emergence_tracker import fix (already on `main`)
  plus the I2 regression test. Tag + release this weekend.
- **v3.12.2 (if it converges over the weekend)**: backfill heat
  assignment fix, bimodality-aware homeostatic, cls + memify diagnostic
  signals. If it doesn't converge cleanly, it becomes next-week scope
  rather than a rushed release.

If you're open to it, running `consolidate` once more on your store after
v3.12.2 and sharing the JSON would close the loop on the user-level
symptom ("hcrdashboard buried under the claude-mem bucket"). And if the
`run_a.json` / `run_b.json` dumps from your earlier benchmark are still
around, they'd become the before-picture for the larger A3 migration.

Cheers.
