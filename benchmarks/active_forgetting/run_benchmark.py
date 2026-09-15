"""Active-forgetting benchmark — two independent DA forgetting circuits (A2).

source: ADR-0815
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# The core under test (the same functions production calls).
from mcp_server.hooks.wiring import wire_composition_root  # noqa: E402 — source: issue #560

wire_composition_root()

from mcp_server.core.active_forgetting import (  # noqa: E402
    ACUTE_OVERLAP_THRESHOLD,
    ACUTE_RECENCY_WINDOW_HOURS,
    CORTICAL_AVAILABILITY_BETA,
    PRESSURE_LEAK_LAMBDA,
    PERMANENT_ACCUM_THRESHOLD,
    TAU_DUP,
    chronic_interference,
    is_permanent_forgetting,
    is_transient_forgetting,
    update_pressure_accum,
)
from mcp_server.core.curation import MERGE_THRESHOLD  # noqa: E402

RESULTS_DIR = REPO / "benchmarks" / "results" / "active_forgetting"

GRID_LAMBDAS = [round(0.05 * i, 2) for i in range(1, 19)]  # 0.05 … 0.90

# source: ADR-0815


SIGNAL_POOL = [
    {
        "id": "G1",
        "newer_sims": [0.52, 0.61, 0.48, 0.55, 0.67, 0.50, 0.58, 0.49, 0.63, 0.54],
        "exp_chronic_zero": True,
        "note": (
            "10 background neighbours (~0.5) ⇒ chronic 0 (NON-SATURATION, load-bearing)"
        ),
    },
    {
        "id": "G2",
        "newer_sims": [0.52, 0.61, 0.48, 0.99, 0.55, 0.50, 0.58],
        "exp_chronic_zero": False,
        "note": "one near-exact duplicate (0.99) in a background field ⇒ chronic high",
    },
    {
        "id": "G3",
        "newer_sims": [0.95, 0.92],
        "exp_chronic_zero": False,
        "note": "two genuine near-dups ⇒ accumulating chronic (monotone in count)",
    },
    {
        "id": "G4",
        "newer_sims": [0.84, 0.83, 0.82, 0.80],
        "exp_chronic_zero": True,
        "note": "all JUST BELOW τ_dup ⇒ chronic 0 (membership gate, not rescale)",
    },
    {
        "id": "G5",
        "newer_sims": [],
        "exp_chronic_zero": True,
        "note": "no newer neighbours ⇒ chronic 0 (driver falsifier)",
    },
]


# source: ADR-0815


_P = 0.667
SERIES_POOL = [
    {
        "id": "S1",
        "stage": "labile",
        "fire_by": 3,
        "recovers": False,
        "cycles": [(_P, False)] * 5,
        "note": "sustained interference ⇒ permanent erosion accumulates and fires",
    },
    {
        "id": "S2",
        "stage": "labile",
        "fire_by": None,
        "recovers": False,
        "cycles": [(_P, False), (0.0, False), (0.0, False), (0.0, False), (0.0, False)],
        "note": "single bout ⇒ NEVER (Sabandal: no conversion from one episode)",
    },
    {
        "id": "S3",
        "stage": "labile",
        "fire_by": None,
        "recovers": False,
        "cycles": [(_P, False), (_P, True), (_P, True), (_P, False), (_P, True)],
        "note": (
            "interference present but mostly sleep-protected ⇒ leak dominates, NEVER"
        ),
    },
    {
        "id": "S4",
        "stage": "labile",
        "fire_by": 5,
        "recovers": False,
        "cycles": [
            (0.22, False),
            (0.33, False),
            (0.50, False),
            (_P, False),
            (_P, False),
        ],
        "note": "ramping interference ⇒ fires on crossing, not at the first cycle",
    },
    {
        "id": "S5",
        "stage": "labile",
        "fire_by": 3,
        "recovers": True,
        "cycles": [
            (_P, False),
            (_P, False),
            (_P, False),
            (0.0, False),
            (0.0, False),
            (0.0, False),
            (0.0, False),
        ],
        "note": (
            "decay-recovery ⇒ fires then accumulator leaks back below Θ (reinstatement)"
        ),
    },
]


# ── Transient pool: acute recent interferer, stage-INDEPENDENT ───────────────────
# (chronic axis is irrelevant here; transient reads only the strongest acute
# interferer and its age.)
TRANSIENT_POOL = [
    {
        "id": "T1",
        "acute_overlap": 0.90,
        "acute_age_hours": 1.0,
        "is_protected": False,
        "recently_active": False,
        "exp_transient": True,
        "note": (
            "consolidated-stage acute recent interferer ⇒ transient (STAGE-INDEPENDENT)"
        ),
    },
    {
        "id": "T2",
        "acute_overlap": 0.85,
        "acute_age_hours": 2.0,
        "is_protected": False,
        "recently_active": False,
        "exp_transient": True,
        "note": "acute recent interferer ⇒ transient (reversibility tested)",
    },
    {
        "id": "T3",
        "acute_overlap": 0.85,
        "acute_age_hours": 24.0,
        "is_protected": False,
        "recently_active": False,
        "exp_transient": False,
        "note": "strong overlap but interferer too OLD ⇒ no transient (isolates W)",
    },
    {
        "id": "T4",
        "acute_overlap": 0.30,
        "acute_age_hours": 1.0,
        "is_protected": False,
        "recently_active": False,
        "exp_transient": False,
        "note": "recent but overlap too LOW ⇒ no transient (isolates X)",
    },
    {
        "id": "T5",
        "acute_overlap": 0.90,
        "acute_age_hours": 1.0,
        "is_protected": True,
        "recently_active": False,
        "exp_transient": False,
        "note": "acute interferer but pinned ⇒ no transient",
    },
]


# source: ADR-0815


_S1 = next(s for s in SERIES_POOL if s["id"] == "S1")


# ── Accumulator trajectory helper ────────────────────────────────────────────────


def _trajectory(
    series: dict, lam: float, *, hippocampal_dependency: float = 0.0
) -> list[float]:
    """Accumulator value after each cycle for a series under leak ``lam``.

    ``hippocampal_dependency`` (CLS-B gate C, default 0.0 = no modulation)
    forwards to ``update_pressure_accum`` unchanged from every pre-CLS-B call
    site in this file.
    """
    accum = 0.0
    out = []
    for chronic, sleep in series["cycles"]:
        accum = update_pressure_accum(
            accum,
            series["stage"],
            chronic,
            sleep,
            lam,
            hippocampal_dependency=hippocampal_dependency,
        )
        out.append(accum)
    return out


# source: ADR-0815

# source: ADR-0815


# source: ADR-0815
_RECENT_NEGATIVE_AGE_HOURS = 12.0


def derive_thresholds() -> dict:
    """Read every separating constant off the labelled fixtures.

    source: ADR-0815

    X, W — acute-overlap / recency max-margin midpoints on the transient pool.
    """
    best = None
    for lam in GRID_LAMBDAS:
        floor = float("inf")  # min accum among fire fixtures at their fire cycle
        ceiling = 0.0  # max accum among never fixtures / recovered tails
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
                best = {
                    "lam": lam,
                    "theta": (ceiling + floor) / 2.0,
                    "floor": floor,
                    "ceiling": ceiling,
                    "margin": margin,
                }
    if best is None:
        raise AssertionError(
            "no (λ, Θ) reproduces the S1–S5 labels — fixtures inconsistent"
        )

    # Transient X / W (max-margin midpoints).
    yes = [m for m in TRANSIENT_POOL if m["exp_transient"] and not m["is_protected"]]
    yes_overlap_min = min(m["acute_overlap"] for m in yes)
    recent_no_overlap = [
        m["acute_overlap"]
        for m in TRANSIENT_POOL
        if not m["exp_transient"]
        and not m["is_protected"]
        and m["acute_age_hours"] <= _RECENT_NEGATIVE_AGE_HOURS
    ]
    x = (max(recent_no_overlap) + yes_overlap_min) / 2.0
    yes_age_max = max(m["acute_age_hours"] for m in yes)
    strong_no_age = [
        m["acute_age_hours"]
        for m in TRANSIENT_POOL
        if not m["exp_transient"] and not m["is_protected"] and m["acute_overlap"] >= x
    ]
    w = (yes_age_max + min(strong_no_age)) / 2.0

    return {
        "lambda": best["lam"],
        "Theta_accum": best["theta"],
        "accum_floor": best["floor"],
        "accum_ceiling": best["ceiling"],
        "accum_margin": best["margin"],
        "X": x,
        "W": w,
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
            mismatches.append(
                {
                    "id": m["id"],
                    "chronic": round(c, 4),
                    "exp_zero": m["exp_chronic_zero"],
                }
            )
    return {"passed": not mismatches, "mismatches": mismatches, "n": len(SIGNAL_POOL)}


# source: ADR-0815

# source: ADR-0815
_CHRONIC_HIGH_BAND = 0.5


def fixture_non_saturation() -> dict:
    """A full field of background neighbours stays at chronic 0; one exact duplicate
    alone goes high.

    source: ADR-0815
    """
    background = chronic_interference([0.5] * 10, TAU_DUP)
    one_dup = chronic_interference([0.5] * 10 + [0.99], TAU_DUP)
    return {
        "passed": background == 0.0 and one_dup > _CHRONIC_HIGH_BAND,
        "background_chronic": round(background, 6),
        "one_dup_chronic": round(one_dup, 4),
    }


def fixture_tau_dup_provenance() -> dict:
    """τ_dup is the committed curation cutoff, not a free constant."""
    return {
        "passed": TAU_DUP == MERGE_THRESHOLD,
        "tau_dup": TAU_DUP,
        "merge_threshold": MERGE_THRESHOLD,
    }


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
                mismatches.append(
                    {"id": s["id"], "expected": "never", "got_cycle": fire}
                )
            continue
        if fire is None or fire > s["fire_by"]:
            mismatches.append(
                {"id": s["id"], "fire_by": s["fire_by"], "got_cycle": fire}
            )
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
        got = is_transient_forgetting(
            m["acute_overlap"], m["acute_age_hours"], pinned, m["recently_active"]
        )
        if got != m["exp_transient"]:
            mismatches.append(
                {"id": m["id"], "expected": m["exp_transient"], "got": got}
            )
    return {
        "passed": not mismatches,
        "mismatches": mismatches,
        "n": len(TRANSIENT_POOL),
    }


# source: ADR-0815


def fixture_consolidated_graded_not_immune() -> dict:
    """Consolidated RESISTS permanent even under sustained strong chronic (graded), yet
    is NOT globally immune: the transient circuit still fires on it.

    source: ADR-0815
    """
    accum = 0.0
    for _ in range(20):  # sustained, strong chronic, consolidated stage
        accum = update_pressure_accum(accum, "consolidated", 0.95, False)
    permanent = is_permanent_forgetting(accum, False, False)
    transient = is_transient_forgetting(0.90, 1.0, False, False)
    return {
        "passed": (not permanent) and transient,
        "consolidated_accum_steady": round(accum, 4),
        "consolidated_permanent": permanent,
        "consolidated_transient": transient,
    }


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
    """An acute recent interferer triggers transient regardless of stage.

    source: ADR-0815
    """
    fires = is_transient_forgetting(0.90, 1.0, False, False)
    return {"passed": fires, "note": "stage not an arg"}


def fixture_transient_needs_recency_and_overlap() -> dict:
    """Transient requires BOTH overlap≥X AND age≤W (the AND, not either)."""
    old = is_transient_forgetting(0.90, 48.0, False, False)  # strong but old
    weak = is_transient_forgetting(0.20, 1.0, False, False)  # recent but weak
    fires = is_transient_forgetting(0.90, 1.0, False, False)  # both ⇒ fires
    return {
        "passed": (not old) and (not weak) and fires,
        "old": old,
        "weak": weak,
        "both": fires,
    }


def fixture_circuits_independent_no_conversion() -> dict:
    """Check that transient and permanent forgetting circuits remain independent.

    source: ADR-0815
    """
    accum = 0.0
    for _ in range(20):  # repeated acute interference but chronic 0 ⇒ accum stays 0
        accum = update_pressure_accum(accum, "labile", 0.0, False)
    transient = is_transient_forgetting(0.90, 1.0, False, False)
    permanent = is_permanent_forgetting(accum, False, False)
    return {
        "passed": transient and not permanent,
        "transient": transient,
        "permanent": permanent,
        "accum": round(accum, 6),
    }


def fixture_reversibility() -> dict:
    """Both modes reversible. Transient recovers on re-access (recently_active).
    Permanent is reinstated: once interference abates, the accumulator leaks back
    below Θ (the S5 decay-recovery trajectory)."""
    transient_recovers = is_transient_forgetting(
        0.85, 2.0, False, False
    ) and not is_transient_forgetting(0.85, 2.0, False, True)
    s5 = next(s for s in SERIES_POOL if s["id"] == "S5")
    traj = _trajectory(s5, PRESSURE_LEAK_LAMBDA)
    fired = any(a >= PERMANENT_ACCUM_THRESHOLD for a in traj)
    reinstated = traj[-1] < PERMANENT_ACCUM_THRESHOLD
    return {
        "passed": transient_recovers and fired and reinstated,
        "transient_recovers": transient_recovers,
        "permanent_fired": fired,
        "permanent_reinstated": reinstated,
        "final_accum": round(traj[-1], 4),
    }


# ── CLS-B gate C: cortical-availability modulation of the PERMANENT circuit ───────


def fixture_hippocampal_dependency_non_regression() -> dict:
    """Check the permanent-forgetting trigger for zero hippocampal dependency.

    source: ADR-0815
    """
    baseline = _trajectory(_S1, PRESSURE_LEAK_LAMBDA)
    cortical = _trajectory(_S1, PRESSURE_LEAK_LAMBDA, hippocampal_dependency=0.0)
    fire_cycle = next(
        (i for i, a in enumerate(cortical, start=1) if a >= PERMANENT_ACCUM_THRESHOLD),
        None,
    )
    return {
        "passed": cortical == baseline
        and fire_cycle is not None
        and fire_cycle <= _S1["fire_by"],
        "fire_cycle": fire_cycle,
        "expected_fire_by": _S1["fire_by"],
        "matches_ungated_baseline": cortical == baseline,
    }


def fixture_hippocampal_dependency_protects() -> dict:
    """Check that full hippocampal dependency reduces accumulated pressure.

    source: ADR-0815
    """
    cortical = _trajectory(_S1, PRESSURE_LEAK_LAMBDA, hippocampal_dependency=0.0)
    hippocampal = _trajectory(_S1, PRESSURE_LEAK_LAMBDA, hippocampal_dependency=1.0)
    # source: ADR-0815

    less_pressure_every_cycle = all(
        h < c for h, c in zip(hippocampal, cortical, strict=True)
    )
    still_growing = hippocampal[-1] > 0.0
    fires_late_or_never = not any(
        a >= PERMANENT_ACCUM_THRESHOLD for a in hippocampal[: _S1["fire_by"]]
    )
    return {
        "passed": less_pressure_every_cycle and still_growing and fires_late_or_never,
        "cortical_trajectory": [round(a, 4) for a in cortical],
        "hippocampal_trajectory": [round(a, 4) for a in hippocampal],
        "beta": CORTICAL_AVAILABILITY_BETA,
    }


def fixture_hippocampal_dependency_never_zeroes_pressure() -> dict:
    """Check that full hippocampal dependency leaves pressure strictly positive.

    source: ADR-0815
    """
    accum = update_pressure_accum(
        0.0, "labile", 0.667, False, hippocampal_dependency=1.0
    )
    return {"passed": accum > 0.0, "accum_after_one_cycle": round(accum, 6)}


def main() -> int:
    th = derive_thresholds()

    print("=" * 78)
    print("ACTIVE-FORGETTING BENCHMARK  (two independent DA circuits)")
    print("=" * 78)
    print("\n[derived constants — SOURCE for mcp_server/core/active_forgetting.py]")
    print(f"  PRESSURE_LEAK_LAMBDA       = {th['lambda']:.4f}")
    print(
        f"  PERMANENT_ACCUM_THRESHOLD  = {th['Theta_accum']:.5f}"
        f"   (never/recover≤{th['accum_ceiling']:.4f} | fire≥{th['accum_floor']:.4f}; "
        f"margin {th['accum_margin']:.4f})"
    )
    print(
        f"  TAU_DUP                    = {TAU_DUP:.4f}   (== curation.MERGE_THRESHOLD)"
    )
    print(
        f"  ACUTE_OVERLAP_THRESHOLD    = {th['X']:.5f}   "
        f"(margin {th['overlap_margin']:.4f})"
    )
    print(
        f"  ACUTE_RECENCY_WINDOW_HOURS = {th['W']:.5f}   "
        f"(margin {th['age_margin']:.4f}h)"
    )
    print(
        f"\n[baked in core] λ={PRESSURE_LEAK_LAMBDA}  "
        f"Θ_accum={PERMANENT_ACCUM_THRESHOLD}"
        f"  X={ACUTE_OVERLAP_THRESHOLD}  W={ACUTE_RECENCY_WINDOW_HOURS}"
    )

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
    f_dep_nonreg = fixture_hippocampal_dependency_non_regression()
    f_dep_protect = fixture_hippocampal_dependency_protects()
    f_dep_nonzero = fixture_hippocampal_dependency_never_zeroes_pressure()

    print(
        f"\n[signal construction] passed={sig['passed']}  "
        f"mismatches={sig['mismatches']}"
    )
    print(
        f"[series (λ,Θ) reproduced] passed={ser['passed']}  "
        f"mismatches={ser['mismatches']}"
    )
    print(
        f"[transient reproduced] passed={tran['passed']}  "
        f"mismatches={tran['mismatches']}"
    )
    print("\n[falsifiers]")
    print(
        f"  non-saturation (background 0, one dup high)  "
        f"passed={f_sat['passed']}  {f_sat}"
    )
    print(f"  τ_dup == curation.MERGE_THRESHOLD            passed={f_tau['passed']}")
    print(f"  consolidated graded-resistant, not immune    passed={f_graded['passed']}")
    print(f"  sleep protects permanent                     passed={f_sleep['passed']}")
    print(f"  zero chronic ⇒ no permanent                  passed={f_zero['passed']}")
    print(
        f"  transient stage-independent                  passed={f_stageind['passed']}"
    )
    print(
        f"  transient needs recency AND overlap          passed={f_recency['passed']}"
    )
    print(f"  circuits independent (no conversion)         passed={f_indep['passed']}")
    print(f"  both modes reversible                        passed={f_rev['passed']}")
    print("\n[CLS-B gate C — cortical_availability(hippocampal_dependency)]")
    print(
        f"  (i)  non-regression (dep=0.0 matches S1 baseline)   "
        f"passed={f_dep_nonreg['passed']}"
        f"  fire_cycle={f_dep_nonreg['fire_cycle']}"
    )
    print(
        f"  (ii) protection (dep=1.0 resists longer, still grows) "
        f"passed={f_dep_protect['passed']}"
    )
    print(
        f"  pressure never zeroed at dep=1.0 (β={CORTICAL_AVAILABILITY_BETA})    "
        f"passed={f_dep_nonzero['passed']}"
    )

    passed = all(
        [
            sig["passed"],
            ser["passed"],
            tran["passed"],
            f_sat["passed"],
            f_tau["passed"],
            f_graded["passed"],
            f_sleep["passed"],
            f_zero["passed"],
            f_stageind["passed"],
            f_recency["passed"],
            f_indep["passed"],
            f_rev["passed"],
            f_dep_nonreg["passed"],
            f_dep_protect["passed"],
            f_dep_nonzero["passed"],
        ]
    )

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
        "margins": {
            "accum": round(th["accum_margin"], 5),
            "overlap": round(th["overlap_margin"], 5),
            "age_hours": round(th["age_margin"], 5),
        },
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
        "fixture_hippocampal_dependency_non_regression": f_dep_nonreg["passed"],
        "fixture_hippocampal_dependency_protects": f_dep_protect["passed"],
        "fixture_hippocampal_dependency_never_zeroes_pressure": f_dep_nonzero["passed"],
        "cortical_availability_beta": CORTICAL_AVAILABILITY_BETA,
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
