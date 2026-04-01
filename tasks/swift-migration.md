# Long-Term Task: Port Cortex to Swift

**Status:** Not started
**Timeline:** Incremental, during compilation downtime
**Priority:** Side project — no deadline pressure
**Decision date:** 2026-04-02
**Motivation:** Apple opened Swift to Android (March 2026). Existing Swift projects (ai-prd-generator-plugin: 237 files, ai-architect-prd-builder) already have Clean Architecture, postgres-nio, XCFrameworks. Swift Cortex can be embedded as a framework rather than running as a separate MCP server.

---

## Phase 1: CortexCore Swift Package (Pure Math)

Start here — each module is self-contained, pure functions, perfect for compilation-time chunks.

- [ ] Set up Swift package with Clean Architecture (mirrors Python `core/`)
- [ ] Port `shared/` layer: `linear_algebra.py` → Accelerate/vDSP, `sparse.py`, `similarity.py`, `hash.py`, `text.py`, `categorizer.py`
- [ ] Port `thermodynamics.py` — heat, surprise, importance, valence, metamemory
- [ ] Port `decay_cycle.py` — stage-dependent cooling rates
- [ ] Port predictive coding (`hierarchical_predictive_coding.py`, `predictive_coding_flat.py`, `predictive_coding_gate.py`, `predictive_coding_signals.py`)
- [ ] Port `coupled_neuromodulation.py` — DA/NE/ACh/5-HT cascade (Doya 2002, Schultz 1997)
- [ ] Port `emotional_tagging.py` — Yerkes-Dodson curve (Wang & Bhatt 2024)
- [ ] Port `synaptic_tagging.py` — Frey & Morris 1997
- [ ] Port `oscillatory_clock.py` + `oscillatory_phases.py` — theta/gamma/SWR (Hasselmo 2005, Buzsaki 2015)
- [ ] Port `cascade.py` + `cascade_stages.py` + `cascade_advancement.py` — consolidation (Kandel 2001)
- [ ] Port `pattern_separation.py` + `separation_core.py` + `neurogenesis.py` — DG orthogonalization (Leutgeb 2007)
- [ ] Port `write_gate.py`, `memory_ingest.py`, `memory_decomposer.py`
- [ ] Port `scoring.py`, `temporal.py`, `query_intent.py`, `query_decomposition.py`
- [ ] Port `retrieval_dispatch.py`, `retrieval_signals.py`
- [ ] Set up Swift tests mirroring Python test suite

## Phase 2: Infrastructure Layer

- [ ] PostgreSQL via postgres-nio (already proven in ai-prd-generator-plugin)
- [ ] pgvector integration for Swift
- [ ] Embedding engine — CoreML conversion of all-MiniLM-L6-v2
- [ ] Reranker — CoreML conversion of FlashRank or ONNX Runtime Swift binding
- [ ] File I/O, config, scanner modules

## Phase 3: MCP Server / Integration

- [ ] Swift MCP server (evaluate available Swift MCP SDKs)
- [ ] Handler layer — composition roots wiring core + infrastructure
- [ ] Validation layer
- [ ] Hook system (session lifecycle, auto-capture)

## Phase 4: Distribution & Integration

- [ ] Package as XCFramework for embedding in ai-prd-generator-plugin and ai-architect-prd-builder
- [ ] Native macOS app wrapper (optional — menu bar agent?)
- [ ] iOS companion (optional — iCloud sync)
- [ ] Swift for Android target (when toolchain matures)

## Phase 5: Benchmark Parity

- [ ] Port all 6 benchmarks to Swift test targets
- [ ] Achieve parity with Python scores (LongMemEval 98%, LoCoMo 97.7%, BEAM 0.627)
- [ ] Decommission Python server

---

## Dependencies to Research

- Swift MCP SDK maturity
- CoreML conversion pipeline for sentence-transformers + FlashRank
- Swift Numerics vs Accelerate for sparse coding / K-SVD / OMP
- pgvector Swift client support

## Notes

- Python `core/` has zero I/O — translates 1:1 to Swift pure functions
- Existing ai-prd-generator-plugin already has postgres-nio, XCFrameworks, Clean Architecture
- 108 core modules, 1826 tests, 6 benchmarks to eventually port
- Phase 1 modules are 100-300 lines each, ideal for short focused sessions
