"""Core: active_forgetting — two independent dopaminergic forgetting circuits.

The *Drosophila* dopaminergic active-forgetting literature describes TWO
anatomically and molecularly DISTINCT forgetting circuits — not two points on a
single severity axis. This module implements both as independent decisions over
a memory's offline (consolidation-time) signals; neither influences the other.

  PERMANENT circuit — Rac1/cofilin trace erosion (PPL1-γ2α'1).
    An "ongoing" dopaminergic forgetting signal gradually erodes the trace. It is
    "increased robustly with locomotor activity" and sensory input — i.e. by
    interference from newer activity — and "inhibit[ed]" by "sleep and rest"
    (Davis & Zhong 2017, Neuron 95:490-503, PMC5657245; Cervantes-Sandoval 2017,
    PMC6168074). Stronger/consolidated memories are "much more resistant … not
    immune" (Davis & Zhong 2017) — a GRADED resistance, modelled by reusing the
    cascade interference_vulnerability curve.

    Two faithfulness fixes over the first implementation (both refuted on the
    live 6989-memory corpus, where the naive signal marked 46% PERMANENT-stale in
    one cycle and never fired the transient circuit):

      1. SIGNAL — ``chronic_interference`` is a REDUNDANCY-GATED excess noisy-OR
         over the newer neighbours: only neighbours at or above the near-duplicate
         cutoff τ_dup contribute, each by its *excess* over that cutoff. A plain
         noisy-OR over the 10 nearest newer neighbours saturated to ≈1.0 for
         99.6% of memories because 384-dim sentence-transformer pairs sit on a
         high similarity floor (μ≈0.15, p50 strongest-newer≈0.68); it measured
         background topical density, not the papers' *retroactive interference
         from new overlapping learning*. Gating at τ_dup excludes the background
         band entirely → ``chronic = 0`` for ~96% of the corpus, restoring the
         "forgetting is the default *unless* there is genuine new interference"
         semantics. (Pearl 1988 noisy-OR is kept; only the *set* it ORs changes
         to the genuine near-duplicate set.)

      2. SUSTAINED PRESSURE — permanent erosion accumulates over cycles through a
         LEAKY INTEGRATOR rather than firing on a single instantaneous compare.
         The papers describe Rac1/cofilin erosion as *gradual/sustained* and
         *inhibited by sleep/rest*; a single-cycle trigger is unfaithful. The
         leak λ is natural recovery when interference abates (matches the
         documented reversibility/reinstatement); a sleep-protected cycle adds
         pressure 0 and lets the accumulator leak down — it does NOT reset it (a
         consecutive-cycle counter would, contradicting "much more resistant …
         not immune").

        pressure_t = chronic_interference × stage_vulnerability(stage)
        accum_t    = λ · accum_{t-1} + pressure_t          (0 when sleep-protected)
        permanent ⟺ accum_t ≥ Θ_accum, and the memory is neither pinned nor
                    sleep-protected this cycle.

    Effect = mark is_stale (reversible soft-delete: the row persists as a residual
    engram and is reinstated when the trace is reactivated).

  TRANSIENT circuit — DAMB retrieval block (PPL1-α2α'2).
    "Triggered by interfering stimuli presented just prior to retrieval", it
    "blocks retrieval" of an otherwise intact trace, recovering spontaneously /
    with time (Sabandal, Berry & Davis 2021, Nature 591:426-430, PMC8522469). It
    acts even on consolidated PSD-LTM, so it is STAGE-INDEPENDENT and acute (a
    single recent interferer), never accumulated. Faithful operationalization:

        transient ⟺ an acute interferer exists (acute_overlap ≥ X) that is recent
                    (acute_age_hours ≤ W), and the memory is neither pinned nor
                    just re-accessed.

    Effect = reduce heat (lower recall rank), reversible: recovers on re-access.

Independence is load-bearing. Sabandal (2021) found "two separate DA-based
circuits", and directly tested and REJECTED conversion of transient into
permanent ("returned to normal … by day 14"). The two circuits therefore read
DISJOINT signals (accumulated chronic interference vs a single acute interferer)
and share no state.

No salience term: the papers give "stronger resists / weaker vulnerable" only
ordinally — no rate law (Berry, Phan & Davis 2018, PMC6239218; confirmed silent
across all four papers). Salience-resistance is expressed solely through the
consolidation stage, never an invented (1 - heat) factor. No phasic-DA reuse.

Calibration honesty. The constants below have NO biological source at the
hours/days timescale (the literature is ms *Drosophila* / in-vitro kinetics), so
each traces to "source: benchmark <path>":
  - τ_dup is NOT free-derived: it is the already-committed curation near-duplicate
    cutoff (``curation.MERGE_THRESHOLD``), making consolidation-time "interference"
    identical to write-time "duplicate". Zero new constants; doubly-anchored.
  - λ and Θ_accum are read off the S1–S5 time-series fixtures as the max-margin
    pair reproducing every label.
  - X and W are read off the transient labelled pool.
Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Iterable

from mcp_server.core.cascade_stages import get_stage_properties_by_name
from mcp_server.core.curation import MERGE_THRESHOLD

# Near-duplicate cutoff for the redundancy gate. NOT a free constant: it is the
# committed curation cosine cutoff at which the write path already declares two
# memories near-duplicates/supersedes, so consolidation-time interference uses the
# identical definition of "overlapping" as write-time deduplication (Berry 2018
# "same pathway"). It sits above the ~0.5 background band and the p90=0.748
# strongest-newer-neighbour similarity, which is why gating here removes the
# saturation a plain noisy-OR suffered.
# source: core/curation.py MERGE_THRESHOLD (committed system constant); validated
#         against the measured single-digit near-duplicate rate on the live corpus.
TAU_DUP = MERGE_THRESHOLD

# Permanent-circuit leaky-integrator constants: max-margin (λ, Θ_accum) pair that
# reproduces every S1–S5 time-series label (sustained fires, single-bout never,
# sleep-protected never, ramp fires on crossing, decay-recovery leaks back below
# Θ). No biological rate law exists at this timescale.
# source: benchmark benchmarks/active_forgetting/run_benchmark.py
# (max-margin pair over S1–S5: never/recover ≤ 0.9690 | fire ≥ 1.5443; margin 0.5753)
PRESSURE_LEAK_LAMBDA = 0.85
PERMANENT_ACCUM_THRESHOLD = 1.25662

# Transient-circuit acute-interferer thresholds: maximum-margin separators for the
# overlap and recency dimensions of the transient label class.
# source: benchmark benchmarks/active_forgetting/run_benchmark.py
ACUTE_OVERLAP_THRESHOLD = 0.575
ACUTE_RECENCY_WINDOW_HOURS = 13.0


def chronic_interference(
    newer_sims: Iterable[float], tau_dup: float = TAU_DUP
) -> float:
    """Redundancy-gated excess noisy-OR over newer-neighbour similarities.

    Only neighbours at or above the near-duplicate cutoff ``tau_dup`` count as
    genuine retroactive interferers; each contributes its *excess* over the
    cutoff, rescaled to [0, 1]:

        e_i     = (sim_i − τ_dup) / (1 − τ_dup)      for sim_i ≥ τ_dup
        chronic = 1 − ∏_i (1 − e_i)                  (noisy-OR; Pearl 1988)

    Background-band neighbours (the ~0.5 similarity floor of 384-dim embeddings)
    are excluded entirely, so ``chronic`` is 0 for the ~96% of memories with no
    genuine near-duplicate — this is the membership gate that fixes the
    saturation a plain noisy-OR suffered. Monotone in both the count and the
    strength of genuine near-duplicates, preserving the papers'
    ongoing/accumulating interference semantics. Similarities are clamped to
    [0, 1] (cosine can dip negative); an empty / all-background set yields 0.0.
    """
    product = 1.0
    span = 1.0 - tau_dup
    for s in newer_sims:
        s = max(0.0, min(1.0, float(s)))
        if s >= tau_dup:
            excess = 1.0 if span <= 0.0 else (s - tau_dup) / span
            product *= 1.0 - excess
    return 1.0 - product


def forgetting_pressure(stage: str, chronic: float) -> float:
    """Instantaneous permanent-circuit pressure = chronic × stage_vulnerability.

    ``chronic`` (>= 0) is the redundancy-gated interference signal above.
    ``stage_vulnerability`` is the cascade interference_vulnerability (labile 0.9 →
    consolidated 0.05): a graded resistance, so consolidated memories resist
    strongly but are never zeroed by fiat. The transient circuit does NOT use it.
    """
    vuln = get_stage_properties_by_name(stage).interference_vulnerability
    return max(0.0, chronic) * vuln


def update_pressure_accum(
    prev_accum: float,
    stage: str,
    chronic: float,
    recently_active: bool,
    lam: float = PRESSURE_LEAK_LAMBDA,
) -> float:
    """Advance the leaky integrator one cycle: ``λ·accum_{t-1} + pressure_t``.

    A sleep-protected (``recently_active``) cycle contributes ``pressure_t = 0``
    and lets the accumulator leak down — sleep inhibits the ongoing forgetting
    signal but does not erase accumulated erosion. ``lam`` ∈ [0, 1): the per-cycle
    retention of past pressure (1 − λ is natural recovery when interference abates).
    """
    pressure = 0.0 if recently_active else forgetting_pressure(stage, chronic)
    return lam * max(0.0, prev_accum) + pressure


def is_permanent_forgetting(
    accum: float,
    is_pinned: bool,
    recently_active: bool,
    theta: float = PERMANENT_ACCUM_THRESHOLD,
) -> bool:
    """Decide the Rac1 (permanent) circuit from the accumulated pressure.

    ``accum`` is the post-update leaky-integrator value for this cycle.
    ``is_pinned`` is user protection or an anchor (heat == 1.0); ``recently_active``
    means replayed/accessed this cycle (sleep quiets the ongoing forgetting
    signal). Either exempts the memory. Otherwise it is forgotten once *sustained*
    chronic-interference pressure overcomes the accumulation threshold.
    """
    if is_pinned or recently_active:
        return False
    return accum >= theta


def is_transient_forgetting(
    acute_overlap: float,
    acute_age_hours: float,
    is_pinned: bool,
    recently_active: bool,
) -> bool:
    """Decide the DAMB (transient) circuit: transiently suppress retrieval?

    Stage-independent (Sabandal 2021): fires whenever an acute interferer is both
    strong enough (``acute_overlap`` ≥ threshold) and recent enough
    (``acute_age_hours`` ≤ window). ``is_pinned`` exempts; ``recently_active`` means
    the memory was just retrieved successfully, so it is not currently blocked.
    """
    if is_pinned or recently_active:
        return False
    return (
        acute_overlap >= ACUTE_OVERLAP_THRESHOLD
        and acute_age_hours <= ACUTE_RECENCY_WINDOW_HOURS
    )
