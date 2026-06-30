# Cortex — Methodology Agent

Persistent memory and cognitive profiling MCP server for Claude Code. Python 3.10+ with FastMCP, Pydantic, and numpy.

## Problem Statement

Claude Code sessions generate rich behavioral data (tool usage, session duration, first messages, keyword patterns) but this data is lost between sessions. Cortex mines this history to build a cognitive profile per domain and provides a thermodynamic memory system with heat/decay, predictive coding write gates, causal graphs, and intent-aware retrieval.

## Code Quality Rules

- **300 lines max** per file — split into focused modules when exceeded
- **40 lines max** per method — extract helpers for readability
- **Clean Architecture** — inner layers never import outer layers
- **SOLID principles** — single responsibility, dependency inversion
- **Reverse dependency injection** — core defines interfaces, infrastructure implements
- **Factory injection** — handlers compose core + infrastructure via factories
- **No dead code** — remove unused functions, backward-compat shims, commented-out code
- **No unwired code** — if it's built, it must be called somewhere

See `docs/provenance/refactoring-plan.md` for the file-by-file split plan (31 files over 300 lines).

## Research Methodology

When implementing neuroscience-inspired mechanisms, always consult primary research papers before coding. Use [arxivisual](https://arxivisual.com) to explore and understand referenced papers visually — it provides detailed visual explanations of arxiv papers. Paper references are listed in `docs/adr/`. The implementation should follow the computational model described in the paper, not just the metaphor. Every new mechanism must cite its source paper and match the paper's equations/algorithms as closely as practical for a memory system operating at hours/days timescale (vs milliseconds in biology).

## Architecture

Clean Architecture with concentric layers. Inner layers never import outer layers.

```
SERVER → HANDLERS → CORE ← SHARED
                      ↓
                INFRASTRUCTURE → SHARED
```

Handlers are the **composition roots**: they wire infrastructure (I/O) to core (logic) and are the only layer allowed to import both.

### Dependency Rules

| Layer | May Import | Must NOT Import |
|---|---|---|
| **shared/** | Python stdlib only | core, infrastructure, handlers, server |
| **core/** | shared/ only | infrastructure, handlers, server, os/pathlib |
| **infrastructure/** | shared/, Python stdlib | core, handlers, server |
| **validation/** | shared/, errors/ | core, infrastructure, handlers |
| **errors/** | nothing | everything |
| **handlers/** | core, infrastructure, shared, validation, errors | server |
| **server/** | handlers, errors | core, infrastructure (except via handlers) |
| **hooks/** | infrastructure, core, shared | server |

### Module Inventory

**shared/** — Pure utility functions (11 modules)
- `text.py` — Keyword extraction with stopword filtering
- `categorizer.py` — 10-category work classification
- `similarity.py` — Jaccard similarity coefficient
- `hash.py` — DJB2 non-cryptographic hash
- `project_ids.py` — Path ↔ project ID ↔ label ↔ domain ID conversion
- `yaml_parser.py` — Lightweight YAML frontmatter parser
- `types.py` — Pydantic models (ProfilesV2, DomainProfile, CognitiveStyle, etc.)
- `types_profiles.py` — Profile-specific Pydantic models
- `linear_algebra.py` — Dense vector math via numpy (dot, norm, cosine, project, clamp)
- `sparse.py` — Sparse vector operations (dict-based, topK, conversions)
- `memory_types.py` — Runtime validation types for the memory subsystem

**core/** — Pure business logic, zero I/O (108 modules)

*Cognitive Profiling:*
- `domain_detector.py` — 3-signal weighted domain classification
- `context_generator.py` — Human-readable profile text generation
- `pattern_extractor.py` — Entry points, recurring patterns, tool preferences, session shape
- `style_classifier.py` — Felder-Silverman cognitive style classification + EMA update
- `style_classifier_ema.py` — EMA update logic for style classification
- `bridge_finder.py` — Cross-domain connection detection (structural + analogical)
- `blindspot_detector.py` — Category, tool, and pattern gap analysis
- `profile_builder.py` — Profile orchestration (assembles all core modules)
- `profile_assembler.py` — Profile assembly from extracted components
- `blindspot_patterns.py` — Blind spot pattern definitions
- `session_shape.py` — Session shape analysis
- *(graph construction — `graph_builder*.py`, `graph_quality_scorer.py` — was extracted to the standalone **cortex-viz** MCP along with the HTTP/3D visualization stack)*

*Behavioral Interpretability:*
- `sparse_dictionary.py` — Behavioral feature dictionary learning (OMP sparse coding, K-SVD)
- `sparse_dictionary_learning.py` — Dictionary learning algorithms
- `sparse_dictionary_activation.py` — Activation computation
- `persona_vector.py` — 12D persona vector with drift detection and context steering
- `behavioral_crosscoder.py` — Cross-domain behavioral feature persistence detection
- `attribution_tracer.py` — Pipeline attribution graph via perturbation-based tracing

*Memory Thermodynamics:*
- `thermodynamics.py` — Heat, surprise, importance, valence, metamemory
- `hierarchical_predictive_coding.py` — 3-level Friston free energy gate (sensory/entity/schema) replacing flat 4-signal
- `predictive_coding_flat.py` — Flat predictive coding fallback
- `predictive_coding_gate.py` — Gate decision logic
- `predictive_coding_signals.py` — Signal computation for predictive coding
- `coupled_neuromodulation.py` — DA/NE/ACh/5-HT coupled cascade with cross-channel effects (Doya 2002, Schultz 1997)
- `neuromodulation_channels.py` — Individual neuromodulator channel definitions
- `emotional_tagging.py` — Amygdala-inspired priority encoding with Yerkes-Dodson curve (Wang & Bhatt 2024)
- `synaptic_tagging.py` — Retroactive promotion of weak memories sharing entities (Frey & Morris 1997)
- `curation.py` — Active curation logic (merge, link, create decisions)
- `engram.py` — Memory trace structure (Josselyn & Tonegawa 2020)
- `decay_cycle.py` — Thermodynamic cooling with stage-dependent rates
- `tripartite_synapse.py` — Astrocyte calcium dynamics, D-serine LTP facilitation, metabolic gating (Perea 2009)
- `tripartite_calcium.py` — Calcium dynamics computation for tripartite synapse
- `write_gate.py` — Write gate decision logic
- `write_post_store.py` — Post-store processing after memory write
- `memory_ingest.py` — Memory ingestion pipeline
- `memory_decomposer.py` — Decompose complex memories into atomic units
- `compression.py` — Full-text → gist → tag compression
- `staleness.py` — File-reference staleness scoring
- `response_budget.py` — Bounded MCP responses: total payload budget (measured 100k-char Claude Code MAX_MCP_OUTPUT_TOKENS cap × 0.75 UTF-16-divergence safety factor) + priority-weighted water-filling (budget proportional to retrieval score/heat, least relevant condensed first); truncated items keep ids for dynamic fetch-by-id
- `gist_extraction.py` — Deterministic gist (head + signal lines + tail) for oversized auto-captures; GIST_BUDGET = measured p90 curated memory length; full raw output lives in a filesystem artifact, one Read away (no truncation)

*Oscillatory & Cascade:*
- `oscillatory_clock.py` — Theta/gamma/SWR phase gating (Hasselmo 2005, Buzsaki 2015)
- `oscillatory_phases.py` — Phase definitions and gating logic
- `cascade.py` — Consolidation stages: LABILE → EARLY_LTP → LATE_LTP → CONSOLIDATED (Kandel 2001)
- `cascade_stages.py` — Stage definitions and transitions
- `cascade_advancement.py` — Stage advancement logic
- `pattern_separation.py` — DG orthogonalization + neurogenesis analog (Leutgeb 2007, Yassa & Stark 2011)
- `separation_core.py` — Core orthogonalization algorithms
- `neurogenesis.py` — Neurogenesis analog for pattern separation
- `schema_engine.py` — Cortical knowledge structures with Piaget accommodation (Tse 2007, Gilboa & Marlatte 2017)
- `schema_extraction.py` — Schema extraction from memories
- `interference.py` — Proactive/retroactive interference detection + sleep orthogonalization
- `interference_detection.py` — Interference detection algorithms
- `homeostatic_plasticity.py` — Synaptic scaling + BCM threshold (Turrigiano 2008, Abraham & Bear 1996)
- `homeostatic_health.py` — Homeostatic health metrics
- `dendritic_clusters.py` — Branch-specific nonlinear integration + priming (Kastellakis 2015)
- `dendritic_computation.py` — Branch-specific computation logic
- `two_stage_model.py` — Hippocampal-cortical transfer protocol (McClelland 1995)
- `two_stage_transfer.py` — Transfer protocol execution
- `emergence_tracker.py` — System-level metrics: forgetting curve, spacing effect, schema acceleration
- `emergence_metrics.py` — Emergence metric definitions
- `ablation.py` — Lesion study framework (29 ablatable units spanning the 24 neuroscience-grounded mechanisms)
- `active_forgetting.py` — Two independent dopaminergic forgetting circuits: permanent Rac1 trace erosion (chronic interference × stage vulnerability) + transient DAMB retrieval block (Davis & Zhong 2017, Sabandal et al. 2021)
- `ablation_report.py` — Ablation report generation

*Consolidation:*
- `consolidation_engine.py` — Orchestrates decay, compression, CLS, causal discovery
- `dual_store_cls.py` — Episodic → semantic memory consolidation (CLS)
- `dual_store_cls_abstraction.py` — CLS abstraction extraction
- `causal_graph.py` — PC Algorithm for causal discovery
- `reconsolidation.py` — Memory updating on access
- `replay.py` — Hippocampal replay for memory consolidation
- `replay_types.py` — Replay type definitions
- `replay_selection.py` — Replay candidate selection
- `replay_execution.py` — Replay execution logic
- `replay_formatting.py` — Replay result formatting
- `sleep_compute.py` — Dream replay, cluster summarization, re-embedding, auto-narration
- `synaptic_plasticity.py` — LTP/LTD Hebbian learning + STDP causal direction + stochastic transmission + phase-gated plasticity (Hebb 1949, BCM 1982, Bi & Poo 1998, Markram 1998)
- `synaptic_plasticity_hebbian.py` — Hebbian learning algorithms
- `synaptic_plasticity_stochastic.py` — Stochastic transmission
- `microglial_pruning.py` — Complement-dependent edge elimination + orphan archival (Wang et al. 2020)

*Retrieval & Navigation:*
- `query_intent.py` — Intent classification (temporal/causal/semantic/entity/knowledge_update/multi_hop) + weight profiles
- `query_decomposition.py` — Multi-entity query splitting + entity extraction
- `retrieval_dispatch.py` — 3-tier dispatch (simple/mixed/deep) + WRRF weight computation
- `retrieval_signals.py` — Retrieval signal definitions and computation
- `query_router.py` — Query routing to appropriate retrieval tier
- `pg_recall.py` — PostgreSQL recall orchestration
- `reranker.py` — FlashRank ONNX cross-encoder reranking (client-side post-PG)
- `scoring.py` — BM25, n-gram, keyword scoring (reference; PG does this server-side)
- `temporal.py` — Date parsing, distance decay, recency boost (reference; PG does this server-side)
- `spreading_activation.py` — Collins & Loftus 1975 semantic priming over entity graph
- `hdc_encoder.py` — 1024D bipolar HDC (bind/bundle/permute/similarity)
- `cognitive_map.py` — Successor Representation co-access graph + 2D projection
- `hopfield.py` — Hopfield network for content-addressable recall
- `fractal.py` — Hierarchical clustering (L0/L1/L2 levels)
- `fractal_clustering.py` — Clustering algorithm implementation
- `enrichment.py` — Doc2Query synthetic queries + concept synonym expansion
- `concept_vocabulary.py` — Concept vocabulary for synonym expansion
- `sensory_buffer.py` — Bounded pre-consolidation ring buffer
- `knowledge_graph.py` — Entity and relationship extraction
- `prospective.py` — Trigger-based proactive recall (keyword, time, file, domain)
- `memory_rules.py` — Neuro-symbolic rules system (soft/hard filtering)

*Analysis & Narrative:*
- `narrative.py` — Story generation from memories
- `metacognition.py` — Self-reflection on memory system performance
- `metacognition_analysis.py` — Metacognition analysis algorithms
- `session_critique.py` — Post-session analysis and improvement suggestions
- `session_critique_format.py` — Session critique output formatting
- `session_extractor.py` — Extracts memories from session transcripts

**infrastructure/** — All I/O (21 modules)
- `config.py` — Centralized path constants via pathlib
- `file_io.py` — Generic JSON/text read/write operations
- `profile_store.py` — profiles.json persistence
- `session_store.py` — session-log.json persistence
- `brain_index_store.py` — brain-index.json reader
- `scanner.py` — Discovers memories + conversations from ~/.claude/
- `scanner_parse.py` — JSONL conversation parsing
- `mcp_client.py` — Async MCP client over stdio (JSON-RPC 2.0, version negotiation)
- `mcp_client_pool.py` — Singleton connection pool (lazy connect, reuse, idle timeout)
- `pg_store.py` — PostgreSQL + pgvector persistence (MANDATORY)
- `pg_store_entities.py` — Entity storage and retrieval
- `pg_store_relationships.py` — Relationship storage, co-activation strengthening
- `pg_store_queries.py` — Query execution helpers
- `pg_store_auxiliary.py` — Auxiliary storage operations
- `pg_store_rules.py` — Rule storage and retrieval
- `pg_store_stats.py` — Statistics and diagnostics queries
- `pg_schema.py` — DDL, extensions, PL/pgSQL stored procedures, migrations
- `memory_config.py` — Runtime configuration (DATABASE_URL, env vars with CORTEX_MEMORY_ prefix)
- `memory_store.py` — Memory store abstraction
- `embedding_engine.py` — Vector embeddings (384-dim, sentence-transformers)
- `artifact_store.py` — Content-addressed raw-output artifacts (`~/.claude/methodology/artifacts/<yyyy-mm>/<sha256[:16]>.md`) backing gist+pointer memories
- `agent_config.py` — Agent configuration and topic scoping

**handlers/** — Composition roots (43 standalone tools + 3 upstream-integration tools conditionally registered = 46 total + helpers, one per tool)

**validation/** — `schemas.py` — Per-tool argument validation

**errors/** — `__init__.py` — MethodologyError, ValidationError, StorageError, AnalysisError, McpConnectionError

**server/** — MCP tool registration + composition roots. The HTTP visualization
stack (galaxy/trace/wiki/knowledge/board UI) was extracted to the standalone
**cortex-viz** MCP, which reads this same PostgreSQL store read-only.

**hooks/** — Session lifecycle automation
- `session_lifecycle.py` — SessionEnd hook for automatic profile updates
- `session_start.py` — SessionStart hook: injects anchored + hot memories + checkpoint state
- `post_tool_capture.py` — PostToolUse auto-capture hook
- `compaction_checkpoint.py` — Saves state before context compaction

## MCP Tools

### Tier 1 — Core Memory & Profiling (21 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `query_methodology` | Returns cognitive profile + hot memories for current domain | <50ms |
| `detect_domain` | Lightweight domain classification | <20ms |
| `rebuild_profiles` | Full rescan of session data | <10s |
| `list_domains` | Overview of all domains | <10ms |
| `record_session_end` | Incremental profile update + session critique | <200ms |
| `explore_features` | Interpretability exploration (features, attribution, persona, crosscoder) | <100ms |
| `remember` | Store a memory through the 4-signal predictive coding gate | <100ms |
| `recall` | Retrieve memories via 6-signal WRRF fusion | <200ms |
| `consolidate` | Run maintenance: decay, compression, CLS, sleep compute | <5s |
| `checkpoint` | Save/restore working state for hippocampal replay | <100ms |
| `narrative` | Generate project narrative from stored memories | <500ms |
| `memory_stats` | Memory system diagnostics | <50ms |
| `import_sessions` | Import conversation history into memory store | varies |
| `forget` | Hard/soft delete with is_protected guard | <50ms |
| `validate_memory` | Validate memories against filesystem state | <500ms |
| `rate_memory` | Useful/not-useful feedback → metamemory confidence | <50ms |
| `seed_project` | 5-stage codebase bootstrap | varies |
| `anchor` | Mark memory as compaction-resistant (heat=1.0) | <50ms |
| `backfill_memories` | Auto-import prior Claude Code conversations | varies |
| `unified_search` | Unified retrieval across memories, wiki, and code graph | <200ms |
| `get_telemetry` | Retrieval and memory-system telemetry metrics | <50ms |

### Tier 2 — Navigation & Exploration (5 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `recall_hierarchical` | Fractal L0/L1/L2 weighted recall | <200ms |
| `drill_down` | Navigate into fractal cluster (L2 → L1 → memories) | <100ms |
| `navigate_memory` | Successor Representation co-access BFS traversal | <200ms |
| `get_causal_chain` | Trace entity relationships through knowledge graph | <200ms |
| `detect_gaps` | Identify isolated entities, sparse domains, temporal drift | <500ms |

### Tier 3 — Automation & Intelligence (8 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `sync_instructions` | Push top memory insights into CLAUDE.md | <500ms |
| `create_trigger` | Prospective memory triggers (keyword/time/file/domain) | <100ms |
| `add_rule` | Add neuro-symbolic hard/soft/tag rules | <100ms |
| `get_rules` | List active rules by scope/type | <50ms |
| `get_project_story` | Period-based autobiographical narrative | <500ms |
| `assess_coverage` | Knowledge coverage score (0-100) + recommendations | <500ms |
| `codebase_analyze` | Native AST codebase analysis (tree-sitter, 7 languages) | varies |
| `curate_wiki` | Auto-curate wiki pages from memory clusters | varies |

### Tier 4 — Wiki (9 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `wiki_write` | Create a first-class wiki page (ADR, spec, note) | <100ms |
| `wiki_read` | Read a wiki page | <50ms |
| `wiki_list` | List wiki pages by scope/kind | <50ms |
| `wiki_link` | Create a typed link between wiki pages | <50ms |
| `wiki_adr` | Create an Architecture Decision Record | <100ms |
| `wiki_rename` | Rename a wiki page and update backlinks | <100ms |
| `wiki_verify` | Verify wiki page integrity and links | <100ms |
| `wiki_reindex` | Reindex wiki pages into memory pointers | varies |
| `wiki_purge` | Permanently delete a wiki page | <50ms |

**Upstream-integration tools (3, conditionally registered)** — these register
only when their upstream MCP server is configured, bringing the total to 46:
`ingest_codebase` + `change_impact` (automatised-pipeline) and `ingest_prd`
(prd-spec-generator). With no upstream present, exactly the **43 standalone
tools** above register. Driving the ai-architect pipeline end-to-end
(formerly `run_pipeline`) is **not** part of this server — it lives in the
automatised-pipeline MCP.

## Slash Commands

- `/methodology` — View cognitive methodology profile

## Data Flow

### Memory Write Path

1. **Gate**: 4-signal novelty filter (embedding distance, entity overlap, temporal proximity, structural similarity)
2. **Curate**: Active curation — merge with similar, link to related, or create new
3. **Store**: PostgreSQL + pgvector with auto tsvector indexing → entity extraction → knowledge graph

### Memory Read Path

1. **Route**: Intent classification (temporal/causal/semantic/entity/knowledge_update/multi_hop)
2. **Enrich**: Doc2Query expansion + concept synonyms
3. **Fuse**: PL/pgSQL `recall_memories()` — WRRF fusion of vector + FTS + trigram + heat + recency (server-side)
4. **Rerank**: FlashRank cross-encoder (client-side, top-3x candidates)
5. **Filter**: Neuro-symbolic rules → ranked results

### Cognitive Profile Pipeline

1. **Scan**: Read ~/.claude/projects/ for JSONL conversations and memory .md files
2. **Group**: Map projects to domains via project ID matching
3. **Extract**: Per-domain pattern extraction (clustering, n-grams, tool stats, session shape)
4. **Classify**: Felder-Silverman cognitive style from behavioral signals
5. **Bridge**: Cross-domain connections from brain-index cross-refs and text analogies
6. **Detect gaps**: Blind spots by comparing domain coverage against global averages
7. **Learn features**: Sparse dictionary learning on 27D behavioral activation space
8. **Encode**: Per-domain sparse feature activations + persona vectors
9. **Crosscode**: Detect persistent behavioral features across domains
10. **Store**: Persist as ~/.claude/methodology/profiles.json

## Testing

```bash
pytest                                      # All tests (3000+ passing)
pytest --cov=mcp_server --cov-report=term-missing  # With coverage
pytest tests_py/core/                       # Core layer only
pytest tests_py/shared/                     # Shared layer only
pytest tests_py/handlers/                   # Handler layer only
```

**Coverage targets**: shared 95%+, core 90%+, infrastructure 85%+, handlers 85%+, validation/errors 95%+, server 80%+, hooks 90%+.

## Benchmarks

6 benchmarks covering long-term memory from 2024-2026:

```bash
# Tier 1 — Active (results tracked)
python3 benchmarks/longmemeval/run_benchmark.py --variant s        # LongMemEval (ICLR 2025) — 500 Qs
python3 benchmarks/locomo/run_benchmark.py                          # LoCoMo (ACL 2024) — 1986 Qs
python3 benchmarks/beam/run_benchmark.py --split 100K              # BEAM (ICLR 2026) — 200 Qs

# Tier 2 — Additional
python3 benchmarks/memoryagentbench/run_benchmark.py               # MemoryAgentBench (ICLR 2026)
python3 benchmarks/evermembench/run_benchmark.py                    # EverMemBench (2026) — 2400 Qs
python3 benchmarks/episodic/run_benchmark.py --events 20           # Episodic Memories (ICLR 2025)
```

**Current benchmark scores (E1 v3; canonical source: the arxiv papers under `docs/arxiv-thermodynamic/` and `docs/arxiv-context-assembly/`):**
| Benchmark | Cortex | Best in paper |
|---|---|---|
| LongMemEval R@10 | **98.4%** | 78.4% |
| LongMemEval MRR | **0.9124** | -- |
| LoCoMo R@10 | **94.2%** | -- |
| LoCoMo MRR | **0.8278** | 0.794 |
| BEAM-100K MRR (retrieval-proxy) | **0.591** | -- |

Consolidation note: these retrieval scores are measured `--with-consolidation`.
The benchmark runners default to consolidation OFF, in which mode every loaded
memory keeps its ingest-time `heat_base_set_at`/`stage_entered_at`
(`hours_elapsed ≈ 0`), so the consolidation stage never advances past *labile*,
`effective_heat` stays at the labile floor (`≈1e-4`, see `pg_schema.py`
`effective_heat` and `core/pg_recall.py`), and the read-path heat gate
(`min_heat = 0.01`) prefilters every candidate — retrieval collapses to ≈0%.
This is a harness artifact of the OFF default, not a property of the stored
memories; it reproduces identically across branches. Subset reconfirmation
(`cortex_bench`, 2026-06-30, `--with-consolidation` vs OFF): LongMemEval-s n=50
R@10 94.0% / MRR 0.854 vs 0%; LoCoMo n=10 (1982 Qs) R@10 93.8% / MRR 0.821 vs
9.3%.

BEAM note: 0.591 is a retrieval-proxy MRR (the rank of the first gold-matching
memory), which is **not** commensurable with BEAM's end-to-end LLM-as-judge
metric; no head-to-head BEAM claim is made — it is used only for within-system,
same-harness comparisons. The context-assembly architecture adds +33.4% on
BEAM-10M with label-free temporal stage detection (+21.5% with oracle labels).
Source of truth: `docs/arxiv-thermodynamic/main.pdf` and
`docs/arxiv-context-assembly/main.pdf` (the CLAUDE.md numbers must match the
papers, not the other way around).

## Research-Driven Improvement Workflow

When improving benchmark scores or adding capabilities:

1. **Identify weakness** — Run benchmarks, find the lowest-scoring categories
2. **Research** — Find relevant papers (neuroscience, IR, NLP) that address the specific weakness
3. **Implement** — Translate the paper's key insight into a core module (pure logic, no I/O)
4. **Wire** — Connect via handlers (composition roots) with ablation support
5. **Benchmark** — Re-run affected benchmarks, compare before/after
6. **Record** — Update CLAUDE.md scores, commit with paper reference

Every mechanism should trace back to a published paper. No ad-hoc heuristics.

## Key Design Decisions

See `docs/adr/` for Architecture Decision Records:
- ADR-001: Zero external dependencies (superseded by ADR-012)
- ADR-002: Clean architecture layers
- ADR-003: Felder-Silverman cognitive model
- ADR-004: Jaccard over cosine similarity
- ADR-005: Agglomerative over k-means clustering
- ADR-006: EMA for incremental updates
- ADR-007: Head/tail JSONL reading
- ADR-008: Handler as composition root
- ADR-009: node:test over Jest (superseded by ADR-012)
- ADR-010: Sparse dictionary learning for behavioral features
- ADR-011: 12D persona vector design
- ADR-012: Python migration from Node.js
- ADR-013: Thermodynamic memory model
- ADR-014: Biological mechanisms (spreading activation, synaptic tagging, neuromodulation, LTP/LTD, STDP, emotional tagging, microglial pruning)

## Technology Stack

**Runtime:** Python 3.10+ with `fastmcp>=2.0.0`, `pydantic>=2.0.0`, `numpy>=1.24.0`.

**Storage (MANDATORY):** PostgreSQL 15+ with pgvector and pg_trgm extensions. No SQLite. No in-memory fallbacks.
- `psycopg[binary]>=3.1` — PostgreSQL driver
- `pgvector>=0.3` — Vector similarity search (HNSW index)
- `pg_trgm` — Trigram similarity for n-gram signal
- Connection via `DATABASE_URL` env var: `postgresql://cortex:password@localhost:5432/cortex`

**Retrieval engine:** PL/pgSQL stored procedures. WRRF fusion, vector search, FTS, trigram similarity, heat filtering — all server-side. Client-side: intent classification (regex), FlashRank reranking (ONNX), embedding generation (sentence-transformers).

**Benchmarks use the production database.** No custom retrievers. Load data → call `recall_memories()` → measure. Same code path as production.

Pre-computed profiles stored at `~/.claude/methodology/profiles.json`.

## Scientific Implementation Standard (Zetetic Principle)

Every change to the retrieval or memory system MUST follow this protocol:

1. **No implementation without a source.** Every algorithm, equation, constant, and threshold must trace to a published paper, verified benchmark data, or documented empirical result. If no source exists, say "I don't know" and stop.

2. **Multiple sources required.** A single paper is a hypothesis, not a fact. Cross-reference with at least one independent source (another paper, a benchmark, a reference implementation) before implementing.

3. **Verify sources before accepting.** Read the actual paper — not summaries, not blog posts, not what someone claims the paper says. Extract the exact equations. Check the experimental conditions match our setting (small corpus, conversational content, 384-dim embeddings).

4. **No invented constants.** Every hardcoded number must come from the paper's equations, the paper's experimental results, or measured ablation data from our own benchmarks. If a value can't be justified, it doesn't go in the code.

5. **Benchmark before commit.** Every change must be benchmarked on all three benchmarks (LongMemEval, LoCoMo, BEAM). No regression is accepted. Results must be reproducible — run on clean DB, single process.

6. **Say "I don't know" when you don't know.** Do not fabricate solutions, invent heuristics, or approximate algorithms without explicitly stating what was changed and why. A faithful "I don't know" is worth more than a confident wrong answer.

7. **Audit trail.** Every module's docstring must cite the exact paper, the exact equations implemented, and document any adaptations with justification. The audit at `docs/provenance/paper-implementation-audit.md` must stay current.
