# ADR-0055: Request-Scoped SQLite Connections With Thread Ownership

**Status:** Proposed
**Date:** 2026-08-30
**Decision-makers:** cdeust
**Related:** HC-CORTEX-002; ADR-0045 R6; I10

## Context

`SqliteMemoryStore` owns one `sqlite3.Connection` configured with
`check_same_thread=False`. `safe_handler` executes concurrent MCP calls on
worker threads, so unrelated operations share one implicit transaction.

The HC-CORTEX-002 baseline at Cortex revision
`8f5ae3b87b6969f3abcb3736859febfdab69304a` injected a failure after a
supersession insert and compare-and-set. A concurrent acknowledged insert
committed the shared connection before the rejected supersession rolled back.
The rejected memory, its FTS row, and its `superseded_by_id` edge remained,
while `PRAGMA integrity_check` still returned `ok`.

A second RED fixture rejected an `insert_memory` after its first write, then
ran an unrelated acknowledged request on the same reused worker. A connection
per thread alone still let the second request commit the first request's dirty
transaction. Thread ownership is therefore necessary but not sufficient: the
request boundary must finalize unfinished work before a worker is reused.

This is the documented SQLite boundary, not a damaged database file:

- Python's `sqlite3` documentation says that disabling `check_same_thread`
  permits cross-thread access but requires the caller to serialize writes to
  avoid corruption: <https://docs.python.org/3/library/sqlite3.html#sqlite3.connect>.
- SQLite provides isolation between separate connections and explicitly no
  isolation between operations on the same connection:
  <https://www.sqlite.org/isolation.html>.
- Python exposes `Connection.in_transaction` as the read-only view of SQLite's
  low-level autocommit state, and documents `rollback()` as reverting a pending
  transaction: <https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.in_transaction>.
- WAL permits simultaneous readers and a single serialized writer across
  separate connections: <https://www.sqlite.org/isolation.html#isolation_and_concurrency>.

## Decision

The SQLite adapter and handler boundary will enforce both ownership levels:

1. Each execution thread lazily receives one native connection to the same
   database file. The on-disk path is resolved once at registry construction,
   so a later process `cwd` change cannot redirect worker handles.
2. Every `safe_handler` path is offloaded through `asyncio.to_thread`; an
   optional tool name controls admission and named metrics, not execution or
   isolation. The request installs a thread-safe `ContextVar` state that
   records the exact registry/connection identities touched by the handler
   and any nested `to_thread` calls. Python documents that `to_thread` copies
   the current context into its worker:
   <https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread>.
3. On an exception, the boundary rolls back every pending connection recorded
   for that request. If a handler tries to return success with pending work,
   the boundary rolls it back and raises
   `UncommittedSqliteTransactionError`; it cannot emit a false
   acknowledgement. A rollback failure quarantines and closes that native
   connection so later work cannot commit its unknown state. The original
   handler exception remains the reported failure.
   After finalization, every non-anchor request-opened handle is closed and
   removed from the registry. While healthy, one anchor remains until
   store shutdown so a named in-memory database cannot disappear between
   requests. If rollback itself fails on that last in-memory keeper, the
   registry becomes explicitly unusable; it never silently reopens an empty
   database as recovered state.
4. Nested handler transaction scopes are rejected before the inner handler
   starts. This change does not implement savepoints and therefore does not
   pretend that an inner request can independently commit or roll back.
5. The primary on-disk connection requests WAL once and records a warning if
   SQLite retains another mode; the benchmark records the observed mode.
   Every connection enables foreign keys and loads
   `sqlite-vec` when vector support was enabled by the primary connection.
   SQLite documents both WAL persistence and the in-memory `MEMORY`/`OFF`
   restriction: <https://www.sqlite.org/pragma.html#pragma_journal_mode>.
6. The existing `_raw_conn` and psycopg-compatible `_conn` surfaces remain
   stable proxies, so the existing store/mixin contract does not gain backend
   or thread branching.
7. Store shutdown, after requests are quiescent, closes every connection
   registered by the process. `check_same_thread=False` remains intentional
   only so that shutdown can close worker-owned handles centrally; normal SQL
   operations are routed to their owner by the proxy.
8. Direct `SqliteMemoryStore(":memory:")` fixtures use a uniquely named
   in-memory URI so worker connections observe the same ephemeral database.
   They use SQLite's `MEMORY` journal mode because WAL is unavailable for an
   in-memory database. This is the only shared-cache use. It is test-only;
   production/plugin construction supplies the configured on-disk fallback
   path. SQLite discourages shared cache for production and recommends WAL:
   <https://sqlite.org/sharedcache.html#use_of_shared_cache_is_discouraged>.

Transaction ownership follows the connection that performed the operation,
and request finalization prevents a dirty transaction from crossing a worker
reuse boundary. A commit or rollback from another request cannot affect it.

## Options Considered

### A. Global handler semaphore

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Integrity | Incomplete |
| Scalability | Poor |

Serializing every SQLite-backed MCP handler would close the demonstrated tool
race, but direct store callers and any internal concurrency would remain
unsafe. It would also serialize read-side ranking work that does not need the
writer lock. Rejected because the invariant belongs at the storage boundary.

### B. Transaction-aware lock around the shared connection

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Integrity | Sensitive to every error path |
| Scalability | One connection |

A re-entrant lock could be retained from the first implicit write until
`commit` or `rollback`. The lock would have to infer transaction ownership,
survive cursor and raw-connection paths, and release correctly after every
exception. SQLite would still define same-connection read/write interleaving
as non-isolated. Rejected as a second transaction manager layered over
SQLite's own.

### C. Request-scoped worker connections plus one lifetime anchor

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Integrity | Native SQLite isolation |
| Scalability | Concurrent readers; one SQLite writer |

Accepted. Separate connections use SQLite's documented isolation unit, while
the handler scope closes the reused-worker gap demonstrated by the second RED
fixture and releases its non-anchor handles after finalization. The lifetime
anchor preserves the named in-memory fixture. Existing multi-statement methods
keep one stable connection for their complete call.

### D. Autocommit plus explicit unit-of-work contexts everywhere

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Integrity | Explicit |
| Migration risk | High |

This would require auditing and rewriting every multi-statement method across
the store and shared mixins. It may be useful for a later typed unit-of-work
API, but it is not the smallest correction for the proven ownership defect.

## Consequences

- Unfinished work on a connection recorded by the request scope cannot be
  committed or rolled back by another worker.
- A failed request cannot leave recorded, uncommitted writes for a later
  request to commit, and a successful response cannot acknowledge a recorded,
  unfinished transaction.
- When the file is actually in WAL mode, WAL can serve readers while SQLite
  serializes the sole writer. The requested and observed modes are distinct
  benchmark evidence.
- The first SQLite call in a request pays one connection-open cost; later calls
  on that request's worker reuse the handle. Non-anchor request handles are
  then released, so inactive per-request executors do not accumulate
  connections.
- Concurrent writers may queue or return SQLite's documented busy result.
  The HC-CORTEX-002 load ladder must publish error/retry and saturation data;
  this ADR does not invent a throughput threshold.
- On the current `safe_handler` host path, retained connection count returns to
  the construction-time anchor after requests become quiescent; peak handles
  follow the active request workers. Direct applications outside a request
  scope that create arbitrary ephemeral threads retain those handles until
  `SqliteMemoryStore.close()`; reclamation outside the host path is not claimed.
- Shutdown assumes the store is quiescent; closing a handle while a request is
  using it remains outside the lifecycle contract.
- A rollback failure on the in-memory anchor is unrecoverable without a durable
  backing file. The triggering handler keeps its original error, and every
  later registry access fails explicitly until the store is closed.
- The request boundary does not undo writes that a store method has already
  committed before a later method in the same handler fails. Handler-wide
  atomic units of work require a separate explicit transaction API and are
  outside this correction. HC-CORTEX-002 claims only that unfinished work from
  a rejected request cannot cross a request/worker boundary or be finalized by
  an unrelated request.
- Cancelling the coroutine awaiting `asyncio.to_thread` does not stop the
  native worker. A cancelled or transport-lost call is therefore
  `indeterminate`, not a rejected operation: the benchmark must wait for
  worker quiescence and reconcile its operation identifier against storage
  before assigning an outcome. This ADR does not claim cancellable
  handler-wide atomicity.
- `ContextVar` propagation is guaranteed for `asyncio.to_thread`, not for an
  arbitrary manually-created `threading.Thread`, and a child task that outlives
  its handler is outside the quiescent request contract.
- The in-memory compatibility path uses SQLite's documented named-memory
  shared-cache mechanism only because separate `:memory:` opens otherwise
  create different databases: <https://www.sqlite.org/inmemorydb.html>.

## Verification

- Preserve the deterministic rejected-supersede/concurrent-insert ledger as a
  regression: rejected row/FTS/edge count is zero; acknowledged insert count is
  one.
- Preserve the failed-request/acknowledged-next-request fixture on one reused
  worker, plus a fixture proving that apparent success with pending work is
  rejected and rolled back.
- Prove nested `to_thread` work is finalized through its exact native handle,
  nested handler scopes fail before inner work, and concurrent unnamed
  `safe_handler` calls do not share the event-loop thread's connection.
- Force rollback cleanup to fail and prove the connection is quarantined, the
  original handler error is preserved, and a later acknowledged request opens
  a clean on-disk replacement. Prove the equivalent in-memory anchor failure
  invalidates the registry instead of exposing a fresh empty database.
- Verify the same fixture after closing and reopening the database.
- Verify worker handles cannot be reused after registry close, future worker
  handles receive `sqlite-vec`, and observed journal modes are `wal` for the
  file fixture and `memory` for the in-memory fixture.
- Repeat direct and nested-worker requests and prove registry cardinality
  returns to its pre-request value after each one.
- Construct from a relative on-disk path, change process `cwd`, and prove a
  later worker still opens the original database and creates no second file.
- Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
- Prove two worker threads receive isolated transaction outcomes on both an
  on-disk fixture and the in-memory compatibility path.
- Run the preregistered concurrency ladder twice and publish throughput,
  latency percentiles, queueing/busy errors, retries, resources, and recovery.
- Do not count a client cancellation or transport timeout as a rejection.
  Record it as `indeterminate`, wait for worker quiescence, and reconcile it
  before closing the store or publishing the cell.
- Run the matched PostgreSQL reference cell; PostgreSQL storage code is
  unchanged.
