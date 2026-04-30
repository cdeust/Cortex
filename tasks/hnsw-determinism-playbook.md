# HNSW Determinism Playbook — Cortex Verification Campaign

**Audience:** benchmark operators and the `db_snapshot.py` author.
**Scope:** the `memories.embedding` HNSW index, built with `m=16, ef_construction=64, vector_cosine_ops` (source: `mcp_server/infrastructure/pg_schema.py:506-507`). Same reasoning applies to wiki HNSW indexes (`pg_schema.py:287, 292, 307`) when those are exercised by benchmarks.
**Engine:** PostgreSQL 15+ with pgvector C extension (server-side) and `pgvector` Python client `>=0.3` (`pyproject.toml:49,76`).
**Stakes classification:** High — benchmark scores are load-bearing claims (CLAUDE.md "Scientific Implementation Standard" §5: "no regression accepted"). Non-determinism in the index makes those claims unfalsifiable.

---

## 1. The Non-Determinism Source

HNSW (Malkov & Yashunin 2018, *"Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs"*, IEEE TPAMI, Algorithm 1) inserts each point into a multi-layer graph. Two sources of run-to-run variation:

1. **Random level assignment.** Each insert draws a level `l = floor(-ln(unif(0,1)) * mL)` (Algorithm 1, line 4). Without a seeded RNG, two builds against the same dataset produce different per-node levels → different graph topology → different traversal order → different recall on edge-case queries.
2. **Insertion order sensitivity.** Even with deterministic levels, the greedy connection step (Algorithm 1, lines 10-17) selects the M closest already-inserted neighbors. Insertion order changes which neighbors are *available* at each step. In Postgres, `INSERT ... RETURNING id` is ordered by transaction commit, but parallel index build (`max_parallel_maintenance_workers > 0`) shards the work non-deterministically.

**pgvector specific:** the upstream C source at `src/hnswbuild.c` (https://github.com/pgvector/pgvector/blob/master/src/hnswbuild.c) calls `RandomDouble()` from PG core (`src/backend/utils/adt/float.c`) which uses `pg_prng_double()` seeded from `pg_global_prng_state`. That seed is **not** user-settable as of pgvector 0.7.x — verified by absence of `seed` in the index DDL grammar at `src/vector.c`. **ASSUMED — needs verification on installed extension version** (`SELECT extversion FROM pg_extension WHERE extname='vector';` and check release notes for that exact version).

---

## 2. Why `pg_dump --format=custom` + `pg_restore` Collapses This to a One-Time Outcome

`pg_dump --format=custom` captures index relfile contents via the standard physical-page export path (PostgreSQL docs: "pg_dump — Custom Format", https://www.postgresql.org/docs/current/app-pgdump.html). For HNSW, the index pages contain the serialized graph: per-node level, per-level neighbor list, entry point. `pg_restore` rewrites these pages verbatim into `pg_class`/`pg_index` storage.

**Guarantee:** PostgreSQL's on-disk page format is stable within a major version (PG docs, "Database File Layout", https://www.postgresql.org/docs/current/storage-file-layout.html — "the format used is consistent across all platforms supported by a given major version"). So:

- Same PG major version + same pgvector C-code version + restored pages ⇒ identical graph traversal ⇒ identical query results for `<=>` distance ops.
- The randomness happened **once**, at index build time before the dump. The snapshot freezes that outcome.

This is the mechanism that makes the verification campaign reproducible.

---

## 3. What Can Still Vary Across Restores

| Source | Effect | Mitigation |
|---|---|---|
| Stale `pg_statistic` after restore | Planner may switch to seq-scan vs index-scan on borderline queries, changing latency *and* (with `LIMIT`) result ordering on ties | `ANALYZE memories;` after every restore |
| pgvector C extension version drift | Different graph traversal C-code ⇒ different results for the *same* pages | Pin extension version in manifest; assert on every run |
| Autovacuum during run | Page rewrites, HOT chain reorganization, cost-model perturbation | `ALTER TABLE memories SET (autovacuum_enabled = false);` on test DB |
| Connection-pooler plan cache | Different prepared-plan shapes across runs of the same query | `application_name='cortex_bench_<run_id>'`, `DISCARD ALL` between batches |
| `work_mem` / `maintenance_work_mem` env-dependent | Affects sort spillover; in HNSW build affects parallel partitioning thresholds | Pin per-session via `SET LOCAL` |
| `effective_io_concurrency` | Page prefetch order in bitmap heap scans → tie-break order | Pin via `SET LOCAL` |
| Locale (`LC_COLLATE`) | Affects text sort order in candidate-set tie-break | Capture in manifest; assert match |
| PG major version mismatch | Page format may change | Capture `server_version_num`; assert exact match |

---

## 4. Hardening Playbook (operator runs once before measurements)

15-item checklist. Every item is `psql`-executable or a one-line shell command.

1. **Pin pgvector extension version.** `SELECT extversion FROM pg_extension WHERE extname='vector';` — record in manifest; fail benchmark if a future restore reports a different value.
2. **Pin PG major version.** `SHOW server_version_num;` — record; assert the first two digits match on restore.
3. **Disable autovacuum on the benchmark tables.** `ALTER TABLE memories SET (autovacuum_enabled = false);` (and likewise for any other measured tables). Note: `autovacuum` itself is a postmaster GUC — it can only be turned off cluster-wide, so `ALTER DATABASE … SET autovacuum = off` raises `CantChangeRuntimeParam` on every PG version. We achieve the same effect by disabling autovacuum *for the test tables* via reloptions, which is per-table and per-DB safe.
4. **Disable parallel maintenance for the index build (one-time, before snapshot).** `SET max_parallel_maintenance_workers = 0;` before `CREATE INDEX`. Parallel build forks workers with independent RNG state — non-recoverable randomness.
5. **Disable parallel query for measurement.** `SET max_parallel_workers_per_gather = 0;` per session. Parallel scans return results in non-deterministic order on ties.
6. **Pin `work_mem`.** `SET work_mem = '64MB';` (or value chosen from a documented baseline run).
7. **Pin `maintenance_work_mem`.** `SET maintenance_work_mem = '512MB';` before index build; record value in manifest.
8. **Pin `effective_io_concurrency = 0`** for the test DB to disable page-prefetch reordering.
9. **`SET enable_seqscan = on; SET enable_hashagg = on;`** — explicitly hold defaults so a future PG default change doesn't silently flip plans.
10. **`ANALYZE memories;`** after restore, before the first measurement query.
11. **`DISCARD ALL;`** between query batches in a single session to flush prepared-plan cache.
12. **Set per-run `application_name`** so the pooler keys plans by run ID and never cross-pollinates.
13. **Reject production URLs.** `db_snapshot.py` MUST refuse to operate on any URL whose database name is not on an allow-list (e.g. matches `^cortex_bench(_|$)` or `^cortex_test`). Hard refusal — see refusal conditions below.
14. **Lock the snapshot file.** Compute SHA-256 of the dump; record in manifest; fail if it changes between runs (means someone re-baked silently).
15. **Capture `pg_settings` diff at restore time.** Any setting in §5's manifest list that differs from the snapshot's value → fail loudly.

---

## 5. Reproducibility Manifest Fields

Fields `db_snapshot.py` MUST capture beyond what the parallel agent already records:

```yaml
# Existing (per the parallel agent)
pgvector_extversion: "0.7.4"          # SELECT extversion FROM pg_extension WHERE extname='vector'
snapshot_sha256: "..."                # SHA-256 of the .dump file

# New — required additions
pg_server_version_num: 150006         # SHOW server_version_num
pg_locale_collate: "C.UTF-8"          # SHOW lc_collate
pg_locale_ctype: "C.UTF-8"            # SHOW lc_ctype
hnsw_index_params:                    # from pg_indexes / pg_class.reloptions
  table: "memories"
  column: "embedding"
  m: 16
  ef_construction: 64
  ops: "vector_cosine_ops"
pg_settings_relevant:                 # SELECT name,setting FROM pg_settings WHERE name IN (...)
  work_mem: "64MB"
  maintenance_work_mem: "512MB"
  max_parallel_workers_per_gather: 0
  max_parallel_maintenance_workers: 0
  effective_io_concurrency: 0
  enable_seqscan: "on"
  enable_hashagg: "on"
  enable_indexscan: "on"
  enable_bitmapscan: "on"
  jit: "off"                          # JIT can perturb timing-dependent tie-breaks
ingest_provenance:
  source_dataset: "longmemeval_s_v1"
  ingest_commit_sha: "..."            # git rev-parse HEAD at ingest time
  embedding_model: "all-MiniLM-L6-v2"
  embedding_dim: 384
row_counts:
  memories: 12345
  entities: 6789
  # …each table the benchmark reads
```

The manifest goes alongside the `.dump` file. On restore, `db_snapshot.py` must compare every field against the live DB and fail loudly on any mismatch.

---

## 6. When pgvector Adds an HNSW `seed` Parameter

Likely future feature (tracked at https://github.com/pgvector/pgvector/issues — **ASSUMED — needs verification**; no merged PR as of 2026-04). When it lands:

1. Update `pg_schema.py:507` DDL: `WITH (m = 16, ef_construction = 64, seed = <fixed_int>)`.
2. Re-bake the snapshot once with the new build.
3. Add `hnsw_seed` to the manifest.
4. The snapshot file remains the source of truth either way — the seed only adds a second layer of reproducibility (you can rebuild from scratch *and* match the snapshot).

This does not retroactively help existing snapshots. Don't switch until benchmarks are re-baselined.

---

## 7. Operational FAQ

**Q1: Can I snapshot on macOS and restore on Linux?**
Yes for `pg_dump --format=custom` — it serializes pages through the logical export path, portable across platforms within a PG major version (PG docs: "pg_dump", https://www.postgresql.org/docs/current/app-pgdump.html, "the format is portable across architectures"). NOT for `pg_basebackup` (physical replication; tied to the source's filesystem byte order). Use only `--format=custom` or `--format=directory`.

**Q2: What if memory IDs differ across runs?**
They won't if you snapshot **after** ingest. `pg_dump` captures sequence state via `SELECT setval(...)` in the dump (PG docs: "pg_dump — Notes"). `pg_restore` re-applies it before any inserts. If the benchmark inserts new rows post-restore, those will have predictable next-IDs.

**Q3: Can I snapshot a live production DB?**
**No.** The safety guard in item §4.13 must reject any URL not matching the test-DB allow-list. Two reasons: (a) `pg_dump` of a live DB takes a snapshot at `txid_current()` but in-flight writes during the dump can produce subtly different results across runs; (b) production URLs leaking into benchmark tooling is a credential-handling failure. **Refusal condition (DBA agent rule):** snapshot-from-prod is a hard refuse, no override flag.

**Q4: Does `ef_search` (query-time parameter) need to be pinned?**
Yes. `ef_search` (default 40, pgvector docs https://github.com/pgvector/pgvector#hnsw) controls candidate-set size at query time. It's a *session* GUC, not baked into the index. Add `SET hnsw.ef_search = 40;` to the per-session setup and record in manifest §5.

**Q5: What about `INSERT`s that happen *during* the benchmark (e.g. memory-write tests)?**
HNSW supports incremental insert — graph stays consistent but the *new* node's neighbor selection uses live RNG. If the benchmark writes, those writes are non-deterministic by construction. Two options: (a) measure read-only benchmarks against the snapshot; (b) for write-path benchmarks, compute aggregate metrics (recall@k mean over many writes) rather than per-query exact match. Document which mode each benchmark uses.

**Q6: Why not just `CREATE INDEX` deterministically every run instead of snapshotting?**
Build is O(N log N) with large constants; on the LongMemEval-S corpus (≈500 memories) it's seconds, but on BEAM-100K it's minutes. Plus, even with all GUCs pinned, parallel build (item §4.4) introduces unrecoverable randomness. Snapshot is the only path that scales.

**Q7: How do I verify the snapshot actually reproduces?**
Operator-level smoke test: restore twice into two separate DB names, run the same 10 fixed queries against both via `recall_memories()`, assert byte-equal JSON results. Add this as a CI gate before any benchmark run consumes the snapshot.

---

## 8. Division of Labor — `db_snapshot.py` vs new `db_setup.py`

**Recommendation: create `benchmarks/lib/db_setup.py`.** `db_snapshot.py` should be a focused dump/restore tool; the GUC-pinning and validation logic is a separate concern (SRP, `~/.claude/rules/coding-standards.md` §1.1).

### Goes into `db_snapshot.py` (the existing agent's scope):
- Item §4.1 — capture `pgvector_extversion` in manifest.
- Item §4.13 — reject non-test-DB URLs (safety guard).
- Item §4.14 — SHA-256 the dump file.
- Item §4.15 — diff `pg_settings` against manifest at restore time, fail loudly.
- All of §5 — manifest schema (snapshot owns the manifest format).
- §7 Q7 — provide a `verify()` method that restores into a temp DB and runs a fixed smoke-query set.

### Goes into new `benchmarks/lib/db_setup.py`:
- Items §4.3, §4.4, §4.5, §4.6, §4.7, §4.8, §4.9 — all the `SET` / `ALTER` GUC pinning. Exposed as `apply_deterministic_session(conn)` and `apply_deterministic_database(conn, dbname)`.
- Item §4.10 — `ANALYZE memories;` after restore.
- Item §4.11 — `DISCARD ALL;` between batches.
- Item §4.12 — `application_name` per-run.
- §7 Q4 — `SET hnsw.ef_search` pinning.

### Goes into the benchmark runner (no new file):
- Calling `db_setup.apply_deterministic_session()` on every connection check-out (extends the existing `pg_store.py:130` pool callback).

### Refusal conditions for both modules
- `db_snapshot.py.create()` against a non-allow-listed DB → refuse.
- `db_setup.apply_deterministic_database()` without prior `db_snapshot.verify()` pass → warn loudly (operator may proceed during initial bake).
- Any code path that calls `CREATE INDEX hnsw` outside the snapshot bake step → refuse; HNSW must be built once, in the controlled bake, then captured.

---

## Sources

- Malkov, Y. & Yashunin, D. (2018). "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs." *IEEE TPAMI* 42(4). Algorithm 1.
- pgvector source: https://github.com/pgvector/pgvector — files cited inline. Specific line numbers ASSUMED — the engineer agent should pin the exact tag version installed in the test DB (`SELECT extversion`) and re-cite against that tag.
- PostgreSQL docs (current): pg_dump (https://www.postgresql.org/docs/current/app-pgdump.html), Database File Layout (https://www.postgresql.org/docs/current/storage-file-layout.html), Routine Vacuuming (https://www.postgresql.org/docs/current/routine-vacuuming.html).
- Cortex repo: `mcp_server/infrastructure/pg_schema.py:506-507` (HNSW DDL); `mcp_server/infrastructure/pg_store.py:130` (pool callback hook); `pyproject.toml:49,76` (`pgvector>=0.3` Python client — note: this is the client lib, NOT the server-side C extension; the C extension version must be checked separately via `pg_extension`).
- `~/.claude/rules/coding-standards.md` §1.1 (SRP), §10 (high-stakes calibration).
