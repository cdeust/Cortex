"""Active-forgetting benchmark — two independent DA forgetting circuits (A2).

Acceptance instrument for Tier-A item A2: a consolidation settlement pass that,
faithful to the *Drosophila* dopaminergic active-forgetting literature, applies
TWO anatomically/molecularly DISTINCT forgetting circuits — not a severity
ladder. Full design rationale lives in ADR-017; this docstring fixes only the
testable contract.

This revision replaces a synthetic-abstraction benchmark that abstracted
``chronic`` into a hand-labelled [0, 1] value and so NEVER exercised the
raw-similarity → chronic construction. Against the live 6989-memory corpus that
omission hid a saturation bug: a plain noisy-OR over the 10 nearest newer
neighbours marked 46% of the corpus PERMANENT-stale in one cycle and never fired
the transient circuit. Two load-bearing changes close that gap:

  - PERMANENT fixtures now carry RAW newer-neighbour similarity lists and the
    benchmark computes ``chronic`` through the core ``chronic_interference``
    (redundancy-gated excess noisy-OR), so the aggregator is exercised
    end-to-end. A non-saturation fixture makes the old failure fail loudly forever.
  - PERMANENT firing is SUSTAINED (a leaky integrator over cycles), so it is
    tested by S1–S5 *time-series* fixtures from which ``derive_thresholds`` reads
    the leak λ and accumulation threshold Θ_accum as the max-margin pair
    reproducing every label.

Primary sources (open-access via PMC; quotes verified against raw text):
  - Sabandal, Berry & Davis (2021), Nature 591:426-430 (PMC8522469): transient
    and permanent forgetting are "two separate DA-based circuits"; transient
    (DAMB / PPL1-α2α'2) "blocks retrieval" and is "triggered by interfering
    stimuli presented just prior to retrieval", recovering spontaneously;
    permanent (PPL1-γ2α'1 / Rac1) erodes the trace. Sustained transient
    stimulation did NOT convert to permanent loss ("returned to normal by day 14").
    Transient forgetting acts on consolidated PSD-LTM ⇒ it is STAGE-INDEPENDENT.
  - Davis & Zhong (2017), Neuron 95:490-503 (PMC5657245): "This does not
    necessarily mean that consolidated memories are immune … just much more
    resistant" ⇒ GRADED resistance, not a hard immunity gate. The intrinsic
    forgetting DA signal is "ongoing", "increased robustly with locomotor
    activity"/sensory input (interference) and "inhibit[ed]" by "sleep and rest".
  - Berry, Phan & Davis (2018), Cell Reports 25:651-662.e4 (PMC6239218): "strong
    memories … more resistant … weaker memories … more vulnerable" — ordinal
    ONLY; no quantitative strength→rate law exists in any of these papers.

Benchmark-FIRST rationale: no biological rate constant exists at hours/days, so
every threshold traces to "source: benchmark <path>". This file IS that source —
the labelled fixtures fix ground truth and ``derive_thresholds`` reads
τ_dup-provenance, (λ, Θ_accum), X and W off them; the core
(mcp_server/core/active_forgetting.py) bakes them and is verified here.

Run:
    Cortex/.venv/bin/python3 benchmarks/active_forgetting/run_benchmark.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# The core under test (the same functions production calls).
from mcp_server.core.active_forgetting import (  # noqa: E402
    ACUTE_OVERLAP_THRESHOLD,
    ACUTE_RECENCY_WINDOW_HOURS,
    PRESSURE_LEAK_LAMBDA,
    PERMANENT_ACCUM_THRESHOLD,
    TAU_DUP,
    chronic_interference,
    forgetting_pressure,
    is_permanent_forgetting,
    is_transient_forgetting,
    update_pressure_accum,
)
from mcp_server.core.curation import MERGE_THRESHOLD  # noqa: E402

RESULTS_DIR = REPO / "benchmarks" / "results" / "active_forgetting"

GRID_LAMBDAS = [round(0.05 * i, 2) for i in range(1, 19)]  # 0.05 … 0.90

# ── Permanent SIGNAL pool ───────────────────────────────────────────────────────
# Each row carries the RAW newer-neighbour cosine list ``newer_sims`` and the
# expected redundancy-gated ``chronic`` BAND (zero vs positive). This exercises
# the aggregator that the old abstracted pool never touched. τ_dup = 0.85, so only
# genuine near-duplicates (sim ≥ 0.85) contribute; the ~0.5 background band is
# excluded. ``acute`` (strongest newer sim, its age) feeds the disjoint transient
# circuit and lets the same neighbour list drive both circuits.
SIGNAL_POOL = [
    {"id": "G1", "newer_sims": [0.52, 0.61, 0.48, 0.55, 0.67, 0.50, 0.58, 0.49, 0.63, 0.54],
     "exp_chronic_zero": True,
     "note": "10 background neighbours (~0.5) ⇒ chronic 0 (NON-SATURATION, load-bearing)"},
    {"id": "G2", "newer_sims": [0.52, 0.61, 0.48, 0.99, 0.55, 0.50, 0.58],
     "exp_chronic_zero": False,
     "note": "one near-exact duplicate (0.99) in a background field ⇒ chronic high"},
    {"id": "G3", "newer_sims": [0.95, 0.92],
     "exp_chronic_zero": False,
     "note": "two genuine near-dups ⇒ accumulating chronic (monotone in count)"},
    {"id": "G4", "newer_sims": [0.84, 0.83, 0.82, 0.80],
     "exp_chronic_zero": True,
     "note": "all JUST BELOW τ_dup ⇒ chronic 0 (membership gate, not rescale)"},
    {"id": "G5", "newer_sims": [],
     "exp_chronic_zero": True,
     "note": "no newer neighbours ⇒ chronic 0 (driver falsifier)"},
]


# ── Permanent TIME-SERIES pool (S1–S5): derives (λ, Θ_accum) ─────────────────────
# Each series is a per-cycle list of (chronic, recently_active) at a fixed stage.
# ``fire_by`` is the cycle index (1-based) at which the memory MUST be stale;
# ``recovers`` asserts the accumulator leaks back below Θ by the final cycle
# (reinstatement). chronic 0.667 ≈ one 0.95 near-dup ⇒ labile pressure ≈ 0.60.
_P = 0.667  # per-cycle chronic when a genuine interferer is present (labile pressure 0.60)
SERIES_POOL = [
    {"id": "S1", "stage": "labile", "fire_by": 3, "recovers": False,
     "cycles": [(_P, False)] * 5,
     "note": "sustained interference ⇒ permanent erosion accumulates and fires"},
    {"id": "S2", "stage": "labile", "fire_by": None, "recovers": False,
     "cycles": [(_P, False), (0.0, False), (0.0, False), (0.0, False), (0.0, False)],
     "note": "single bout ⇒ NEVER (Sabandal: no conversion from one episode)"},
    {"id": "S3", "stage": "labile", "fire_by": None, "recovers": False,
     "cycles": [(_P, False), (_P, True), (_P, True), (_P, False), (_P, True)],
     "note": "interference present but mostly sleep-protected ⇒ leak dominates, NEVER"},
    {"id": "S4", "stage": "labile", "fire_by": 5, "recovers": False,
     "cycles": [(0.22, False), (0.33, False), (0.50, False), (_P, False), (_P, False)],
     "note": "ramping interference ⇒ fires on crossing, not at the first cycle"},
    {"id": "S5", "stage": "labile", "fire_by": 3, "recovers": True,
     "cycles": [(_P, False), (_P, False), (_P, False),
                (0.0, False), (0.0, False), (0.0, False), (0.0, False)],
     "note": "decay-recovery ⇒ fires then accumulator leaks back below Θ (reinstatement)"},
]


# ── Transient pool: acute recent interferer, stage-INDEPENDENT ───────────────────
# (chronic axis is irrelevant here; transient reads only the strongest acute
# interferer and its age.)
TRANSIENT_POOL = [
    {"id": "T1", "acute_overlap": 0.90, "acute_age_hours": 1.0,
     "is_protected": False, "recently_active": False, "exp_transient": True,
     "note": "consolidated-stage acute recent interferer ⇒ transient (STAGE-INDEPENDENT)"},
    {"id": "T2", "acute_overlap": 0.85, "acute_age_hours": 2.0,
     "is_protected": False, "recently_active": False, "exp_transient": True,
     "note": "acute recent interferer ⇒ transient (reversibility tested)"},
    {"id": "T3", "acute_overlap": 0.85, "acute_age_hours": 24.0,
     "is_protected": False, "recently_active": False, "exp_transient": False,
     "note": "strong overlap but interferer too OLD ⇒ no transient (isolates W)"},
    {"id": "T4", "acute_overlap": 0.30, "acute_age_hours": 1.0,
     "is_protected": False, "recently_active": False, "exp_transient": False,
     "note": "recent but overlap too LOW ⇒ no transient (isolates X)"},
    {"id": "T5", "acute_overlap": 0.90, "acute_age_hours": 1.0,
     "is_protected": True, "recently_active": False, "exp_transient": False,
     "note": "acute interferer but pinned ⇒ no transient"},
]


# ── Accumulator trajectory helper ────────────────────────────────────────────────


def _trajectory(series: dict, lam: float) -> list[float]:
    """Accumulator value after each cycle for a series under leak ``lam``."""
    accum = 0.0
    out = []
    for chronic, sleep in series["cycles"]:
        accum = update_pressure_accum(accum, series["stage"], chronic, sleep, lam)
        out.append(accum)
    return out


# ── Constant derivation (this benchmark IS the source for the core constants) ─────


def derive_thresholds() -> dict:
    """Read every separating constant off the labelled fixtures.

    (λ, Θ_accum) — grid-search the leak λ; for each, the firing fixtures impose a
    floor (accum at their required-fire cycle) and the never/recovery fixtures a
    ceiling (their peak / recovered-tail accum). The admissible band is
    ``ceiling < Θ ≤ floor``; the chosen λ maximises ``floor − ceiling`` and Θ is
    its midpoint — the 2-D max-margin separator for a by-construction labelled set.

    X, W — acute-overlap / recency max-margin midpoints on the transient pool.
    """
    best = None
    for lam in GRID_LAMBDAS:
        floor = float("inf")   # min accum among fire fixtures at their fire cycle
        ceiling = 0.0          # max accum among never fixtures / recovered tails
        ok = True
        for s in SERIES_POOL:
            traj = _trajectory(s, lam)
            if s["fire_by"] is not None:
                floor = min(floor, traj[s["fire_by"] - 1])
            else:
                ceiling = max(ceiling, max(traj))
            if s["recovers"]:
                ceiling = max(ceiling, traj[-1])  # post-recovery tail must stay below Θ
        if not (ceiling < floor):
            ok = False
        if ok:
            margin = floor - ceiling
            if best is None or margin > best["margin"]:
                best = {"lam": lam, "theta": (ceiling + floor) / 2.0,
                        "floor": floor, "ceiling": ceiling, "margin": margin}
    if best is None:
        raise AssertionError("no (λ, Θ) reproduces the S1–S5 labels — fixtures inconsistent")

    # Transient X / W (max-margin midpoints).
    yes = [m for m in TRANSIENT_POOL if m["exp_transient"] and not m["is_protected"]]
    yes_overlap_min = min(m["acute_overlap"] for m in yes)
    recent_no_overlap = [m["acute_overlap"] for m in TRANSIENT_POOL
                         if not m["exp_transient"] and not m["is_protected"]
                         and m["acute_age_hours"] <= 12.0]
    x = (max(recent_no_overlap) + yes_overlap_min) / 2.0
    yes_age_max = max(m["acute_age_hours"] for m in yes)
    strong_no_age = [m["acute_age_hours"] for m in TRANSIENT_POOL
                     if not m["exp_transient"] and not m["is_protected"]
                     and m["acute_overlap"] >= x]
    w = (yes_age_max + min(strong_no_age)) / 2.0

    return {
        "lambda": best["lam"], "Theta_accum": best["theta"],
        "accum_floor": best["floor"], "accum_ceiling": best["ceiling"],
        "accum_margin": best["margin"],
        "X": x, "W": w,
        "overlap_margin": yes_overlap_min - max(recent_no_overlap),
        "age_margin": min(strong_no_age) - yes_age_max,
    }


# ── Verification: signal construction ─────────────────────────────────────────────


def signal_reproduced() -> dict:
    """Core ``chronic_interference`` lands every SIGNAL_POOL row in its band."""
    mismatches = []
    for m in SIGNAL_POOL:
        c = chronic_interference(m["newer_sims"], TAU_DUP)
        zero = c == 0.0
        if zero != m["exp_chronic_zero"]:
            mismatches.append({"id": m["id"], "chronic": round(c, 4),
                               "exp_zero": m["exp_chronic_zero"]})
    return {"passed": not mismatches, "mismatches": mismatches, "n": len(SIGNAL_POOL)}


def fixture_non_saturation() -> dict:
    """A full field of background neighbours stays at chronic 0; one exact
    duplicate alone goes high. The exact guard against the 46%-saturation bug."""
    background = chronic_interference([0.5] * 10, TAU_DUP)
    one_dup = chronic_interference([0.5] * 10 + [0.99], TAU_DUP)
    return {"passed": background == 0.0 and one_dup > 0.5,
            "background_chronic": round(background, 6), "one_dup_chronic": round(one_dup, 4)}


def fixture_tau_dup_provenance() -> dict:
    """τ_dup is the committed curation cutoff, not a free constant."""
    return {"passed": TAU_DUP == MERGE_THRESHOLD,
            "tau_dup": TAU_DUP, "merge_threshold": MERGE_THRESHOLD}


# ── Verification: permanent firing (accumulator, baked constants) ─────────────────


def _series_fire_cycle(series: dict) -> int | None:
    """First cycle (1-based) at which the baked core marks the series permanent."""
    accum = 0.0
    for i, (chronic, sleep) in enumerate(series["cycles"], start=1):
        accum = update_pressure_accum(accum, series["stage"], chronic, sleep)
        if is_permanent_forgetting(accum, False, sleep):
            return i
    return None


def series_reproduced() -> dict:
    """Baked (λ, Θ_accum) reproduce every S1–S5 fire/never/recovery label."""
    mismatches = []
    for s in SERIES_POOL:
        fire = _series_fire_cycle(s)
        if s["fire_by"] is None:
            if fire is not None:
                mismatches.append({"id": s["id"], "expected": "never", "got_cycle": fire})
            continue
        if fire is None or fire > s["fire_by"]:
            mismatches.append({"id": s["id"], "fire_by": s["fire_by"], "got_cycle": fire})
            continue
        if s["recovers"]:
            tail = _trajectory(s, PRESSURE_LEAK_LAMBDA)[-1]
            if tail >= PERMANENT_ACCUM_THRESHOLD:
                mismatches.append({"id": s["id"], "no_recovery_tail": round(tail, 4)})
    return {"passed": not mismatches, "mismatches": mismatches, "n": len(SERIES_POOL)}


# ── Verification: transient (baked constants) ─────────────────────────────────────


def transient_reproduced() -> dict:
    mismatches = []
    for m in TRANSIENT_POOL:
        pinned = bool(m["is_protected"])
        got = is_transient_forgetting(m["acute_overlap"], m["acute_age_hours"],
                                      pinned, m["recently_active"])
        if got != m["exp_transient"]:
            mismatches.append({"id": m["id"], "expected": m["exp_transient"], "got": got})
    return {"passed": not mismatches, "mismatches": mismatches, "n": len(TRANSIENT_POOL)}


# ── Falsifier fixtures (paper predictions; require the core) ──────────────────────


def fixture_consolidated_graded_not_immune() -> dict:
    """Consolidated RESISTS permanent even under sustained strong chronic (graded),
    yet is NOT globally immune: the transient circuit still fires on it
    (Davis&Zhong 2017 + Sabandal 2021)."""
    accum = 0.0
    for _ in range(20):  # sustained, strong chronic, consolidated stage
        accum = update_pressure_accum(accum, "consolidated", 0.95, False)
    permanent = is_permanent_forgetting(accum, False, False)
    transient = is_transient_forgetting(0.90, 1.0, False, False)
    return {"passed": (not permanent) and transient,
            "consolidated_accum_steady": round(accum, 4),
            "consolidated_permanent": permanent, "consolidated_transient": transient}


def fixture_sleep_protects_permanent() -> dict:
    """Sustained chronic but sleep-protected EVERY cycle ⇒ never permanent
    (sleep zeroes pressure and the accumulator leaks; Davis&Zhong)."""
    accum = 0.0
    fired = False
    for _ in range(20):
        accum = update_pressure_accum(accum, "labile", 0.95, True)  # recently_active
        fired = fired or is_permanent_forgetting(accum, False, True)
    return {"passed": not fired, "final_accum": round(accum, 6)}


def fixture_zero_chronic_no_permanent() -> dict:
    """No chronic driver ⇒ accumulator stays 0 ⇒ no permanent, any stage."""
    failures = []
    for s in ("labile", "early_ltp", "late_ltp", "consolidated"):
        accum = 0.0
        for _ in range(20):
            accum = update_pressure_accum(accum, s, 0.0, False)
        if is_permanent_forgetting(accum, False, False):
            failures.append(s)
    return {"passed": not failures, "failures": failures}


def fixture_transient_stage_independent() -> dict:
    """An acute recent interferer triggers transient regardless of stage
    (stage is not even an argument; Sabandal 2021)."""
    fires = is_transient_forgetting(0.90, 1.0, False, False)
    return {"passed": fires, "note": "stage not an arg"}


def fixture_transient_needs_recency_and_overlap() -> dict:
    """Transient requires BOTH overlap≥X AND age≤W (the AND, not either)."""
    old = is_transient_forgetting(0.90, 48.0, False, False)   # strong but old
    weak = is_transient_forgetting(0.20, 1.0, False, False)   # recent but weak
    fires = is_transient_forgetting(0.90, 1.0, False, False)  # both ⇒ fires
    return {"passed": (not old) and (not weak) and fires,
            "old": old, "weak": weak, "both": fires}


def fixture_circuits_independent_no_conversion() -> dict:
    """The circuits read disjoint signals; a purely transient (acute-only,
    chronic 0) history NEVER becomes permanent (Sabandal: no conversion)."""
    accum = 0.0
    for _ in range(20):  # repeated acute interference but chronic 0 ⇒ accum stays 0
        accum = update_pressure_accum(accum, "labile", 0.0, False)
    transient = is_transient_forgetting(0.90, 1.0, False, False)
    permanent = is_permanent_forgetting(accum, False, False)
    return {"passed": transient and not permanent,
            "transient": transient, "permanent": permanent, "accum": round(accum, 6)}


def fixture_reversibility() -> dict:
    """Both modes reversible. Transient recovers on re-access (recently_active).
    Permanent is reinstated: once interference abates, the accumulator leaks back
    below Θ (the S5 decay-recovery trajectory)."""
    transient_recovers = (is_transient_forgetting(0.85, 2.0, False, False)
                          and not is_transient_forgetting(0.85, 2.0, False, True))
    s5 = next(s for s in SERIES_POOL if s["id"] == "S5")
    traj = _trajectory(s5, PRESSURE_LEAK_LAMBDA)
    fired = any(a >= PERMANENT_ACCUM_THRESHOLD for a in traj)
    reinstated = traj[-1] < PERMANENT_ACCUM_THRESHOLD
    return {"passed": transient_recovers and fired and reinstated,
            "transient_recovers": transient_recovers,
            "permanent_fired": fired, "permanent_reinstated": reinstated,
            "final_accum": round(traj[-1], 4)}


def main() -> int:
    th = derive_thresholds()

    print("=" * 78)
    print("ACTIVE-FORGETTING BENCHMARK  (two independent DA circuits)")
    print("=" * 78)
    print("\n[derived constants — SOURCE for mcp_server/core/active_forgetting.py]")
    print(f"  PRESSURE_LEAK_LAMBDA       = {th['lambda']:.4f}")
    print(f"  PERMANENT_ACCUM_THRESHOLD  = {th['Theta_accum']:.5f}"
          f"   (never/recover≤{th['accum_ceiling']:.4f} | fire≥{th['accum_floor']:.4f}; "
          f"margin {th['accum_margin']:.4f})")
    print(f"  TAU_DUP                    = {TAU_DUP:.4f}   (== curation.MERGE_THRESHOLD)")
    print(f"  ACUTE_OVERLAP_THRESHOLD    = {th['X']:.5f}   (margin {th['overlap_margin']:.4f})")
    print(f"  ACUTE_RECENCY_WINDOW_HOURS = {th['W']:.5f}   (margin {th['age_margin']:.4f}h)")
    print(f"\n[baked in core] λ={PRESSURE_LEAK_LAMBDA}  Θ_accum={PERMANENT_ACCUM_THRESHOLD}"
          f"  X={ACUTE_OVERLAP_THRESHOLD}  W={ACUTE_RECENCY_WINDOW_HOURS}")

    sig = signal_reproduced()
    f_sat = fixture_non_saturation()
    f_tau = fixture_tau_dup_provenance()
    ser = series_reproduced()
    tran = transient_reproduced()
    f_graded = fixture_consolidated_graded_not_immune()
    f_sleep = fixture_sleep_protects_permanent()
    f_zero = fixture_zero_chronic_no_permanent()
    f_stageind = fixture_transient_stage_independent()
    f_recency = fixture_transient_needs_recency_and_overlap()
    f_indep = fixture_circuits_independent_no_conversion()
    f_rev = fixture_reversibility()

    print(f"\n[signal construction] passed={sig['passed']}  mismatches={sig['mismatches']}")
    print(f"[series (λ,Θ) reproduced] passed={ser['passed']}  mismatches={ser['mismatches']}")
    print(f"[transient reproduced] passed={tran['passed']}  mismatches={tran['mismatches']}")
    print("\n[falsifiers]")
    print(f"  non-saturation (background 0, one dup high)  passed={f_sat['passed']}  {f_sat}")
    print(f"  τ_dup == curation.MERGE_THRESHOLD            passed={f_tau['passed']}")
    print(f"  consolidated graded-resistant, not immune    passed={f_graded['passed']}")
    print(f"  sleep protects permanent                     passed={f_sleep['passed']}")
    print(f"  zero chronic ⇒ no permanent                  passed={f_zero['passed']}")
    print(f"  transient stage-independent                  passed={f_stageind['passed']}")
    print(f"  transient needs recency AND overlap          passed={f_recency['passed']}")
    print(f"  circuits independent (no conversion)         passed={f_indep['passed']}")
    print(f"  both modes reversible                        passed={f_rev['passed']}")

    passed = all([sig["passed"], ser["passed"], tran["passed"], f_sat["passed"],
                  f_tau["passed"], f_graded["passed"], f_sleep["passed"],
                  f_zero["passed"], f_stageind["passed"], f_recency["passed"],
                  f_indep["passed"], f_rev["passed"]])

    report = {
        "benchmark": "active_forgetting",
        "date": datetime.now(timezone.utc).isoformat(),
        "derived_thresholds": {
            "PRESSURE_LEAK_LAMBDA": round(th["lambda"], 5),
            "PERMANENT_ACCUM_THRESHOLD": round(th["Theta_accum"], 5),
            "TAU_DUP": TAU_DUP,
            "ACUTE_OVERLAP_THRESHOLD": round(th["X"], 5),
            "ACUTE_RECENCY_WINDOW_HOURS": round(th["W"], 5),
        },
        "margins": {"accum": round(th["accum_margin"], 5),
                    "overlap": round(th["overlap_margin"], 5),
                    "age_hours": round(th["age_margin"], 5)},
        "signal_reproduced": sig["passed"],
        "series_reproduced": ser["passed"],
        "transient_reproduced": tran["passed"],
        "fixture_non_saturation": f_sat["passed"],
        "fixture_tau_dup_provenance": f_tau["passed"],
        "fixture_consolidated_graded_not_immune": f_graded["passed"],
        "fixture_sleep_protects_permanent": f_sleep["passed"],
        "fixture_zero_chronic_no_permanent": f_zero["passed"],
        "fixture_transient_stage_independent": f_stageind["passed"],
        "fixture_transient_needs_recency_and_overlap": f_recency["passed"],
        "fixture_circuits_independent": f_indep["passed"],
        "fixture_reversibility": f_rev["passed"],
        "passed": passed,
    }
    _write(report)
    print(f"\nPASSED={passed}")
    return 0 if passed else 1


def _write(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"{stamp}.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nresults written to {out}")


if __name__ == "__main__":
    raise SystemExit(main())
