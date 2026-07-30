"""Parity + monotonicity tests for the piecewise α-integral decay exponent.

Root cause (forgetting-curve fidelity benchmark, 2026-06-30): effective_heat()
applied α(final stage)·hours_elapsed. When a trace matured (α drops, e.g.
late_ltp 0.8 → consolidated 0.5) the lower α was applied retroactively to the
whole past, so the decay exponent shrank across a stage boundary and heat ROSE
with age — non-physical, non-monotonic forgetting (B_consolidated 6h 0.98982 →
8h 0.99151). Fix: the decay exponent is ∫ α(stage(s)) ds (alpha_integral), and
effective_heat() uses the difference of cumulative integrals over the decay
window. α>0 everywhere ⇒ the integral is increasing ⇒ forgetting is monotone.

These tests pin:
  1. SQL alpha_integral() == a Python oracle mirroring effective_stage's walk.
  2. alpha_integral is non-decreasing in τ (the property that makes forgetting
     monotone) and single-stage traces reduce exactly to α·τ.
  3. effective_heat() is monotone non-increasing across an age grid for every
     benchmark profile — the direct regression for the shipped defect.

Runs against cortex_test (conftest redirects DATABASE_URL).
"""

from __future__ import annotations

import itertools

import pytest


# psycopg ships in the optional [postgresql] extra, absent from the
# SQLite-default install. The mcp_server import below pulls it in, so
# without this guard the module raises ModuleNotFoundError at COLLECTION
# time — an error, not a skip, which fails the whole run (#220). Skip the
# module cleanly instead; the PG gate below still applies when it is present.
pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — alpha_integral needs live schema"
)

_FORWARD_CHAIN = ("labile", "early_ltp", "late_ltp", "consolidated")


def _alpha_integral_oracle(
    stored: str, tau: float, importance: float, access: int, schema: float
) -> float:
    """∫₀^tau α(stage(s)) ds — Python mirror of the SQL alpha_integral().

    Walks the same forward chain and gates as effective_stage(), accumulating
    α·(time spent in each stage). α: labile 2.0, early_ltp 1.2, late_ltp 0.8,
    consolidated 0.5, reconsolidating 1.5, other 1.0 (Kandel 2001).
    """
    cur = stored
    remaining = max(0.0, tau)
    total = 0.0
    if cur not in _FORWARD_CHAIN:
        return (1.5 if cur == "reconsolidating" else 1.0) * remaining

    if cur == "labile":
        if importance > 0.3:
            cur = "early_ltp"  # min_dwell 0 → instant, no α contribution
        else:
            return total + 2.0 * remaining

    if cur == "early_ltp":
        dwell = 1.0 * (1.0 - schema * 0.2)
        if not (access >= 1 or importance > 0.4):
            return total + 1.2 * remaining
        seg = min(remaining, dwell)
        total += 1.2 * seg
        remaining -= seg
        if remaining <= 0.0:
            return total
        cur = "late_ltp"

    if cur == "late_ltp":
        dwell = 6.0 * (15.0 ** (-schema))
        late_thr = 3 if schema < 0.5 else 1
        if not (access >= late_thr):
            return total + 0.8 * remaining
        seg = min(remaining, dwell)
        total += 0.8 * seg
        remaining -= seg
        if remaining <= 0.0:
            return total
        cur = "consolidated"

    return total + 0.5 * remaining


# Benchmark signal profiles (benchmarks/forgetting_curve/criteria.py PROFILES).
_PROFILES = {
    "A_labile": (0.2, 0, 0.0),
    "B_consolidated": (0.6, 3, 0.0),
    "early_ltp": (0.35, 0, 0.0),
    "late_ltp": (0.5, 0, 0.0),
}
_AGES = [0.5, 1, 2, 4, 6, 8, 12, 24, 72, 168, 336, 720, 1440, 2160, 4320, 8760]


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    s.close()


def _sql_alpha_integral(
    store: PgMemoryStore, stored: str, tau: float, imp: float, acc: int, sch: float
) -> float:
    row = store._execute(
        "SELECT alpha_integral(%s, %s::DOUBLE PRECISION, %s::REAL, %s::INTEGER, "
        "%s::REAL) AS v",
        (stored, tau, imp, acc, sch),
    ).fetchone()
    assert row is not None
    return float(row["v"])


def test_alpha_integral_matches_oracle(store: PgMemoryStore) -> None:
    """SQL alpha_integral() == Python oracle across a signal/τ grid."""
    grid = itertools.product(
        _FORWARD_CHAIN + ("reconsolidating", "bogus"),
        (0.0, 0.5, 1.0, 6.0, 7.0, 30.0, 9000.0),
        (0.2, 0.35, 0.45, 0.6),
        (0, 1, 3),
        (0.0, 0.6),
    )
    mismatches = []
    for stored, tau, imp, acc, sch in grid:
        want = _alpha_integral_oracle(stored, tau, imp, acc, sch)
        got = _sql_alpha_integral(store, stored, tau, imp, acc, sch)
        if abs(got - want) > 1e-6:
            mismatches.append((stored, tau, imp, acc, sch, want, got))
    assert not mismatches, "alpha_integral diverged at:\n" + "\n".join(
        f"  stored={m[0]} tau={m[1]} imp={m[2]} acc={m[3]} sch={m[4]}: "
        f"oracle={m[5]:.6f} sql={m[6]:.6f}"
        for m in mismatches
    )


def test_alpha_integral_nondecreasing(store: PgMemoryStore) -> None:
    """∫α is non-decreasing in τ — the property that makes forgetting monotone."""
    for label, (imp, acc, sch) in _PROFILES.items():
        prev = -1.0
        for tau in _AGES:
            v = _sql_alpha_integral(store, "labile", tau, imp, acc, sch)
            assert v >= prev - 1e-9, f"{label}: ∫α decreased at τ={tau} ({v} < {prev})"
            prev = v


def test_alpha_integral_single_stage_is_alpha_times_tau(store: PgMemoryStore) -> None:
    """A trace stuck in one stage reduces exactly to α·τ (no piecewise change)."""
    # imp≤0.3 stays labile (α=2.0); imp=0.35,acc=0 stays early_ltp (α=1.2).
    for stored, imp, acc, alpha in (
        ("labile", 0.2, 0, 2.0),
        ("early_ltp", 0.35, 0, 1.2),
    ):
        for tau in (0.5, 10.0, 500.0):
            got = _sql_alpha_integral(store, stored, tau, imp, acc, 0.0)
            assert abs(got - alpha * tau) < 1e-6, (
                f"{stored} τ={tau}: {got} != {alpha * tau}"
            )


def _probe_heat_trajectory(
    store: PgMemoryStore, imp: float, acc: int, sch: float
) -> list[tuple[float, float]]:
    """Insert one synthetic row, probe effective_heat across the age grid,
    delete it. heat_base=1.0, valence 0, stored stage labile (as on insert)."""
    row = store._execute(
        """
        INSERT INTO memories (content, heat_base, heat_base_set_at,
            stage_entered_at, created_at, importance, access_count,
            schema_match_score, emotional_valence, consolidation_stage,
            is_protected, no_decay)
        VALUES (%s, 1.0, NOW(), NOW(), NOW(), %s, %s, %s, 0.0, 'labile',
            FALSE, FALSE)
        RETURNING id
        """,
        (f"alpha-integral monotonicity probe imp={imp}", imp, acc, sch),
    ).fetchone()
    assert row is not None
    mid = int(row["id"])
    try:
        traj = []
        for h in _AGES:
            r = store._execute(
                "SELECT effective_heat(m, m.heat_base_set_at + (%s||' hours')"
                "::interval) AS heat FROM memories m WHERE m.id=%s",
                (f"{h:.6f}", mid),
            ).fetchone()
            assert r is not None
            traj.append((h, float(r["heat"])))
        return traj
    finally:
        store._execute("DELETE FROM memories WHERE id=%s", (mid,))


def test_effective_heat_is_monotone_non_increasing(store: PgMemoryStore) -> None:
    """REGRESSION: effective_heat() never rises with age, for every profile.

    Before the α-integral fix, B_consolidated rose 0.98982 (6h) → 0.99151 (8h)
    at the late_ltp→consolidated boundary. The piecewise integral removes the
    non-physical bump at every stage transition.
    """
    for label, (imp, acc, sch) in _PROFILES.items():
        traj = _probe_heat_trajectory(store, imp, acc, sch)
        # strict=False: this is a deliberate pairwise (offset-by-one) walk
        # over traj — traj[1:] is always exactly one element shorter.
        for (t_prev, h_prev), (t_cur, h_cur) in zip(traj, traj[1:], strict=False):
            # Allow float4 round-trip noise; a real bump (≥1e-6) must not occur.
            assert h_cur <= h_prev + 1e-6, (
                f"{label}: heat rose with age {t_prev}h={h_prev:.8f} → "
                f"{t_cur}h={h_cur:.8f}"
            )
