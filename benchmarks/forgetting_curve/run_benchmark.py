"""Measure forgetting-curve fidelity of effective_heat.

source: ADR-0830
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import benchmarks.lib._composition_root_wiring  # noqa: E402,F401 — source: issue #560
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

# source: ADR-0830


AGES_HOURS_FULL = [
    0.5,
    1,
    2,
    4,
    6,
    8,
    12,
    24,
    72,
    168,
    336,
    720,
    1440,
    2160,
    4320,
    6480,
    8760,
]
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
        (
            f"forgetting-curve probe {name}",
            spec["importance"],
            spec["access"],
            spec["schema"],
        ),
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
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — source: ADR-0830

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
    c4 = criteria.criterion_benna_fusi_sqrt_t(trajs, ages)
    return _finish(quick, ages, trajs, c1, c2, c3, c4)


def _finish(quick, ages, trajs, c1, c2, c3, c4) -> Path:
    verdict = criteria.verdict(c1, c2, c4)
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
        "criterion_4_benna_fusi_sqrt_t": c4,
        "overall_passed": bool(c1["passed"] and c2["passed"]),
        "verdict": verdict,
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_ROOT / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(payload, indent=2))
    _print_report(c1, c2, c3, c4, verdict, out_path)
    return out_path


def _print_report(c1, c2, c3, c4, verdict, out_path) -> None:
    print("=" * 78)
    print("FORGETTING-CURVE FIDELITY BENCHMARK  (effective_heat vs paper forms)")
    print("=" * 78)
    cmp1 = c1["comparison"]
    print(f"\n[C1 power-law-over-exponential]  PASS={c1['passed']}")
    print(
        f"  power r²(h)={cmp1['r2_hspace_power']:.4f}  "
        f"exp r²(h)={cmp1['r2_hspace_exp']:.4f}  "
        f"ΔAIC(exp-power)={cmp1['delta_aic_exp_minus_power']:.2f}  "
        f"winner={cmp1['winner']}"
    )
    print(f"\n[C2 permastore Bahrick]          PASS={c2['passed']}")
    print(
        f"  B@365d={c2['b_heat_at_365d']:.4f} (floor {c2['permastore_floor']}, "
        f"holds={c2['b_holds_floor']})  "
        f"A@365d={c2['a_heat_at_365d']:.2e} (collapses={c2['a_collapses']})"
    )
    print(f"\n[C3 exponent plausibility]       PASS={c3['passed']}")
    for label, p in c3["profiles"].items():
        print(
            f"  {label}: power b={p['power_b']:.4f} "
            f"(in band {p['power_b_in_band']})  "
            f"exp half-life={p['exp_half_life_hours']}h"
        )
    cmpe = c4["comparison"]
    print(f"\n[C4 Benna&Fusi √t law-family]    PASS={c4['passed']}")
    print(
        f"  mixture power r²(h)={cmpe['r2_hspace_power']:.4f}  "
        f"exp r²(h)={cmpe['r2_hspace_exp']:.4f}  "
        f"ΔAIC(exp-power)={cmpe['delta_aic_exp_minus_power']:.2f}  "
        f"winner={cmpe['winner']}"
    )
    print(
        f"  fit b={c4['power_b_exponent']:.4f}  "
        f"√t band {c4['sqrt_t_band']}  "
        f"in band={c4['power_b_in_sqrt_t_band']}"
    )
    print(f"\nVERDICT: {verdict}")
    print(f"results → {out_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forgetting-curve fidelity benchmark")
    parser.add_argument("--quick", action="store_true", help="coarse 9-point age grid")
    args = parser.parse_args(argv)
    run(args.quick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
