# Ecosystem Bounded-I/O Plan — 2026-06-09

Goal: every MCP boundary in the ecosystem (Cortex, automatised-pipeline, prd-spec-generator,
zetetic-team-subagents, session-optimizer) is bounded — no single response, load, or write can
blow up the MCP frame (~1MB ceiling, measured in query_workflow_graph comments) or machine RAM.
Prior art: ~/.claude/plans/sharded-popping-harbor.md (AIMD BatchWriter, calibration protocol).

Evidence base: 5-agent parallel audit, 2026-06-09. Reproduction: recall(15) → 815KB,
query_methodology → 262KB, both exceeded MCP tool-result limits.

## Phase 0 — Quick wins, hours, no design risk — DONE 2026-06-10 (gate green: 3143 passed + invariants 18/18)
- [x] Cortex: recall response ships `results` ≡ `memories` byte-identical duplicate → remove one. (~50% payload cut) — commit 1810d29
- [x] Cortex: `pg_store_queries.py:180` `get_all_memories_for_decay` SELECT * no LIMIT → route through `iter_memories_for_decay` unconditionally. — commit 1810d29
- [x] Cortex: query_methodology `firedTriggers` (55.6% of 262KB) — dedupe repeated triggers, cap content per trigger; stop re-embedding hot memories + triggers inside `context` string (shipped twice today). — commit 1810d29
- [x] session-optimizer: `stop-context-guard.py` `readlines()` loads whole transcript → reverse seek, bounded tail scan. — commits bc5db50 + 70411a8
- [x] zetetic-team-subagents: 19 doc strings "Optional MCP server: ai-architect" → automatised-pipeline; plugin.json/marketplace.json emails. — commits 2ff6f7a + e405ff6

## Phase 1 — Response budgets at every MCP boundary (the core fix)
- [x] Cortex: per-memory content truncation + total payload budget in recall / query_methodology / unified_search / wiki_read responses. Truncated items carry `truncated: true` + memory_id; full content retrievable by id (recall `memory_id`+`content_offset`, wiki_read `offset`). Budget MEASURED 2026-06-10: Claude Code 2.1.170 binary — MAX_MCP_OUTPUT_TOKENS default 25000 tokens × 4 chars/token = 100,000 chars compact JSON; verified char-exact against a rejected 324,429-char recall response. → core/response_budget.py, env override CORTEX_MEMORY_MAX_RESPONSE_CHARS.
  - Committed f28d1f1 (3173 tests).
  - Safety factor 0.75 on the host cap (→ 75,000 chars): Python `len()` counts code points, the host counts UTF-16 units — non-BMP chars diverge 2:1, so an exactly-full payload can overshoot. Factor reused from ai-prd-builder ContextManager.swift (`contextWindowSize * 0.75`, commit 462de01) per author direction; guarantees no overshoot up to 1/3 non-BMP fraction.
  - Priority-weighted water-filling (not a blind hard cap): surviving budget allocated proportionally to retrieval `score` (recall, unified_search) / `heat` (query_methodology hot memories) — ContextDecomposer allocation, ai-prd-builder 462de01: least relevant slots condense first; equal weights = plain max-min fairness; truncated detail stays dynamically loadable by id/offset.
- [x] automatised-pipeline (Rust): byte-budget at the 4 MCP boundaries (`bound_values` in new src/response_budget.rs, serialized-size accumulation) instead of the planned `take(MAX_QUERY_ROWS)` in `execute_query` — 70+ internal callers need complete result sets; truncating the shared primitive would corrupt graph resolution. LIMIT in find_related_out/in Cypher + LIMIT-injection for caller Cypher in query_graph (`limit_injected` flag); get_impact/get_processes arrays bounded with `truncated` + `*_total` fields (dependents_total pre-truncation = true blast radius). 219 tests green. — commit 6c99eb1; follow-up 967545d: docs + invariant test that UTF-8-byte counting ≥ UTF-16 units ⇒ inherently conservative, no safety factor needed (121+99 tests)
- [x] prd-spec-generator: Zod size contracts on PrdInputBundle (per-field char + element caps, rejection not truncation), MAX_CLARIFICATION_TURNS=50, MAX_PIPELINE_ERRORS=50 with FIFO eviction + `errors_dropped` counter. 607 tests green. — commit cd356ad; follow-up e43f41a fixed the aggregate overshoot (per-field shares summed to ~165% of the 100k cap): `boundFullStateResponse` sheds least-relevant detail first (grounding/validation blobs → oldest clarifications → section bodies; never the error trail), every shed observable in `__bounded.applied` with re-fetch hints via new `format:"grounding"`/`format:"validation"` selectors; JS `.length` is UTF-16 units = exact host match, no safety factor needed. 617 tests green.

## Phase 2 — Write-side hygiene (root cause of memory pollution) — design + code DONE 2026-06-10 (3207 tests; bench gate in flight)
Design: docs/provenance/bounded-io-phase2-design.md. Three measured inversion mechanisms, not one:
M1 trigger-injection bypass (PRIMARY live — 317 garbage keyword triggers, single-substring
matching, hardcoded 0.9 prepend, unbounded), M2 WRRF multi-pool amplification,
M3 source/store_type/confidence output-only.
- [x] post_tool_capture: gist + pointer (NO hard cap per 2026-06-10 user directive). core/gist_extraction.py (GIST_BUDGET=3000 = measured p90 curated length) + infrastructure/artifact_store.py (content-addressed ~/.claude/methodology/artifacts/); raw output one Read away; artifact failure falls back to full content.
- [x] Fix scoring inversion: (a) hot/recency CTEs exclude source='post_tool_capture' (mechanical freshness ≠ importance, categorical); (b) final_score × confidence (Kraaij 2002 document prior, rate_memory feedback channel); (c) trigger hygiene — write_post_store skips prospective extraction for auto sources, check_trigger word-boundary matching, inject_triggered_memories respects LOW_SIGNAL_TAGS + source + max_inject cap + injected:true, created_by provenance column, 319 garbage keyword triggers deactivated (reversible). Repro tests fail pre-fix / pass post-fix (severity verified via stash).
- [x] backfill/import: gist_oversized_content choke point in backfill_helpers before remember_handler (both import_sessions + backfill_memories).
- Follow-ups recorded in design doc: CLS consolidation needs same gist discipline (live example: raw blob promoted to semantic "Convention"); bulk migration of existing 6,799 raw blobs deferred (scoring de-bias makes their rank honest); post_tool_capture.py at 411 lines (>300, pre-existing) needs split; recall response score semantics post-rerank.

## Phase 3 — Concurrency governors — DONE 2026-06-10
- [x] Cortex mcp_client_pool: max-connections (LRU-evict idle / fail-fast McpConnectionError; cap CORTEX_MEMORY_MCP_POOL_MAX_CONNECTIONS, auto = max(2, cpu_count), pending RSS calibration). Per-server cap was ALREADY implemented (upstream_governor threading.Semaphore — asyncio primitive would break across worker loops); verified with regression tests instead of duplicated. — commit 41fb0a3 (6 new tests, infra 310)
- [x] automatised-pipeline: plan premises didn't hold (no JSON deserialization — embedded lbug DB handle; single-threaded stdin loop = single-flight free; GraphStore !Sync) → thread_local path-keyed Rc<GraphStore> cache, fingerprint (mtime+bytes) invalidation, 9 read tools cached, 6 write tools deliberately uncached. — commit 682185f (tests 327→331)
- [x] prd-spec-generator: start_pipeline semaphore (PRD_MAX_CONCURRENT_RUNS=8, structured retryable rejection — no queue, it would hold the MCP connection); RunStore TTL 30min + max-runs 64 (≈12.8MB ceiling from measured 100k per-run bound), terminal-only LRU eviction, injected clock, observable evicted counter; EvidenceRepository is SQLite (plan said in-memory — mismatch reported): pruneRunEvidence wired to run eviction + MAX_EVIDENCE_ROWS=10k standalone retention. — commit e833686 (tests 617→629)

## Phase 4 — Execute sharded-popping-harbor plan (constant-memory pipeline)
2026-06-10 audit (Phase-3 lesson applied — verify premises before implementing):
most of this plan ALREADY LANDED in prior sessions; the checkboxes below were stale.
- [x] Phase A core ports — EXISTS: core/streaming/{ports,adaptive_controller,backpressure_pipeline,adaptive_writer,calibrated}.py + infrastructure/{batch_sinks,staging_resolve_sink,stream_sources,pooled_sink}.py; A3 schema (uq_relationships_directed + ingest_progress) in pg_schema.py; tests test_adaptive_controller/test_backpressure_pipeline/test_staging_resolve_sink.
- [x] Phase B calibration — EXISTS: benchmarks/streaming_calibration/run.py + results.json (7 batch sizes × 20 batches, per-kind row_bytes/p99/rows_per_s measured).
- Phase C status per item:
  - [x] C1 ingest writers — StagingResolveSink wired in ingest_codebase_writers.py
  - [x] C2 cypher fetchers — generator yields; OFFSET retained with documented I-readstable precondition (Kuzu read-only during ingest)
  - [x] C3 Kuzu async paging (workflow_graph_source_ast.py, moved to infrastructure/): timeout on every cross-loop future.result (untimed at :44 = the Lamport H4 hang; AP_SYNC_RESULT_TIMEOUT_S=3900 sourced from mcp_client 3600s in-loop ceiling + 300s drain margin); per-query accumulators (89 edge / 21 symbol queries) → generators. FINDING: AP has no cursor — one query's rows is the smallest streamable unit; iter_symbols/iter_ast_edges are the seam for C5 consumers. — DONE 2026-06-10
  - [x] C4 sleep_compute — iter_memories_for_decay wired (Phase 0 commit 1810d29 + sleep.py:36)
  - [x] C5 viz monolith — memory nodes emitted then DISCARDED from builder (structural-size retention), tiles + /api/memories pagination serve them; memory_entity_edges skipped from base build
  - [x] C6 /api/quadtree — read_all_positions was already replaced by iter_positions_chunked (keyset 50k) + per-chunk Arrow record batches; remaining materialization was the RESPONSE (BufferOutputStream accumulated the whole IPC frame, gzip.compress made a 2nd full copy) → streamed per-batch through gzip to the socket, constant-memory in node count (user directive 2026-06-10: optimize like the others, no deferral). — DONE 2026-06-10

## Deferred decisions (user)
- [ ] Push the 5 unpushed rename commits (Cortex×2, automatised-pipeline, prd-spec-generator, zetetic-team-subagents).
- [ ] Agent duplication: zetetic-team-subagents vs reasoning plugin export identical 116 agents — pick canonical, make other a mirror.
- [ ] Restart Cortex MCP server to live-verify ingest fix (no hot-reload).

## Review

### Phase 2 (2026-06-10) — write-side hygiene + scoring inversion
- Investigation upgraded the prior verdict: the live inversion was PRIMARILY
  trigger injection (M1), a post-ranking enrichment invisible to scorer-only
  analysis — 319 garbage keyword triggers (harvested from raw dumps, substring
  matched) each prepending FTS hits at a hardcoded 0.9. WRRF multi-pool
  amplification (M2) and the source/confidence structural gap (M3) sat beneath it.
- Gate results: full suite 3207 passed (baseline 3173 + exactly 34 new tests);
  repro tests fail pre-fix / pass post-fix (verified via git stash); ruff clean.
- Historical Phase 2 validation benchmarks (clean DB; protocol-specific, not current headlines): LongMemEval R@10 98.4% (=), MRR 0.916 (≥0.9124);
  LoCoMo MRR 0.828 (=0.8279), R@10 94.1% (94.35% post-fix reference, 1982 vs 1986 Qs);
  BEAM 100K re-based to 395 Qs — A/B old 0.502 vs new 0.501, regression-free.
- Production data ops: 319 keyword triggers deactivated (reversible);
  created_by column arrives at server restart (DDL); 6,799 existing raw blobs
  left in place (scoring de-bias makes their rank honest; migration deferred).
- Lesson (Cortex memory 4195543): audit post-ranking enrichment paths when
  diagnosing ranking inversions; gate write-side extractors by source; the
  write gate itself was blinded by pollution (rejected the curated lesson at
  novelty 0.16).

### Phase 3 (2026-06-10) — concurrency governors
- 3 repos in parallel (engineer agents), all committed, nothing pushed:
  Cortex 41fb0a3, automatised-pipeline 682185f, prd-spec-generator e833686.
- Two plan items did not match codebase reality and were correctly re-derived
  instead of forced: (a) Cortex per-server cap already existed
  (upstream_governor; an asyncio.Semaphore would break across worker loops) —
  verified, not duplicated; (b) Rust GraphStore "re-deserialization" never
  existed — the cost was per-request DB-handle opens on a single-threaded
  !Sync store, so thread_local Rc cache + fingerprint invalidation, not
  OnceLock<Arc<RwLock>>. Lesson: audit-derived plan items inherit the
  audit's guesses; re-verify premises against the code before implementing.
- All limits configurable + source-commented; unmeasured defaults honestly
  marked with their calibrating measurement (child RSS for pool cap, p99
  in-flight for run semaphore, complete→last-read gap for RunStore TTL).
- Gates: Cortex infra 310 + full suite green; Rust 331; TS 629. No silent
  caps anywhere — every rejection/eviction is structured + observable.
