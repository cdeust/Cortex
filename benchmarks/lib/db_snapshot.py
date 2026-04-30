"""Postgres snapshot/restore with fingerprint + version-drift enforcement.
pg_dump --format=custom round-trips index bytes so dump+restore collapses
HNSW build non-determinism to a single outcome.
Source: tasks/hnsw-determinism-playbook.md §2 mechanism, §5 manifest.
API: create_snapshot, restore_snapshot, fingerprint, verify_fingerprint,
     verify_compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg

# source: spec — refuse non-allow-listed prod DB names without --allow-prod.
_PROD_DBNAME_RE = re.compile(r"^cortex(_cowork)?$")
_DUMP_READ_CHUNK = 1 << 20  # 1 MiB; standard hashlib idiom.
# source: playbook §5 — 10 GUCs the manifest must capture.
_TRACKED_SETTINGS = (
    "work_mem", "maintenance_work_mem",
    "max_parallel_workers_per_gather", "max_parallel_maintenance_workers",
    "effective_io_concurrency",
    "enable_seqscan", "enable_hashagg", "enable_indexscan", "enable_bitmapscan",
    "jit",
)

@dataclass
class SnapshotMeta:
    """Sidecar metadata for a dump file (playbook §5 manifest)."""
    path: str
    created_at_iso: str
    size_bytes: int
    sha256: str
    pg_version: str
    pg_server_version_num: int
    pgvector_version: str
    pg_locale_collate: str
    pg_locale_ctype: str
    n_memories: int
    n_entities: int
    source_db_url: str
    hnsw_indexes: list = field(default_factory=list)
    pg_settings_relevant: dict = field(default_factory=dict)
    # source: PG docs https://www.postgresql.org/docs/current/view-pg-config.html
    # pg_config() exposes PKGLIBDIR which locates the loaded extension binary.
    # SHA-256 of the actual .so/.dylib catches distro patches that share an
    # upstream extversion label — closes the "same version, different code"
    # gap that pgvector_version alone cannot detect.
    pgvector_lib_path: str = ""        # "" = unresolved (remote DB, missing pg_config)
    pgvector_lib_sha256: str = ""      # "" = file unreadable; "absent" = no pgvector

@dataclass
class RestoreReport:
    success: bool
    wall_seconds: float
    n_memories_actual: int
    n_entities_actual: int
    mismatch: list[str]
    version_drift: list[str] = field(default_factory=list)
    settings_drift: dict[str, tuple[str, str]] = field(default_factory=dict)

@dataclass
class CompatibilityReport:
    all_match: bool
    fields: dict[str, dict]  # field -> {snap, live, match}

def _parse_db_url(db_url: str) -> tuple[str, str]:
    parsed = urlparse(db_url)
    dbname = (parsed.path or "/").lstrip("/")
    if not dbname:
        raise ValueError(f"db_url missing database name: {db_url}")
    return dbname, urlunparse(parsed._replace(path="/postgres"))

def _redact(db_url: str) -> str:
    parsed = urlparse(db_url)
    if parsed.password:
        netloc = f"{parsed.username}:***@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        parsed = parsed._replace(netloc=netloc)
    return urlunparse(parsed)

def safety_guard(db_url: str, *, allow_prod: bool = False) -> None:
    """Refuse production-DB targets unless allow_prod is set."""
    dbname, _ = _parse_db_url(db_url)
    if _PROD_DBNAME_RE.match(dbname) and not allow_prod:
        raise SystemExit(f"refusing prod DB '{dbname}'. Pass --allow-prod.")

def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_DUMP_READ_CHUNK):
            h.update(chunk)
    return h.hexdigest()

def verify_fingerprint(path: Path, expected: str) -> bool:
    return fingerprint(path) == expected.lower()

def _show(conn: psycopg.Connection, name: str) -> str:
    row = conn.execute(f"SHOW {name}").fetchone()
    return "" if row is None else str(row[0])

def _meta_path(p: Path) -> Path:
    return p.with_suffix(p.suffix + ".meta.json")

def _resolve_db_url(name_or_url: str) -> str:
    return name_or_url if "://" in name_or_url else f"postgresql://localhost:5432/{name_or_url}"

# Capture every HNSW index in the cluster (playbook §1: memories.embedding +
# 3 wiki indexes per pg_schema.py:287, 292, 307, 506-507). Result is a list
# so the manifest faithfully records all four when wiki tables are present.
_HNSW_SQL = """
SELECT ns.nspname  AS schema_name,
       c.relname   AS table_name,
       idx.relname AS index_name,
       a.attname   AS column_name,
       oc.opcname  AS ops,
       idx.reloptions
FROM pg_index ix
JOIN pg_class idx ON idx.oid = ix.indexrelid
JOIN pg_class c   ON c.oid = ix.indrelid
JOIN pg_namespace ns ON ns.oid = c.relnamespace
JOIN pg_am am     ON am.oid = idx.relam
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ix.indkey[0]
JOIN pg_opclass oc ON oc.oid = ix.indclass[0]
WHERE am.amname = 'hnsw'
ORDER BY ns.nspname, c.relname, idx.relname
"""

def _hnsw_indexes(conn: psycopg.Connection) -> list[dict]:
    """All HNSW indexes: [{schema,table,index_name,column,ops,m,ef_construction}, ...]."""
    try:
        rows = conn.execute(_HNSW_SQL).fetchall()
    except psycopg.Error:
        return []
    out: list[dict] = []
    for row in rows or []:
        schema, table, idx_name, col, opc, reloptions = row
        entry: dict = {
            "schema": schema, "table": table, "index_name": idx_name,
            "column": col, "ops": opc,
        }
        for opt in (reloptions or []):
            if "=" in opt:
                k, v = opt.split("=", 1)
                entry[k] = int(v) if v.isdigit() else v
        out.append(entry)
    if not out:
        print("WARN: snapshot has no HNSW indexes (pre-build).", file=sys.stderr)
    return out

# source: pgvector installs as `vector.so` / `.dylib` / `.dll` per platform.
# Order matters only if multiple are present (shouldn't happen on a single host).
_VECTOR_LIB_NAMES = ("vector.so", "vector.dylib", "vector.dll")


def _resolve_pgvector_lib(conn: psycopg.Connection) -> tuple[str, str]:
    """Return (path, sha256) of the pgvector shared library on disk.

    Strategy: query pg_config view for PKGLIBDIR (PG docs: pg_config view
    exposes the same info as the pg_config CLI). Probe for vector.{so,
    dylib,dll} in that directory; sha256 the first one found.

    Critically, this is DECOUPLED from `pg_extension` presence — the
    binary file exists on disk for the cluster regardless of which DBs
    have run CREATE EXTENSION. This matters because the version-drift
    check runs against the admin `postgres` DB, which typically has no
    user extensions installed. Without this decoupling, the lib SHA
    check would silently skip with `live_sha == "absent"`.

    Returns ("", "") if pg_config unavailable; (libdir, "") if no
    vector.* found in PKGLIBDIR; (path, sha256) on success.
    """
    try:
        row = conn.execute(
            "SELECT setting FROM pg_config WHERE name = 'PKGLIBDIR'"
        ).fetchone()
    except psycopg.Error:
        return ("", "")
    if not row or not row[0]:
        return ("", "")
    libdir = Path(str(row[0]))
    for name in _VECTOR_LIB_NAMES:
        candidate = libdir / name
        if candidate.is_file():
            try:
                return (str(candidate), fingerprint(candidate))
            except OSError:
                return (str(candidate), "")
    return (str(libdir), "")


def _capture_db_state(db_url: str) -> dict:
    """Capture all manifest fields from a live cluster (playbook §5)."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        # Locale is per-database (source: PG docs, pg_database catalog).
        loc = conn.execute("SELECT datcollate, datctype FROM pg_database "
                           "WHERE datname = current_database()").fetchone()
        lib_path, lib_sha = _resolve_pgvector_lib(conn)
        return {
            "pg_version": _show(conn, "server_version"),
            "pg_server_version_num": int(_show(conn, "server_version_num") or 0),
            "pgvector_version": ext[0] if ext else "absent",
            "pg_locale_collate": loc[0] if loc else "",
            "pg_locale_ctype": loc[1] if loc else "",
            "pg_settings_relevant": {n: _show(conn, n) for n in _TRACKED_SETTINGS},
            "hnsw_indexes": _hnsw_indexes(conn),
            "pgvector_lib_path": lib_path,
            "pgvector_lib_sha256": lib_sha,
        }

def _count_rows(db_url: str) -> tuple[int, int]:
    counts = {"memories": 0, "entities": 0}
    with psycopg.connect(db_url, autocommit=True) as conn:
        for table in counts:
            try:
                row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
                if row:
                    counts[table] = int(row[0])
            except psycopg.errors.UndefinedTable:
                pass
    return counts["memories"], counts["entities"]

def create_snapshot(db_url: str, snapshot_path: Path, *, allow_prod: bool = False) -> SnapshotMeta:
    """pg_dump --format=custom + sidecar manifest (playbook §5)."""
    safety_guard(db_url, allow_prod=allow_prod)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    n_mem, n_ent = _count_rows(db_url)
    state = _capture_db_state(db_url)
    if not state["hnsw_indexes"]:
        print("WARN: snapshot pre-HNSW-build; hnsw_indexes will be empty.")
    cmd = ["pg_dump", "--format=custom", "--file", str(snapshot_path), db_url]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {res.stderr.strip()}")
    meta = SnapshotMeta(
        path=str(snapshot_path),
        created_at_iso=datetime.now(timezone.utc).isoformat(),
        size_bytes=snapshot_path.stat().st_size, sha256=fingerprint(snapshot_path),
        n_memories=n_mem, n_entities=n_ent, source_db_url=_redact(db_url),
        **state,  # pg_version + pg_server_version_num + pgvector + locale + settings + hnsw
    )
    _meta_path(snapshot_path).write_text(json.dumps(asdict(meta), indent=2))
    return meta

def _drop_and_create(db_url: str) -> None:
    dbname, admin_url = _parse_db_url(db_url)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     "WHERE datname = %s AND pid <> pg_backend_pid()", (dbname,))
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        conn.execute(f'CREATE DATABASE "{dbname}"')

def _check_version_drift(meta: dict, live: dict) -> list[str]:
    """Hard-fail entries (playbook §5): PG major, pgvector minor, locale, lib SHA."""
    drift: list[str] = []
    sn, ln = int(meta.get("pg_server_version_num", 0)), live["pg_server_version_num"]
    if (sn // 10000) != (ln // 10000):
        drift.append(f"pg_server_version_num major: snap={sn} live={ln}")
    spv, lpv = str(meta.get("pgvector_version", "")), str(live["pgvector_version"])
    if spv and lpv and "absent" not in (spv, lpv):
        if spv.split(".")[:2] != lpv.split(".")[:2]:
            drift.append(f"pgvector_version minor: snap={spv} live={lpv}")
        elif spv != lpv:
            print(f"WARN: pgvector patch drift snap={spv} live={lpv}")
    for f in ("pg_locale_collate", "pg_locale_ctype"):
        if meta.get(f) and meta.get(f) != live[f]:
            drift.append(f"{f}: snap={meta[f]!r} live={live[f]!r}")
    # pgvector library SHA-256 — same extversion + different SHA = distro patch
    # or rebuild. Fail hard: even a "compatible" patched build can change HNSW
    # traversal arithmetic. Skip the check if either side is unresolved (""),
    # since that means PKGLIBDIR was unavailable, not that a mismatch occurred.
    snap_sha = str(meta.get("pgvector_lib_sha256", ""))
    live_sha = str(live.get("pgvector_lib_sha256", ""))
    if snap_sha and live_sha and snap_sha not in ("absent",) and live_sha not in ("absent",):
        if snap_sha != live_sha:
            drift.append(
                f"pgvector_lib_sha256: snap={snap_sha[:12]} live={live_sha[:12]} "
                f"(extversion {spv!r}={lpv!r}; binary differs)"
            )
    return drift

_COMPAT_FIELDS = ("pg_server_version_num", "pgvector_version",
                  "pg_locale_collate", "pg_locale_ctype",
                  "pgvector_lib_sha256")

def verify_compatibility(snapshot_path: Path, target_db_url: str) -> CompatibilityReport:
    """Pre-flight diff snapshot manifest vs live target (playbook §4.15)."""
    meta = json.loads(_meta_path(snapshot_path).read_text())
    try:
        live = _capture_db_state(target_db_url)
    except psycopg.OperationalError as exc:
        return CompatibilityReport(False, {"_error": {"snap": "", "live": str(exc), "match": False}})
    fields = {f: {"snap": meta.get(f), "live": live.get(f),
                  "match": str(meta.get(f)) == str(live.get(f))} for f in _COMPAT_FIELDS}
    return CompatibilityReport(all(v["match"] for v in fields.values()), fields)

def _diff_settings(snap: dict, live: dict) -> dict:
    return {n: (str(sv), str(live.get(n, "")))
            for n, sv in (snap or {}).items() if str(sv) != str(live.get(n, ""))}

def restore_snapshot(db_url: str, snapshot_path: Path, *, allow_prod: bool = False) -> RestoreReport:
    """Drop+recreate target, then pg_restore. Enforces version equality
    (playbook §5); records settings_drift on success."""
    safety_guard(db_url, allow_prod=allow_prod)
    meta_path = _meta_path(snapshot_path)
    if not meta_path.exists():
        raise FileNotFoundError(f"missing sidecar meta: {meta_path}")
    meta = json.loads(meta_path.read_text())
    # Check target via 'postgres' DB before drop — fail without destruction.
    drift = _check_version_drift(meta, _capture_db_state(_parse_db_url(db_url)[1]))
    if drift:
        return RestoreReport(False, 0.0, 0, 0,
                             [f"version_drift: {'; '.join(drift)}"], drift, {})
    t0 = time.monotonic()
    _drop_and_create(db_url)
    cmd = ["pg_restore", "--no-owner", "--dbname", db_url, str(snapshot_path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.monotonic() - t0
    if res.returncode != 0:
        return RestoreReport(False, wall, 0, 0,
                             [f"pg_restore: {res.stderr.strip()}"], drift, {})
    n_mem, n_ent = _count_rows(db_url)
    mismatch: list[str] = []
    if n_mem != meta["n_memories"]:
        mismatch.append(f"memories: expected {meta['n_memories']}, got {n_mem}")
    if n_ent != meta["n_entities"]:
        mismatch.append(f"entities: expected {meta['n_entities']}, got {n_ent}")
    sd = _diff_settings(meta.get("pg_settings_relevant") or {},
                        _capture_db_state(db_url)["pg_settings_relevant"])
    return RestoreReport(not mismatch, wall, n_mem, n_ent, mismatch, drift, sd)

def _cmd_create(args: argparse.Namespace) -> int:
    m = create_snapshot(_resolve_db_url(args.db), Path(args.out), allow_prod=args.allow_prod)
    print(f"snapshot: {m.path} size={m.size_bytes:,}B sha={m.sha256[:12]}")
    print(f"  pg={m.pg_server_version_num} pgvector={m.pgvector_version} locale={m.pg_locale_collate}")
    print(f"  rows: memories={m.n_memories} entities={m.n_entities}")
    print(f"  hnsw: {len(m.hnsw_indexes)} indexes" if m.hnsw_indexes else "  hnsw: (empty — pre-build)")
    return 0

def _cmd_restore(args: argparse.Namespace) -> int:
    r = restore_snapshot(_resolve_db_url(args.db), Path(getattr(args, "from")),
                         allow_prod=args.allow_prod)
    print(f"restore: {'OK' if r.success else 'FAIL'} wall={r.wall_seconds:.2f}s "
          f"memories={r.n_memories_actual} entities={r.n_entities_actual}")
    for m in r.mismatch: print(f"  ! mismatch: {m}")
    for d in r.version_drift: print(f"  ! version_drift: {d}")
    if r.settings_drift:
        print(f"  settings_drift ({len(r.settings_drift)}):")
        for k, (s, lv) in r.settings_drift.items():
            print(f"    {k}: snap={s!r} live={lv!r}")
    return 0 if r.success else 1

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--allow-prod", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("create")
    pc.add_argument("--db", required=True); pc.add_argument("--out", required=True)
    pc.set_defaults(func=_cmd_create)
    pr = sub.add_parser("restore")
    pr.add_argument("--db", required=True)
    pr.add_argument("--from", dest="from", required=True)
    pr.set_defaults(func=_cmd_restore)
    args = p.parse_args()
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
