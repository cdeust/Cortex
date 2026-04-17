# Phase 5 — ConnectionPool + to_thread + admission control design spec

**Status**: design. Implementation follows the step plan in §10.

**Goal**: eliminate single-connection serialization. Give interactive
tools (recall, remember) and batch tools (consolidate, wiki_pipeline)
separate pools so a long-running consolidate cannot block a hot-path
recall. Wrap sync DB calls in `asyncio.to_thread` so concurrent MCP
invocations actually run concurrently. Add per-tool admission
semaphores so the process cannot be DoS'd by one tool.

**Ground-truth sources** (absolute paths as of 2026-04-17):
- Today's single connection: `mcp_server/infrastructure/pg_store.py:60`
  (`self._conn = self._create_connection()`) — called once per
  `PgMemoryStore.__init__`; every DB call funnels through `_execute`
  which wraps `self._conn.execute`.
- Tool handler surface: `mcp_server/handlers/*.py` — each exports
  `async def handler(args: dict)`. Most handlers call store methods
  synchronously inside the async function, defeating concurrency
  (one slow tool call blocks the event loop).
- Server entry: `mcp_server/__main__.py` / FastMCP register.
- Governance: [ADR-0045 R6](../adr/ADR-0045-scalability-governance-rules.md)
  — "Latency classes" rule. Interactive/batch pool separation becomes
  enforceable post-Phase-5.
- Invariants: [I10](../invariants/cortex-invariants.md) — pool capacity
  rule.

---

## 1. What changes

### 1.1 Dual connection pools

Add `psycopg_pool.ConnectionPool` as the canonical DB resource.
**Two pools** — interactive and batch — matching ADR-0045 R6.

```
PgMemoryStore
├── _interactive_pool : ConnectionPool(min=2, max=8, timeout=5s)
│       Used by: recall, remember, anchor, detect_domain, list_domains,
│                 get_*, explore_features, memory_stats, query_methodology,
│                 validate_memory, rate_memory, navigate_memory,
│                 drill_down, recall_hierarchical, assess_coverage
│
└── _batch_pool       : ConnectionPool(min=1, max=2, timeout=30min)
        Used by: consolidate, seed_project, codebase_analyze,
                 wiki_pipeline, backfill_memories, import_sessions,
                 ingest_codebase, ingest_prd, rebuild_profiles
```

Pools are separate resources with independent queuing; a blocking
batch connection cannot starve an interactive call.

### 1.2 Compatibility shim (transitional)

Today 281 call sites across mcp_server reference `self._conn` or
`store._conn` directly. Breaking them all at once is too risky.
Phase 5 introduces:

```python
class PgMemoryStore:
    @property
    def _conn(self) -> psycopg.Connection:
        """Deprecated. Returns a checked-out interactive-pool connection
        for the CURRENT thread-local scope. Every direct `store._conn.execute(...)`
        call site is a Phase 5 migration target — it should become:
            with store.interactive_pool.connection() as conn:
                conn.execute(...)
        or route through `store._execute(...)` which already handles
        pool checkout internally. See docs/program/phase-5-pool-admission-design.md §4.
        """
        return self._thread_local_conn()
```

This preserves backward compat while callers migrate. `_execute` is
the first internal call site flipped to `with pool.connection(): ...`.

### 1.3 `asyncio.to_thread` wrap at handler boundary

Today:
```python
async def handler(args: dict) -> dict:
    store = _get_store()
    return store.do_sync_work(args)   # blocks event loop
```

Post-Phase 5:
```python
async def handler(args: dict) -> dict:
    store = _get_store()
    return await asyncio.to_thread(store.do_sync_work, args)
```

Every handler wraps. Two concurrent MCP tool invocations now genuinely
run in parallel on separate threads, each borrowing its own pool
connection.

### 1.4 Admission middleware — per-tool semaphore

Each tool declares a concurrency budget. The MCP server registers a
`Semaphore(N)` per tool and awaits it on entry:

```python
_ADMISSION: dict[str, asyncio.Semaphore] = {
    "recall":              asyncio.Semaphore(8),
    "remember":            asyncio.Semaphore(4),
    "consolidate":         asyncio.Semaphore(1),   # one at a time
    "seed_project":        asyncio.Semaphore(1),
    "wiki_pipeline":       asyncio.Semaphore(1),
    # default: Semaphore(4) for interactive, Semaphore(1) for batch
}

async def admit(tool_name: str, coro):
    sem = _ADMISSION.get(tool_name, _default_for_class(tool_name))
    async with sem:
        return await coro
```

Prevents queue-of-death when a client hammers consolidate in a loop.

### 1.5 I10 test

```python
def test_I10_pool_capacity_respects_cycle_workers():
    """pool.max >= number of cycle workers + 1 for hot path."""
    store = get_memory_store()
    n_workers = len(registered_cycle_workers())
    assert store._interactive_pool.max_size >= n_workers + 1
```

---

## 2. Dependencies

- `psycopg_pool>=3.1` — already present in dependency graph via
  `psycopg[binary]>=3.1` (pool is a separate extra; add explicitly
  to `pyproject.toml`).

---

## 3. Invariant impact

| Ik | Holds post-Phase-5? | Notes |
|---|---|---|
| I1 | Yes | No change to heat semantics. |
| I2 | Yes | No change to writers. |
| I3 | Yes | `effective_heat` pure. |
| I4 | Yes | Reconciliation unchanged. |
| I5 | Yes | Decay formula unchanged. |
| I6 | **Strengthened**. Consolidate snapshot remains — batch pool dedicated for it. |
| I7 | Yes | |
| I8 | Yes | |
| I9 | Yes | Synchronous write path preserved; `to_thread` is a concurrency boundary, not a semantic one. |
| **I10** | **Introduced as enforceable**. Pre-Phase-5 I10 was "trivially false". Post-Phase-5 it's a runtime-checkable config assertion. |

---

## 4. Blast radius / migration map

Files that need changes (priority order):

1. **`mcp_server/infrastructure/pg_store.py`** — introduce pool, update
   `_execute`, add `interactive_pool` / `batch_pool` properties,
   compat shim `_conn`.
2. **`mcp_server/infrastructure/memory_config.py`** — pool config knobs
   (min/max/timeout per pool).
3. **`mcp_server/__main__.py`** (server entry) — register admission
   middleware, wrap handlers in `asyncio.to_thread`.
4. **`mcp_server/handlers/*.py`** — tag each handler with its latency
   class (docstring `# class: interactive | batch`). No code change
   required at first; admission middleware reads the class.
5. **`tests_py/invariants/test_I10_pool_capacity.py`** — new invariant
   test.
6. **`pyproject.toml`** — add `psycopg_pool` dependency.

Direct `store._conn` callers (external to PgMemoryStore — 8 sites
across hooks/handlers) migrate to `store.interactive_pool.connection()`
context manager. These are flagged in the commit and reviewed
individually.

---

## 5. Risk

### 5.1 Pool exhaustion
If `max=8` and 9 concurrent consolidates are attempted, the 9th
blocks up to `timeout`. Admission middleware (`Semaphore(1)` for
batch tools) prevents this by rejecting at tool-entry rather than
blocking at the pool.

### 5.2 Connection pinning
Pre-A3, one process, one connection — simple. With pools,
connection state (prepared statements, session_role, search_path) is
per-connection; any code relying on session state must re-set on
checkout. Mitigation: pool's `configure` callback sets session
defaults at checkout; `DEALLOCATE ALL` on recycle.

### 5.3 Benchmark regression
Pool overhead (checkout/checkin per call) adds ~0.1-0.5 ms per DB
operation. For the benchmark suite this is sub-measurement-noise
because each question's total time is ~5 s. Regression gate:
LongMemEval R@10 ≥ 97.8%, LoCoMo R@10 ≥ 92.6%, BEAM-100K ≥ 0.591
(same floors as A3).

---

## 6. Kill switch

Env var `CORTEX_POOL_DISABLED=true`. When set, pool initialization
routes every `pool.connection()` to a single shared `psycopg.connect()`
(pre-Phase-5 behavior). Default `false`.

Removed one month after v3.13.0 release without pool-related incident.

---

## 7. Benchmark regression plan — BLOCKING

Post-Phase-5 floors (clean DB):

| Benchmark | Floor | Parity strategy |
|---|---|---|
| LongMemEval R@10 | ≥ 97.8% | Pool adds <1ms per query; 500-Q run unchanged. |
| LongMemEval MRR | ≥ 0.881 | Same floor as post-A3. |
| LoCoMo R@10 | ≥ 92.3% | Same floor as post-A3. |
| BEAM-100K MRR | ≥ 0.591 | Same. |

If any floor fails by > 0.5 pp, Phase 5 is blocked.

---

## 8. Sequenced execution plan

Each step is one commit.

1. **Commit: add `psycopg_pool` dep + config knobs**
   `pyproject.toml` + `memory_config.py` pool sizes.
   Test: import-only.
2. **Commit: introduce `_interactive_pool` in PgMemoryStore, route `_execute` through it**
   `_conn` still exists (compat). Hot path functions unchanged.
   Test: existing pg_store tests green.
3. **Commit: add `_batch_pool`, classify handlers**
   Docstring class tags; `_get_batch_store()` helper for consolidate/wiki.
   Test: class coverage assertion.
4. **Commit: wrap handlers in `asyncio.to_thread` at server registration**
   Single decorator applied at the register-loop.
   Test: concurrent-call integration test (two recalls in parallel beat
   one-at-a-time serialization).
5. **Commit: admission middleware with per-tool semaphores**
   `admit()` wrapping the dispatch. Budget table in one file.
   Test: overflow rejection test.
6. **Commit: I10 invariant test**
   Assert `pool.max >= registered_workers + 1` at server start.
7. **Benchmark gate** — all 3 benchmarks, 0.5 pp tolerance vs A3 floors.
8. **Migrate direct `store._conn` callers** (8 external sites)
   Incremental, one PR each with test.
9. **Post-soak (one month)**: delete `CORTEX_POOL_DISABLED` kill switch.

---

## 9. References

- psycopg3 pool docs: https://www.psycopg.org/psycopg3/docs/advanced/pool.html
- ADR-0045 R6 (latency classes): docs/adr/ADR-0045-scalability-governance-rules.md
- I10 formal definition: docs/invariants/cortex-invariants.md
- Erlang queuing (bounded-buffer M/M/c/K): Kleinrock, *Queueing Systems Vol. 1*, 1975.
