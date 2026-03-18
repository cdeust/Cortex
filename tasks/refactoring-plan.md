# Codebase Refactoring Plan

Rules: Clean Architecture, SOLID, 300 lines max per file, 40 lines max per method,
reverse dependency injection, factory injection, no dead code.

## Files Over 300 Lines (31 total, priority order)

### Critical (>700 lines)
1. `infrastructure/memory_store.py` (1386) — Split: schema/migrations, CRUD, search/FTS, embeddings
2. `handlers/run_pipeline.py` (851) — Split: pipeline stages, orchestration, reporting
3. `handlers/consolidate.py` (847) — Split: decay, plasticity, compression, CLS, sleep steps
4. `core/hierarchical_predictive_coding.py` (815) — Split: sensory, entity, schema levels + gate + compat signals
5. `__main__.py` (737) — Extract: server config, handler registry, transport setup

### High (500-700 lines)
6. `core/replay.py` (675) — Split: context restoration (existing API) + SWR replay dynamics
7. `server/http_server.py` (592) — Split: routes, dashboard data, visualization
8. `core/schema_engine.py` (585) — Split: schema model, matching, evolution
9. `core/synaptic_plasticity.py` (568) — Split: LTP/LTD, STDP, stochastic transmission
10. `handlers/remember.py` (560) — Split: write gate, storage, neuromodulation integration
11. `core/oscillatory_clock.py` (547) — Split: theta/gamma/SWR state, phase logic
12. `core/unified_graph_builder.py` (500) — Split: node builders, edge builders, layout

### Medium (300-500 lines)
13. `handlers/recall.py` (460) — Split: WRRF fusion, reranking, recency/ordering
14. `core/metacognition.py` (432) — Split: metrics, analysis, reporting
15. `core/interference.py` (429) — Split: detection, resolution, orthogonalization
16. `core/coupled_neuromodulation.py` (426) — Split: channels, coupling, modulation
17. `core/tripartite_synapse.py` (414) — Split: calcium, D-serine, metabolic gating
18. `core/dendritic_clusters.py` (391) — Split: branch model, integration, priming
19. `handlers/seed_project.py` (382) — Split: scanning, extraction, ingestion
20. `core/sparse_dictionary.py` (380) — Split: OMP, K-SVD, activation
21. `core/two_stage_model.py` (379) — Split: hippocampal, cortical, transfer
22. `core/fractal.py` (368) — Split: clustering, hierarchy, navigation
23. `handlers/backfill_memories.py` (366) — Split: scanning, parsing, import
24. `core/pattern_separation.py` (364) — Split: DG orthogonalization, neurogenesis
25. `shared/types.py` (363) — Split: memory types, profile types, config types

### Benchmark files
26. `benchmarks/longmemeval/run_benchmark.py` (945) — Split: data loading, retriever, evaluation, reporting
27. `benchmarks/beam/run_benchmark.py` (549) — Wire shared retriever, split data/eval
28. `benchmarks/locomo/run_benchmark.py` (527) — Wire shared retriever, split data/eval
29. `benchmarks/episodic/run_benchmark.py` (396) — Wire shared retriever
30. `benchmarks/evermembench/run_benchmark.py` (384) — Wire shared retriever
31. `benchmarks/memoryagentbench/run_benchmark.py` (297) — OK (under limit)

## Method audit needed
After splitting files, scan for methods >40 lines and extract helper functions.

## Dead code cleanup
- Old `benchmarks/shared_retriever.py` (replaced by `benchmarks/lib/`)
- Backward-compat comments in `hierarchical_predictive_coding.py`
- Unused `retrieve_multihop` in LoCoMo retriever
