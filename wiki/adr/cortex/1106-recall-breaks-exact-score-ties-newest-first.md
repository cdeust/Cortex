---
created: 2026-10-14T17:00:00Z
kind: adr
number: 1106
status: accepted
tags: [retrieval, postgresql, sqlite, recall, determinism, benchmarks]
title: Recall breaks exact score ties newest first
---
# ADR-1106: Recall breaks exact score ties newest first

## Status

accepted. Rule 1 amended by ADR-1109 for the five `recall_memories()` pools and the SQLite recall signals: a pool keeps its whole boundary tie group instead of cutting it newest first.

## Context

`recall_memories()` (`pg_schema.py`) builds five candidate pools, each cut by `ORDER BY <score> LIMIT v_pool` (`v_pool = p_max_results * 10`): `vec` (cosine distance), `fts` (`ts_rank_cd`), `ngram` (trigram similarity), `hot` (`effective_heat`) and `recency` (`created_at`). The fused result is cut again by `ORDER BY (superseded_by_id IS NOT NULL), final_score DESC LIMIT p_max_results * 3`. None of these orders was total. When more rows than the LIMIT shared a score, PostgreSQL's sort (a top-N heap sort, not stable) kept the rows in the order the scan delivered them, which is heap order for a sequential scan. `CLUSTER`, `VACUUM`, autovacuum and the reuse of free space after deletes change that order.

Measured on 2026-10-14 (ADR-1105's evidence, `pgvector/pgvector:pg16`):

- LongMemEval `f4f1d8a4`: all 110 eligible rows have `effective_heat` 0.05, so `hot` (`LIMIT 100`) dropped 10 rows chosen by heap order. With `p_w_heat` 0.5 for that `knowledge_update` intent against a fused top of about 1.6, losing the heat contribution decided whether the answer reached the top 10. Over 20 seeded heap layouts the number of rows cut from `hot` varied with the layout.
- LoCoMo conv-41 (122 rows): two runs of origin/main differed in 128 of 193 top-10 sets. Recall writes back heat and access counts (`bump_heat_raw`, `update_memory_access`), so one changed result carries into the heat of every later query of the conversation.
- The PostgreSQL benchmarks were therefore not reproducible once a haystack held more than 100 eligible rows: two runs of the same commit scored LongMemEval R@10 0.982 and 0.980.

The same defect sits in the queries the recall pipeline composes with: `spread_activation_memories()` (`ORDER BY MAX(act) DESC LIMIT`, reached through the default `sa_mode="tail"`), `search_fts` (prospective-trigger injection, `LIMIT 3`), `search_by_tag_vector` (typed-intent reserve, both branches), the FTS-only hook recalls (`auto_recall.py`, `agent_briefing_query.py`), and three lookups with `LIMIT 1` or an early `break` and no `ORDER BY` at all: `get_entity_by_name` (dendritic modulation), the entity lookups of `reinforce_or_create_relationship` (Hebbian co-activation after recall) and `get_active_prospective_memories` (recall injects at most `max_results` triggered memories in the order read).

On SQLite the fusion is client-side and rank-based (`w / (k + rank)`), so the order of tied rows inside a signal changes their scores, not only which rows a LIMIT keeps. The heat, recency, FTS5 and vector signals, the final `sorted(scores, ...)` and the spread-activation mapping (`LIKE ... LIMIT 20` with no `ORDER BY`) inherited whatever order SQLite read: deterministic for a given file, but not the order PostgreSQL uses, and not a decision.

## Decision

1. **Every `ORDER BY ... LIMIT` on the recall path ends in `created_at DESC, id DESC`.** In `recall_memories()`: the five pools and the final order. Also `spread_activation_memories()`, `search_fts`, both `search_by_tag_vector` branches (the vector branch inside its materialized CTE and in the re-sort outside it, ADR-1105), and the hook queries that feed recall-like context: `auto_recall`, the agent briefing's FTS, team and role-prior passes (`agent_briefing_query.py`, `agent_briefing_role.py`, and the SQLite twin `agent_briefing_sqlite.py`), and the SessionStart banner's anchor, team-decision and hot queries (`session_start_fetch.py`). The listings those paths and the opt-in `include_related` enrichment read take the same key: `get_hot_memories` (the SQLite banner's source, both backends), `get_memories_mentioning_entity` (both branches, both backends), `get_entities_for_memory` (`e.heat DESC, e.created_at DESC, e.id DESC`: a heat ranking the caller cuts with a slice, not a name lookup, so rule 3 does not apply) and `get_relationships_for_entity` (`r.weight DESC, r.created_at DESC, r.id DESC` in all three directions; `created_at`, not `last_reinforced`, so the rule stays one rule). On SQLite: `_signal_heat`, `_signal_recency`, `_signal_fts`, `_signal_vector`, `search_fts`, the final ranking (`_ranked_ids`) and `_map_entities_to_memories`. `id` is the primary key, so the order is total; `created_at` comes first because it is the memory's own time. **Exception, measured: an ORDER BY on stored `heat_base` breaks ties by `id DESC`, not by `created_at`.** Those queries are `get_hot_memories`, the SessionStart banner's hot query, the SQLite agent briefing passes and role prior (on PostgreSQL those order by `effective_heat` and keep `created_at`), `get_memories_mentioning_entity`, the SQLite heat signal (`_signal_heat`) and `search_by_tag_vector`'s heat ordering. Their `(heat_base DESC, id DESC)` index (`idx_memories_heat_base_id`, ADR-0537; on SQLite, the `(heat_base)` index carries the rowid) serves `id DESC`. With `created_at` inserted between the two, PostgreSQL sorted the whole tied group before the LIMIT: read-only on the owner's store (5,039 heads at heat 1.0), `get_hot_memories(limit=10)`, which `remember`'s gate reads on every write, took 159.5 ms against 0.16 ms through the index (review of 3c42ea91 measured 0.08–0.33 ms on main and 177–208 ms with `created_at`). `id` is the insertion order, so the newer memory still wins; it differs from `created_at` only for memories imported with a backdated `created_at`. Computed scores (the pools of `recall_memories()`, fused rankings) keep `created_at DESC, id DESC`: no index orders them, and they are sorted in full anyway.
2. **Exact ties go to the newer memory.** The codebase already says what "newer" means at a tie:
   - the `recency` pool is `created_at DESC` by definition;
   - `effective_heat` never increases with elapsed time (ADR-0537). Rows that tie on it either do not decay (`no_decay`, `is_protected`) or sit on a floor that erased their age difference (`late_ltp` and `reconsolidating` floor at 0.05, the value all 110 `f4f1d8a4` rows share); above the floor the newer row would have ranked higher;
   - a newer memory supersedes an older one, and listings that serve content return chain heads, most recent first (ADR-1100);
   - `f4f1d8a4` is a `knowledge_update` question: the later statement is the one the intent asks for.
   `created_at` before `id`, because ingestion takes `created_at` from the source (`memory_ingest`, `import_sessions`, every benchmark loader); `id` follows insertion order and breaks the remaining ties.
3. **Entity name lookups take the oldest row (`ORDER BY id`).** `insert_entity` returns the existing row for a case-insensitive name match, so every write since then resolved to the first row inserted; a read that picks another row would disagree with the writes. Active prospective memories are read in `id` order.
4. **The HNSW path is kept.** With the extra keys the `vec` pool plans `Index Scan using idx_memories_embedding` under an `Incremental Sort` presorted on the distance, checked read-only on the owner's store (69,155 rows, pgvector 0.8.2, PostgreSQL 17.9) and under the ANN tests' `enable_seqscan=off, enable_sort=off`. The `recency` pool keeps `idx_memories_curated_created_at` the same way. On an HNSW plan the pool is still approximate (ADR-1105); the tie-break makes exact plans total and does not change ADR-1105's `relaxed_order` decision.
5. **Existing installs get the new function on the next store open.** `PgDdlMixin._init_schema` re-applies the whole DDL set when `schema_meta.ddl_hash` differs from the code's (ADR-0545); the function text changed, so the hash did. `recall_memories()` keeps its signature, so `CREATE OR REPLACE` swaps the body in place.

Out of scope, listed so the omission is a decision: `search_vectors` and `search_newer_neighbors` (write-path callers: remember, active forgetting); `get_hot_embeddings` and `get_temporal_co_access` (reached only from `recall_helpers.collect_signals`, which nothing calls); the other `get_*_memories` listings (maintenance, consolidation and handler listings that read whole sets rather than recall candidates); and the cut inside sqlite-vec's own KNN query, which takes no second `ORDER BY` key: its rows are re-ordered totally outside it, but which rows it keeps at its LIMIT on an exact distance tie is sqlite-vec's choice.

## Benchmark

Branch at cfd03db9 (the `git_sha` of every run's `MANIFEST.json`), `benchmarks/reproduce.sh --only longmemeval,locomo --no-ablation`, `pgvector/pgvector:pg16`, Python 3.13.7. These runs predate the hook and listing tie-breaks added after review (`get_hot_memories`, which the write path also reads, `get_memories_mentioning_entity`, the entity and relationship reads, the hook queries); they were not re-measured. Two runs of the same commit were compared question by question on their per-query journals (top-10 memory ids, content hashes, order and scores):

| benchmark | questions | R@10 | MRR | run-to-run |
|---|---|---|---|---|
| LongMemEval-S, run 1 and run 2 | 500 | 0.9800 | 0.9057 | 0 of 500 top-10 lists differ |
| LoCoMo, all 10 conversations | 1982 | 0.8870 | 0.7780 | one run |
| LoCoMo, conv-26, conv-30, conv-41 (`--limit 3`), run a and run b | 495 | 0.8687 | 0.7660 | 0 of 495 differ (conv-41: 0 of 193) |

On origin/main two runs differed in 128 of conv-41's 193 top-10 sets (Context). [Retiré 2026-10-29 : porte de non-régression contre main supprimée sur ordre de l'owner ; les benchmarks sont une mesure, pas une porte.]

Reference range of origin/main (fee4c61a / 6cecb7c2, ADR-1105): LongMemEval-S R@10 0.980 to 0.982, MRR 0.904 to 0.906; LoCoMo R@10 0.8875 to 0.8900, MRR 0.780. Main's run-to-run spread on these benchmarks is being measured and will be added here.

## Consequences

Positive: one database state now gives one recall result. Tests on PostgreSQL (`tests_py/infrastructure/test_pg_recall_deterministic_ties.py`) put 130 rows on one tied score per pool and rewrite the heap in three orders with `CLUSTER`; on origin/main the `fts`, `ngram`, `hot` and `vec` pools return a different row set per layout and `recency` a different order, and `spread_activation_memories()` keeps the oldest rows; all pass now. `test_pg_recall_ddl_upgrade.py` puts a database back on origin/main's function body and hash and asserts that opening a store installs the new body. The SQLite tests (`test_sqlite_recall_deterministic_ties.py`) pin the same order there. The hook queries and listings are pinned the same way: `tests_py/hooks/test_pg_hook_ties.py` and `tests_py/infrastructure/test_pg_listing_ties.py` (three heap layouts each) and `test_sqlite_listing_ties.py` (rowid order shuffled against `created_at`); all 21 fail at cfd03db9. Negative: where the newest-first choice differs from the heap order a run happened to read, individual results change; the benchmark section names them. A memory imported with an older `created_at` than its neighbours loses exact ties to them.
