"""Deterministic Postgres session/database setup for benchmark runs.

API: apply_deterministic_session, apply_deterministic_database,
     analyze_after_restore, capture_session_state, verify_session_matches_snapshot.

source: ADR-0071"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import tuple_row
from urllib.parse import urlparse

from mcp_server.infrastructure.pg_iterative_scan import enable_iterative_scan


def _scalar(conn: psycopg.Connection, sql: str) -> str:
    """Execute SHOW/SELECT-of-one-column and return scalar string.

    source: ADR-0071"""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return "" if row is None else str(row[0])


# source: ADR-0071
_WORK_MEM = "64MB"  # source: ADR-0071
_MAINTENANCE_WORK_MEM = "512MB"  # source: ADR-0071
_MAX_PARALLEL_WORKERS_PER_GATHER = 0  # source: ADR-0071
_MAX_PARALLEL_MAINTENANCE_WORKERS = 0  # source: ADR-0071
_EFFECTIVE_IO_CONCURRENCY = 0  # source: ADR-0071
_ENABLE_SEQSCAN = "on"  # source: ADR-0071
_ENABLE_HASHAGG = "on"  # source: ADR-0071
_ENABLE_INDEXSCAN = "on"  # source: ADR-0071
_ENABLE_BITMAPSCAN = "on"  # source: ADR-0071
_JIT = "off"  # source: ADR-0071
# source: ADR-0071
_HNSW_EF_SEARCH = 40

# source: ADR-0071
_SNAPSHOT_TRACKED_SETTINGS = (
    "work_mem",
    "maintenance_work_mem",
    "max_parallel_workers_per_gather",
    "max_parallel_maintenance_workers",
    "effective_io_concurrency",
    "enable_seqscan",
    "enable_hashagg",
    "enable_indexscan",
    "enable_bitmapscan",
    "jit",
)

# GUCs we self-check post-apply. application_name + ef_search are session
# state too, but SHOW reports them via different keys, so handle separately.
# Numeric ef_search comparison must tolerate '40' vs 40 mismatch.
_SELF_CHECK_KEYS = (
    "work_mem",
    "maintenance_work_mem",
    "max_parallel_workers_per_gather",
    "max_parallel_maintenance_workers",
    "effective_io_concurrency",
    "enable_seqscan",
    "enable_hashagg",
    "enable_indexscan",
    "enable_bitmapscan",
    "jit",
    "hnsw.ef_search",
    "application_name",
)


@dataclass
class SessionApplied:
    """Outcome of apply_deterministic_session.

    source: ADR-0071"""

    run_id: str
    mode: str = "transaction"
    settings_set: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DatabaseApplied:
    """Outcome of apply_deterministic_database."""

    run_id: str
    applied: list[str] = field(default_factory=list)
    skipped_due_to_permissions: list[str] = field(default_factory=list)


def apply_deterministic_session(
    conn: psycopg.Connection, *, run_id: str
) -> SessionApplied:
    """Pin per-session GUCs; mode chosen from conn.autocommit.

    source: ADR-0071"""
    autocommit = bool(conn.autocommit)
    mode = "session" if autocommit else "transaction"
    set_keyword = "SET" if autocommit else "SET LOCAL"

    # source: ADR-0071
    if not autocommit:
        conn.commit()  # close any implicit tx so DISCARD ALL is legal
        conn.autocommit = True
    conn.execute("DISCARD ALL")
    # source: ADR-1105 — DISCARD ALL resets hnsw.iterative_scan, which the
    # store set when it opened this connection; a run without it measures
    # the lossy pre-0.8.0 index path instead of the shipped one.
    enable_iterative_scan(conn)
    if not autocommit:
        conn.autocommit = False  # SET LOCAL requires we're back inside a tx

    out = SessionApplied(run_id=run_id, mode=mode)
    pairs = _session_guc_pairs(run_id)
    # psycopg cannot parameterise SET; values come only from the frozen
    # constant table above (no user input) so f-string is safe here.
    for name, val in pairs:
        sql = f"{set_keyword} {name} = {_format_value(val)}"
        try:
            conn.execute(sql)
            out.settings_set[name] = val
        except psycopg.Error as exc:
            out.warnings.append(f"{name}: {exc.__class__.__name__}: {exc}")

    _self_check_settings(conn, out)
    return out


def _session_guc_pairs(run_id: str) -> list[tuple[str, str]]:
    """Frozen (name, value) list applied by apply_deterministic_session."""
    return [
        ("work_mem", _WORK_MEM),
        ("maintenance_work_mem", _MAINTENANCE_WORK_MEM),
        ("max_parallel_workers_per_gather", str(_MAX_PARALLEL_WORKERS_PER_GATHER)),
        ("max_parallel_maintenance_workers", str(_MAX_PARALLEL_MAINTENANCE_WORKERS)),
        ("effective_io_concurrency", str(_EFFECTIVE_IO_CONCURRENCY)),
        ("enable_seqscan", _ENABLE_SEQSCAN),
        ("enable_hashagg", _ENABLE_HASHAGG),
        ("enable_indexscan", _ENABLE_INDEXSCAN),
        ("enable_bitmapscan", _ENABLE_BITMAPSCAN),
        ("jit", _JIT),
        ("hnsw.ef_search", str(_HNSW_EF_SEARCH)),
        # source: ADR-0071
        ("application_name", f"cortex_bench_{run_id}"),
    ]


def _self_check_settings(conn: psycopg.Connection, out: SessionApplied) -> None:
    """Read every tracked GUC back; append warnings for placebo SET failures.

    source: ADR-0071"""
    expected = dict(out.settings_set)
    for name in _SELF_CHECK_KEYS:
        want = expected.get(name)
        if want is None:
            continue
        try:
            live = _scalar(conn, f"SHOW {name}")
        except psycopg.Error as exc:
            out.warnings.append(f"selfcheck {name}: {exc.__class__.__name__}: {exc}")
            continue
        if not _guc_equal(name, want, live):
            out.warnings.append(
                f"selfcheck {name}: requested={want!r} live={live!r} (mode={out.mode})"
            )


# source: ADR-0071
_MEM_UNITS_BYTES: tuple[tuple[str, int], ...] = (
    ("pb", 1024**5),
    ("tb", 1024**4),
    ("gb", 1024**3),
    ("mb", 1024**2),
    ("kb", 1024),
    ("b", 1),
)
# source: ADR-0071
_TIME_UNITS_MS: tuple[tuple[str, int], ...] = (
    ("d", 86_400_000),
    ("h", 3_600_000),
    ("min", 60_000),
    ("s", 1_000),
    ("ms", 1),
    ("us", 0),  # sub-ms; collapsed to 0 (PG echoes via min unit anyway)
)
# source: ADR-0071
_MEMORY_GUCS = frozenset(
    {
        "work_mem",
        "maintenance_work_mem",
        "shared_buffers",
        "effective_cache_size",
        "temp_buffers",
        "wal_buffers",
        "autovacuum_work_mem",
        "logical_decoding_work_mem",
    }
)
# source: ADR-0071
_TIME_GUCS = frozenset(
    {
        "statement_timeout",
        "lock_timeout",
        "idle_in_transaction_session_timeout",
        "deadlock_timeout",
        "checkpoint_timeout",
        "vacuum_cost_delay",
        "autovacuum_vacuum_cost_delay",
        "wal_writer_delay",
    }
)


def _guc_equal(name: str, want: str, live: str) -> bool:
    """Compare a requested GUC value against what SHOW returns.

    source: ADR-0071"""
    if want == live:
        return True
    if want.lower() == live.lower():
        return True
    try:
        return int(want) == int(live)
    except ValueError:
        pass
    if name in _MEMORY_GUCS:
        a, b = _to_bytes(want), _to_bytes(live)
        return a is not None and a == b
    if name in _TIME_GUCS:
        a, b = _to_ms(want), _to_ms(live)
        return a is not None and a == b
    return False


def _split_value_unit(val: str) -> tuple[str, str]:
    """Split '64MB' → ('64', 'mb'); '512' → ('512', '')."""
    s = val.strip()
    i = len(s)
    while i > 0 and not s[i - 1].isdigit():
        i -= 1
    return s[:i], s[i:].lower()


def _to_bytes(val: str) -> int | None:
    """Parse any PG memory string into bytes; None on parse fail.

    Bare integer values are interpreted as 8kB blocks.

    source: ADR-0071"""
    digits, suffix = _split_value_unit(val)
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    if not suffix:
        return n * 8 * 1024  # 8kB blocks
    for unit, mult in _MEM_UNITS_BYTES:
        if suffix == unit:
            return n * mult
    return None


def _to_ms(val: str) -> int | None:
    """Parse any PG duration string into milliseconds; None on parse fail."""
    digits, suffix = _split_value_unit(val)
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    if not suffix:
        return n  # bare number = ms (PG default for time GUCs)
    for unit, mult in _TIME_UNITS_MS:
        if suffix == unit:
            return n * mult
    return None


def _to_kb(val: str) -> int | None:
    """Back-compat: parse a memory string into kB. Implemented via _to_bytes."""
    b = _to_bytes(val)
    return None if b is None else b // 1024


def _format_value(val: str) -> str:
    """Render a GUC value as a SQL literal (numeric passthrough, else quoted)."""
    if val.lstrip("-").isdigit():
        return val
    return "'" + val.replace("'", "''") + "'"


def apply_deterministic_database(db_url: str, *, run_id: str) -> DatabaseApplied:
    """Idempotent ALTER TABLE — autovacuum off for benchmark tables (playbook §4.3).

    Note: ``autovacuum`` is a postmaster-global GUC. ALTER DATABASE …
    SET autovacuum = off raises CantChangeRuntimeParam on every PG
    version — autovacuum can only be turned off cluster-wide. We achieve
    the equivalent by disabling autovacuum *for the benchmark tables*
    via reloptions, which is per-table and per-DB safe.

    Permission errors are recorded, not raised. Caller must enforce
    benchmark-DB allow-listing via db_snapshot.safety_guard.
    """
    out = DatabaseApplied(run_id=run_id)
    stmts = [
        "ALTER TABLE memories SET (autovacuum_enabled = false)",
    ]
    with psycopg.connect(db_url, autocommit=True) as conn:
        for sql in stmts:
            try:
                conn.execute(sql)
                out.applied.append(sql)
            except psycopg.errors.InsufficientPrivilege as exc:
                out.skipped_due_to_permissions.append(f"{sql}: {exc}")
            except psycopg.Error as exc:
                out.skipped_due_to_permissions.append(
                    f"{sql}: {exc.__class__.__name__}: {exc}"
                )
    return out


def analyze_after_restore(db_url: str) -> None:
    """Run ANALYZE on benchmark-relevant tables; refresh pg_statistic.

    source: ADR-0071"""
    t0 = time.monotonic()
    targets = ("memories", "entities")
    with psycopg.connect(db_url, autocommit=True) as conn:
        for tbl in targets:
            try:
                conn.execute(f"ANALYZE {tbl}")
            except psycopg.errors.UndefinedTable:
                print(f"  [analyze] skip {tbl}: table absent")
            except psycopg.Error as exc:
                print(f"  [analyze] {tbl}: {exc.__class__.__name__}: {exc}")
    print(f"  [analyze] wall={time.monotonic() - t0:.2f}s")


def capture_session_state(conn: psycopg.Connection) -> dict:
    """Return snapshot-tracked GUCs + ef_search + application_name.

    Uses _scalar so we work regardless of conn.row_factory.
    """
    keys = list(_SNAPSHOT_TRACKED_SETTINGS) + ["application_name", "hnsw.ef_search"]
    return {name: _scalar(conn, f"SHOW {name}") for name in keys}


def verify_session_matches_snapshot(
    conn: psycopg.Connection, snapshot_meta: dict
) -> list[str]:
    """Return ['name: snap=X live=Y', ...] for any GUC mismatch (empty = ok)."""
    expected = snapshot_meta.get("pg_settings_relevant", {}) or {}
    live = capture_session_state(conn)
    out: list[str] = []
    for name, snap_val in expected.items():
        live_val = live.get(name, "<absent>")
        if str(snap_val) != str(live_val):
            out.append(f"{name}: snap={snap_val!r} live={live_val!r}")
    return out


def _dbname(db_url: str) -> str:
    """Extract dbname from a postgres URL; refuse names with embedded quote."""

    name = (urlparse(db_url).path or "/").lstrip("/")
    if not name:
        raise ValueError(f"db_url missing database name: {db_url}")
    if '"' in name:
        raise ValueError(f"refusing dbname containing quote: {name!r}")
    return name
