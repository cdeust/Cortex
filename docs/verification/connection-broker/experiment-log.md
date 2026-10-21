# Connection-broker study: experiment log (ADR-1112)

Append-only. One variable per entry; failures are recorded like successes.
New entries are appended by `python scripts/repro_connection_broker.py
<measurement>` or by hand at the bottom; earlier entries are never edited.
Times are UTC unless marked. Entries 1 to 8 were written by hand on
2026-10-20/21 from the commands run in the investigating session; the times
given are those the commands printed (Europe/Paris where PostgreSQL printed
local time).

## Control environment

- Developer server: PostgreSQL 17.9 (Homebrew), `max_connections = 100`, the
  connecting role is a superuser (`rolsuper = true`).
- Baseline cluster: a private cluster from the same binaries, created per run
  in a pytest temporary directory (`tests_py/_pg_private_cluster.py`):
  `initdb -A trust`, TCP 127.0.0.1 on a free port, no Unix socket,
  `max_connections = 20`, `fsync = off`. Never the live store.
- Test database for increment 0: the per-process throwaway database the suite
  already creates (`tests_py/_pg_throwaway_db.py`).

## Entries

### 1. 2026-10-21 00:00:48 +02:00: live store, read-only probe

- Variable: none (observation). One read-only connection
  (`default_transaction_read_only=on`, `statement_timeout=3000`).
- `schema_meta`: `ddl_hash` prefix `c867454173d6227e`, `applied_at`
  2026-10-20 23:59:31 +02:00 (77 s before the read).
- `pg_stat_activity` on `cortex`: 21 idle, 1 active, 0 idle in transaction.

### 2. 2026-10-21 ~00:05 +02:00: DDL fingerprint of each installed tree

- Variable: code tree. `sha256("\n".join(get_all_ddl()))`, first 16 hex.
- Claude Code plugin cache `hypermnesia-mcp/4.23.5` (built 2026-10-16):
  `44002703f29f0c2d`. This worktree at `df3a4479`: `44002703f29f0c2d`.
- Codex uv tool `hypermnesia-mcp` 4.23.5 (wheel
  `dist/codex-hooks-20261002/hypermnesia_mcp-4.23.5-py3-none-any.whl`,
  installed 2026-10-02): `c867454173d6227e`. Same version label, different
  `pg_schema.py` (ADR-1106/1109 recall-function changes absent).

### 3. Increment-0 tests before the fix (worktree at `df3a4479`)

- `pytest tests_py/infrastructure/test_pg_no_runtime_ddl_no_idle_tx.py`:
  4 failed, 1 passed in 11.70 s.
- Failed: store open on a foreign revision still alive after 10 s behind an
  idle reader (queued DDL); `apply_schema` missing (ImportError); 1 backend
  `idle in transaction` while the decay stream was paused between chunks; a
  row deleted mid-pass was still streamed (`7 in [4, 5, 6, 7]`, cursor
  snapshot).
- Passed: the PostgreSQL fact. `ALTER TABLE memories ADD COLUMN IF NOT EXISTS
  is_team_decision ...` on an existing column fails with `LockNotAvailable`
  under `lock_timeout = 500ms` while another session holds an open
  transaction that read `memories`.

### 4. Failed approach: per-database CONNECTION LIMIT on the shared server

- Variable: saturation mechanism. Idea: `ALTER DATABASE <throwaway> CONNECTION
  LIMIT n` to saturate one database without touching the others.
- Rejected before running: the role is a superuser and PostgreSQL does not
  apply a database connection limit to superusers. Replaced by the private
  cluster of the control environment.

### 5. Baseline, three runs (private cluster, `max_connections = 20`, 8 children)

| run | backends at peak | connections held per blocked child | refused or timed out | outcomes |
|---|---|---|---|---|
| a | 17 | 2, 4, 4, 4 | 4 of 8 | 3 PoolTimeout (5.00 s), 1 `FATAL: sorry, too many clients already` |
| b | 16 | 2, 3, 4, 4 | 4 of 8 | 4 PoolTimeout |
| c | 15 | 4, 4, 4 | 5 of 8 | 5 PoolTimeout |

- A blocked child holds its persistent connection plus pooled connections
  that grow toward `POOL_INTERACTIVE_MAX = 8` while its request waits.

### 6. Increment-0 tests after the fix

- Same file plus the touched suites (`test_migrate.py`,
  `test_pg_recall_ddl_upgrade.py`, `test_pg_schema_provision_ready.py`,
  `test_sqlite_parity_197.py`, `test_hook_receipts.py`): 51 passed.

### 7. 2026-10-21 00:18:32 +02:00: live store, read-only probe again

- `schema_meta`: `ddl_hash` prefix `44002703f29f0c2d`, `applied_at`
  2026-10-21 00:16:57 +02:00. Between entries 1 and 7 (17 min) the recorded
  revision flipped from the Codex tree to the Claude tree: at least two full
  DDL re-applications on the live store, each taking AccessExclusive locks.
- 22 client backends; per Cortex process 3 to 4 TCP connections (`lsof`), six
  processes holding connections, two detached `session_lifecycle
  --consolidate` processes alive for 1 h 26 min and 2 h 50 min.

### 8. Not measured

- Which statement the 2 h `ALTER TABLE` of 2026-10-20 was, and which process
  issued it: `pg_locks` was not captured during the incident.

### 2026-10-20T22:23:56+00:00 baseline

- head: `df3a4479fbd0207de6e0bade919f4de09da4273e` (dirty)
- command: `python scripts/repro_connection_broker.py baseline`
- pytest exit code: 0 (1 passed in 29.23s)
- measured: `{"backends_at_peak": 15, "children": 8, "max_connections": 20, "outcomes": ["PoolTimeout: couldn't get a connection after 5.00 sec", "PoolTimeout: couldn't get a connection after 5.00 sec", "PoolTimeout: couldn't get a connection after 5.00 sec", "PoolTimeout: couldn't get a connection after 5.00 sec", "PoolTimeout: couldn't get a connection after 5.00 sec"], "per_blocked_child": [4, 4, 4], "refused_or_timed_out": 5}`

### 2026-10-20T22:24:00+00:00 increment0

- head: `df3a4479fbd0207de6e0bade919f4de09da4273e` (dirty)
- command: `python scripts/repro_connection_broker.py increment0`
- pytest exit code: 0 (5 passed in 1.79s)
- measured: `{}`

### 20261020T223155Z lock chain

- head: `df3a4479fbd0207de6e0bade919f4de09da4273e`
- command: `python scripts/repro_lock_chain.py`
- evidence: `docs/verification/connection-broker/evidence/lock-chain-20261020T223155Z.json`
- stream/main: `{'tree': 'main', 'consumer_ready': True, 'consumer_write_done_within_deadlock_window': False, 'released_by': 'consumer process killed by the harness', 'alter': {'at': 16658.7436365}, 'readers_completed': 3, 'readers_waited_s': 3.138, 'readers_completed_before_release': 0}`
  chain at capture:
  - `main-consolidation` idle
  - `main-consolidation` idle in transaction
  - `main-consolidation` idle
  - `ddl` active, waits Lock, blocked by ['main-consolidation']
  - `reader-0` active, waits Lock, blocked by ['ddl']
  - `reader-1` active, waits Lock, blocked by ['ddl']
  - `reader-2` active, waits Lock, blocked by ['ddl']
- open/main: `{'tree': 'main', 'opened_while_reader_idle': None, 'store_done': True, 'readers_completed': 3, 'readers_waited_s': 0.168, 'readers_completed_before_release': 0, 'ddl_statements_logged': 98, 'ddl_sample': ['2026-10-21 00:31:47.270 CEST [19964] main-store-open LOG:  statement: CREATE EXTENSION IF NOT EXISTS vector;', '2026-10-21 00:31:47.271 CEST [19964] main-store-open LOG:  statement: CREATE EXTENSION IF NOT EXISTS pg_trgm;', '2026-10-21 00:31:47.271 CEST [19964] main-store-open LOG:  statement: CREATE TABLE IF NOT EXISTS memories ('], 'recorded_revision_after': '44002703f29f0c2d'}`
  chain at capture:
  - `blocker` idle in transaction
  - `main-store-open` active, waits Lock, blocked by ['blocker']
  - `reader-0` active, waits Lock, blocked by ['main-store-open']
  - `reader-1` active, waits Lock, blocked by ['main-store-open']
  - `reader-2` active, waits Lock, blocked by ['main-store-open']
- stream/branch: `{'tree': 'branch', 'consumer_ready': True, 'consumer_write_done_within_deadlock_window': True, 'released_by': 'consumer finished its pass', 'alter': {'at': 16664.256566375}, 'readers_completed': 3, 'readers_waited_s': 0.006, 'readers_completed_before_release': 3}`
  chain at capture:
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `ddl` idle
- open/branch: `{'tree': 'branch', 'opened_while_reader_idle': 'OPENED', 'store_done': True, 'readers_completed': 3, 'readers_waited_s': 0.008, 'readers_completed_before_release': 3, 'ddl_statements_logged': 0, 'ddl_sample': [], 'recorded_revision_after': 'another-install-'}`
  chain at capture:
  - `blocker` idle in transaction
- flipflop/main+other: `{'order': ['main', 'other', 'main', 'other'], 'steps': [{'tree': 'main', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'main', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}]}`
- flipflop/branch+other: `{'order': ['branch', 'other', 'branch', 'other'], 'steps': [{'tree': 'branch', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'branch', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': 'c867454173d6227e'}]}`

### 20261020T223237Z lock chain

- head: `df3a4479fbd0207de6e0bade919f4de09da4273e`
- command: `python scripts/repro_lock_chain.py`
- evidence: `docs/verification/connection-broker/evidence/lock-chain-20261020T223237Z.json`
- stream/main: `{'tree': 'main', 'consumer_ready': True, 'consumer_write_done_within_deadlock_window': False, 'released_by': 'consumer process killed by the harness', 'alter': {'at': 16699.748722875}, 'readers_completed': 3, 'readers_waited_s': 3.143, 'readers_completed_before_release': 0}`
  chain at capture:
  - `main-consolidation` idle
  - `main-consolidation` idle in transaction
  - `main-consolidation` idle
  - `ddl` active, waits Lock, blocked by ['main-consolidation']
  - `reader-0` active, waits Lock, blocked by ['ddl']
  - `reader-1` active, waits Lock, blocked by ['ddl']
  - `reader-2` active, waits Lock, blocked by ['ddl']
  after the consumer's own write:
  - `main-consolidation` idle
  - `main-consolidation` idle in transaction
  - `main-consolidation` idle
  - `ddl` active, waits Lock, blocked by ['main-consolidation']
  - `reader-0` active, waits Lock, blocked by ['ddl']
  - `reader-1` active, waits Lock, blocked by ['ddl']
  - `reader-2` active, waits Lock, blocked by ['ddl']
  - `main-consolidation` active, waits Lock, blocked by ['ddl']
  - `main-consolidation` idle
  - `main-consolidation` idle
- open/main: `{'tree': 'main', 'opened_while_reader_idle': None, 'store_done': True, 'readers_completed': 3, 'readers_waited_s': 0.173, 'readers_completed_before_release': 0, 'ddl_statements_logged': 98, 'ddl_sample': ['2026-10-21 00:32:28.384 CEST [25688] main-store-open LOG:  statement: CREATE EXTENSION IF NOT EXISTS vector;', '2026-10-21 00:32:28.385 CEST [25688] main-store-open LOG:  statement: CREATE EXTENSION IF NOT EXISTS pg_trgm;', '2026-10-21 00:32:28.385 CEST [25688] main-store-open LOG:  statement: CREATE TABLE IF NOT EXISTS memories ('], 'recorded_revision_after': '44002703f29f0c2d'}`
  chain at capture:
  - `blocker` idle in transaction
  - `main-store-open` active, waits Lock, blocked by ['blocker']
  - `reader-0` active, waits Lock, blocked by ['main-store-open']
  - `reader-1` active, waits Lock, blocked by ['main-store-open']
  - `reader-2` active, waits Lock, blocked by ['main-store-open']
- stream/branch: `{'tree': 'branch', 'consumer_ready': True, 'consumer_write_done_within_deadlock_window': True, 'released_by': 'consumer finished its pass', 'alter': {'at': 16705.400003208}, 'readers_completed': 3, 'readers_waited_s': 0.008, 'readers_completed_before_release': 3}`
  chain at capture:
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `ddl` idle
  after the consumer's own write:
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `ddl` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
- open/branch: `{'tree': 'branch', 'opened_while_reader_idle': 'OPENED', 'store_done': True, 'readers_completed': 3, 'readers_waited_s': 0.009, 'readers_completed_before_release': 3, 'ddl_statements_logged': 0, 'ddl_sample': [], 'recorded_revision_after': 'another-install-'}`
  chain at capture:
  - `blocker` idle in transaction
- flipflop/main+other: `{'order': ['main', 'other', 'main', 'other'], 'steps': [{'tree': 'main', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'main', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}]}`
- flipflop/branch+other: `{'order': ['branch', 'other', 'branch', 'other'], 'steps': [{'tree': 'branch', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'branch', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'other', 'completed': True, 'ddl_statements_logged': 0, 'recorded_revision_after': 'c867454173d6227e'}]}`

### 9. 2026-10-20T22:35Z: note on the two lock-chain entries above (by hand)

- Both runs are the same experiment on the same code; between them only the
  summary printer changed (it now also prints the chain after the consumer's
  own write, which the first run's evidence JSON already contains under
  `after_write`). Results agree: `stream/main` forms the client-closed cycle
  (consumer `idle in transaction` -> `ALTER` waits -> readers and the
  consumer's own `UPDATE` wait on the `ALTER`), released only by killing the
  consumer; `open/main` logs 98 DDL statements and its first waiting
  statement is the ADR-1083 `ADD COLUMN IF NOT EXISTS`; the branch variants
  form no chain and log no DDL; `flipflop/main+other` logs 0, 98, 98, 98 DDL
  statements and `flipflop/branch+other` 0, 98, 0, 0.

### 20261020T230256Z lock chain

- head: `8b1e2d2b9819646d5d2a661152805248613f2544`
- command: `python scripts/repro_lock_chain.py`
- evidence: `docs/verification/connection-broker/evidence/lock-chain-20261020T230256Z.json`
- stream/main: `{'tree': 'main', 'consumer_ready': True, 'consumer_write_done_within_deadlock_window': False, 'released_by': 'consumer process killed by the harness', 'alter': {'at': 18519.786166166}, 'readers_completed': 3, 'readers_waited_s': 3.132, 'readers_completed_before_release': 0}`
  chain at capture:
  - `main-consolidation` idle
  - `main-consolidation` idle in transaction
  - `main-consolidation` idle
  - `ddl` active, waits Lock, blocked by ['main-consolidation']
  - `reader-0` active, waits Lock, blocked by ['ddl']
  - `reader-1` active, waits Lock, blocked by ['ddl']
  - `reader-2` active, waits Lock, blocked by ['ddl']
  after the consumer's own write:
  - `main-consolidation` idle
  - `main-consolidation` idle in transaction
  - `main-consolidation` idle
  - `ddl` active, waits Lock, blocked by ['main-consolidation']
  - `reader-0` active, waits Lock, blocked by ['ddl']
  - `reader-1` active, waits Lock, blocked by ['ddl']
  - `reader-2` active, waits Lock, blocked by ['ddl']
  - `main-consolidation` idle
  - `main-consolidation` active, waits Lock, blocked by ['ddl']
  - `main-consolidation` idle
- open/main: `{'tree': 'main', 'opened_while_reader_idle': None, 'store_outcome': 'DONE', 'readers_completed': 3, 'readers_waited_s': 0.162, 'readers_completed_before_release': 0, 'ddl_statements_logged': 98, 'ddl_sample': ['2026-10-21 01:02:48.289 CEST [43384] main-store-open LOG:  statement: CREATE EXTENSION IF NOT EXISTS vector;', '2026-10-21 01:02:48.289 CEST [43384] main-store-open LOG:  statement: CREATE EXTENSION IF NOT EXISTS pg_trgm;', '2026-10-21 01:02:48.289 CEST [43384] main-store-open LOG:  statement: CREATE TABLE IF NOT EXISTS memories ('], 'recorded_revision_after': '44002703f29f0c2d'}`
  chain at capture:
  - `blocker` idle in transaction
  - `main-store-open` active, waits Lock, blocked by ['blocker']
  - `reader-0` active, waits Lock, blocked by ['main-store-open']
  - `reader-1` active, waits Lock, blocked by ['main-store-open']
  - `reader-2` active, waits Lock, blocked by ['main-store-open']
- stream/branch: `{'tree': 'branch', 'consumer_ready': True, 'consumer_write_done_within_deadlock_window': True, 'released_by': 'consumer finished its pass', 'alter': {'at': 18525.297148458}, 'readers_completed': 3, 'readers_waited_s': 0.007, 'readers_completed_before_release': 3}`
  chain at capture:
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `ddl` idle
  after the consumer's own write:
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `ddl` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
  - `branch-consolidation` idle
- open/branch: `{'tree': 'branch', 'opened_while_reader_idle': 'REFUSED SchemaTamperedError', 'store_outcome': 'REFUSED SchemaTamperedError', 'readers_completed': 3, 'readers_waited_s': 0.009, 'readers_completed_before_release': 3, 'ddl_statements_logged': 0, 'ddl_sample': [], 'recorded_revision_after': 'another-install-'}`
  chain at capture:
  - `blocker` idle in transaction
- flipflop/main+other: `{'order': ['main', 'other', 'main', 'other'], 'steps': [{'tree': 'main', 'outcome': 'DONE', 'ddl_statements_logged': 0, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'outcome': 'DONE', 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'main', 'outcome': 'DONE', 'ddl_statements_logged': 98, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'outcome': 'DONE', 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}]}`
- flipflop/branch+other: `{'order': ['branch', 'other', 'branch', 'other'], 'steps': [{'tree': 'branch', 'outcome': 'DONE', 'ddl_statements_logged': 0, 'recorded_revision_after': '44002703f29f0c2d'}, {'tree': 'other', 'outcome': 'DONE', 'ddl_statements_logged': 98, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'branch', 'outcome': 'REFUSED SchemaTamperedError', 'ddl_statements_logged': 0, 'recorded_revision_after': 'c867454173d6227e'}, {'tree': 'other', 'outcome': 'DONE', 'ddl_statements_logged': 0, 'recorded_revision_after': 'c867454173d6227e'}]}`

### 10. 2026-10-20T23:10Z: increment 1 measurements (by hand)

- Variable: increment 1 code (versioned schema, refusal, atomic migration).
- `pytest tests_py/infrastructure/test_pg_migrations.py`: 15 passed (state
  table of refusals, first migration, newer schema refused and untouched,
  failed statement records nothing then retried, pre-versioning database
  adopted, two concurrent migrations apply once, failed state read never a
  first run).
- Audit probe D on a private cluster (`test_pg_role_probes.py`): owner role
  without superuser; `CREATE EXTENSION vector` fails; `MigrationFailedError`;
  `schema_version` and `schema_meta` both absent; `python -m mcp_server.migrate`
  exits 1 with "was not recorded". On main the same probe recorded the
  fingerprint after 58 swallowed failures (audit E13).
- Measured before writing increment 1 (scratch script, private cluster): the
  full DDL set applied on a fresh database and re-applied over itself with 0
  failing statements, so "record only when every statement succeeded" does not
  block a normal migration.
- Lock-chain rerun (entry above): `open/branch` refuses with
  `SchemaTamperedError` and logs 0 DDL; `flipflop/branch+other` 0, 98, 0, 0 with
  the branch's second open refused.
- CI job `broker-measurements` simulated locally with
  `CORTEX_TEST_DATABASE_URL=postgresql://127.0.0.1:1/unused`: the saturation
  and role-probe tests ran on private clusters only, 2 passed.

### 2026-10-20T23:22:44+00:00 DDL census

- command: `python scripts/repro_ddl_census.py`
- statements: `99`
- before/superuser/fresh: `{"failed": 0, "by_error": {}}`
- before/superuser/rerun: `{"failed": 0, "by_error": {}}`
- before/owner-noext/fresh: `{"failed": 58, "by_error": {"UndefinedTable: relation \"memories\" does not exist": 23, "UndefinedTable: relation \"wiki.pages\" does not exist": 8, "UndefinedObject: type \"vector\" does not exist": 5, "UndefinedTable: relation \"wiki.concepts\" does not exist": 3, "UndefinedTable: relation \"wiki.claim_events\" does not exist": 3, "UndefinedTable: relation \"wiki.links\" does not exist": 3, "UndefinedTable: relation \"wiki.citations\" does not exist": 3, "UndefinedTable: relation \"stage_transitions\" does not exist": 2, "UndefinedObject: type memories does not exist": 2, "UndefinedObject: type vector does not exist": 2, "InsufficientPrivilege: permission denied to create extension \"vector\"": 1, "UndefinedTable: relation \"memory_entities\" does not exist": 1, "UndefinedTable: relation \"wiki.drafts\" does not exist": 1, "UndefinedTable: relation \"wiki.page_sources\" does not exist": 1}}`
- before/owner-noext/rerun: `{"failed": 58, "by_error": {"UndefinedTable: relation \"memories\" does not exist": 23, "UndefinedTable: relation \"wiki.pages\" does not exist": 8, "UndefinedObject: type \"vector\" does not exist": 5, "UndefinedTable: relation \"wiki.concepts\" does not exist": 3, "UndefinedTable: relation \"wiki.claim_events\" does not exist": 3, "UndefinedTable: relation \"wiki.links\" does not exist": 3, "UndefinedTable: relation \"wiki.citations\" does not exist": 3, "UndefinedTable: relation \"stage_transitions\" does not exist": 2, "UndefinedObject: type memories does not exist": 2, "InsufficientPrivilege: permission denied to create extension \"vector\"": 1, "UndefinedTable: relation \"memory_entities\" does not exist": 1, "UndefinedTable: relation \"wiki.drafts\" does not exist": 1, "UndefinedTable: relation \"wiki.page_sources\" does not exist": 1, "InsufficientPrivilege: permission denied to set parameter \"pg_trgm.similarity_threshold\"": 1, "UndefinedObject: type vector does not exist": 1}}`
- before/owner-ext/fresh: `{"failed": 0, "by_error": {}}`
- before/owner-ext/rerun: `{"failed": 1, "by_error": {"InsufficientPrivilege: permission denied to set parameter \"pg_trgm.similarity_threshold\"": 1}}`
- after/superuser/fresh: `{"failed": 0, "applied": 99}`
- after/superuser/rerun: `{"failed": 0, "applied": 99}`
- after/owner-noext/fresh: `{"failed": 0, "refused_before_any_statement": "MigrationPrerequisiteError"}`
- after/owner-noext/rerun: `{"failed": 0, "refused_before_any_statement": "MigrationPrerequisiteError"}`
- after/owner-ext/fresh: `{"failed": 0, "applied": 99}`
- after/owner-ext/rerun: `{"failed": 0, "applied": 99}`

### 11. 2026-10-20T23:30Z: root causes of the failing schema statements (by hand)

- Variable: database setup (role and extensions), runner (main's loop vs
  increment 1). Raw counts: the DDL census entry above
  (`python scripts/repro_ddl_census.py`), 99 statements per run.
- Superuser owner: 0 failed, fresh and re-run, with both runners.
- Non-superuser owner, no extensions (audit probe D): 58 failed with main's
  loop. One root cause: `CREATE EXTENSION IF NOT EXISTS vector` raises
  `InsufficientPrivilege` (pgvector is not a trusted extension). The other 57
  are its consequences: the `memories` table needs the `vector` type
  (`UndefinedObject`), and every table with a foreign key to `memories` or
  `wiki.pages`, every index on them and every function over them follows
  (`UndefinedTable`). Fix: a prerequisite step before any statement creates a
  missing extension when the role can, and otherwise stops with
  `MigrationPrerequisiteError` naming the one administrator command. After:
  0 statements run, 0 failed, nothing recorded.
- Non-superuser owner, extensions created by an administrator: fresh 0
  failed, but the re-run failed 1 statement with main's loop:
  `recall_memories()` declares `SET pg_trgm.similarity_threshold`
  (pg_schema.py:1201), and a non-superuser may set that parameter only once
  pg_trgm's library has defined it in the session. On a fresh database an
  earlier trigram index creation loads the library; on a re-run every
  `CREATE INDEX IF NOT EXISTS` is skipped, the library is never loaded, the
  parameter is a placeholder, and the function statement is refused (an
  ordering dependency on session state). Fix: the prerequisite step calls
  `similarity('', '')`, which loads the library, before the statements. After:
  0 failed, fresh and re-run.
- Tests that pin it: `tests_py/infrastructure/test_pg_role_probes.py`
  (zero failures fresh and on a full re-run, superuser and non-superuser
  owner; probe D refused before any statement) and
  `tests_py/infrastructure/test_pg_migrations.py`.

### store funnel census 2026-10-21T01:22Z (`python scripts/repro_store_funnel.py`)

- Variable: the code tree (main vs working tree); no database.
- main: `{"connection_access_lines": 59, "connection_access_files": 42, "driver_importers_outside_diagnostics": 3}`
- working tree: `{"connection_access_lines": 0, "connection_access_files": 0, "driver_importers_outside_diagnostics": 0}`
- main files: handlers/anchor.py, handlers/backfill_helpers.py, handlers/calibration.py, handlers/codebase_analyze.py, handlers/codebase_analyze_helpers.py, handlers/consolidation/cascade.py, handlers/consolidation/memify.py, handlers/consolidation/memify_derive.py, handlers/consolidation/memory_dedup_exact_pass.py, handlers/consolidation/memory_domain_backfill_pass.py, handlers/consolidation/memory_reheat_pass.py, handlers/consolidation/near_dup_calibration_pass.py, handlers/consolidation/sleep.py, handlers/consolidation/wiki_backlog_pass.py, handlers/consolidation/wiki_citation_seed_pass.py, handlers/consolidation/wiki_domain_backfill_pass.py, handlers/consolidation/wiki_source_backfill_pass.py, handlers/consolidation/write_class_backfill_pass.py, handlers/curate_wiki_uncited.py, handlers/forget.py, handlers/get_grooming_health.py, handlers/get_rules.py, handlers/ingest_codebase.py, handlers/ingest_findings.py, handlers/lesson_promotion.py, handlers/predict.py, handlers/remember_helpers.py, handlers/resolve_prediction.py, handlers/wiki_compile.py, handlers/wiki_consolidate.py, handlers/wiki_curate.py, handlers/wiki_emerge.py, handlers/wiki_extract.py, handlers/wiki_migrate.py, handlers/wiki_read.py, handlers/wiki_refine.py, handlers/wiki_resolve.py, handlers/wiki_synthesize.py, handlers/wiki_view.py, handlers/wiki_write.py, hooks/agent_briefing_role.py, hooks/agent_briefing_sqlite.py
- main driver importers: hooks/agent_briefing_query.py, hooks/auto_recall.py, hooks/session_start_db.py

### 12. 2026-10-21T01:25Z: increment 2 closed (funnel)

- Measurement: the store funnel census above (`python scripts/repro_store_funnel.py`): 59 connection-reaching lines in 42 files and 3 driver importers on `main`, 0 and 0 on the branch.
- Side measurement while migrating the hook tests (scratch database, dropped after): a hook process that used the shared store without closing it waited 5 s per pool worker thread at exit, 20.7 s for `auto_recall` with 0.57 s of work; with `close_shared_store_on_exit` around `main()`, 0.44 s.
- Schema: version 2 (`backfill_log` in the DDL); a version-1 database is refused at runtime and migrated by the explicit step (`test_pg_migrations.py`, 16 passed).
- Full suite: 10246 passed, 22 skipped (`pytest tests_py`, 545 s).

### 13. 2026-10-21T02:10Z: increment 3, the frame decoder under mutation (before the field checks)

- Command: `python scripts/repro_broker_frame_fuzz.py --no-log --inputs 20000` (seed 1112) against the first decoder, which trusted the JSON type of every tagged field.
- Result: 234 escapes in 20000 inputs. Grouped over 100000 inputs: `AttributeError` from `uuid.UUID` on a non-string (1047), `decimal.InvalidOperation` (97), `OverflowError` from `timedelta` and `Decimal` on huge or infinite numbers (57), `SyntaxError` from `numpy.dtype(",f4")` (2). Each one is a connection thread dying on a stack trace instead of a clean refusal.
- Fix: every tagged field is type-checked before it is built (`broker_codec._field`); text constructors map their errors to `CodecError`; arrays accept only twelve named numeric dtypes and a shape of non-negative integers; base64 is strict. The four reproducers are committed under `fuzz/corpus/fuzz_broker_frame/repro-*` and replayed by `tests_py/fuzz`.
- After: 0 escapes in 200000 inputs (seed 1112) and in 400000 inputs for each of seeds 1 to 5; the entry below is the logged run.

### broker frame fuzz 2026-10-21T01:32Z (`python scripts/repro_broker_frame_fuzz.py --seed 1112`)

- `{"inputs": 200000, "refused": 163366, "accepted": 36634, "escapes": 0, "seconds": 2.3, "first_escape": null}`

### 14. 2026-10-21T02:40Z: increment 3 closed (broker process)

- Broker tests: 67 unit (codec, frames, queues, server and client over sockets) plus 4 endpoint and 5 real-process tests on the test database, all passing; the pipe tests run in the `test-windows` job only (3 skipped here, on macOS).
- Full suite: 10326 passed, 25 skipped (`pytest tests_py`, 517 s).

### 2026-10-21T01:48:28+00:00 bounds

- head: `fa8165b06ce6c14d8d77558b32d5081be93caf02` (dirty)
- command: `python scripts/repro_connection_broker.py bounds`
- pytest exit code: 0 (2 passed in 0.68s)
- measured: `{"batch": {"application_name": "cortex-store-batch", "idle_in_transaction_session_timeout": "30s", "lock_timeout": "30min", "statement_timeout": "30min"}, "direct": {"application_name": "cortex-store-direct", "idle_in_transaction_session_timeout": "30s", "lock_timeout": "30s", "statement_timeout": "30s"}, "interactive": {"application_name": "cortex-store-interactive", "idle_in_transaction_session_timeout": "30s", "lock_timeout": "30s", "statement_timeout": "30s"}}`

### 2026-10-21T01:49:34+00:00 priority

- head: `fa8165b06ce6c14d8d77558b32d5081be93caf02` (dirty)
- command: `python scripts/repro_connection_broker.py priority`
- pytest exit code: 0 (1 passed in 65.05s (0:01:05))
- measured: `{"background": {"heavy_class": "background", "heavy_pages_served": 54, "max_ms": 357.3, "p50_ms": 1.5, "p95_ms": 91.2, "point_reads": 443}, "brokers": 1, "single_class": {"heavy_class": "interactive", "heavy_pages_served": 66, "max_ms": 7024.7, "p50_ms": 5968.4, "p95_ms": 4912.1, "point_reads": 2}}`

- Note on the entry above: its `single_class.p95_ms` (4912.1, below the p50) came from a wrong percentile index on 2 samples (`int(0.95 * (n - 1))` picks the first). Fixed to the nearest-rank index; the next entry is the corrected run.

### 2026-10-21T01:50:57+00:00 priority

- head: `fa8165b06ce6c14d8d77558b32d5081be93caf02` (dirty)
- command: `python scripts/repro_connection_broker.py priority`
- pytest exit code: 0 (1 passed in 70.58s (0:01:10))
- measured: `{"background": {"heavy_class": "background", "heavy_pages_served": 54, "max_ms": 225.4, "p50_ms": 1.6, "p95_ms": 107.6, "point_reads": 329}, "brokers": 1, "single_class": {"heavy_class": "interactive", "heavy_pages_served": 82, "max_ms": 9165.0, "p50_ms": 8452.2, "p95_ms": 9165.0, "point_reads": 2}}`

### 15. 2026-10-21T03:30Z: increment 4 closed (request classes, session bounds, A5)

- A5 and probe A: the `priority` and `bounds` entries above. The first full-suite run after naming store connections failed one test: the saturation baseline identified its children by `PGAPPNAME`, which the store now overrides. Store connections are named `cortex-store-<pool>-<pid>` and the baseline maps backends to children by PID; it reproduces as before (4 of 8 refused or timed out, blocked children holding 3 to 4 connections).
- Full suite: 10329 passed, 26 skipped (`pytest tests_py`, 524 s).

### census entry withdrawn before commit

- The first logged `census` run recorded each step's output tail, which quoted a path under the developer's home directory (a SessionStart banner naming another memory tool's database). The entry was removed before any commit and the measurement now records seconds and exit code per step only; the next entry is the re-run.

### 2026-10-21T02:46:54+00:00 census

- head: `36b8237137e560b23da9fbca37ae3f9ca950fb11` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 22.16s)
- measured: `{"cold_hook": [1.12, 0], "consolidate": [5.33, 0], "idle_in_transaction_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["26471"], "peak_cortex_backends": 6, "remember": [7.87, 0], "samples": 284, "seeded_memories": 5000, "warm_hooks": [[0.44, 0], [0.51, 0], [0.49, 0]]}`

### 16. 2026-10-21T05:40Z: increment 5, the suite through the broker

- Variable: the store a test process gets (`CORTEX_TEST_BROKER_MODE=1`: a real broker per Cortex root, started by the first store user through the production launcher; default: the in-process store the broker runs).
- First broker-mode run: 40 failed, 40 errors, 10185 passed, 122 skipped. Grouped by error line (a failing test and its teardown error can both count): 56 `AttributeError: _conn` and 10 `AttributeError: acquire_interactive` (tests reaching the store's own connection or pools), 8 `TypeError` from tests re-instantiating the store's class, 3 hook tests failed on `AF_UNIX path too long` (a hook test's own `CORTEX_CLAUDE_DIR` under `/var/folders` put the socket past `sun_path`), 1 used the private `store._now_iso()` (production, `core/write_post_store.py`), 1 asserted the test-database drop statement, 1 asserted a clean process table mid-session, 1 captured a log line emitted where the operation runs; 96 further tests skipped themselves because the store was not a `PgMemoryStore`.
- Fixes: production, `_now_iso` replaced by the stores' own expression, socket paths that do not fit move to an owner-only per-user runtime directory, built-in exception types cross back as themselves, start-up failures reach the client with their reason. Tests, counted: 24 modules and 1 test marked `in_process_store` (they test the store itself), 8 files read rows through `tests_py/_db_peek.store_connection`, 1 test skipped in broker mode (mid-session process table).
- Final: default 10336 passed, 27 skipped; broker mode 10335 passed, 28 skipped (the 27 plus that one).

### least-privilege suite 2026-10-21T04:01Z (`python scripts/repro_least_privilege_suite.py`)

- role `cortex_lp` (rolsuper, rolcreatedb, rolcreaterole) = (False, True, False)
- pytest tests_py/infrastructure/test_pg_migrations.py tests_py/infrastructure/test_pg_recall_ddl_upgrade.py: exit 1, `2 failed, 16 passed in 2.71s`
- FAILED tests_py/infrastructure/test_pg_recall_ddl_upgrade.py::test_migrating_replaces_the_old_recall_function
- FAILED tests_py/infrastructure/test_pg_recall_ddl_upgrade.py::test_migrating_installs_the_tie_keeping_pools

### least-privilege suite 2026-10-21T04:04Z (`python scripts/repro_least_privilege_suite.py`)

- role `cortex_lp` (rolsuper, rolcreatedb, rolcreaterole) = (False, True, False)
- pytest tests_py/infrastructure/test_pg_migrations.py tests_py/infrastructure/test_pg_recall_ddl_upgrade.py: exit 0, `18 passed in 2.86s`

### least-privilege suite 2026-10-21T04:13Z (`python scripts/repro_least_privilege_suite.py`)

- role `cortex_lp` (rolsuper, rolcreatedb, rolcreaterole) = (False, True, False)
- pytest tests_py: exit 1, `4 failed, 10335 passed, 25 skipped, 2 warnings, 417 subtests passed in 482.89s (0:08:02)`
- FAILED tests_py/infrastructure/test_pg_recall_indexed_pools.py::test_trigram_between_point_one_and_session_default
- FAILED tests_py/infrastructure/test_pg_recall_pool_sql.py::test_each_pool_filters_exact_heat_before_limit_and_exposes_index_operator
- FAILED tests_py/scripts/test_check_ci_gate_complete.py::RepositoryWorkflowIsGated::test_runtime_policy_matches_live_workflow
- FAILED tests_py/scripts/test_check_ci_gate_results.py::ExecutableContract::test_docs_only_cli_succeeds

### least-privilege suite 2026-10-21T04:14Z (`python scripts/repro_least_privilege_suite.py`)

- role `cortex_lp` (rolsuper, rolcreatedb, rolcreaterole) = (False, True, False)
- pytest tests_py/infrastructure/test_pg_recall_indexed_pools.py tests_py/infrastructure/test_pg_recall_pool_sql.py tests_py/infrastructure/test_pg_migrations.py tests_py/infrastructure/test_pg_recall_ddl_upgrade.py: exit 1, `1 failed, 47 passed in 4.07s`
- FAILED tests_py/infrastructure/test_pg_recall_pool_sql.py::test_signature_return_shape_and_fusion_unchanged

### 2026-10-21T04:16:05+00:00 saturation

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py saturation`
- pytest exit code: 1 (1 failed in 45.68s)
- measured: `{"64": {"backend_owner_pids": 1, "children": 64, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_cortex_backends": 16, "peak_waiting_on_the_alter": 10}, "8": {"backend_owner_pids": 1, "children": 8, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_cortex_backends": 11, "peak_waiting_on_the_alter": 8}}`

### 17. 2026-10-21T07:10Z: A1 found a pool race (before the fix)

- Command: `python scripts/repro_connection_broker.py saturation` (the `saturation` entry above, exit 1), then the same run with the peak broken down by pool name.
- Result: zero refused and zero failed children, one owner PID (the broker), but 11 to 13 Cortex backends with 8 children and 16 to 17 with 64, above P + 1 = 12; the breakdown showed 12 to 16 `cortex-store-interactive` connections from a pool whose maximum is 8.
- Cause: `PgSchemaMixin.interactive_pool` and `batch_pool` opened their pool lazily without a lock; the broker's 10 worker threads raced the first use and each opened its own pool (2 connections each at `min_size`), leaving the extra pools open. The same race exists in any multi-threaded process using the store (the MCP server's tool threads).
- Fix: double-checked creation under a per-store lock (`pg_store_schema.py`); `tests_py/infrastructure/test_pg_pool_once.py` fails without it (2 of 2) and passes with it. The next entry is the re-run.

### 2026-10-21T04:19:16+00:00 saturation

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py saturation`
- pytest exit code: 1 (1 failed in 45.20s)
- measured: `{"64": {"backend_owner_pids": 1, "children": 64, "failed": 6, "failed_before_release": 6, "max_connections": 20, "outcomes": ["BrokerRemoteError: PoolTimeout: couldn't get a connection after 5.00 sec"], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}, "8": {"backend_owner_pids": 1, "children": 8, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}}`

### 18. 2026-10-21T07:25Z: A1 after the pool lock (one more design fix)

- Re-run (entry above, exit 1): backends now bounded (9 at peak: 8 interactive and the persistent one, one PID), 8 children all served, but 6 of 64 failed with `PoolTimeout: couldn't get a connection after 5.00 sec`.
- Cause: the scheduler let interactive requests use all 10 workers while the interactive pool has 8 connections; with 8 requests blocked behind the `ALTER`, workers 9 and 10 waited on the pool and timed out after `POOL_INTERACTIVE_TIMEOUT_S` (a request was admitted with no connection for it).
- Fix: each class gets as many slots as its pool has connections (`SchedulerPolicy(interactive_slots, background_slots)`, set from `POOL_INTERACTIVE_MAX` and `POOL_BATCH_MAX`); a request waits in the broker's queue, bounded by its own deadline, never in the pool. The next entry is the re-run.

### 2026-10-21T04:21:14+00:00 saturation

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py saturation`
- pytest exit code: 0 (1 passed in 45.49s)
- measured: `{"64": {"backend_owner_pids": 1, "children": 64, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}, "8": {"backend_owner_pids": 1, "children": 8, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}}`

### 2026-10-21T04:22:26+00:00 priority

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py priority`
- pytest exit code: 0 (1 passed in 60.92s (0:01:00))
- measured: `{"background": {"heavy_class": "background", "heavy_pages_served": 55, "max_ms": 412.2, "p50_ms": 2.0, "p95_ms": 110.0, "point_reads": 255}, "brokers": 1, "single_class": {"heavy_class": "interactive", "heavy_pages_served": 63, "max_ms": 9899.9, "p50_ms": 9899.9, "p95_ms": 9899.9, "point_reads": 1}}`

### 2026-10-21T04:23:40+00:00 latency

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py latency`
- pytest exit code: 1 (1 failed in 52.23s)
- measured: `{}`

### 2026-10-21T04:26:06+00:00 latency

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py latency`
- pytest exit code: 1 (1 failed in 42.76s)
- measured: `{}`

### 2026-10-21T04:30:18+00:00 latency

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py latency`
- pytest exit code: 1 (1 failed in 183.22s (0:03:03))
- measured: `{"broker": {"p50_ms": 266.26, "p95_ms": 349.04}, "embedding_mode": "neural", "in_process": {"p50_ms": 261.99, "p95_ms": 355.84}, "memories": 3000, "queries": 150, "ranking_mismatches": 6}`

### 2026-10-21T04:34:35+00:00 latency

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py latency`
- pytest exit code: 1 (1 failed in 211.09s (0:03:31))
- measured: `{"broker": {"p50_ms": 221.27, "p95_ms": 275.38}, "embedding_mode": "neural", "in_process": {"p50_ms": 214.1, "p95_ms": 267.33}, "memories": 3000, "queries": 150, "time_unstable_queries": 15, "transport_mismatches": 5}`

### 2026-10-21T04:40:35+00:00 latency

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py latency`
- pytest exit code: 0 (1 passed in 288.28s (0:04:48))
- measured: `{"broker": {"p50_ms": 219.59, "p95_ms": 276.33}, "embedding_mode": "neural", "in_process": {"p50_ms": 215.54, "p95_ms": 262.3}, "memories": 3000, "parity": {"broker": {"mismatched": 3, "time_unstable": 6}, "control_second_in_process_store": {"mismatched": 3, "time_unstable": 9}}, "queries": 150}`

### 19. 2026-10-21T08:05Z: A1, A5 and A6 after the two fixes

- A1 (`saturation` entry above, exit 0): with 8 and with 64 clients, 9 Cortex backends at peak (8 interactive, 1 persistent), one PID (the broker), 8 reads waiting on the `ALTER`, 0 refused, 0 failed; every client finished once the reader ended its transaction. Baseline on main: 4 or 5 of 8 refused, 2 to 4 connections per blocked client.
- A5 re-run with per-class slots (`priority` entry above): point reads p50 2.0 ms, p95 110.0 ms under a saturated background queue; 1 read in 8 s, 9900 ms, when the same load shares one class.
- A6 (`latency` entries above). The first two runs failed on the measurement, not on the broker: a wrong row key, then a parity check that compared two `recall_memories` calls made at different instants after recall had written heat. The final design checks parity before any write, brackets each call between two in-process calls, and adds a control arm (a second in-process store): broker 3 mismatches of 150, control 3 of 150, so the broker adds none beyond the connection-dependent order of close scores. Latency on the benchmark's recall path (3000 memories, 150 queries, neural embeddings, rerank off): in process p50 215.5 ms, p95 262.3 ms; through the broker p50 219.6 ms, p95 276.3 ms (+1.9 % and +5.3 %). Regression budget set from this first measurement: broker p95 within 10 % of in-process p95.

### least-privilege suite 2026-10-21T05:06Z (`python scripts/repro_least_privilege_suite.py`)

- role `cortex_lp` (rolsuper, rolcreatedb, rolcreaterole) = (False, True, False)
- pytest tests_py: exit 0, `10342 passed, 27 skipped, 2 warnings, 426 subtests passed in 475.19s (0:07:55)`

### 20. 2026-10-21T08:50Z: increment 6 closed

- Default suite (store in process): 10340 passed, 29 skipped. Broker mode: 10339 passed, 30 skipped. As a role with LOGIN and CREATEDB only (`least-privilege suite` entry above): 10342 passed, 27 skipped. Before the schema-3 fix the same non-superuser run failed `test_pg_recall_ddl_upgrade.py` 2 of 2 (audit E14), reproduced first on two files (entry above it).
- Measurements of this increment: entries 17 to 19 (A1, A5, A6), probe B in `tests_py/infrastructure/test_pg_least_privilege_probe_b.py`.

### 2026-10-21T05:08:16+00:00 census

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 19.20s)
- measured: `{"cold_hook": [1.26, 0], "consolidate": [4.22, 0], "idle_in_transaction_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["88778"], "peak_cortex_backends": 6, "remember": [6.5, 0], "samples": 232, "seeded_memories": 5000, "shared_ddl_during_session": 0, "warm_hooks": [[0.42, 0], [0.52, 0], [0.38, 0]]}`

### 2026-10-21T05:08:48+00:00 census

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 19.21s)
- measured: `{"cold_hook": [1.13, 0], "consolidate": [4.13, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["91764"], "peak_cortex_backends": 6, "remember": [6.69, 0], "samples": 230, "seeded_memories": 5000, "shared_ddl_during_session": 0, "warm_hooks": [[0.41, 0], [0.52, 0], [0.37, 0]]}`

### 2026-10-21T05:12:23+00:00 census

- head: `b02a19194836ebe915593ed71042ec52c4e843e8` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 19.15s)
- measured: `{"cold_hook": [1.08, 0], "consolidate": [4.21, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["11692"], "peak_cortex_backends": 6, "remember": [6.83, 0], "samples": 231, "seeded_memories": 5000, "shared_ddl_during_session": 0, "warm_hooks": [[0.39, 0], [0.35, 0], [0.36, 0]]}`

### least-privilege suite 2026-10-21T05:47Z (`python scripts/repro_least_privilege_suite.py`)

- role `cortex_lp` (rolsuper, rolcreatedb, rolcreaterole) = (False, True, False)
- pytest tests_py: exit 0, `10344 passed, 27 skipped, 2 warnings, 426 subtests passed in 435.00s (0:07:14)`

### 21. 2026-10-21T09:40Z: final suites of increment 6

- Default suite (store in process): 10342 passed, 29 skipped. Broker mode: 10341 passed, 30 skipped. As a role without SUPERUSER (`least-privilege suite` entry above, 05:47Z): 10344 passed, 27 skipped. Each run collects 10371 tests, 2 more than at entry 20 (10369): tests added after it, in the same increment.
- A first broker-mode run of this round had 12 errors, all at the setup of `tests_py/benchmarks/test_codebase_alteration.py` and `test_spell_alteration.py`: I had just deleted this checkout's `sets/` install (the launcher's, committed by mistake in increment 5 and taken out of it), so the broker's launcher refused to start and began reinstalling, as `broker.out` reported. Rerun on the reinstalled set: 0 errors (above). The client reported the refusal with the broker's own output, which is the behaviour increment 5 added.

### 2026-10-21T06:07:43+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (clean)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed in 19.91s)
- measured: `{"cold_hook": [1.35, 0], "consolidate": [3.74, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "other_client_backends": [""], "owner_is_broker": true, "owners": ["81779"], "peak_cortex_backends": 6, "remember": [7.59, 0], "samples": 243, "seeded_memories": 5000, "shared_ddl_during_session": 0, "warm_hooks": [[0.59, 0], [0.37, 0], [0.38, 0]]}`

### 2026-10-21T06:08:29+00:00 saturation

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py saturation`
- pytest exit code: 0 (1 passed in 45.10s)
- measured: `{"64": {"backend_owner_pids": 1, "children": 64, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}, "8": {"backend_owner_pids": 1, "children": 8, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}}`

### 2026-10-21T06:09:28+00:00 priority

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py priority`
- pytest exit code: 0 (1 passed in 57.47s)
- measured: `{"background": {"heavy_class": "background", "heavy_pages_served": 60, "max_ms": 553.7, "p50_ms": 4.5, "p95_ms": 104.0, "point_reads": 231}, "brokers": 1, "single_class": {"heavy_class": "interactive", "heavy_pages_served": 72, "max_ms": 10993.2, "p50_ms": 10993.2, "p95_ms": 10993.2, "point_reads": 1}}`

### 2026-10-21T06:11:46+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 19.42s)
- measured: `{"cold_hook": [1.24, 0], "consolidate": [4.21, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["4311"], "peak_cortex_backends": 6, "remember": [6.83, 0], "samples": 237, "seeded_memories": 5000, "shared_ddl_during_session": 0, "warm_hooks": [[0.43, 0], [0.38, 0], [0.54, 0]]}`

### 2026-10-21T06:12:06+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed in 19.35s)
- measured: `{"cold_hook": [1.14, 0], "consolidate": [4.22, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 1, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["6154"], "peak_cortex_backends": 6, "remember": [7.01, 0], "samples": 238, "seeded_memories": 5000, "shared_ddl_during_session": 0, "warm_hooks": [[0.35, 0], [0.41, 0], [0.47, 0]]}`

### 2026-10-21T06:12:26+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 18.63s)
- measured: `{"cold_hook": [1.08, 0], "consolidate": [4.25, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["8224"], "peak_cortex_backends": 6, "remember": [6.38, 0], "samples": 228, "seeded_memories": 5000, "shared_ddl_during_session": 0, "warm_hooks": [[0.45, 0], [0.49, 0], [0.37, 0]]}`

### 2026-10-21T06:13:43+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed in 19.07s)
- measured: `{}`

### 2026-10-21T06:13:59+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed, 1 error in 14.15s)
- measured: `{}`

### 2026-10-21T06:14:15+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 14.71s)
- measured: `{"cold_hook": [1.01, 0], "consolidate": [0.35, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 1, "other_client_backends": [], "owner_is_broker": true, "owners": ["18941"], "peak_cortex_backends": 6, "remember": [5.77, 0], "samples": 149, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.49, 0], [0.46, 0], [0.38, 0]]}`

### 2026-10-21T06:14:30+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 14.43s)
- measured: `{"cold_hook": [1.04, 0], "consolidate": [0.47, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["19924"], "peak_cortex_backends": 6, "remember": [5.86, 0], "samples": 153, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.44, 0], [0.49, 0], [0.45, 0]]}`

### 2026-10-21T06:14:46+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 14.34s)
- measured: `{"cold_hook": [1.01, 0], "consolidate": [0.5, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 1, "other_client_backends": [], "owner_is_broker": true, "owners": ["21675"], "peak_cortex_backends": 6, "remember": [5.46, 0], "samples": 143, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.38, 0], [0.39, 0], [0.48, 0]]}`

### 2026-10-21T06:15:00+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 13.74s)
- measured: `{"cold_hook": [1.11, 0], "consolidate": [0.53, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["22649"], "peak_cortex_backends": 6, "remember": [5.12, 0], "samples": 140, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.46, 0], [0.35, 0], [0.36, 0]]}`

### 2026-10-21T06:15:15+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 13.72s)
- measured: `{"cold_hook": [1.0, 0], "consolidate": [0.34, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["24402"], "peak_cortex_backends": 6, "remember": [5.06, 0], "samples": 135, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.39, 0], [0.36, 0], [0.48, 0]]}`

### 2026-10-21T06:15:30+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 13.89s)
- measured: `{"cold_hook": [1.11, 0], "consolidate": [0.42, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 1, "other_client_backends": [], "owner_is_broker": true, "owners": ["25374"], "peak_cortex_backends": 6, "remember": [4.75, 0], "samples": 133, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.47, 0], [0.49, 0], [0.35, 0]]}`

### 2026-10-21T06:15:45+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 13.57s)
- measured: `{"cold_hook": [0.97, 0], "consolidate": [0.34, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["27110"], "peak_cortex_backends": 6, "remember": [5.21, 0], "samples": 134, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.42, 0], [0.36, 0], [0.37, 0]]}`

### 2026-10-21T06:15:59+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 13.58s)
- measured: `{"cold_hook": [1.02, 0], "consolidate": [0.37, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["28091"], "peak_cortex_backends": 6, "remember": [4.79, 0], "samples": 132, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.41, 0], [0.49, 0], [0.46, 0]]}`

### 2026-10-21T06:17:10+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed, 1 error in 14.03s)
- measured: `{}`

### 2026-10-21T06:17:41+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed, 1 error in 13.81s)
- measured: `{"cold_hook": [1.14, 0], "consolidate": [0.34, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 1, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["38271"], "peak_cortex_backends": 6, "remember": [5.12, 0], "samples": 136, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [["idle_in_transaction", 38412, "cortex-store-interactive-38271", "idle in transaction", 0, 0, "SET LOCAL jit = off"]], "warm_hooks": [[0.39, 0], [0.37, 0], [0.48, 0]]}`

### 2026-10-21T06:21:32+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed in 19.13s)
- measured: `{"cold_hook": [1.06, 0], "consolidate": [4.28, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 1, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["59600"], "peak_cortex_backends": 6, "remember": [6.66, 0], "samples": 229, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [["idle_in_transaction", 59615, "cortex-store-interactive-59600", "idle in transaction", 0, 0, "SET LOCAL jit = off"]], "warm_hooks": [[0.47, 0], [0.39, 0], [0.37, 0]]}`

### 2026-10-21T06:21:47+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 14.13s)
- measured: `{"cold_hook": [1.05, 0], "consolidate": [0.4, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["61408"], "peak_cortex_backends": 6, "remember": [5.58, 0], "samples": 142, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.42, 0], [0.37, 0], [0.36, 0]]}`

### 2026-10-21T06:22:02+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 13.85s)
- measured: `{"cold_hook": [1.02, 0], "consolidate": [0.53, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["63175"], "peak_cortex_backends": 6, "remember": [5.2, 0], "samples": 140, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.4, 0], [0.49, 0], [0.38, 0]]}`

### 2026-10-21T06:22:17+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 14.22s)
- measured: `{"cold_hook": [1.04, 0], "consolidate": [0.38, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["64166"], "peak_cortex_backends": 6, "remember": [5.67, 0], "samples": 146, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.42, 0], [0.39, 0], [0.36, 0]]}`

### 2026-10-21T06:22:32+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 passed, 1 error in 13.70s)
- measured: `{"cold_hook": [1.0, 0], "consolidate": [0.5, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["65928"], "peak_cortex_backends": 6, "remember": [5.02, 0], "samples": 134, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.42, 0], [0.48, 0], [0.37, 0]]}`

### 2026-10-21T06:22:47+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 1 (1 failed, 1 error in 14.15s)
- measured: `{"cold_hook": [1.13, 0], "consolidate": [0.4, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_samples": 1, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["66892"], "peak_cortex_backends": 6, "remember": [5.56, 0], "samples": 144, "seeded_memories": 5000, "shared_ddl_during_session": 0, "unexpected_samples": [["idle_in_transaction", 66907, "cortex-store-interactive-66892", "idle in transaction", 7, 0, "SELECT m.id, m.content, m.tags, m.domain, m.is_global, m.directory_context, m.cr"]], "warm_hooks": [[0.42, 0], [0.39, 0], [0.36, 0]]}`

### 2026-10-21T06:32:38+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 22.13s)
- measured: `{"cold_hook": [1.2, 0], "consolidate": [4.1, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["20678"], "peak_cortex_backends": 6, "remember": [5.82, 0], "samples": 283, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.95, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.44, 0], [0.43, 0], [0.42, 0]]}`

### 2026-10-21T06:33:00+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 20.93s)
- measured: `{"cold_hook": [0.99, 0], "consolidate": [4.08, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 1, "max_idle_ms": 0, "max_idle_transaction_age_ms": 8, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["23242"], "peak_cortex_backends": 6, "remember": [5.25, 0], "samples": 261, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.39, "shared_ddl_during_session": 0, "unexpected_samples": [["idle_in_transaction", 23248, "cortex-store-interactive-23242", "idle in transaction", 8, 0, "SELECT m.id, m.content, m.tags, effective_heat(m, NOW()) AS effective_heat, m.cr"]], "warm_hooks": [[0.39, 0], [0.51, 0], [0.44, 0]]}`

### 2026-10-21T06:33:22+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 21.16s)
- measured: `{"cold_hook": [1.02, 0], "consolidate": [3.97, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["25026"], "peak_cortex_backends": 6, "remember": [5.08, 0], "samples": 263, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.97, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.4, 0], [0.51, 0], [0.41, 0]]}`

### 2026-10-21T06:33:44+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 20.92s)
- measured: `{"cold_hook": [1.0, 0], "consolidate": [3.63, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["26825"], "peak_cortex_backends": 6, "remember": [5.21, 0], "samples": 263, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.95, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.45, 0], [0.57, 0], [0.45, 0]]}`

### 2026-10-21T06:34:05+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 20.12s)
- measured: `{"cold_hook": [0.99, 0], "consolidate": [3.67, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["28612"], "peak_cortex_backends": 6, "remember": [5.03, 0], "samples": 250, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.38, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.38, 0], [0.4, 0], [0.49, 0]]}`

### 2026-10-21T06:34:27+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 21.21s)
- measured: `{"cold_hook": [1.09, 0], "consolidate": [3.97, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["30395"], "peak_cortex_backends": 6, "remember": [5.16, 0], "samples": 270, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.96, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.42, 0], [0.48, 0], [0.39, 0]]}`

### 2026-10-21T06:34:49+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 21.12s)
- measured: `{"cold_hook": [1.23, 0], "consolidate": [3.86, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["32976"], "peak_cortex_backends": 6, "remember": [5.26, 0], "samples": 267, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.97, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.37, 0], [0.35, 0], [0.34, 0]]}`

### 2026-10-21T06:35:11+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 21.30s)
- measured: `{"cold_hook": [1.02, 0], "consolidate": [4.01, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["34792"], "peak_cortex_backends": 6, "remember": [5.39, 0], "samples": 269, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.97, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.39, 0], [0.37, 0], [0.36, 0]]}`

### 2026-10-21T06:35:32+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 20.14s)
- measured: `{"cold_hook": [1.04, 0], "consolidate": [3.6, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["36611"], "peak_cortex_backends": 6, "remember": [5.18, 0], "samples": 248, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.39, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.39, 0], [0.36, 0], [0.35, 0]]}`

### 2026-10-21T06:35:53+00:00 census

- head: `96a989584750cb1cec96fdf268b12971a1f8333f` (dirty)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 19.88s)
- measured: `{"cold_hook": [1.01, 0], "consolidate": [3.53, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["38384"], "peak_cortex_backends": 6, "remember": [4.97, 0], "samples": 245, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.41, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.44, 0], [0.49, 0], [0.37, 0]]}`

### 22. 2026-10-21T06:40Z: A4's criterion, the session's detached jobs, the migration connection named

- On the clean head `96a98958` the census failed once (06:07Z entry): one client backend with an empty `application_name`, outside the broker's names. That instrument recorded names only, so the backend has no attribution. It has not appeared in any of the 28 runs recorded since.
- The broker's migration and grant connections carried no `application_name` (`pg_migrations.apply_schema`, `pg_roles.grant_runtime`). They are now `cortex-migrate-<pid>` (`pg_session_bounds.migration_name`; `test_the_migration_connection_is_named_for_its_process` fails without the change), and the census counts them as the broker's. `migration_samples` is 0 in every run since: the step is shorter than the 50 ms period. The sampler now records pid, state, transaction age, idle time and query head of any unattributed backend, so a recurrence names itself.
- A4 as worded ("no `idle in transaction` sample") failed in 4 of the runs between 06:12Z and 06:23Z, one sample each; 3 of them ran with the detailed sampler (06:17Z, 06:21Z, 06:22Z entries). Every detailed sample was a broker interactive connection, transaction 0 to 7 ms old, idle 0 ms, last statement `SET LOCAL jit = off` or the recall `SELECT`: a transaction inside one request, caught between two of its statements. The earlier zero counts were the 50 ms period missing these gaps. Criterion now asserted, for the owner to confirm: every `idle in transaction` sample is on a broker store connection (a client never holds a transaction), and none belongs to a transaction older than `deadlock_timeout`'s default, 1 s (PostgreSQL 17 documentation, 19.12; the incident's transaction lasted about 2 h, a whole consolidation pass). The raw count stays in the record.
- Every census session starts a detached consolidation cycle (the groomer coordinator's `runs.log` says `started` for each run) and, while its working directory was the census root, a code reanalysis by the user's installed `ai-architect-mcp-codebase` over the cluster's data directory (1497 files). Most runs from 06:13Z to 06:23Z failed at teardown because those jobs outlived the test (two failed earlier: the first detailed sampler wrote PostgreSQL `numeric` ages, which JSON cannot hold, fixed by a cast); their `consolidate` step took 0.34 s, the cycle holding the single-flight lock. The census now waits, sampler on, for every process carrying the test session's token (the private cluster excepted), and the session's working directory is a one-file project.
- After these changes, 10 runs (06:32Z to 06:36Z): 10 passed; one owner PID each, the broker's; 0 other client backends; `idle in transaction` samples 0 in 9 runs and 1 in one (broker interactive connection, transaction 8 ms old); 0 DDL on shared relations; `consolidate` 3.5 to 4.1 s; the detached cycle started in each run and ended inside the sampled window, before the wait began (only the broker was waited for, 3.4 to 4.0 s, its 3 s idle exit).
- Found on the way, older than this branch, not changed here: `consolidate_background` writes `~/.claude/methodology/.last_consolidate` through `Path.home()` whatever `CORTEX_CLAUDE_DIR` says (`mcp_server/hooks/consolidate_background.py:36`), so the census runs rewrote that stamp in the user's home (06:18:09Z); every test on a fresh private-cluster URL leaves one directory in `~/.cache/cortex/groomer-coordinator` (618 there, 74 dated today).
- Craftsmanship: five functions committed in `96a98958` exceeded the 40-line cap (`pg_roles.provision`, the suite script's `main`, probe B, the A1 scenario, the A6 test); the gate had run while those files were untracked. Split in this change, behaviour unchanged.

### least-privilege suite 2026-10-21T07:01Z (`python scripts/repro_least_privilege_suite.py`)

- role `cortex_lp` (rolsuper, rolcreatedb, rolcreaterole) = (False, True, False)
- pytest tests_py: exit 0, `10345 passed, 27 skipped, 2 warnings, 426 subtests passed in 439.07s (0:07:19)`

### 23. 2026-10-21T07:01Z: suites after entry 22

- Suites after the changes of entry 22: default (store in process) 10343 passed, 29 skipped; broker mode 10342 passed, 30 skipped; as a role without SUPERUSER 10345 passed, 27 skipped (entry above). One test more than entry 21 in each: the migration connection's name.

### 2026-10-21T07:15:23+00:00 census

- head: `069403a475cbb734df4699582b0e07b5ae3a2230` (clean)
- command: `python scripts/repro_connection_broker.py census`
- pytest exit code: 0 (1 passed in 37.90s)
- measured: `{"cold_hook": [2.76, 0], "consolidate": [6.29, 0], "ddl_logged_by_the_setup": 103, "idle_in_transaction_outside_broker": 0, "idle_in_transaction_samples": 0, "max_idle_ms": 0, "max_idle_transaction_age_ms": 0, "migration_samples": 0, "other_client_backends": [], "owner_is_broker": true, "owners": ["69303"], "peak_cortex_backends": 6, "remember": [15.47, 0], "samples": 543, "seeded_memories": 5000, "session_jobs_seen": ["mcp_server.hooks.store_broker"], "session_jobs_waited_seconds": 3.46, "shared_ddl_during_session": 0, "unexpected_samples": [], "warm_hooks": [[0.5, 0], [0.51, 0], [0.56, 0]]}`

### 2026-10-21T07:16:11+00:00 saturation

- head: `069403a475cbb734df4699582b0e07b5ae3a2230` (dirty)
- command: `python scripts/repro_connection_broker.py saturation`
- pytest exit code: 0 (1 passed in 46.55s)
- measured: `{"64": {"backend_owner_pids": 1, "children": 64, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}, "8": {"backend_owner_pids": 1, "children": 8, "failed": 0, "failed_before_release": 0, "max_connections": 20, "outcomes": [], "peak_by_pool": {"direct": 1, "interactive": 8}, "peak_cortex_backends": 9, "peak_waiting_on_the_alter": 8}}`

### 2026-10-21T07:17:22+00:00 priority

- head: `069403a475cbb734df4699582b0e07b5ae3a2230` (dirty)
- command: `python scripts/repro_connection_broker.py priority`
- pytest exit code: 0 (1 passed, 1 warning in 69.73s (0:01:09))
- measured: `{"background": {"heavy_class": "background", "heavy_pages_served": 52, "max_ms": 238.0, "p50_ms": 1.5, "p95_ms": 88.0, "point_reads": 383}, "brokers": 1, "single_class": {"heavy_class": "interactive", "heavy_pages_served": 95, "max_ms": 27087.8, "p50_ms": 27087.8, "p95_ms": 27087.8, "point_reads": 1}}`

### 2026-10-21T07:22:24+00:00 latency

- head: `069403a475cbb734df4699582b0e07b5ae3a2230` (dirty)
- command: `python scripts/repro_connection_broker.py latency`
- pytest exit code: 1 (+++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++)
- measured: `{}`

### 2026-10-21T07:30:05+00:00 latency

- head: `e76ebea2083d7ce93e907ef50474647745ee6f23` (clean)
- command: `python scripts/repro_connection_broker.py latency`
- pytest exit code: 0 (1 passed in 394.02s (0:06:34))
- measured: `{"broker": {"p50_ms": 294.79, "p95_ms": 600.17}, "embedding_mode": "neural", "in_process": {"p50_ms": 289.38, "p95_ms": 493.54}, "memories": 3000, "parity": {"broker": {"mismatched": 1, "time_unstable": 7}, "control_second_in_process_store": {"mismatched": 3, "time_unstable": 8}}, "queries": 150}`

### 24. 2026-10-21T07:31Z: the acceptance measurements on the final head, under load

- Heads: `069403a4` for census, saturation and priority (07:1xZ entries above, the log the only dirty file), `e76ebea2` (clean) for latency. The machine carried a load average of 16 to 19 from processes outside this work (`uptime` at 07:22Z: 19.4, 16.0, 11.3; at 07:30Z: 17.3, 15.1, 12.6); the load during entries 17 to 21 was not recorded.
- Census (A2, A3, A4): passed; one owner PID, the broker's; 0 other backends; 0 `idle in transaction` samples; 0 shared DDL. Slower under load (`remember` 15.5 s, `consolidate` 6.3 s).
- A1 (`saturation`): passed; 9 Cortex backends at peak with 8 and with 64 clients, one PID, 0 failed.
- A5 (`priority`): passed; point reads under a saturated background queue p50 1.5 ms, p95 88.0 ms; 1 read in 8 s (27088 ms) when the same load shares one class.
- A6 (`latency`): parity holds (broker 1 ranking of 150 differs, control 3). Latency: in process p50 289.4 ms, p95 493.5 ms; broker p50 294.8 ms, p95 600.2 ms, so +1.9 % at p50 and +21.6 % at p95. The p95 is outside the 10 % budget set from entry 19. The test asserts parity only, not the budget. The first run on this head timed out at the suite's 300 s default; `e76ebea2` gives A6 its own 1200 s bound. One run under a load this branch does not control does not separate the broker's tail from the machine's; a run on an unloaded machine (or the CI job `broker-measurements`) is the next measurement, and whether the budget becomes an assertion is the owner's call.
- Correction: the message of `e76ebea2` calls the 288 s run (04:40Z entry) an idle machine's; its load was not recorded. The test's source comment now cites the entry only.
