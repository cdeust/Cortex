# ADR-0362: mcp_server/handlers/consolidation/homeostatic.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/consolidation/homeostatic.py`; original SHA-256 `3fa4d309435a94421f9b9f660eab9e93188ccfd19b61f5a3e4040c29d8d1f67b`.

## Original docstring, lines 1–45

````text
"""Homeostatic cycle: per-write-class health measurement + regulation.

**A3 lazy-heat implementation**: heat is a *function*, not a *state vector*.
The multiplicative scaling factor is stored as a single scalar per
(domain, write_class) in ``homeostatic_state.factor`` and read by
``effective_heat()`` at query time:

    effective_heat(m, t, factor) = LEAST(1.0, GREATEST(floor,
        heat_base * factor * POWER(decay_factor, α·t)))

**M-D3 (7.1, 2026-07-10) — full stratification by write class.** Design
doc ``scratchpad/memoire-qui-comprend-design.md`` §M-D3, arbitrage user:
"stratification complète, pas l'exemption minimale". Confirmed empirically
(SQL against dev DB, before this change): the class-blind fold at
2026-07-10 19:22 wrote ``heat_base *= factor`` + reset
``heat_base_set_at`` on **1021 rows in one UPDATE**, 511 of them
``post_tool_capture`` (auto) and 510 of them deliberate-class sources
(feature/lesson/bug-fix/benchmark/decision/...) — the fold's target-mean
regulation was computed against the WHOLE domain's mean (92% auto by
volume, I6 audit) and then applied to every row in that domain including
the deliberate minority, collapsing the deliberate class's median
``heat_base`` from 0.25 (post re-heat campaign, 15:13Z) to 0.1346 hours
later. The re-heat campaign's own effect was erased same-day, not at the
planned J+30 check.

Every write class now gets its own health measurement AND its own fold
verdict — not one aggregate computation with an exclusion predicate
bolted onto it. See ``_REGULATED_CLASSES`` below for which classes are
actually SCALED (currently: only ``auto``) and why — every non-regulated
class's health is still measured and journaled, its fold verdict is just
always "none" by documented doctrine, not by omission.

This module owns the POLICY (which write class is measured/regulated,
how the corpus is bucketed per cycle). The MECHANICS (scalar update,
fold, bimodal cohort correction — the actual writes) live in
``homeostatic_apply.py`` — split to keep both files under the 500-line
cap (§4.1 coding standards), same precedent as
``core/homeostatic_health.py``.

References:
    Turrigiano 2008 — multiplicative synaptic scaling (order-preserving)
    Tetzlaff 2011 Eq. 3 — delta_w = alpha * w * (r_target - r_actual)
    docs/program/phase-3-a3-migration-design.md §5
    scratchpad/memoire-qui-comprend-design.md §M-D2, §M-D3
"""
````

## Original docstring, lines 69–97

````text
"""Measure health and (for regulated classes) update the homeostatic
    factor / fold, independently per write class.

    Branching (per class, in ``_dispatch_class``):
      1. class not regulated → verdict is always "none", health still
         measured and reported (M-D3 doctrine, see ``_REGULATED_CLASSES``).
      2. healthy AND unimodal → no-op.
      3. bimodal → cohort correction (per-row writes via bump_heat_raw),
         scoped to that class's own rows.
      4. off-target → scalar factor update, fold if drift > log(2.0),
         scoped to that class's own rows.

    Phase 4: when the caller passes ``memories=None`` we compute the
    health metrics via a streaming server-side cursor
    (``store.iter_memories_for_decay``) + per-class Welford moments. Peak
    memory is O(chunk_size) instead of O(N) — crucial at 66K+ memory
    stores. When the caller passes a pre-loaded list (hot-path consolidate
    sharing one snapshot across stages, or unit tests), we bucket it by
    class directly.

    Returns:
        Same top-level shape as before stratification
        (scaling_applied/scaling_kind/health_score/mean_heat/std_heat/
        bimodality/memories_scanned) mirroring the ``auto`` class's
        outcome — existing callers that only look at the top level see
        identical behavior to pre-M-D3 for the auto-dominated corpus.
        Additive key ``by_class``: ``{class_name: outcome_dict}`` for
        every class in ``write_class.ALL_WRITE_CLASSES``.
    """
````

## Original docstring, lines 320–328

````text
"""Pick the most-frequent domain key from a precomputed frequency map.

    Same doctrine as before Phase 4: docs/program/phase-3-a3-migration-
    design.md §5 describes one scalar UPDATE per cycle, keyed by domain —
    M-D3 narrows this further to "one scalar UPDATE per (domain, class)
    per cycle, keyed within that class's own rows" — not a new weighting
    scheme, just the same rule applied within a class instead of across
    the whole corpus.
    """
````

