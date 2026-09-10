"""Generate isolated psql experiments for W3-5; never opens a DB connection.

The output refuses databases other than cortex_w3_5_calibration. Provision a
disposable DB with a representative public.memories fixture first. Candidates
are explicit; this script never selects a production fillfactor.
"""

from __future__ import annotations

import argparse
import re

from mcp_server.infrastructure.pg_schema import MEMORIES_STORAGE_OPTIONS_DDL

# source: ADR-0774
MIN_ROWS = 30_000
# source: ADR-0774
REPETITIONS = 4
# source: ADR-0774
MAX_IDENTIFIER_BYTES = 63
# source: ADR-0774
MIN_FILLFACTOR = 10
DEFAULT_FILLFACTOR = 100

_GUARD = r"""\set ON_ERROR_STOP on
\timing on
DO $$ BEGIN
  IF current_database() <> 'cortex_w3_5_calibration' THEN
    RAISE EXCEPTION 'W3-5 requires the isolated cortex_w3_5_calibration database';
  END IF;
  IF current_setting('track_counts') <> 'on' THEN
    RAISE EXCEPTION 'W3-5 requires track_counts=on';
  END IF;
END $$;
SELECT version(), current_database(), current_setting('block_size'),
       current_setting('autovacuum_vacuum_threshold'),
       current_setting('autovacuum_vacuum_scale_factor');
"""

_CLONE = """
CREATE TABLE {table} (LIKE public.memories INCLUDING ALL)
  WITH (fillfactor={fillfactor}, autovacuum_enabled=false,
        autovacuum_vacuum_scale_factor=0.05);
DO $$ DECLARE cols text; BEGIN
  SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO cols
    FROM pg_attribute WHERE attrelid='public.memories'::regclass
      AND attnum>0 AND NOT attisdropped AND attgenerated='';
  EXECUTE format('INSERT INTO {table} (%s) OVERRIDING SYSTEM VALUE '
    'SELECT %s FROM public.memories ORDER BY id LIMIT {rows}', cols, cols);
END $$;
VACUUM (ANALYZE) {table};
SELECT '{table}' AS trial, reloptions FROM pg_class WHERE oid='{table}'::regclass;
"""


def validate(schema: str, fillfactors: list[int], rows: int, passes: int) -> None:
    # source: ADR-0774
    if (
        not re.fullmatch(r"w3_5_[a-z0-9_]+", schema)
        or len(schema) > MAX_IDENTIFIER_BYTES
    ):
        raise ValueError("schema must be an ASCII w3_5_ identifier of <=63 bytes")
    # source: ADR-0774
    if not fillfactors or DEFAULT_FILLFACTOR not in fillfactors:
        raise ValueError("include the default fillfactor 100 as baseline")
    if any(
        type(value) is not int or not MIN_FILLFACTOR <= value <= DEFAULT_FILLFACTOR
        for value in fillfactors
    ):
        raise ValueError("fillfactors must be integers in PostgreSQL's 10..100 range")
    if rows < MIN_ROWS or passes < 1:
        raise ValueError("rows must meet the plan minimum; passes must be positive")


def migration_check(schema: str) -> str:
    """Execute the exact production DDL twice and compare catalog options."""
    ddl = MEMORIES_STORAGE_OPTIONS_DDL.strip()
    return f"""
CREATE SCHEMA {schema};
SET search_path TO {schema}, public;
CREATE TABLE {schema}.memories (id integer)
 WITH (fillfactor=100, autovacuum_vacuum_scale_factor=0.2);
{ddl}
CREATE TABLE {schema}.first_options AS
 SELECT array_agg(opt ORDER BY opt) AS opts
 FROM pg_class c, unnest(c.reloptions) opt WHERE c.oid='{schema}.memories'::regclass;
{ddl}
DO $$ DECLARE opts text[]; BEGIN
 SELECT array_agg(opt ORDER BY opt) INTO opts
 FROM pg_class c, unnest(c.reloptions) opt WHERE c.oid='{schema}.memories'::regclass;
 IF opts IS DISTINCT FROM (SELECT f.opts FROM {schema}.first_options f)
    OR NOT (opts @> ARRAY['autovacuum_vacuum_scale_factor=0.05','fillfactor=100']) THEN
   RAISE EXCEPTION 'W3-5 reloptions mismatch or non-idempotent migration';
 END IF;
END $$;
SELECT reloptions FROM pg_class WHERE oid='{schema}.memories'::regclass;
RESET search_path;
"""  # noqa: S608 — generate validates the ASCII schema identifier


def fixture_check(rows: int) -> str:
    return f"""
DO $$ BEGIN
 IF (SELECT count(*) FROM public.memories) < {rows} THEN
   RAISE EXCEPTION 'W3-5 fixture has fewer than {rows} rows';
 END IF;
 IF EXISTS (
   SELECT FROM pg_index i JOIN pg_depend d ON d.objid=i.indexrelid
   JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=d.refobjsubid
   WHERE i.indrelid='public.memories'::regclass AND a.attname='replay_count'
     AND d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass
     AND d.refobjid=i.indrelid
 ) THEN
   RAISE EXCEPTION 'replay_count has an index dependency; not HOT-eligible';
 END IF;
 IF NOT EXISTS (
   SELECT FROM pg_index i JOIN pg_class ix ON ix.oid=i.indexrelid
   JOIN pg_am am ON am.oid=ix.relam
   JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
   WHERE i.indrelid='public.memories'::regclass AND a.attname='heat_base'
     AND am.amname='btree'
 ) THEN RAISE EXCEPTION 'heat_base B-tree control index is missing'; END IF;
END $$;
SELECT indexname, indexdef FROM pg_indexes
 WHERE schemaname='public' AND tablename='memories' ORDER BY indexname;
"""  # noqa: S608 — rows is an argparse integer checked by generate


def sizes(table: str, phase: str) -> str:
    return f"""
SELECT '{table}' AS trial, '{phase}' AS phase,
 pg_relation_size('{table}') AS heap_bytes,
 pg_indexes_size('{table}') AS index_bytes,
 pg_total_relation_size('{table}') AS total_bytes;
"""


def update_pass(table: str, workload: str, pass_number: int) -> str:
    # source: ADR-0774
    assignment = "replay_count = replay_count + 1"
    indexed_check = ""
    if workload == "indexed":
        assignment = (
            "heat_base = CASE WHEN heat_base=0 THEN 1 ELSE 0 END, "
            "heat_base_set_at = NOW()"
        )
        indexed_check = f"""
DO $$ BEGIN
 IF EXISTS (SELECT FROM pg_stat_xact_user_tables
            WHERE relid='{table}'::regclass AND n_tup_hot_upd <> 0) THEN
   RAISE EXCEPTION 'indexed heat change unexpectedly counted as HOT';
 END IF;
END $$;
"""
    return f"""
BEGIN;
EXPLAIN (ANALYZE, BUFFERS, WAL, FORMAT JSON) UPDATE {table} SET {assignment};
SELECT '{table}' AS trial, {pass_number} AS pass, n_tup_upd, n_tup_hot_upd,
 n_tup_hot_upd::numeric / NULLIF(n_tup_upd,0) AS hot_ratio
 FROM pg_stat_xact_user_tables WHERE relid='{table}'::regclass;
{indexed_check}
COMMIT;
"""  # noqa: S608 — validated table, integer pass, fixed assignments


def trial_sql(
    table: str, fillfactor: int, workload: str, shape: tuple[int, int]
) -> str:
    rows, passes = shape
    pieces = [_CLONE.format(table=table, fillfactor=fillfactor, rows=rows)]
    pieces.append(sizes(table, "before_updates"))
    pieces.extend(update_pass(table, workload, step) for step in range(1, passes + 1))
    pieces.append(sizes(table, "before_vacuum"))
    pieces.append(f"VACUUM (VERBOSE, ANALYZE) {table};\n")
    pieces.append(sizes(table, "after_vacuum"))
    return "".join(pieces)


def generate(schema: str, fillfactors: list[int], rows: int, passes: int) -> str:
    validate(schema, fillfactors, rows, passes)
    parts = [_GUARD, migration_check(schema), fixture_check(rows)]
    for repeat in range(REPETITIONS):
        for fillfactor in dict.fromkeys(fillfactors):
            for workload in ("eligible", "indexed"):
                table = f"{schema}.ff{fillfactor}_{workload}_r{repeat}"
                parts.append(trial_sql(table, fillfactor, workload, (rows, passes)))
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--fillfactors", nargs="+", type=int, required=True)
    parser.add_argument("--rows", type=int, default=MIN_ROWS)
    parser.add_argument("--passes", type=int, required=True)
    parser.add_argument("--migration-only", action="store_true")
    args = parser.parse_args()
    try:
        validate(args.schema, args.fillfactors, args.rows, args.passes)
        output = _GUARD + migration_check(args.schema)
        if not args.migration_only:
            output = generate(args.schema, args.fillfactors, args.rows, args.passes)
    except ValueError as exc:
        parser.error(str(exc))
    print(output)


if __name__ == "__main__":
    main()
