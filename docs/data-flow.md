# JARVIS — Data Flow

## Memory Write Path (`remember`)

The write path uses a multi-stage pipeline to filter noise and maintain memory quality.

```mermaid
flowchart TD
    A[remember content] --> B[Embedding Engine]
    B --> C{4-Signal Write Gate}
    C -->|embedding novelty| C1[Vector distance from existing]
    C -->|entity novelty| C2[Entity overlap check]
    C -->|temporal novelty| C3[Recent memory proximity]
    C -->|structural novelty| C4[Tag/domain overlap]
    C1 & C2 & C3 & C4 --> D{Novel?}
    D -->|yes| E[Active Curation]
    D -->|no| X[Rejected with reason]
    E -->|similar exists| F[Merge into existing]
    E -->|related found| G[Link + create]
    E -->|genuinely new| H[Create new memory]
    F --> I[(SQLite + FTS5)]
    G --> I
    H --> I
    H --> J[Entity Extraction]
    J --> K[Knowledge Graph edges]
    H --> L[Engram Competition]

    style C fill:#f59e0b,color:#000
    style I fill:#06b6d4,color:#000
    style X fill:#ef4444,color:#fff
    style E fill:#22c55e,color:#000
```

### Write Gate Signals

| Signal | Source | What it measures |
|---|---|---|
| Embedding | `embedding_engine.py` | Cosine distance from nearest existing memory vector |
| Entity | `knowledge_graph.py` | Overlap ratio of extracted entities with existing |
| Temporal | `thermodynamics.py` | Time gap from most recent memory in same domain |
| Structural | `curation.py` | Tag and domain overlap with existing memories |

The gate uses `JARVIS_MEMORY_SURPRISAL_THRESHOLD` (default 0.3) as the minimum combined novelty score. `force=True` bypasses the gate entirely.

## Memory Read Path (`recall`)

The read path uses intent-aware routing and multi-signal fusion.

```mermaid
flowchart TD
    Q[recall query] --> QE[Query Enrichment]
    QE -->|Doc2Query| QE1[Synthetic sub-questions]
    QE -->|Concept expansion| QE2[Synonym terms]
    QE1 & QE2 --> R[Query Router]
    R -->|classify intent| S{Intent Type}
    S -->|temporal| W1[Boost time signals]
    S -->|causal| W2[Boost causal graph]
    S -->|semantic| W3[Boost vector similarity]
    S -->|entity| W4[Boost entity graph]
    W1 & W2 & W3 & W4 --> F[6-Signal WRRF Fusion]
    F --> F1[Signal 1: Vector similarity]
    F --> F2[Signal 2: FTS5 full-text]
    F --> F3[Signal 3: Thermodynamic heat]
    F --> F4[Signal 4: Hopfield associative]
    F --> F5[Signal 5: HDC hyperdimensional]
    F --> F6[Signal 6: SR co-access]
    F1 & F2 & F3 & F4 & F5 & F6 --> RR[Reciprocal Rank Fusion]
    RR --> MR[Neuro-symbolic Rules]
    MR --> RES[Ranked Results]

    style R fill:#d946ef,color:#000
    style F fill:#06b6d4,color:#000
    style RES fill:#22c55e,color:#000
    style QE fill:#f59e0b,color:#000
```

### Retrieval Signals

| Signal | Module | What it measures |
|---|---|---|
| Vector similarity | `embedding_engine.py` | Cosine similarity between query and memory embeddings |
| FTS5 full-text | `memory_store.py` | SQLite FTS5 BM25 ranking |
| Thermodynamic heat | `thermodynamics.py` | Current heat value (recency + importance) |
| Hopfield associative | `hopfield.py` | Content-addressable recall via energy minimization |
| HDC hyperdimensional | `hdc_encoder.py` | 1024D bipolar hypervector similarity |
| SR co-access | `cognitive_map.py` | Successor Representation transition probabilities |

### Intent Classification

The query router classifies queries into four intent types, each with different signal weightings:

| Intent | Trigger keywords | Boosted signals |
|---|---|---|
| **temporal** | "when", "recently", "last week" | heat, FTS5 time filters |
| **causal** | "why", "because", "caused" | causal graph edges, entity graph |
| **semantic** | "what", "how", "explain" | vector similarity, HDC |
| **entity** | proper nouns, specific names | entity graph, knowledge graph |

## Hierarchical Recall Path (`recall_hierarchical`)

```mermaid
flowchart TD
    Q[query] --> FC[Fractal Clustering]
    FC --> L2[L2 clusters — broad themes]
    FC --> L1[L1 clusters — sub-topics]
    FC --> L0[L0 — individual memories]
    L2 --> AW[Adaptive Level Weighting]
    L1 --> AW
    L0 --> AW
    AW --> RES[Weighted results by cluster relevance]

    style FC fill:#8b5cf6,color:#fff
    style AW fill:#06b6d4,color:#000
```

## Memory Navigation Path (`navigate_memory`)

```mermaid
flowchart TD
    M[memory_id] --> SR[Successor Representation]
    SR --> CO[Co-access transition matrix]
    CO --> BFS[BFS traversal]
    BFS --> NB[Neighboring memories]
    NB --> PROJ{include_2d_map?}
    PROJ -->|yes| MAP[2D projection via eigendecomposition]
    PROJ -->|no| RES[Memory graph with distances]
    MAP --> RES

    style SR fill:#d946ef,color:#000
    style MAP fill:#22c55e,color:#000
```

## Consolidation Pipeline (`consolidate`)

Runs maintenance to keep the memory store healthy.

```mermaid
flowchart TD
    START[consolidate] --> MODE{deep?}
    MODE -->|normal| D[Heat Decay]
    MODE -->|deep| SC[Sleep Compute first]
    SC --> DR[Dream replay of hot memories]
    SC --> CS[Cluster summarization]
    SC --> RE[Re-embed drifted vectors]
    SC --> AN[Auto-narration]
    DR & CS & RE & AN --> D
    D --> AP[Astrocyte Pool]
    AP -->|code 1.0x| N[Normal decay]
    AP -->|decisions 1.5x| S[Slow decay]
    AP -->|errors 0.7x| F[Fast decay]
    N & S & F --> CP[Compression]
    CP -->|hot| KEEP[Keep full text]
    CP -->|warm| GIST[Compress to gist]
    CP -->|cold| TAG[Compress to tags]
    CP -->|frozen| ARCH[Archive]
    KEEP & GIST & TAG & ARCH --> CLS[CLS Consolidation]
    CLS --> EP[Episodic → Semantic]
    EP --> CD[Causal Discovery]
    CD --> PC[PC Algorithm → new edges]

    style START fill:#f59e0b,color:#000
    style SC fill:#1e40af,color:#fff
    style AP fill:#8b5cf6,color:#fff
    style CLS fill:#22c55e,color:#000
```

### Decay Rates (Astrocyte Pool)

| Memory Type | Decay Multiplier | Rationale |
|---|---|---|
| Code patterns | 1.0x (normal) | Standard baseline |
| Decisions | 1.5x (slow) | Decisions are hard-won and expensive to re-derive |
| Error details | 0.7x (fast) | Error specifics become stale quickly |

### Compression Stages

| Stage | Heat Range | Content |
|---|---|---|
| Full text | heat > 0.5 | Original content preserved |
| Gist | 0.1 < heat ≤ 0.5 | Summarized to key points |
| Tags | 0.01 < heat ≤ 0.1 | Reduced to tag set only |
| Archived | heat ≤ 0.01 | Frozen, excluded from active recall |

## Cognitive Profile Pipeline (`rebuild_profiles`)

The cognitive profiling pipeline transforms raw session history into structured profiles.

```mermaid
flowchart TD
    SCAN[Scanner: read ~/.claude/] --> GROUP[Domain Detector: group by project]
    GROUP --> EXTRACT[Pattern Extractor: per-domain features]
    EXTRACT --> STYLE[Style Classifier: Felder-Silverman]
    STYLE --> BRIDGE[Bridge Finder: cross-domain links]
    BRIDGE --> BLIND[Blindspot Detector: gap analysis]
    BLIND --> SPARSE[Sparse Dictionary: 27D feature learning]
    SPARSE --> PERSONA[Persona Vector: 12D encoding]
    PERSONA --> CROSS[Behavioral Crosscoder: persistent features]
    CROSS --> STORE[Profile Store: ~/.claude/methodology/profiles.json]

    style SCAN fill:#06b6d4,color:#000
    style STORE fill:#22c55e,color:#000
    style SPARSE fill:#8b5cf6,color:#fff
```

### Pipeline Stages

| Stage | Module | Output |
|---|---|---|
| 1. Scan | `infrastructure/scanner.py` | Raw session records from JSONL + memory .md files |
| 2. Group | `core/domain_detector.py` | Sessions grouped by domain (3-signal classification) |
| 3. Extract | `core/pattern_extractor.py` | Entry points, patterns, tool preferences, session shape |
| 4. Classify | `core/style_classifier.py` | Felder-Silverman scores (Active/Reflective, Sensing/Intuitive, Visual/Verbal, Sequential/Global) |
| 5. Bridge | `core/bridge_finder.py` | Cross-domain connections (structural + analogical) |
| 6. Detect gaps | `core/blindspot_detector.py` | Category, tool, and pattern gaps vs global averages |
| 7. Learn features | `core/sparse_dictionary.py` | Behavioral dictionary + OMP sparse activations |
| 8. Encode | `core/persona_vector.py` | 12D persona with drift detection |
| 9. Crosscode | `core/behavioral_crosscoder.py` | Persistent cross-domain features |
| 10. Store | `infrastructure/profile_store.py` | Persisted to profiles.json |

## Incremental Update Path (`record_session_end`)

Called at the end of each Claude Code session to update profiles without a full rescan.

1. **Append** to session log (capped at 1,000 entries)
2. **Running average** update for session shape (duration, turn count, burst ratio, exploration ratio)
3. **EMA update** for cognitive style dimensions (ADR-006)
4. **Tool preference decay** for unused tools; reinforcement for used tools

## Session Start Path (SessionStart Hook)

The `hooks/session_start.py` module runs at session start:

1. Load anchored memories (is_protected=True, heat=1.0)
2. Load hot memories above heat threshold
3. Load any saved checkpoint state
4. Check and fire prospective triggers (keyword, time, file, domain)
5. Auto-trigger backfill on fresh installs (no existing memories)

## AI Architect Pipeline (`run_pipeline`)

The 11-stage pipeline orchestrates ai-architect MCP calls:

```
init → discovery → impact → strategy → PRD → interview →
verification → implementation → HOR* → audit* → push/PR

* = NON_FATAL stages (failures don't halt the pipeline)
```

Each stage calls the ai-architect MCP server via `mcp_client_pool`, collects findings, and feeds them forward. Cognitive context from the methodology profile is injected into the strategy and PRD stages.
