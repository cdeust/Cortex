"""Forgetting-curve fidelity benchmark — paper-form validation of effective_heat.

WHAT THIS TESTS (and why the retrieval benchmarks cannot)
---------------------------------------------------------
LongMemEval / LoCoMo / BEAM and the longitudinal harness measure RANKING,
not the decay LAW: at year-scale ages heat collapses to its stage floor
regardless of law, and on synthetic corpora vector/lexical similarity
dominates ranking so the heat signal is never decisive (A/B on the
longitudinal runner: ±1 hit/100 = noise). The biomimetic forgetting law must
therefore be validated on PAPER FIDELITY — does the curve effective_heat()
produces over real elapsed time match the FORM of published retention curves?

NON-CIRCULARITY: ground truth = published curve FORMS + parameter ranges, NOT
Cortex's own heat/importance/stage signals. The target is external:
  - Wixted & Ebbesen 1991 (Psych. Sci. 2:409): human forgetting is fit BETTER
    by a power law R=a·t^-b than by a single exponential. Falsifiable claim =
    the ORDERING (power ≥ exponential). b is small, ~0.1-0.5.
  - Anderson & Schooler 1991 / ACT-R: retention follows a power law, d≈0.5.
  - Benna & Fusi 2016 (Nat. Neurosci. 19:1697): cascade synapse decays ∝ 1/√t
    (power law b≈0.5) via a continuum of separated timescales. The α-ladder
    (2.0→1.2→0.8→0.5) is a 4-level discrete analog — does it approximate the
    power law, or just a piecewise/single exponential?
  - Bahrick 1984 (JEP:General 113:1): "permastore" — a residual retention
    floor that persists for decades and does NOT decay to zero.

ARTIFACT UNDER TEST: effective_heat() + effective_stage() in
mcp_server/infrastructure/pg_schema.py. Probed directly via SQL against a
single synthetic row per signal-profile, varying t_now across an age grid.

This benchmark CAN FAIL. If the cascade produces only a single exponential
plus a floor (no power-law character), criterion 1 fails — and that is
reported as a (partial) falsification, not hidden.

Run:
    .venv/bin/python3 benchmarks/forgetting_curve/run_benchmark.py
    .venv/bin/python3 benchmarks/forgetting_curve/run_benchmark.py --quick
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import psycopg  # noqa: E402

from benchmarks.forgetting_curve import criteria  # noqa: E402
from benchmarks.forgetting_curve.criteria import PROFILES  # noqa: E402
from benchmarks.lib.longitudinal_runner import (  # noqa: E402
    configure_environment,
    reset_database,
)

RESULTS_ROOT = REPO / "benchmarks" / "results" / "forgetting_curve"
PROD_URL = "postgresql://localhost:5432/cortex"
DB_NAME = "cortex_curve_test"

# Age grid in hours. Dense in the 0-8h stage-transition window (captures the
# α-ladder) then logarithmic out to 365d (captures the floor regime).
# source: task spec grid (1h,6h,1d,3d,7d,14d,30d,60d,90d,180d,270d,365d)
# enriched with sub-day points to resolve the cascade transitions.
AGES_HOURS_FULL = [0.5, 1, 2, 4, 6, 8, 12, 24, 72, 168, 336, 720, 1440, 2160,
                   4320, 6480, 8760]
AGES_HOURS_QUICK = [1, 6, 24, 72, 168, 720, 2160, 4320, 8760]


def _insert_profile(conn, name: str, spec: dict) -> int:
    """Insert one synthetic memory at heat_base=1.0, valence 0, stage labile."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memories (content, heat_base, heat_base_set_at,
            stage_entered_at, created_at, importance, access_count,
            schema_match_score, emotional_valence, consolidation_stage,
            is_protected, no_decay)
        VALUES (%s, 1.0, NOW(), NOW(), NOW(), %s, %s, %s, 0.0, 'labile',
            FALSE, FALSE)
        RETURNING id
        """,
        (f"forgetting-curve probe {name}", spec["importance"],
         spec["access"], spec["schema"]),
    )
    mid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return mid


def _probe_trajectory(conn, mid: int, spec: dict, ages: list[float]) -> list[dict]:
    """Probe effective_heat + effective_stage across the age grid for one row."""
    cur = conn.cursor()
    traj = []
    for h in ages:
        cur.execute(
            "SELECT effective_heat(m, m.heat_base_set_at + (%s||' hours')"
            "::interval) FROM memories m WHERE m.id=%s",
            (f"{h:.6f}", mid),
        )
        heat = float(cur.fetchone()[0])
        cur.execute(
            "SELECT effective_stage('labile', %s::double precision, %s::real, "
            "%s::integer, %s::real)",
            (h, spec["importance"], spec["access"], spec["schema"]),
        )
        stage = cur.fetchone()[0]
        traj.append({"age_hours": h, "heat": heat, "stage": stage})
    cur.close()
    return traj


def run(quick: bool) -> Path:
    ages = AGES_HOURS_QUICK if quick else AGES_HOURS_FULL
    reset_database(PROD_URL, DB_NAME)
    url = configure_environment(PROD_URL, DB_NAME)
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    store = PgMemoryStore(database_url=url)  # applies schema + SQL functions
    conn = psycopg.connect(url, autocommit=True)
    try:
        trajs = {}
        for name, spec in PROFILES.items():
            mid = _insert_profile(conn, name, spec)
            trajs[name] = _probe_trajectory(conn, mid, spec, ages)
    finally:
        conn.close()
        store.close()

    c1 = criteria.criterion_power_over_exp(trajs["B_consolidated"])
    c2 = criteria.criterion_permastore(trajs["A_labile"], trajs["B_consolidated"])
    c3 = criteria.criterion_exponent(trajs["A_labile"], trajs["B_consolidated"])
    ens = criteria.ensemble_diagnostic(trajs, ages)
    return _finish(quick, ages, trajs, c1, c2, c3, ens)


def _finish(quick, ages, trajs, c1, c2, c3, ens) -> Path:
    verdict = criteria.verdict(c1, c2)
    payload = {
        "benchmark": "forgetting_curve_fidelity",
        "date": datetime.now(timezone.utc).isoformat(),
        "artifact_under_test": "effective_heat() + effective_stage() "
                               "(mcp_server/infrastructure/pg_schema.py)",
        "config": {"quick": quick, "ages_hours": ages, "profiles": PROFILES},
        "trajectories": trajs,
        "criterion_1_power_over_exponential": c1,
        "criterion_2_permastore": c2,
        "criterion_3_exponent_plausibility": c3,
        "diagnostic_ensemble_mixture": ens,
        "overall_passed": bool(c1["passed"] and c2["passed"]),
        "verdict": verdict,
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_ROOT / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(payload, indent=2))
    _print_report(c1, c2, c3, ens, verdict, out_path)
    return out_path


def _print_report(c1, c2, c3, ens, verdict, out_path) -> None:
    print("=" * 78)
    print("FORGETTING-CURVE FIDELITY BENCHMARK  (effective_heat vs paper forms)")
    print("=" * 78)
    cmp1 = c1["comparison"]
    print(f"\n[C1 power-law-over-exponential]  PASS={c1['passed']}")
    print(f"  power r²(h)={cmp1['r2_hspace_power']:.4f}  "
          f"exp r²(h)={cmp1['r2_hspace_exp']:.4f}  "
          f"ΔAIC(exp-power)={cmp1['delta_aic_exp_minus_power']:.2f}  "
          f"winner={cmp1['winner']}")
    print(f"\n[C2 permastore Bahrick]          PASS={c2['passed']}")
    print(f"  B@365d={c2['b_heat_at_365d']:.4f} (floor {c2['permastore_floor']}, "
          f"holds={c2['b_holds_floor']})  "
          f"A@365d={c2['a_heat_at_365d']:.2e} (collapses={c2['a_collapses']})")
    print(f"\n[C3 exponent plausibility]       PASS={c3['passed']}")
    for label, p in c3["profiles"].items():
        print(f"  {label}: power b={p['power_b']:.4f} "
              f"(in band {p['power_b_in_band']})  "
              f"exp half-life={p['exp_half_life_hours']}h")
    cmpe = ens["comparison"]
    print(f"\n[diagnostic ensemble mixture]")
    print(f"  power r²(h)={cmpe['r2_hspace_power']:.4f}  "
          f"exp r²(h)={cmpe['r2_hspace_exp']:.4f}  "
          f"ΔAIC(exp-power)={cmpe['delta_aic_exp_minus_power']:.2f}  "
          f"winner={cmpe['winner']}")
    print(f"\nVERDICT: {verdict}")
    print(f"results → {out_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forgetting-curve fidelity benchmark")
    parser.add_argument("--quick", action="store_true",
                        help="coarse 9-point age grid")
    args = parser.parse_args(argv)
    run(args.quick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
