# Bounded-I/O Phase 2 Design — Write-Side Hygiene + Scoring Inversion Fix

Date: 2026-06-10. Evidence: Explore-agent root-cause investigation (transcript
aeaa2cd3279525a1b), recall-dump mining (two 240KB live recall payloads), and
direct production-DB measurement (psql cortex, 2026-06-10). Status: design
approved by the user directives recorded in
~/.claude/memories/checkpoints/bounded-io-phase1-checkpoint.md.

## User directives (binding)

1. NO blunt hard caps — "Hard limit with no dynamic sizing or loading just
   truncates relevant info." Replace raw-blob storage with **gist + pointer to
   the raw artifact, dynamically loadable**.
2. Curated memories must outrank raw dumps (fix the 60× scoring inversion).
3. Benchmark before/after (LongMemEval, LoCoMo, BEAM) — no regression accepted.

## Measured evidence (production DB, 2026-06-10)

| Quantity | Value | Source |
|---|---|---|
| post_tool_capture rows | 6,799 (15 MB; p50 1,125 / p90 4,264 / max 123,639 chars) | psql cortex, memories by source |
| Curated rows (non-auto, non-ingest, non-backfill) | 68 (p50 1,251 / **p90 3,041** / max 3,496 chars) | same |
| Active keyword_match prospective triggers | **317**, sampled conditions 100% garbage (shell fragments, regex shards, dupes) | psql cortex, prospective_memories |
| Live recall scores | all 16 returned items flat **0.9** — zero discrimination | recall-dump mining |
| recall response `source` field | **absent** — fix unverifiable from payload without exposing it | same |

## Three inversion mechanisms (ranked by live impact)

### M1 — Prospective-trigger injection bypass (PRIMARY, live-confirmed)

`handlers/recall_helpers.py:inject_triggered_memories` prepends FTS matches of
every fired trigger at **hardcoded score 0.9**, ahead of all WRRF-ranked
results, unbounded (317 triggers × 3 FTS matches each). Trigger conditions are
garbage because `core/write_post_store.py:21` runs
`extract_prospective_intents` over EVERY stored memory — including raw
post_tool_capture dumps whose stdout contains "TODO"/"later"/"make sure".
`core/prospective.py:check_trigger` keyword matching is `any(kw in
content_lower)` — single-keyword **substring** containment ("ask" fires on
"task"), so dozens of triggers fire on every query. All 16 items in the live
recall dumps were trigger-injected; the "curated at 0.015" items are real WRRF
results pushed below the injected wall.

### M2 — WRRF multi-pool amplification (Explore-agent verdict)

`recall_memories()` (infrastructure/pg_schema.py:741-943) fuses 5 signal pools.
Fresh large auto-captures hit 4–5 pools (vector/fts/ngram + heat/recency via
mechanical freshness); old curated lessons hit 1–2 and fall out of the heat
pool via min_heat decay. WRRF sums per-pool contributions → multi-pool
membership compounds. Heat and recency for auto-captures are artifacts of
capture frequency (one write per tool call, baseline_heat=1.0 + surprise
boost), not evidence of importance — including them in those pools is a
measurement error, not a tuning problem.

### M3 — Structural gap: source/store_type/confidence are output-only

`c.source`, `c.store_type`, `c.confidence` (metamemory, feedback-driven via
rate_memory) exist on the memories table and in the RETURNS clause but never
enter any scoring CTE. There is no channel by which curation quality or user
feedback can influence rank. Constraint discovered: benchmarks use `source` to
carry ground-truth session IDs (benchmarks/lib/_e2_loaders.py), so scoring
logic must key on exactly `source = 'post_tool_capture'` — any broader
source taxonomy would touch benchmark memories.

## Fixes

### F1 — Trigger hygiene (M1)

| Change | File | Rationale |
|---|---|---|
| Skip prospective extraction for auto sources (`post_tool_capture`) | core/write_post_store.py | Mechanical tool output is not user intent. Categorical, no constants. |
| `created_by` column on prospective_memories (`'create_trigger'` / `'auto_extract'`; existing rows `''`) | infrastructure/pg_schema.py migration | Future cleanups can distinguish user triggers from harvested ones. |
| keyword_match requires **word-boundary** match (`\b`) | core/prospective.py check_trigger | Substring matching is a correctness bug ("ask" in "task"), not tuning. |
| Injection: skip memories with source='post_tool_capture'; cap total injected at p_max_results; tag `"injected": true` | handlers/recall_helpers.py | Injection must not exceed the requested k (tool contract) and must be observable. 0.9 stays but is now labeled metadata, not a covert rank. |
| Data cleanup: `UPDATE prospective_memories SET is_active=false WHERE trigger_type='keyword_match'` | one-time, production DB | Sampled 100% garbage; reversible (deactivation, not deletion); user triggers re-creatable via create_trigger. |

### F2 — WRRF de-bias + confidence prior (M2+M3)

In `recall_memories()`:

1. `hot` and `recency` CTEs add `AND c.source <> 'post_tool_capture'` —
   removes the two mechanical-freshness pool memberships; auto-captures still
   compete on content (vector/fts/ngram). Categorical de-bias, no constant.
2. `tag_boosted` final score multiplied by `c.confidence` — document-prior
   form (Kraaij, Westerveld & Hiemstra 2002, "The importance of prior
   probabilities for entry page search", SIGIR — priors multiply query
   likelihood). `confidence` defaults 1.0 (multiplicative identity) and is
   updated only by rate_memory feedback ⇒ structurally benchmark-neutral and
   data-driven, no invented constant.
3. Expose `source` in the recall response item dict (verifiability — the
   mining run proved the fix is otherwise invisible in the payload).

Benchmark-neutrality argument: benchmark fixtures never write
source='post_tool_capture', never create prospective triggers, never set
confidence ≠ 1.0. All three changes are identity transforms on benchmark data.
Still verified by running all three benchmarks (no-regression rule).

### F3 — post_tool_capture gist + pointer (M2 root cause, write side)

New `core/gist_extraction.py` (pure logic) + `infrastructure/artifact_store.py`
(I/O), wired in the hook (hooks are allowed to import core + infrastructure).

- Output ≤ GIST_BUDGET chars → store as today (no artifact).
- Output > GIST_BUDGET → write full raw output to
  `~/.claude/methodology/artifacts/<yyyy-mm>/<sha256[:16]>.md`
  (content-addressed ⇒ repeated identical outputs dedup); memory content =
  header + reference line + deterministic gist + pointer line
  `**Artifact:** \`<path>\` (<N> chars full output)`.
- Gist composition (deterministic, no LLM — hook must stay <200ms): head and
  tail slices of the output + all lines matching _HIGH_VALUE_PATTERNS
  (error/traceback/failed/pass — the retrieval hooks), within budget.
- **GIST_BUDGET = 3,000 chars** — source: measured p90 of curated memory
  length on production DB 2026-06-10 (3,041 chars, n=68). Makes auto-captures
  size-comparable to curated content, removing the ts_rank_cd length-frequency
  bias (M2/H5). Not a truncation: the full artifact is one `Read` away — the
  pointer is a plain file path, loadable by the Read tool, zero new MCP
  surface.
- Same gate applied in backfill/import extraction before remember_handler.

### Out of scope (recorded, not silently dropped)

- CLS consolidation promotes raw blobs to semantic store (live example:
  memory 3895686 "Convention" wrapping a Write dump) — needs the same gist
  discipline in dual_store_cls abstraction; Phase 2 follow-up.
- Migration of the existing 6,799 raw blobs to gist+pointer — F2 makes their
  ranking honest regardless of size; bulk migration deferred.
- recall response `score` semantics post-rerank (flat scores) — observability
  follow-up.

## Verification protocol

1. Reproduction tests (new, PG-backed): (a) fresh oversized auto-capture +
   30-day-old curated lesson, lesson-topic query ⇒ curated must outrank
   (fails before F2, passes after); (b) garbage keyword trigger + query
   containing a partial-word match ⇒ no injection after F1.
2. Full suite: `.venv/bin/pytest tests_py -q` (3,173+ passing baseline).
3. Benchmarks: LongMemEval s, LoCoMo, BEAM on clean DB vs the then-recorded
   protocol-specific baselines (R@10 98.4 / 94.35 post-fix, BEAM 0.591).
   These are historical regression gates, not current publication headlines.
   No regression accepted.
4. open_visualization + commit per repo; PUSH NOTHING.
