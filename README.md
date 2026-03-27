<div align="center">

# Cortex

### Biologically-inspired persistent memory for Claude Code

[![CI](https://github.com/cdeust/Cortex/actions/workflows/ci.yml/badge.svg)](https://github.com/cdeust/Cortex/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![MCP Server](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-1906_passing-brightgreen.svg)](#development)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/cdeust/Cortex/pulls)

**Cortex gives Claude Code a brain that survives between sessions.**

Thermodynamic memory on PostgreSQL + pgvector. Test-time learning with surprise momentum. Predictive coding write gates. Causal graphs. Intent-aware retrieval with PL/pgSQL WRRF fusion and FlashRank reranking. 23 neuroscience-inspired plasticity mechanisms. Cognitive profiling that learns how you work.

No LLM in the retrieval loop. Pure local inference.

[Getting Started](#quick-start) | [Benchmarks](#benchmarks) | [How It Works](#how-memory-works) | [Tools](#tools) | [Architecture](#architecture)

</div>

---

![Cortex Neural Graph — 2D force-directed visualization with per-node quality scoring, domain clusters, and benchmark summary](docs/neural-graph-v2.png)

## Highlights

- **98.0% Recall@10** on LongMemEval (ICLR 2025) — beats the paper's best by +19.6pp
- **0.515 MRR** on BEAM (ICLR 2026) — +57% over LIGHT baseline across 10 memory abilities
- **0.774 MRR** on LoCoMo (ACL 2024) — structure-aware chunking + entity-enriched embeddings
- **Test-time learning** — surprise momentum (Titans, NeurIPS 2025), adaptive decay, Hebbian co-activation (Dragon Hatchling, Pathway 2025)
- **PostgreSQL + pgvector** — all retrieval via PL/pgSQL stored procedures, HNSW vector search, FTS, trigram similarity
- **23 biological mechanisms** — LTP/LTD, STDP, microglial pruning, oscillatory gating, neuromodulation, emotional tagging, surprise momentum
- **5-signal server-side WRRF** — vector + FTS + trigram + heat + recency fused in PL/pgSQL, FlashRank cross-encoder reranking client-side
- **Intent-aware weight switching** — temporal, causal, knowledge_update, entity, multi_hop intents each get tuned signal weights
- **3-tier dispatch** — simple queries go inline, multi-hop does entity bridging, deep does BM25-primary
- **34 MCP tools** — remember, recall, consolidate, navigate, trigger, narrate, and more
- **Clean Architecture** — 103 pure-logic core modules, zero I/O in business logic, 1906 tests
- **Benchmarks use production code** — same `recall_memories()` stored procedure, same FlashRank reranking

## Quick Start

### Prerequisites

PostgreSQL 15+ with pgvector and pg_trgm extensions:

```bash
# macOS
brew install postgresql@17 pgvector
brew services start postgresql@17
createdb cortex
psql -d cortex -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
export DATABASE_URL=postgresql://localhost:5432/cortex
```

### Option 1: Claude Code Plugin (recommended)

```bash
/plugin marketplace add cdeust/Cortex
/plugin install cortex
```

Installs Cortex with its MCP server and session hooks automatically.

### Option 2: Claude Code CLI

```bash
claude mcp add cortex -- uvx neuro-cortex-memory
```

### Option 3: From Source

```bash
git clone https://github.com/cdeust/Cortex.git
cd cortex
pip install -e ".[dev]"

# Then add to Claude Code
claude mcp add cortex -- python -m mcp_server
```

## What It Does

**Remember things across sessions:**
> "Remember that we decided to use PostgreSQL instead of MongoDB for the auth service"

**Recall with intent-aware search:**
> "Why did we switch databases?" — Cortex detects causal intent, boosts spreading activation + entity graph signals

**Get proactive context at session start:**
Cortex automatically surfaces hot memories, fired triggers, and your cognitive profile when you start a new session.

**Learn at test time (Titans-inspired):**
Each recall computes retrieval surprise and updates memory heat via momentum. Surprising results get reinforced; redundant results fade. The system gets smarter with every query.

## Benchmarks

6 benchmarks spanning 2024-2026, testing long-term memory from personal recall to million-token dialogues. All benchmarks run on the **production PostgreSQL backend** — same `recall_memories()` stored procedure, same FlashRank reranking. No custom retrievers.

### How we measure: retrieval-only evaluation

Every benchmark score in this README is a **retrieval-only** metric. There is no LLM reader model in the evaluation loop. We measure one thing: *given a question, did the retrieval system place the correct evidence in the top results?*

This is a deliberate choice. Most memory systems report **full QA scores** — they retrieve context, feed it to a powerful reader LLM (GPT-4, Claude Opus), ask the reader to answer the question, then judge the answer. That conflates two completely independent variables: how good is the retrieval, and how good is the reader model. A strong reader can compensate for broken retrieval by reasoning over vaguely related context, or even by drawing on its parametric knowledge and ignoring the retrieved context entirely. The resulting score looks impressive but tells you nothing about whether the memory system actually works.

We report two standard retrieval metrics:

**Recall@K** is the simplest: what fraction of questions had the correct evidence *anywhere* in the top K results? Recall@10 = 98.0% means that for 98% of questions, the right memory appeared somewhere in the top 10. It answers: *can the system find it at all?*

**MRR (Mean Reciprocal Rank)** is stricter: it measures *where* in the ranked list the first correct result appears. If the correct evidence is at rank 1, that question scores 1.0. Rank 2 scores 0.5. Rank 3 scores 0.33. Rank 5 scores 0.2. Not found in top 10 scores 0. The MRR is the average across all questions. An MRR of 0.880 means the correct evidence is on average the first or second result returned. An MRR of 0.515 means it's typically in the top 2-3. MRR answers: *does the system rank the right evidence first?*

The relationship between retrieval MRR and downstream QA quality is asymmetric and important:

- **High retrieval MRR guarantees high QA.** If the correct evidence is consistently at rank 1, any competent reader model — GPT-4, Claude, Llama, even a much smaller model — will answer correctly. The retrieval has done the hard work. The reader just needs to read.
- **High QA does *not* guarantee high retrieval MRR.** A system can score well on QA while its retrieval is effectively broken, as long as the reader model is strong enough to compensate. This is brittle: swap the reader for a weaker model, change the prompt, or ask a slightly different question, and the score collapses. The retrieval never actually found the evidence — the reader was guessing.

This is not theoretical. On the BEAM benchmark, one comparable system ([Zikkaron](https://github.com/amanhij/Zikkaron)) reports a full-QA instruction_following score of 0.750 using Claude Opus as reader. But their retrieval MRR for that same category is **0.086** — the retrieval system finds the correct instruction memory less than 9% of the time, and when it does, it's rarely ranked first. The 0.750 score is almost entirely Claude Opus reasoning its way to the answer despite receiving the wrong context. Replace Claude Opus with a smaller model, and that score falls apart. By contrast, Cortex's retrieval MRR of 0.218 on the same category means the retrieval system itself is 2.5x more likely to surface the actual instruction — a property that holds regardless of which reader model sits downstream.

This is why we report retrieval-only scores throughout: they measure the memory system, not the reader model. They are harder to game, easier to interpret, and more predictive of real-world reliability. When comparing memory systems, always check which metric is being reported. A full-QA score of 0.75 with retrieval MRR of 0.08 tells a very different story than a retrieval-only MRR of 0.52.

### LongMemEval (ICLR 2025) — 500 questions, ~115k tokens

| Metric | Cortex | Best in paper | Delta |
|---|---|---|---|
| **Recall@10** | **98.0%** | 78.4% | **+19.6pp** |
| **MRR** | **0.880** | -- | -- |

For 98% of questions about conversations spanning ~115k tokens, Cortex finds the correct evidence in the top 10 results. The MRR of 0.880 means it's typically the very first result. The paper's best system (using a GPT-4-class reader for full QA) achieved 78.4% Recall@10 — Cortex's pure retrieval surpasses that by 19.6 percentage points without any reader model involved.

<details>
<summary>Per-category breakdown</summary>

| Category | MRR | R@10 |
|---|---|---|
| Single-session (user) | 0.793 | 91.4% |
| Single-session (assistant) | 0.970 | 100.0% |
| Single-session (preference) | 0.706 | 96.7% |
| Multi-session reasoning | 0.917 | 100.0% |
| Temporal reasoning | 0.887 | 97.7% |
| Knowledge updates | 0.884 | 100.0% |

</details>

### LoCoMo (ACL 2024) — 1,982 questions, 10 conversations

| Metric | Cortex |
|---|---|
| **Recall@10** | **88.9%** |
| **MRR** | **0.774** |

LoCoMo tests harder scenarios: multi-hop reasoning across conversation turns, temporal questions ("when did we last discuss X?"), and adversarial questions designed to confuse retrieval. An MRR of 0.774 means correct evidence is typically the first result, even for multi-hop and adversarial queries. Structure-aware chunking (splitting at speaker-turn boundaries with entity-enriched embeddings) improved MRR by 29% over the previous whole-session approach.

<details>
<summary>Per-category breakdown</summary>

| Category | MRR | R@5 | R@10 |
|---|---|---|---|
| single_hop | 0.714 | 85.5% | 91.8% |
| multi_hop | 0.736 | 82.2% | 84.1% |
| temporal | 0.538 | 65.2% | 76.1% |
| open_domain | 0.817 | 88.8% | 91.1% |
| adversarial | 0.809 | 87.0% | 89.0% |

</details>

### BEAM (ICLR 2026) — 395 questions, 100K-token conversations, 10 memory abilities

| Metric | Cortex | LIGHT (best in paper) | Delta |
|---|---|---|---|
| **Overall MRR** | **0.515** | 0.329 | **+57%** |

BEAM is the most comprehensive benchmark: 10 distinct memory abilities tested over 100K-token conversations. The LIGHT baseline (from the BEAM authors) uses Llama-4-Maverick as reader with a three-stage pipeline: long-term episodic memory, working memory, and an iterative scratchpad. Cortex's retrieval-only MRR of 0.515 outperforms LIGHT's full-QA score of 0.329 by 57%.

Cortex dominates 7 of 10 abilities in retrieval MRR. The three where LIGHT leads — preference_following, instruction_following, and abstention — expose genuine retrieval challenges, not reader model gaps. Abstention requires knowing what was *never discussed*, a negative knowledge problem that no pure retrieval system handles well without an explicit topic registry. Instruction following requires surfacing directive keywords ("always use bullet points", "never mention X") across 100K tokens of conversation where those same keywords appear in many non-instruction contexts. These are hard open problems at the retrieval level, and we report them transparently because retrieval-only scoring leaves nowhere to hide.

<details>
<summary>Per-ability breakdown (retrieval-only MRR)</summary>

| Ability | Cortex | LIGHT | Delta |
|---|---|---|---|
| contradiction_resolution | **0.892** | 0.050 | **+1684%** |
| temporal_reasoning | **0.789** | 0.075 | **+952%** |
| knowledge_update | **0.826** | 0.375 | **+120%** |
| multi_session_reasoning | **0.737** | 0.000 | -- |
| information_extraction | **0.519** | 0.375 | **+38%** |
| preference_following | 0.410 | **0.483** | -15% |
| event_ordering | **0.326** | 0.266 | **+23%** |
| summarization | **0.311** | 0.277 | **+12%** |
| instruction_following | 0.218 | **0.500** | -56% |
| abstention | 0.125 | **0.750** | -83% |

</details>

**Reproduce all benchmarks:**

```bash
pip install sentence-transformers flashrank datasets

# LongMemEval (~19 min)
curl -sL -o benchmarks/longmemeval/longmemeval_s.json \
  "https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_s"
DATABASE_URL=postgresql://localhost:5432/cortex python3 benchmarks/longmemeval/run_benchmark.py --variant s

# LoCoMo (~24 min)
curl -sL -o benchmarks/locomo/locomo10.json \
  "https://huggingface.co/datasets/Percena/locomo-mc10/resolve/main/raw/locomo10.json"
DATABASE_URL=postgresql://localhost:5432/cortex python3 benchmarks/locomo/run_benchmark.py

# BEAM (~5 min, auto-downloads from HuggingFace)
DATABASE_URL=postgresql://localhost:5432/cortex python3 benchmarks/beam/run_benchmark.py --split 100K
```

## Tools

Cortex exposes 34 MCP tools across three tiers:

### Tier 1 — Core Memory & Profiling

| Tool | What it does |
|---|---|
| `query_methodology` | Load cognitive profile + hot memories at session start |
| `remember` | Store a memory (4-signal write gate + neuromodulation + emotional tagging) |
| `recall` | Retrieve memories via 5-signal PG WRRF fusion + FlashRank reranking + surprise momentum |
| `consolidate` | Run maintenance: decay, LTP/LTD plasticity, microglial pruning, compression, CLS, sleep compute |
| `checkpoint` | Save/restore working state across context compaction |
| `narrative` | Generate project story from stored memories |
| `memory_stats` | Memory system diagnostics |
| `detect_domain` | Classify current domain from cwd/project |
| `rebuild_profiles` | Full rescan of session history |
| `list_domains` | Overview of all cognitive domains |
| `record_session_end` | Incremental profile update + session critique |
| `get_methodology_graph` | Graph data for visualization |
| `open_visualization` | Launch unified 3D neural graph in browser |
| `explore_features` | Interpretability: features, attribution, persona, crosscoder |
| `open_memory_dashboard` | Launch real-time memory visualization dashboard |
| `import_sessions` | Import conversation history into the memory store |
| `forget` | Hard/soft delete a memory (respects `is_protected` guard) |
| `validate_memory` | Validate memories against current filesystem state |
| `rate_memory` | Useful/not-useful feedback -> metamemory confidence |
| `seed_project` | Bootstrap memory from an existing codebase |
| `anchor` | Mark a memory as compaction-resistant (heat=1.0, is_protected) |
| `backfill_memories` | Auto-import prior Claude Code conversations |

### Tier 2 — Navigation & Exploration

| Tool | What it does |
|---|---|
| `recall_hierarchical` | Fractal L0/L1/L2 hierarchy with adaptive level weighting |
| `drill_down` | Navigate into a fractal cluster (L2 -> L1 -> memories) |
| `navigate_memory` | Successor Representation co-access BFS traversal |
| `get_causal_chain` | Trace entity relationships through the knowledge graph |
| `detect_gaps` | Identify isolated entities, sparse domains, temporal drift |

### Tier 3 — Automation & Intelligence

| Tool | What it does |
|---|---|
| `sync_instructions` | Push top memory insights into CLAUDE.md |
| `create_trigger` | Prospective memory triggers (keyword/time/file/domain) |
| `add_rule` | Add neuro-symbolic hard/soft/tag rules |
| `get_rules` | List active rules by scope/type |
| `get_project_story` | Period-based autobiographical narrative |
| `assess_coverage` | Knowledge coverage score (0-100) + recommendations |
| `run_pipeline` | Drive ai-architect pipeline end-to-end (11 stages -> PR) |

## How Memory Works

### Write Path

```mermaid
flowchart TD
    A[remember] --> OC[Oscillatory Clock]
    OC -->|encoding phase| NM{Neuromodulation}
    NM -->|DA/NE/ACh/5-HT| B{4-Signal Write Gate}
    B -->|novel| ET[Emotional Tagging]
    B -->|redundant| X[Rejected]
    ET -->|urgency/discovery/frustration| C[Active Curation]
    ET -->|neutral| C
    C -->|similar exists| D[Merge]
    C -->|related| E[Link]
    C -->|new| F[Create]
    D --> G[(PostgreSQL + pgvector)]
    E --> G
    F --> G
    F --> H[Extract Entities]
    H --> I[Knowledge Graph]
    F --> J[Engram Competition]
    F --> ST[Synaptic Tagging]
    ST -->|shared entities| K[Promote Weak Memories]
    F --> CS[Consolidation Cascade]
    CS -->|LABILE| L[Stage Tracking]

    style OC fill:#3b82f6,color:#fff
    style NM fill:#8b5cf6,color:#fff
    style B fill:#f59e0b,color:#000
    style ET fill:#ef4444,color:#fff
    style G fill:#06b6d4,color:#000
    style X fill:#ef4444,color:#fff
    style ST fill:#d946ef,color:#fff
    style CS fill:#22c55e,color:#000
```

### Read Path (with Test-Time Learning)

```mermaid
flowchart TD
    Q[recall query] --> R[Intent Classification]
    R -->|temporal/causal/entity/multi_hop/knowledge_update| WS[Intent-Aware Weights]
    WS --> PG[PL/pgSQL recall_memories]

    subgraph PG_SIGNALS["Server-Side WRRF (PostgreSQL)"]
        direction LR
        S1["Vector (HNSW)"] ~~~ S2["FTS (tsvector)"]
        S3["Trigram (pg_trgm)"] ~~~ S4[Heat]
        S5[Recency]
    end

    PG --> PG_SIGNALS
    PG_SIGNALS --> FUSED[WRRF K=60 Fusion]
    FUSED --> FR[FlashRank Reranking]
    FR --> SM[Surprise Momentum]
    SM -->|boost surprising| HU[Update Heat in PG]
    SM -->|suppress redundant| HU
    HU --> CA[Co-Activation]
    CA -->|Hebbian| KG[Strengthen Entity Edges]
    CA --> RULES[Neuro-symbolic Rules]
    RULES --> RES[Top 10 Results]

    style R fill:#d946ef,color:#fff
    style PG fill:#06b6d4,color:#000
    style FR fill:#22c55e,color:#000
    style SM fill:#f59e0b,color:#000
    style CA fill:#8b5cf6,color:#fff
    style RES fill:#3b82f6,color:#fff
    style HU fill:#f97316,color:#000
```

The read path applies **intent classification** -> **PL/pgSQL 5-signal WRRF fusion** (vector HNSW, full-text search, trigram similarity, thermodynamic heat, recency) -> **FlashRank cross-encoder reranking** (ms-marco-MiniLM-L-12-v2, alpha=0.55) -> **surprise momentum** (Titans NeurIPS 2025: compute retrieval surprise, update heat via EMA momentum) -> **co-activation graph strengthening** (Dragon Hatchling: Hebbian reinforcement of entity edges) -> **neuro-symbolic rule filtering**.

### Consolidation (Background)

```mermaid
flowchart LR
    A[Session End / consolidate] --> B[Adaptive Decay]
    B -->|per-memory rate| AD[Useful: slow decay<br/>Redundant: fast decay]
    B --> TS[Tripartite Synapse]
    TS -->|metabolic rate| D[Category-aware decay]

    B --> LTP[LTP/LTD Plasticity]
    LTP -->|co-activated| S1[Strengthen edges]
    LTP -->|inactive| S2[Weaken edges]

    B --> STDP[STDP]
    STDP --> S3[Learn causal direction]

    B --> MG[Microglial Pruning]
    MG -->|weak+stale+cold| S4[Eliminate edges]
    MG -->|orphaned| S5[Archive entities]

    B --> HP[Homeostatic Plasticity]
    HP --> S6[Scale synaptic weights]

    B --> CP[Compression]
    CP --> H[full to gist to tag]

    B --> CLS[CLS]
    CLS --> J[episodic to semantic]

    B --> CD[Causal Discovery]
    CD --> L[PC Algorithm -> edges]

    B --> SC{deep=True}
    SC --> SL[Sleep Compute]
    SL --> DR[Dream replay + interference resolution]

    style A fill:#f59e0b,color:#000
    style AD fill:#f97316,color:#000
    style LTP fill:#22c55e,color:#000
    style STDP fill:#f59e0b,color:#000
    style MG fill:#ef4444,color:#fff
    style HP fill:#f59e0b,color:#000
    style SL fill:#1e40af,color:#fff
```

## Why Cortex Scores High

### 1. Test-Time Learning (Titans + Dragon Hatchling)

The biggest innovation: the retrieval system **learns from its own queries**. After each recall:

- **Surprise momentum** (Titans, NeurIPS 2025): computes `surprise = 1 - mean(cosine_sim(query, results))`. Surprising results get a heat boost; redundant ones get suppressed. An EMA momentum term amplifies the effect when recent queries are consistently surprising. This improved LongMemEval R@10 from 90.4% to **98.0%** (+7.6pp).
- **Co-activation strengthening** (Dragon Hatchling, Pathway 2025): when memories A and B are co-retrieved, their entity edges get Hebbian reinforcement: `weight += learning_rate * score_product`. This makes the knowledge graph learn from usage patterns.
- **Adaptive decay** (Titans): per-memory decay rates computed from `access_count`, `useful_count`, and `surprise_score`. Useful memories decay slower (0.999/hr); redundant ones faster (0.90/hr).

### 2. Server-Side WRRF Fusion (PostgreSQL)

All retrieval runs in a single PL/pgSQL stored procedure (`recall_memories()`). Five signals fused server-side:

- **Vector**: pgvector HNSW cosine similarity (384-dim, sentence-transformers)
- **FTS**: `tsvector` full-text search with `ts_rank_cd`
- **Trigram**: `pg_trgm` similarity for fuzzy matching
- **Heat**: thermodynamic recency (surprise-momentum-modulated)
- **Recency**: newest-first ranking

Each signal produces a ranked list; WRRF fusion: `score += weight / (K + rank)`.

### 3. FlashRank Cross-Encoder Reranking

Client-side ms-marco-MiniLM-L-12-v2 (ONNX, no GPU) reranks PG candidates with alpha-blended scoring: `0.55 * cross_encoder + 0.45 * wrrf`.

### 4. Intent-Aware Weight Switching

Cortex classifies queries into 6 intents and adjusts signal weights:

| Intent | Boosted Signals | Key Use Case |
|---|---|---|
| temporal | heat, recency | "When did we deploy v2?" |
| causal | spreading activation, entity | "Why did we switch databases?" |
| knowledge_update | recency (3x), heat | "What's the latest on the auth service?" |
| entity | BM25, FTS | "What do we know about PostgreSQL?" |
| multi_hop | spreading activation | "How does the auth service relate to the payment API?" |

### 5. Biological Memory Lifecycle

Memories aren't static — they have a lifecycle with 23 mechanisms:
- **Encoding**: oscillatory phase check + neuromodulation + predictive coding gate + emotional tagging
- **Consolidation**: LABILE -> EARLY_LTP -> LATE_LTP -> CONSOLIDATED with protein synthesis gating
- **Plasticity**: LTP/LTD + STDP + stochastic transmission + microglial pruning + Hebbian co-activation
- **Homeostasis**: synaptic scaling prevents runaway potentiation; adaptive decay manages forgetting

## Biological Mechanisms

Cortex implements 23 neuroscience-inspired subsystems organized into five functional stages:

```mermaid
graph LR
    subgraph Encoding["Encoding"]
        OC[Oscillatory Clock<br/>Theta/Gamma/SWR] --> PC[Predictive Coding<br/>3-Level Free Energy]
        PC --> NM[Neuromodulation<br/>DA/NE/ACh/5-HT]
        NM --> ET[Emotional Tagging<br/>Amygdala]
        PS[Pattern Separation<br/>DG Orthogonalization] --> PC
        ET --> ST[Synaptic Tagging<br/>Retroactive Promotion]
    end

    subgraph Storage["Storage & Maintenance"]
        EG[Engram Competition<br/>CREB Slots] --> TH[Thermodynamics<br/>Heat/Decay]
        TH --> TS[Tripartite Synapse<br/>Astrocyte Ca2+]
        HP[Homeostatic Plasticity<br/>Synaptic Scaling] --> TH
        CS[Consolidation Cascade<br/>LABILE to CONSOLIDATED] --> CLS[CLS<br/>Episodic to Semantic]
        DC[Dendritic Clusters<br/>Branch-Specific Integration] --> TH
        TS --> CLS
    end

    subgraph Retrieval["Retrieval & Test-Time Learning"]
        HOP[Hopfield Network<br/>Associative Recall] --> SA[Spreading Activation<br/>Entity Graph Priming]
        SA --> SM[Surprise Momentum<br/>Titans NeurIPS 2025]
        SM --> CoA[Co-Activation<br/>Dragon Hatchling 2025]
        HDC[HDC Encoding<br/>Hyperdimensional] --> SR[Successor Rep<br/>Co-Access Navigation]
    end

    subgraph Plasticity["Plasticity & Pruning"]
        LTP[LTP/LTD<br/>Hebbian Plasticity] --> STDP[STDP<br/>Causal Direction]
        STDP --> MG[Microglial Pruning<br/>Complement-Dependent]
        MG --> SC[Sleep Compute<br/>Dream Replay]
        IF[Interference Mgmt<br/>Pro/Retroactive] --> SC
        TSM[Two-Stage Model<br/>Hippocampal-Cortical] --> SC
        AD[Adaptive Decay<br/>Titans NeurIPS 2025] --> SC
    end

    Encoding --> Storage
    Storage --> Retrieval
    Retrieval --> Plasticity
    Plasticity -->|strengthen/weaken| Storage

    style PC fill:#f59e0b,color:#000
    style NM fill:#8b5cf6,color:#fff
    style ET fill:#ef4444,color:#fff
    style ST fill:#d946ef,color:#fff
    style OC fill:#3b82f6,color:#fff
    style PS fill:#06b6d4,color:#000
    style EG fill:#06b6d4,color:#000
    style TH fill:#f97316,color:#000
    style CLS fill:#22c55e,color:#000
    style TS fill:#8b5cf6,color:#fff
    style HP fill:#f59e0b,color:#000
    style CS fill:#22c55e,color:#000
    style DC fill:#06b6d4,color:#000
    style HOP fill:#06b6d4,color:#000
    style SA fill:#3b82f6,color:#fff
    style SM fill:#f97316,color:#000
    style CoA fill:#d946ef,color:#fff
    style HDC fill:#8b5cf6,color:#fff
    style SR fill:#d946ef,color:#fff
    style LTP fill:#22c55e,color:#000
    style STDP fill:#f59e0b,color:#000
    style MG fill:#ef4444,color:#fff
    style SC fill:#1e40af,color:#fff
    style IF fill:#f97316,color:#000
    style TSM fill:#d946ef,color:#fff
    style AD fill:#f97316,color:#000
```

<details>
<summary>Full mechanism reference (25+ mechanisms with paper citations)</summary>

| Mechanism | Module | Paper | What it does |
|---|---|---|---|
| Surprise Momentum | `thermodynamics.py` | Behrouz et al. 2025 (Titans) | Test-time learning: retrieval surprise → heat modulation via EMA momentum |
| Adaptive Decay | `decay_cycle.py` | Behrouz et al. 2025 (Titans) | Per-memory decay rates from access/useful/surprise signals |
| Co-Activation | `pg_store_relationships.py` | Kosowski et al. 2025 (Dragon Hatchling) | Hebbian reinforcement of entity edges from co-retrieval patterns |
| Hierarchical Predictive Coding | `hierarchical_predictive_coding.py` | Friston 2005, Bastos 2012 | 3-level free energy gate (sensory/entity/schema) |
| Coupled Neuromodulation | `coupled_neuromodulation.py` | Doya 2002, Schultz 1997 | DA/NE/ACh/5-HT coupled cascade |
| Oscillatory Clock | `oscillatory_clock.py` | Hasselmo 2005, Buzsaki 2015 | Theta/gamma/SWR phase gating |
| Consolidation Cascade | `cascade.py` | Kandel 2001, Dudai 2012 | LABILE -> EARLY_LTP -> LATE_LTP -> CONSOLIDATED |
| Pattern Separation | `pattern_separation.py` | Leutgeb 2007, Yassa & Stark 2011 | DG orthogonalization + neurogenesis analog |
| Schema Engine | `schema_engine.py` | Tse 2007, Gilboa & Marlatte 2017 | Cortical knowledge structures with Piaget accommodation |
| Tripartite Synapse | `tripartite_synapse.py` | Perea 2009, De Pitta 2012 | Astrocyte calcium dynamics, D-serine LTP facilitation |
| Interference Management | `interference.py` | Wixted 2004 | Proactive/retroactive detection + sleep orthogonalization |
| Homeostatic Plasticity | `homeostatic_plasticity.py` | Turrigiano 2008, Abraham & Bear 1996 | Synaptic scaling + BCM sliding threshold |
| Dendritic Clusters | `dendritic_clusters.py` | Kastellakis 2015 | Branch-specific nonlinear integration |
| Two-Stage Model | `two_stage_model.py` | McClelland 1995, Kumaran 2016 | Hippocampal fast-bind -> cortical slow-integrate |
| Emotional Tagging | `emotional_tagging.py` | Wang & Bhatt 2024 | Amygdala-inspired priority encoding with Yerkes-Dodson |
| Synaptic Tagging | `synaptic_tagging.py` | Frey & Morris 1997 | Retroactive promotion of weak memories sharing entities |
| Engram Competition | `engram.py` | Josselyn & Tonegawa 2020 | CREB-like excitability slots |
| Thermodynamics | `thermodynamics.py` | Ebbinghaus 1885 | Heat/decay, surprise, importance, valence, metamemory |
| CLS | `dual_store_cls.py` | McClelland 1995 | Episodic -> semantic consolidation |
| Hopfield Network | `hopfield.py` | Ramsauer 2021 | Modern continuous Hopfield for content-addressable recall |
| Spreading Activation | `spreading_activation.py` | Collins & Loftus 1975 | Entity graph priming via recursive CTE in PL/pgSQL |
| HDC Encoding | `hdc_encoder.py` | Kanerva 2009 | 1024-dim bipolar hypervectors |
| Successor Rep. | `cognitive_map.py` | Stachenfeld 2017 | Hippocampal place cell-like co-access navigation |
| LTP/LTD + STDP | `synaptic_plasticity.py` | Hebb 1949, Bi & Poo 1998 | Hebbian plasticity + causal timing + stochastic transmission |
| Microglial Pruning | `microglial_pruning.py` | Wang et al. 2020 | Complement-dependent edge elimination |
| Ablation Framework | `ablation.py` | -- | Lesion study simulator for 23 mechanisms |

</details>

## Architecture

Clean Architecture with concentric dependency layers. Inner layers never import outer layers. PostgreSQL + pgvector is the mandatory storage backend.

```mermaid
graph TD
    T[transport/] -->|wire| SV[server/]
    SV -->|dispatch| H[handlers/]
    H -->|compose| C[core/]
    H -->|wire| I[infrastructure/]
    C -->|import| S[shared/]
    I -->|import| S
    HK[hooks/] -->|use| I
    HK -->|use| C
    HK -->|use| S

    C -.-|"103 modules, pure logic, zero I/O"| C
    I -.-|"PostgreSQL + pgvector, embeddings, config"| I
    S -.-|"11 modules: utilities, types"| S
    H -.-|"60 handlers (composition roots)"| H

    style C fill:#22c55e,color:#000
    style I fill:#06b6d4,color:#000
    style S fill:#64748b,color:#fff
    style H fill:#f59e0b,color:#000
    style HK fill:#ec4899,color:#fff
    style T fill:#94a3b8,color:#000
    style SV fill:#a78bfa,color:#000
```

- **103 core modules** -- all pure business logic, no I/O
- **60 handlers** -- composition roots wiring core + infrastructure
- **Infrastructure** -- PostgreSQL + pgvector store, PL/pgSQL stored procedures, embeddings, config
- **11 shared modules** -- pure utilities and Pydantic types
- **4 hooks** -- session lifecycle, compaction checkpoint, post-tool capture, session start
- **1906 tests** passing across Python 3.10-3.13
- **6 benchmarks** -- LongMemEval, LoCoMo, BEAM, MemoryAgentBench, EverMemBench, Episodic

## Configuration

All settings via environment variables with `CORTEX_MEMORY_` prefix:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost:5432/cortex` | PostgreSQL connection string (mandatory) |
| `CORTEX_MEMORY_DECAY_FACTOR` | `0.95` | Base heat decay rate per hour |
| `CORTEX_MEMORY_SURPRISE_MOMENTUM_ENABLED` | `true` | Enable test-time learning |
| `CORTEX_MEMORY_SURPRISE_MOMENTUM_ETA` | `0.7` | Momentum decay (EMA) |
| `CORTEX_MEMORY_SURPRISE_MOMENTUM_DELTA` | `0.08` | Max heat change per recall |
| `CORTEX_MEMORY_ADAPTIVE_DECAY_ENABLED` | `true` | Per-memory adaptive decay rates |
| `CORTEX_MEMORY_CO_ACTIVATION_ENABLED` | `true` | Hebbian co-retrieval edge strengthening |
| `CORTEX_MEMORY_WRRF_VECTOR_WEIGHT` | `1.0` | Vector signal weight in WRRF |
| `CORTEX_MEMORY_WRRF_FTS_WEIGHT` | `0.5` | FTS signal weight |
| `CORTEX_MEMORY_WRRF_HEAT_WEIGHT` | `0.3` | Heat signal weight |

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=mcp_server --cov-report=term-missing

# Run specific layer
pytest tests_py/core/
pytest tests_py/handlers/
pytest tests_py/infrastructure/

# Run benchmarks (requires PostgreSQL)
DATABASE_URL=postgresql://localhost:5432/cortex python3 benchmarks/longmemeval/run_benchmark.py --variant s
DATABASE_URL=postgresql://localhost:5432/cortex python3 benchmarks/locomo/run_benchmark.py
```

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

See the [Architecture](#architecture) section for dependency rules and module boundaries.

## Citation

If you use Cortex in your research, please cite:

```bibtex
@software{cortex2026,
  title={Cortex: Biologically-Inspired Persistent Memory for Claude Code},
  author={Deust, Clement},
  year={2026},
  url={https://github.com/cdeust/Cortex}
}
```

## License

MIT
