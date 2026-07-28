"""DRY parity test: the SQL effective_stage() derivation must equal an
iterative application of the canonical Python advancement logic.

Root cause (memory 4202985): A3 made HEAT lazy on the read path but left
STAGE eager (advanced only by the consolidation handler). effective_stage()
re-derives the stage lazily inside effective_heat(). To stay DRY with the
single source of truth — cascade_advancement.compute_advancement_readiness —
this test pins the SQL ladder against an iterative application of that exact
Python function across a grid of inputs.

The reference loop advances repeatedly until no change, treating stage_hours
as a dwell budget consumed stage-by-stage (the same model the SQL uses), and
disables the dopamine gate (encoding-time, unavailable on the read path) so
the LABILE→EARLY_LTP transition is decided by importance alone.

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

from mcp_server.core.cascade_advancement import (  # noqa: E402
    _effective_min_dwell,
    compute_advancement_readiness,
)
from mcp_server.core.cascade_stages import _STAGE_PROPERTIES, ConsolidationStage  # noqa: E402
from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — effective_stage needs live schema"
)

_FORWARD_CHAIN = ("labile", "early_ltp", "late_ltp", "consolidated")


def _reference_effective_stage(
    stored: str,
    hours: float,
    importance: float,
    access_count: int,
    schema: float,
) -> str:
    """Iterative application of compute_advancement_readiness.

    Advances repeatedly until no change, consuming each stage's effective
    min_dwell from the dwell budget (= hours since stage_entered_at).
    dopamine_level=0.0 disables the encoding-time DA gate so LABILE→EARLY_LTP
    is decided by importance alone — matching the read-path SQL.
    """
    if stored not in _FORWARD_CHAIN:
        return stored
    stage = stored
    budget = max(0.0, hours)
    while True:
        ready, nxt, _ = compute_advancement_readiness(
            current_stage=stage,
            hours_in_stage=budget,
            dopamine_level=0.0,
            replay_count=access_count,
            schema_match=schema,
            importance=importance,
        )
        if not ready or nxt == stage or nxt not in _FORWARD_CHAIN:
            return stage
        props = _STAGE_PROPERTIES[ConsolidationStage(stage)]
        budget -= _effective_min_dwell(props, schema, ConsolidationStage(stage))
        stage = nxt


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    s.close()


def _sql_effective_stage(
    store: PgMemoryStore,
    stored: str,
    hours: float,
    importance: float,
    access_count: int,
    schema: float,
) -> str:
    row = store._execute(
        "SELECT effective_stage(%s, %s::DOUBLE PRECISION, %s::REAL, %s::INTEGER, "
        "%s::REAL) AS st",
        (stored, hours, importance, access_count, schema),
    ).fetchone()
    assert row is not None
    return str(row["st"])


def test_sql_matches_python_iteration(store: PgMemoryStore) -> None:
    """SQL effective_stage() == iterative compute_advancement_readiness."""
    grid = itertools.product(
        _FORWARD_CHAIN,
        (0.5, 2.0, 10.0, 30.0, 9000.0),
        (0.2, 0.35, 0.45, 0.6),
        (0, 1, 3, 5),
        (0.0, 0.6),
    )
    mismatches = []
    for stored, hours, importance, access, schema in grid:
        expected = _reference_effective_stage(stored, hours, importance, access, schema)
        actual = _sql_effective_stage(store, stored, hours, importance, access, schema)
        if actual != expected:
            mismatches.append(
                (stored, hours, importance, access, schema, expected, actual)
            )
    assert not mismatches, "SQL/Python stage derivation diverged at:\n" + "\n".join(
        f"  stored={m[0]} h={m[1]} imp={m[2]} acc={m[3]} sch={m[4]}: "
        f"py={m[5]} sql={m[6]}"
        for m in mismatches
    )


def test_monotonic_never_demotes(store: PgMemoryStore) -> None:
    """A derived stage is never earlier than the stored stage (forward-only)."""
    order = {name: i for i, name in enumerate(_FORWARD_CHAIN)}
    # itertools.product over the same four axes the nested loops walked —
    # identical cases, one level of nesting (§4.5 caps depth at 3).
    grid = itertools.product(
        _FORWARD_CHAIN, (0.0, 0.5, 9000.0), (0.2, 0.6), (0, 5), (0.0, 0.6)
    )
    for stored, hours, importance, access, schema in grid:
        got = _sql_effective_stage(store, stored, hours, importance, access, schema)
        assert order[got] >= order[stored], f"demotion: stored={stored} -> {got}"


def test_offchain_stage_passthrough(store: PgMemoryStore) -> None:
    """reconsolidating / unknown stages are returned unchanged."""
    for stage in ("reconsolidating", "bogus_stage"):
        got = _sql_effective_stage(store, stage, 9000.0, 0.9, 5, 0.9)
        assert got == stage
