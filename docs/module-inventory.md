---
description: "Per-layer module inventory for mcp_server/ — extracted from CLAUDE.md (issue #114) so the root file stays under 200 lines."
---

# Module Inventory

Layer-by-layer catalogue of `mcp_server/`. This file is the curated/documented
subset that existed in CLAUDE.md before the #114 refactor — every module below
was already described there; nothing has been dropped. Counts below are
**measured**, not carried over from the prior (stale) prose, per the
zetetic source rule:

```
# source: measured on 2026-07-14 via
#   find mcp_server/<layer> -name "*.py" | grep -v __init__ | grep -v __pycache__ | wc -l
shared/           25 files   (11 documented below — curated subset)
core/            208 files   (~90 documented below — curated subset, incl. core/streaming, core/context_assembly)
infrastructure/   77 files   (21 documented below — curated subset)
handlers/        131 files   (55 registered tools — see docs/mcp-tools.md — + composition-root helpers)
```

The prior CLAUDE.md text asserted "108 modules" for `core/` and similar
counts for the other layers; that was a session-authored estimate, not a
measured one, and had drifted from the actual tree. The counts above are the
corrected, sourced figures. The module descriptions that follow remain a
**curated subset** (the modules judged worth a one-line description at the
time they were documented) — not a 1:1 listing of every file in the layer.
Treat gaps as "undocumented," not "does not exist."

## Dependency Rules

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

## shared/ — Pure utility functions

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

## core/ — Pure business logic, zero I/O

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
- `content_cues.py` — Language-aware decision/error/success cue detection for write-gate bypass (structural runtime markers + multilingual keyword sets, issue #158)
- `hierarchical_predictive_coding.py` — 3-level Friston free energy gate (sensory/entity/schema) replacing flat 4-signal
- `predictive_coding_flat.py` — Flat predictive coding fallback
- `predictive_coding_gate.py` — Gate decision logic
- `predictive_coding_signals.py` — Signal computation for predictive coding
- `coupled_neuromodulation.py` — DA/NE/ACh/5-HT coupled cascade with cross-channel effects (Doya 2002, Schultz 1997)
- `neuromodulation_channels.py` — Individual neuromodulator channel definitions
- `emotional_tagging.py` — Amygdala-inspired priority encoding (Qasim et al. 2023) with the Hebb 1955 inverted-U arousal curve
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
- `ablation.py` — Lesion study framework (41 ablatable units spanning the 36 neuroscience-grounded mechanisms)
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

*Document Ingestion (issue #192):*
- `document_model.py` — Typed model for ingested documents (`ParsedDocument`/`DocumentSection`/`DocumentTable`/`DocumentProvenance`) — the shared normalization seam every adapter and the live-Confluence REST connector (enterprise-backlog#28) target
- `docx_parser.py` — Pure OOXML WordprocessingML parser (`word/document.xml` string → `ParsedDocument`); stdlib `xml.etree` only
- `confluence_parser.py` — Pure Confluence storage-format XHTML parser (entities + ac:/ri: namespaces pre-resolved) → `ParsedDocument`
- `document_normalizer.py` — `ParsedDocument` + provenance → wiki page markdown + memory payloads (skipped-image/empty notices, provenance stamping)

*Undocumented (measured, not yet catalogued individually):* `core/streaming/`
(5 files) and `core/context_assembly/` (9 files) plus ~100 additional
top-level `core/` modules added since the last curation pass — ast
extraction, capture normalization, redaction, abstention gating, adaptive
control/writing, backpressure, and other mechanisms not yet described above.
Run the measurement command in the header to get a current file listing.

## infrastructure/ — All I/O

- `config.py` — Centralized path constants via pathlib
- `file_io.py` — Generic JSON/text read/write operations
- `profile_store.py` — profiles.json persistence
- `session_store.py` — session-log.json persistence
- `brain_index_store.py` — brain-index.json reader
- `scanner.py` — Discovers memories + conversations from ~/.claude/
- `scanner_parse.py` — JSONL conversation parsing
- `mcp_client.py` — Async MCP client over stdio (JSON-RPC 2.0, version negotiation)
- `mcp_client_pool.py` — Singleton connection pool (lazy connect, reuse, idle timeout)
- `pg_store.py` — PostgreSQL + pgvector persistence
- `pg_store_entities.py` — Entity storage and retrieval
- `pg_store_relationships.py` — Relationship storage, co-activation strengthening
- `pg_store_queries.py` — Query execution helpers
- `pg_store_auxiliary.py` — Auxiliary storage operations
- `pg_store_rules.py` — Rule storage and retrieval
- `pg_store_stats.py` — Statistics and diagnostics queries
- `pg_schema.py` — DDL, extensions, PL/pgSQL stored procedures, migrations
- `memory_config.py` — Runtime configuration (DATABASE_URL, env vars with CORTEX_MEMORY_ prefix)
- `backend_marker.py` — Persisted plugin backend selection: reads `~/.claude/methodology/backend.json` (written by `scripts/install-plugin.sh`) and resolves it into `CORTEX_MEMORY_STORE_BACKEND` for the launcher, hooks, and doctor
- `memory_store.py` — Memory store abstraction
- `embedding_engine.py` — Vector embeddings (384-dim, sentence-transformers)
- `artifact_store.py` — Content-addressed raw-output artifacts (`~/.claude/methodology/artifacts/<yyyy-mm>/<sha256[:16]>.md`) backing gist+pointer memories
- `agent_config.py` — Agent configuration and topic scoping
- `wiki_schema_reader.py` — Filesystem adapter for `core/wiki_schema_loader.py`'s data model/parsers; walks `wiki/_kinds|_rules|_views|_triggers/` and builds a `WikiRegistry` (issue #126 port-and-adapter split)
- `document_reader.py` — Reads a .docx (unzips `word/document.xml`) or a Confluence XHTML export off disk into the string its pure parser consumes; raises `DocumentReadError` on a bad container/decoding (issue #192)

Note: `pg_store.py` persists to PostgreSQL when configured (the
`install-plugin.sh --postgres` opt-in or an explicit `DATABASE_URL`);
see `PRIVACY.md` for the SQLite default used by plugin installs and `.mcpb`/Cowork
launches — this file does not assert PostgreSQL is mandatory (that assertion
was the drift #114 was filed against).

## handlers/ — Composition roots

52 standalone tools + 3 upstream-integration tools conditionally registered
(55 total) + a `handlers/consolidation/` subpackage + per-tool helpers. See
`docs/mcp-tools.md` for the full tool catalogue with purpose and target
latency.

## validation/

- `schemas.py` — Per-tool argument validation

## errors/

- `__init__.py` — MethodologyError, ValidationError, StorageError, AnalysisError, McpConnectionError

## server/

MCP tool registration + composition roots. The HTTP visualization stack
(galaxy/trace/wiki/knowledge/board UI) was extracted to the standalone
**cortex-viz** MCP, which reads this same store read-only.

## hooks/ — Session lifecycle automation

- `session_lifecycle.py` — SessionEnd hook for automatic profile updates
- `session_start.py` — SessionStart hook: injects anchored + hot memories + checkpoint state
- `post_tool_capture.py` — PostToolUse auto-capture hook
- `compaction_checkpoint.py` — Saves state before context compaction
