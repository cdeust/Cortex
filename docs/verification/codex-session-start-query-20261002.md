# SessionStart grooming query verification, 2026-10-02

The previous query used MAX(created_at) with lesson and prefix filters.
PostgreSQL selected two backward scans of idx_memories_created_at. Neither
prefix had a matching row in the observed corpus, so both scans exhausted
the index. The replacement materializes the lesson subset first, using the
existing idx_memories_tags_gin. Timestamp selection and wiki MAX(tended)
remain identical. No schema, index or stored data was changed.

Measured from base revision `c32a6a025319407630cab4733a4e0b17ae2d9588`
and the replacement SQL now in the working tree, on the local PostgreSQL
cortex database through the installed 4.23.5 runtime Python and psycopg. The memories heap was 944 MB, total
relation size 3002 MB; statistics estimated 92,862 live rows. Existing
Claude 4.23.4 and Cortex 4.23.5 session_start.py were identical before this
change. This is a query-plan correction, not a demonstrated version regression.

Both queries ran interleaved in one REPEATABLE READ READ ONLY transaction,
with a LOCAL statement_timeout of 60 seconds. This is an observation limit,
not a new hook timeout or algorithm constant. The database was live, with
concurrent activity and warmed pages from earlier probes; the result is not
a clean-cache guarantee or a benchmark of the complete SessionStart hook.

| Iteration | Previous query, seconds | Replacement, seconds |
| --- | ---: | ---: |
| 1 | 0.619434 | 0.005205 |
| 2 | 0.164163 | 0.012441 |
| 3 | 0.179626 | 0.003813 |

Every result tuple was identical in the same snapshot. SHA-256 of sorted
JSON timestamp results was
`f30b6917d99fff148374070ce1dc02f09c8c3f5a7389739a616b57ed9d5f3e1e`.

EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) in the same transaction:

| Plan | Execution, ms | Planning, ms | Shared hits | Shared reads |
| --- | ---: | ---: | ---: | ---: |
| Previous | 153.232 | 0.502 | 104981 | 10408 |
| Replacement | 5.109 | 0.301 | 870 | 437 |

The previous plan contained two Index Scan nodes on idx_memories_created_at,
each producing zero matching rows and evaluating the prefix subplan 970 times.
The replacement contained Bitmap Index Scan on idx_memories_tags_gin followed
by Bitmap Heap Scan of 970 lesson rows. Both prefix aggregates scanned that
materialized subset. Both plans scanned the same 3023 wiki pages. JIT was
absent from these two grooming plans.

Reproduce by extracting the SQL passed to conn.execute in
_fetch_grooming_staleness from HEAD and the working tree, running each against
the same read-only repeatable-read snapshot, asserting result equality,
and collecting the EXPLAIN JSON. The regression file
`tests_py/hooks/test_session_start_grooming_plan.py` executes the actual query
against synthetic VALUES rows through an explicit CORTEX_TEST_DATABASE_URL.
It verifies empty input, nullable timestamps, lesson exclusion, both prefixes
and their timestamp maxima without writing to the database.

The pending-curations query and team-decisions query also scan the memories
heap. Their remaining cost must be measured in the full hook before claiming
that SessionStart satisfies Codex's 30-second deadline.

SessionStart connection JIT policy

The root agent measured the installed full SessionStart hook failing to finish
within 30 or 35 seconds in three baseline probes. The same installed hook
with process-only PGOPTIONS='-c jit=off' completed in 15.147 seconds, returned
zero and emitted 3058 bytes. This was a manual full-hook probe, not native
Codex delivery evidence. The source now requests options='-c jit=off' only
on SessionStart's psycopg connection. It does not set PGOPTIONS or change
server, background-worker or persistent database configuration.

PostgreSQL reported jit=on and jit_above_cost=100000. The pending-curations
plan cost was 124074.8, above that threshold. In a separate read-only probe,
that query exceeded a six-second statement limit with the default JIT policy;
with SET LOCAL jit=off it executed in 1456.186 ms, plus 1407.691 ms planning.
These probes had concurrent load and changing cache state, so their individual
query timings alone do not isolate JIT causally. The root full-hook probe
supplies the direct process-level comparison motivating the scoped policy.

The regression verifies the connection requests jit=off while preserving
the process environment. A subsequent installed-wheel full-hook probe is
required to confirm the combined source corrections within the 30-second
Codex budget.

Focused verification completed: five tests passed in 0.17 seconds with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest --noconftest -p no:cacheprovider -o addopts='' tests_py/hooks/test_session_start_grooming_plan.py -q`.
An explicit CORTEX_TEST_DATABASE_URL selected the read-only connection;
the SQL fixtures never accessed or modified stored memories. Ruff check,
Ruff format check, craftsmanship and git diff --check passed for the owned
Python files.

Banner dependency presence check

After installing the SQL and connection fixes, a direct installed
SessionStart entry trace returned zero in 12.693 seconds and emitted 3163
bytes. The ten-second faulthandler snapshot located execution in
_build_context -> _has_sentence_transformers -> sentence_transformers.base.model
-> torch.distributed.tensor imports. A separate availability-only process
spent 28.249 seconds in the same helper; its ten-second snapshot traversed
sentence_transformers, sklearn and scipy compiled-extension imports.
The processes used the installed Python with -I -B, and captured context
was not printed or stored in this report. These timings have different
cache states and concurrent machine activity; they are not a paired speedup.

The banner now reads the sentence-transformers distribution metadata instead
of importing the ML stack. This checks installation presence only. It does
not establish that transitive imports, embeddings or semantic search work.
The missing-package message reports absence, without claiming a background
installation or promising that the next session will repair it. Regression
tests reject sentence_transformers, torch, scipy and sklearn imports while
building the banner for both present and missing distribution metadata.

The replacement presence helper, evaluated in the same installed runtime
without invoking the hook, returned true in 0.056733 seconds. Both banner
regressions passed in 0.15 seconds. Ruff check, format check, craftsmanship
and git diff --check passed after this change. The full installed hook must
be verified again after the wheel includes this final source correction.
