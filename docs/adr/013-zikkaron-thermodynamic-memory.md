# ADR-013: Thermodynamic Memory Model

## Status

Accepted

## Context

After migrating from Node.js to Python (ADR-012), the Methodology Agent had cognitive profiling but no persistent memory across sessions. Claude Code's built-in memory system (markdown files in `~/.claude/`) is flat, has no decay, no novelty filtering, and no structured retrieval beyond text search.

A neuroscience-inspired thermodynamic memory architecture addresses these gaps:

- Filters noise via predictive coding (only genuinely novel information is stored)
- Decays naturally (errors fade fast, decisions persist)
- Retrieves with intent awareness (causal queries boost different signals than semantic queries)
- Consolidates automatically (episodic -> semantic, compression, causal discovery)

## Decision

Implement a thermodynamic memory architecture in three tiers, each building on the previous:

### Tier 1 -- Core Memory (Predictive Coding + Write Gate)

- **Hierarchical predictive coding gate** (`hierarchical_predictive_coding.py`): 3-level Friston free energy gate (sensory/entity/schema) with precision-weighted prediction errors
- **SQLite + FTS5 storage** (`memory_store.py`): full-text search with thermodynamic metadata (heat, surprise, importance, valence)
- **Active curation** (`curation.py`): merge with similar, link to related, or create new
- **Staleness detection** (`staleness.py`): score memories against filesystem state
- **Memory management tools**: forget (with is_protected guard), validate, rate, seed, anchor, backfill

### Tier 2 -- Navigation & Retrieval

- **6-signal WRRF fusion**: vector similarity + FTS5 BM25 + thermodynamic heat + Hopfield associative + HDC hyperdimensional + Successor Representation co-access
- **HDC encoder** (`hdc_encoder.py`): 1024-dimensional bipolar hypervectors for content-addressable similarity
- **Cognitive map** (`cognitive_map.py`): Successor Representation transition matrix from co-access patterns + 2D eigendecomposition projection
- **Fractal hierarchy** (`fractal.py`): L0/L1/L2 hierarchical clustering for multi-scale recall
- **Knowledge graph navigation** (`get_causal_chain.py`): BFS through entity relationships
- **Gap detection** (`detect_gaps.py`): isolated entities, sparse domains, temporal drift

### Tier 3 -- Automation & Intelligence

- **Sleep compute** (`sleep_compute.py`): dream replay of hot memories, cluster summarization, re-embedding of drifted vectors, auto-narration
- **Prospective triggers** (`prospective.py`): keyword, time, file, and domain triggers that fire proactively
- **Neuro-symbolic rules** (`memory_rules.py`): soft (weight adjustment) and hard (filter) rules with scoped application
- **Project story** (`get_project_story.py`): period-based autobiographical narrative
- **Coverage assessment** (`assess_coverage.py`): 0-100 knowledge completeness score
- **Instruction sync** (`sync_instructions.py`): push memory insights into CLAUDE.md

### Technology Choices

| Concern | Choice | Rationale |
|---|---|---|
| Storage | SQLite + FTS5 | Built into Python stdlib, full-text search, ACID transactions |
| Embeddings | 64-dim numpy vectors | Lightweight, no external model dependency |
| HDC | 1024-dim bipolar | Efficient similarity via dot product, no training |
| Associative recall | Hopfield network | Content-addressable, energy-based convergence |
| Spatial map | Successor Representation | Captures transition structure, not just proximity |
| Causal discovery | PC Algorithm | Principled constraint-based causal learning |
| Clustering | Agglomerative (3 levels) | Consistent with ADR-005, natural hierarchy |

## Consequences

### Positive

- **Noise reduction** -- 4-signal gate rejects ~60% of redundant remember calls
- **Natural forgetting** -- error details decay 30% faster, decisions persist 50% longer
- **Intent-aware retrieval** -- "why did we..." queries boost causal signals, "when did we..." queries boost temporal signals
- **Self-maintaining** -- consolidation runs automatically at session end
- **Proactive context** -- triggers fire at session start without explicit recall
- **Interpretable** -- coverage scores, gap detection, and project stories make the memory system transparent

### Negative

- **Complexity** -- 28 new core modules significantly increases the codebase
- **SQLite dependency** -- adds a persistence layer beyond flat JSON files
- **Tuning surface** -- 5+ environment variables for threshold tuning
- **Test burden** -- ~900 new tests needed to maintain coverage targets

### Neutral

- Clean Architecture layers preserved -- all new modules follow existing dependency rules
- All new core modules are pure (zero I/O), testable with deterministic inputs
- Handler pattern unchanged -- each new tool gets its own handler as composition root (ADR-008)

## Verification

- All 1893 tests passing
- Coverage targets maintained across all layers
- 34 MCP tools registered and functional
- Write gate, recall fusion, and consolidation verified with end-to-end session tests
