# Benchmark Improvement Plan — Research-Driven

Based on arxiv research across 20+ papers (2024-2026). Each fix targets a specific benchmark gap.

## Priority 1: Temporal Retrieval (LoCoMo 0.362→0.7+, BEAM temporal 0→0.15+)

**Papers**: Chronos (2603.16862), Memory-T1 (2512.20092), Timely (Khoj), TempRetriever (2502.21024), Re3 (2509.01306)
**Common approach**: Dual-path FTS content + SQL timestamp filter, `[Date: ...]` prefix injection, hardcoded weights

### Fix A: Date prefix injection (lowest effort, highest immediate impact)
- Prepend `[Date: YYYY-MM-DD]` to memory content at ingest time in benchmark retrievers
- This makes date metadata visible to both embedding similarity and BM25/FTS
- Standard technique for making date metadata visible to retrieval signals

### Fix B: Temporal proximity WRRF signal
- Parse temporal expressions in queries → resolve to `(start_ts, end_ts)`
- Score: `temporal_score = exp(-|memory_ts - target_ts| / scale)` where scale = 7 days for "last week", 30 for "last month"
- Add as WRRF signal with weight gated by temporal intent score

### Fix C: SQL pre-filter for temporal queries
- When intent is TEMPORAL, first filter candidates by time window before running full WRRF
- Prevents semantically similar but temporally wrong memories from dominating

---

## Priority 2: Multi-Hop Retrieval (LoCoMo multi 0.648→0.85+, EverMem MH 0→0.3+)

**Papers**: HippoRAG (NeurIPS 2024), CoRAG (NeurIPS 2025), IRCoT (ACL 2023), Query Decomposition (2507.00355)

### Fix A: Query decomposition + merged retrieval (lowest effort)
- When entity count > 1 or multi-hop intent detected, split into sub-queries (one per entity)
- Run retrieval for each sub-query independently
- Merge + deduplicate + re-rank with FlashRank
- Paper reports +36.7% MRR improvement

### Fix B: Entity-bridged iterative retrieval (IRCoT-lite)
- After first retrieval, extract entities from top-K results
- Identify bridge entities (in results but NOT in original query)
- Second retrieval pass using bridge entities as queries
- Merge all results and re-rank
- Paper reports +21 points retrieval recall

### Fix C: PPR over knowledge graph (HippoRAG)
- Adapt spreading_activation.py to use Personalized PageRank
- Seed from query entities, traverse KG via PPR
- Add PPR scores as WRRF signal
- Single retrieval step achieves multi-hop, 10-20x faster than iterative

---

## Priority 3: Knowledge Updates & Contradiction (BEAM knowledge 0→0.5+, contradiction 0→0.15+)

**Papers**: Zep/Graphiti (2501.13956), Mem0 (2504.19413), LIGHT/BEAM (2510.27246), TSM (2601.07468), Nemori (2508.03341)

### Fix A: Entity-attribute-value supersession (quick win)
- Extract (subject, attribute, value) triples from memory content
- When new memory shares (subject, attribute) with existing but different value → supersession
- Mark old as `superseded_by = new_id`, boost new memory's heat
- On recall, prefer non-superseded memories for each entity-attribute pair

### Fix B: Fact scratchpad (LIGHT-inspired)
- Per-project key-value store: `(entity, attribute, current_value, memory_id, updated_at)`
- Updated on every `remember()` when entity-attribute changes detected
- Prepended to recall results as authoritative current facts

### Fix C: Temporal validity columns (Zep-inspired)
- Add `valid_from` / `valid_until` to memory schema
- Default recall filters to `valid_until IS NULL` (current facts only)
- Temporal queries can access historical facts

---

## Quick Test Commands (scoped for fast iteration)

```bash
# LoCoMo temporal only (2 convs, ~30 questions, ~1 min)
python3 benchmarks/locomo/run_benchmark.py --limit 2 --verbose

# BEAM 5 conversations (~2 min)
python3 benchmarks/beam/run_benchmark.py --split 100K --limit 5

# LongMemEval 50 questions (~1 min)
python3 benchmarks/longmemeval/run_benchmark.py --variant s --limit 50

# Full quick suite
bash benchmarks/quick_test.sh
```

## Implementation Order

1. Date prefix injection → quick test all benchmarks
2. Temporal proximity signal → quick test LoCoMo/BEAM
3. Query decomposition for multi-hop → quick test LoCoMo/EverMem
4. Entity supersession → quick test BEAM
5. Full benchmark run to validate
