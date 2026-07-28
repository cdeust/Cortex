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
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

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

# CLS-B cortical-availability modulation of the PERMANENT circuit (gate C — see
# cortex:remember memory_id 4261603). A memory still hippocampally-dependent
# (the cortex has not yet taken it over — McClelland 1995) should accumulate
# permanent-forgetting pressure MORE SLOWLY, not be exempted from it: the
# accumulator must still cross Θ_accum for a cortically-independent memory
# under sustained interference (non-regression), while a hippocampally-
# dependent memory under the SAME interference resists longer (protection).
#
#     cortical_availability(dep) = 1 - β·dep,   β in (0, 1)
#
# at dep=1.0 (today's value for 100% of production memories, see decision
# memory 4261278/4261481) the factor is (1-β) > 0 — STRICTLY POSITIVE, never
# zero. A naive (1-dep) factor was rejected here for exactly this reason: it
# would zero the permanent circuit for the entire prod corpus (dep=1.0
# everywhere until the CLS-B producer above has run enough replay cycles),
# which is a correctness regression, not a feature. At dep=0.0 (fully
# cortically independent) the factor is 1.0 — forgetting behaves exactly as
# before this change (non-regression for already-consolidated memories).
# beta has no biological rate-law source (see module docstring: no paper
# gives dep vs forgetting-pressure kinetics at this timescale); it is
# calibrated by benchmarks/active_forgetting/run_benchmark.py fixtures (i)
# non-regression / (ii) protection.
# source: engineering choice, calibrated via benchmarks/active_forgetting
CORTICAL_AVAILABILITY_BETA = 0.5


def cortical_availability(hippocampal_dependency: float) -> float:
    """Bounded, strictly-positive modulation factor for permanent-circuit pressure.

    ``1 - β·dep`` — see ``CORTICAL_AVAILABILITY_BETA`` for the non-regression
    argument. ``hippocampal_dependency`` is clamped to [0, 1] before use so an
    out-of-range value (should not occur; the column is constrained [0,1] at
    write time) cannot push the factor outside (1-β, 1].
    """
    dep = max(0.0, min(1.0, hippocampal_dependency))
    return 1.0 - CORTICAL_AVAILABILITY_BETA * dep


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


def forgetting_pressure(
    stage: str,
    chronic: float,
    *,
    hippocampal_dependency: float = 0.0,
) -> float:
    """Instantaneous permanent-circuit pressure.

    ``= chronic × stage_vulnerability × cortical_availability(dep)``.

    ``chronic`` (>= 0) is the redundancy-gated interference signal above.
    ``stage_vulnerability`` is the cascade interference_vulnerability (labile 0.9 →
    consolidated 0.05): a graded resistance, so consolidated memories resist
    strongly but are never zeroed by fiat. ``hippocampal_dependency`` (CLS-B,
    default 0.0 = fully cortical = no additional modulation, matching
    pre-CLS-B-gate-C behaviour for callers that don't pass it) applies the
    bounded, never-zero cortical_availability factor (see its docstring) —
    hippocampally-dependent memories accumulate this pressure more slowly, on
    top of (not instead of) the existing stage-based resistance. The transient
    circuit does NOT use either factor (Sabandal 2021 — stage- and
    dependency-independent).
    """
    vuln = get_stage_properties_by_name(stage).interference_vulnerability
    availability = cortical_availability(hippocampal_dependency)
    return max(0.0, chronic) * vuln * availability


def update_pressure_accum(
    prev_accum: float,
    stage: str,
    chronic: float,
    recently_active: bool,
    lam: float = PRESSURE_LEAK_LAMBDA,
    *,
    hippocampal_dependency: float = 0.0,
) -> float:
    """Advance the leaky integrator one cycle: ``λ·accum_{t-1} + pressure_t``.

    A sleep-protected (``recently_active``) cycle contributes ``pressure_t = 0``
    and lets the accumulator leak down — sleep inhibits the ongoing forgetting
    signal but does not erase accumulated erosion. ``lam`` ∈ [0, 1): the per-cycle
    retention of past pressure (1 − λ is natural recovery when interference abates).
    ``hippocampal_dependency`` (CLS-B gate C, default 0.0 = no modulation) is
    forwarded to ``forgetting_pressure`` — see its docstring.
    """
    pressure = (
        0.0
        if recently_active
        else forgetting_pressure(
            stage, chronic, hippocampal_dependency=hippocampal_dependency
        )
    )
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


# ── E2 reversible extinction: an inhibitory alternative to deletion ─────────
#
# The two circuits above are subtractive: the permanent circuit marks a memory
# is_stale (soft-delete — hides the whole row from recall) and the transient
# circuit lowers heat. Extinction (Bouton 2004, Learn. Mem. 11:485-494,
# doi:10.1101/lm.78804; Milad & Quirk 2012, Annu. Rev. Psychol. 63:129-151,
# doi:10.1146/annurev.psych.121208.131631) is DIFFERENT in kind: it is new
# inhibitory learning laid OVER a retained association, not erasure. The
# original trace is left fully intact and a reversible inhibitory tag suppresses
# its effective retrieval weight, so the association returns on its own over
# time (spontaneous recovery) and snaps back in full on reinstatement.
#
# This function offers extinction as the REVERSIBLE alternative to the permanent
# (is_stale) circuit: when a memory is under sustained chronic forgetting
# pressure but is NOT a good candidate for hard soft-delete — because it may be
# needed again — a caller can deprecate it (grow the inhibitory tag) instead of
# deleting it. The decision here is deliberately conservative and orthogonal to
# the two dopaminergic circuits: it never sets is_stale and never touches heat;
# it only reports whether an extinction (reversible deprecate) is warranted. Tag
# arithmetic and the ablation guard live in `mcp_server.core.extinction`.
#
# It mirrors `is_permanent_forgetting` EXACTLY — same accumulated leaky-integrator
# input and the same accumulation threshold, same pinned/recently-active
# exemptions — so a memory is a candidate for reversible extinction under the
# same sustained-pressure condition that would otherwise permanently soft-delete
# it. It is a SEPARATE decision, producing a reversible tag rather than an
# is_stale erasure.


def should_extinguish(
    accum: float,
    is_pinned: bool,
    recently_active: bool,
    *,
    already_stale: bool = False,
    theta: float = PERMANENT_ACCUM_THRESHOLD,
) -> bool:
    """Decide whether to reversibly EXTINGUISH (deprecate) rather than delete.

    Returns True when the memory is under enough *sustained* chronic-interference
    pressure to warrant suppression but should be kept recoverable rather than
    soft-deleted — the reversible inhibitory route (Bouton 2004). Takes the same
    post-update leaky-integrator ``accum`` and accumulation threshold as
    `is_permanent_forgetting`, with the same exemptions (pinned / recently-active
    memories are never extinguished), but is a SEPARATE decision: it produces a
    reversible tag, not an is_stale erasure. Already-stale memories are skipped
    (deletion already won). Honors ``CORTEX_ABLATE_EXTINCTION=1`` (returns False
    when the mechanism is lesioned, so no extinction tag is ever grown → no
    behaviour change).
    """

    if is_mechanism_disabled(Mechanism.EXTINCTION):
        return False
    if is_pinned or recently_active or already_stale:
        return False
    return accum >= theta
