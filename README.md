<div align="center">

# Cortex

### Persistent memory for Claude Code — built on neuroscience research, not guesswork

[![CI](https://github.com/cdeust/Cortex/actions/workflows/ci.yml/badge.svg)](https://github.com/cdeust/Cortex/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-2080_passing-brightgreen.svg)](#development)

Memory that learns, consolidates, forgets intelligently, and surfaces the right context at the right time. Works standalone or with a team of specialized agents.

[Getting Started](#getting-started) | [How It Works](#how-it-works) | [Neural Graph](#neural-graph) | [Agent Integration](#agent-integration) | [Benchmarks](#benchmarks) | [Scientific Foundation](#scientific-foundation)

**Companion projects:**
[cortex-beam-abstain](https://github.com/cdeust/cortex-know-when-to-stop-training-model) — community-trained retrieval abstention model for RAG systems
| [zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents) — specialist Claude Code agents Cortex orchestrates with

</div>

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **PostgreSQL 15+** with [pgvector](https://github.com/pgvector/pgvector) and pg_trgm extensions
- **Claude Code** CLI or desktop app

### Option A — Claude Code Marketplace (recommended)

```bash
claude plugin marketplace add cdeust/Cortex
claude plugin install cortex
```

Restart your Claude Code session, then run:

```
/cortex-setup-project
```

This handles everything: PostgreSQL + pgvector installation, database creation, embedding model download, cognitive profile building from session history, codebase seeding, conversation import, and hook registration. Zero manual steps.

> **Using Claude Cowork?** Install [Cortex-cowork](https://github.com/cdeust/Cortex-cowork) instead — uses SQLite, no PostgreSQL required.
>
> ```bash
> claude plugin marketplace add cdeust/Cortex-cowork
> claude plugin install cortex-cowork
> ```

### Option B — Standalone MCP (no plugin)

```bash
claude mcp add cortex -- uvx --from "neuro-cortex-memory[postgresql]" neuro-cortex-memory
```

Adds Cortex as a standalone MCP server via [uvx](https://docs.astral.sh/uv/). No hooks, no skills — just the 33 MCP tools. Requires `uv` installed.

### Option C — Clone + Setup Script

```bash
git clone https://github.com/cdeust/Cortex.git
cd Cortex
bash scripts/setup.sh        # macOS / Linux
python3 scripts/setup.py     # Windows / cross-platform
```

Installs PostgreSQL + pgvector (Homebrew on macOS, apt/dnf on Linux), creates the database, downloads the embedding model (~100 MB). On Windows, install PostgreSQL manually first, then run `setup.py`. Restart Claude Code after setup.

### Option D — Docker

```bash
git clone https://github.com/cdeust/Cortex.git
cd Cortex

docker build -t cortex-runtime -f docker/Dockerfile .
docker run -it \
  -v $(pwd):/workspace \
  -v cortex-pgdata:/var/lib/postgresql/17/data \
  -v ~/.claude:/home/cortex/.claude-host:ro \
  -v ~/.claude.json:/home/cortex/.claude-host-json/.claude.json:ro \
  cortex-runtime
```

The container includes PostgreSQL 17, pgvector, the embedding model, and Claude Code. Data persists via the `cortex-pgdata` volume.

### Option E — Manual Setup

<details>
<summary>Step-by-step instructions</summary>

**1. Install PostgreSQL + pgvector**

```bash
# macOS
brew install postgresql@17 pgvector
brew services start postgresql@17

# Ubuntu/Debian
sudo apt-get install postgresql postgresql-server-dev-all
sudo apt-get install postgresql-17-pgvector
sudo systemctl start postgresql
```

**2. Create the database**

```bash
createdb cortex
psql cortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql cortex -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

**3. Install Python dependencies**

```bash
pip install -e ".[postgresql]"
pip install sentence-transformers flashrank
```

**4. Initialize schema**

```bash
export DATABASE_URL=postgresql://localhost:5432/cortex
python3 -c "
from mcp_server.infrastructure.pg_schema import get_all_ddl
from mcp_server.infrastructure.pg_store import PgStore
import asyncio
asyncio.run(PgStore(database_url='$DATABASE_URL').initialize())
"
```

**5. Pre-cache the embedding model**

```bash
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

**6. Register MCP server**

```bash
claude mcp add cortex -- uvx --from "neuro-cortex-memory[postgresql]" neuro-cortex-memory
```

Restart Claude Code to activate.

</details>

### Verify Installation

After setup, open Claude Code in any project. The SessionStart hook should inject context automatically. You can also test manually:

```bash
python3 -m mcp_server  # Should start on stdio without errors
```

### Configuration

Cortex reads `DATABASE_URL` from the environment (default: `postgresql://localhost:5432/cortex`). All tunable parameters use the `CORTEX_MEMORY_` prefix:

| Variable | Default | What It Controls |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost:5432/cortex` | PostgreSQL connection string |
| `CORTEX_RUNTIME` | auto-detected | `cli` (strict) or `cowork` (SQLite fallback) |
| `CORTEX_MEMORY_DECAY_FACTOR` | 0.95 | Per-session heat decay rate |
| `CORTEX_MEMORY_HOT_THRESHOLD` | 0.7 | Heat level considered "hot" |
| `CORTEX_MEMORY_WRRF_VECTOR_WEIGHT` | 1.0 | Vector similarity weight in fusion |
| `CORTEX_MEMORY_WRRF_FTS_WEIGHT` | 0.5 | Full-text search weight in fusion |
| `CORTEX_MEMORY_WRRF_HEAT_WEIGHT` | 0.3 | Thermodynamic heat weight in fusion |
| `CORTEX_MEMORY_DEFAULT_RECALL_LIMIT` | 10 | Max memories returned per query |

See `mcp_server/infrastructure/memory_config.py` for the full list (~40 parameters).

---

## How It Works

Cortex runs invisibly alongside Claude Code. You don't manage memory — it does.

### Your session, automatically enriched

| When | What happens | You see |
|---|---|---|
| **Session starts** | Cortex loads your hot memories, anchored decisions, and team context into Claude's prompt | Claude already knows what you were working on yesterday |
| **You write code** | Hooks capture edits, commands, and test results as memories. Related memories get a heat boost so they surface in future recalls | Nothing — it's automatic |
| **You ask a question** | Cortex searches 5 signals simultaneously (meaning, keywords, fuzzy match, importance, recency), reranks with a cross-encoder, and injects the best matches into Claude's context | Claude answers with context from weeks ago that you forgot about |
| **Session ends** | A "dream" cycle decays old memories, compresses verbose ones, and promotes repeated patterns into general knowledge | Your next session is cleaner and more focused |
| **Days pass** | Unused memories cool down naturally. Important ones stay hot. Protected decisions never decay | Cortex forgets the noise, keeps the signal |

### Retrieval: five signals, one answer

When you search, Cortex doesn't just look for similar text — it combines five different signals, all computed inside PostgreSQL in a single query:

<p align="center">
<img src="docs/diagram-retrieval-pipeline.svg" alt="Retrieval pipeline: Intent → TMM fusion → FlashRank reranking" width="80%"/>
</p>

| Signal | What it finds | Example |
|---|---|---|
| **Vector similarity** | Memories with similar *meaning* | "fix the auth bug" finds "resolved authentication issue" |
| **Full-text search** | Memories with matching *keywords* | "PostgreSQL migration" finds exact term matches |
| **Trigram similarity** | Memories with similar *spelling* | "postgre" still finds "PostgreSQL" |
| **Thermodynamic heat** | Memories you use *frequently* | Your most-accessed architectural decisions rank higher |
| **Recency** | Memories from *recent* sessions | Yesterday's context ranks above last month's |

After fusion, a cross-encoder AI (FlashRank) re-scores the top candidates for a final quality check.

For conversations over 1M tokens, the **Structured Context Assembler** replaces flat search with stage-scoped 3-phase retrieval — see [benchmarks](#benchmarks) for measured results.

### Seven hooks — zero configuration

Hooks fire automatically via Claude Code's plugin system. No manual setup after installation.

| Hook | When it fires | What it does for you |
|---|---|---|
| **SessionStart** | You open Claude Code | Loads your hot memories, anchored decisions, and last checkpoint |
| **UserPromptSubmit** | Before Claude responds | Searches for memories relevant to what you just asked |
| **PostToolUse** | After you edit/write/run code | Captures the action as a memory if it's significant |
| **PostToolUse** | After you read/edit files | Boosts related memories so they surface in the next recall |
| **SessionEnd** | You close Claude Code | Runs the dream cycle — decay, compress, consolidate |
| **Compaction** | Claude's context window fills up | Saves a checkpoint so nothing is lost when context compresses |
| **SubagentStart** | An agent is spawned | Briefs the agent with your prior work and team decisions |

---

## Neural Graph

Launch the interactive visualization with `/cortex-visualize`. Three views: Graph, Board, and Pipeline.

### Graph View

Force-directed neural graph showing domain clusters, memories, entities, and discussions connected by typed edges.

<p align="center">
<img src="docs/neural-graph-overview.png" width="100%" alt="Cortex Neural Graph — unified view with domain clusters, memories, entities, and discussions" />
</p>

### Board View

Memories organized by biological consolidation stage. Each column shows decay rate, vulnerability, and plasticity. Memory cards display domain, heat, importance, and emotional tags.

<p align="center">
<img src="docs/neural-graph-board.png" width="100%" alt="Cortex Board View — kanban consolidation stages with biological metrics" />
</p>

### Pipeline View

Horizontal flow from domains through the write gate into consolidation stages. Block height reflects importance, color indicates domain.

<p align="center">
<img src="docs/neural-graph-pipeline.png" width="100%" alt="Cortex Pipeline View — Sankey flow through consolidation stages" />
</p>

### Detail Panels

Click any node for full context. Discussion nodes show session timeline, tools used, keywords, and a full conversation viewer. Memory nodes show biological meters (encoding strength, interference, schema match) and git diffs.

<p align="center">
<img src="docs/neural-graph-discussion.png" width="49%" alt="Cortex — discussion detail with full conversation history" />
<img src="docs/neural-graph-diff.png" width="49%" alt="Cortex — code diff viewer in memory detail panel" />
</p>

### Filters

Domain, emotion, and consolidation stage dropdowns. Toggle buttons for methodology, memories, knowledge, emotional nodes, protected/hot/global memories, and discussions.

---

## Agent Integration

Cortex is designed to work with a team of specialized agents. Each agent has scoped memory (`agent_topic`) while sharing critical decisions across the team.

### Transactive Memory System

Based on Wegner 1987: teams store more knowledge than individuals because each member specializes, and a shared directory tells everyone who knows what.

<p align="center">
<img src="docs/diagram-team-memory.svg" alt="Transactive Memory System — agent specialization, coordination, directory" width="80%"/>
</p>

**Specialization** — each agent writes to its own topic. Engineer's debugging notes don't clutter tester's recall.

**Coordination** — decisions auto-protect and propagate. When engineer decides "use Redis over Memcached," every agent sees it at next session start.

**Directory** — entity-based queries span all topics. "What do we know about the reranker?" returns results from engineer, tester, and researcher.

### Agent Briefing

When the orchestrator spawns a specialist agent, the SubagentStart hook automatically:

1. Extracts task keywords from the prompt
2. Queries agent-scoped prior work (FTS, no embedding load needed)
3. Fetches team decisions (protected + global memories from other agents)
4. Injects as context prefix — agent starts with knowledge

### Compatible Agent Team

Works with any custom Claude Code agents. See [zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents) for a reference team of 18 specialists:

| Agent | Specialty | Memory Topic |
|---|---|---|
| orchestrator | Parallel agent execution, coordination, merge | `orchestrator` |
| engineer | Clean Architecture, SOLID, any language/stack | `engineer` |
| architect | Module decomposition, layer boundaries, refactoring | `architect` |
| code-reviewer | Clean Architecture enforcement, SOLID violations | `code-reviewer` |
| test-engineer | Testing, CI verification, wiring checks | `test-engineer` |
| dba | Schema design, query optimization, migrations | `dba` |
| research-scientist | Benchmark improvement, neuroscience/IR papers | `research-scientist` |
| frontend-engineer | React/TypeScript, component design, accessibility | `frontend-engineer` |
| security-auditor | Threat modeling, OWASP, defense-in-depth | `security-auditor` |
| devops-engineer | CI/CD, Docker, PostgreSQL provisioning | `devops-engineer` |
| ux-designer | Usability, accessibility, design systems | `ux-designer` |
| data-scientist | EDA, feature engineering, data quality, bias auditing | `data-scientist` |
| experiment-runner | Ablation studies, hyperparameter search, statistical rigor | `experiment-runner` |
| mlops | Training pipelines, model serving, GPU optimization | `mlops` |
| paper-writer | Research paper structure, narrative flow, venue conventions | `paper-writer` |
| reviewer-academic | Peer review simulation (NeurIPS/CVPR/ICML style) | `reviewer-academic` |
| professor | Concept explanation, mental models, adaptive teaching | `professor` |
| latex-engineer | LaTeX templates, figures, TikZ, bibliographies | `latex-engineer` |

### Skills

Cortex ships as a Claude Code plugin with 14 skills:

| Skill | Command | What It Does |
|---|---|---|
| cortex-remember | `/cortex-remember` | Store a memory with full write gate |
| cortex-recall | `/cortex-recall` | Search memories with intent-adaptive retrieval |
| cortex-consolidate | `/cortex-consolidate` | Run maintenance (decay, compress, CLS) |
| cortex-explore-memory | `/cortex-explore-memory` | Navigate memory by entity/domain |
| cortex-navigate-knowledge | `/cortex-navigate-knowledge` | Traverse knowledge graph |
| cortex-debug-memory | `/cortex-debug-memory` | Diagnose memory system health |
| cortex-visualize | `/cortex-visualize` | Launch 3D neural graph in browser |
| cortex-profile | `/cortex-profile` | View cognitive methodology profile |
| cortex-setup-project | `/cortex-setup-project` | Bootstrap a new project |
| cortex-develop | `/cortex-develop` | Memory-assisted development workflow |
| cortex-automate | `/cortex-automate` | Create prospective triggers |

---

## Benchmarks

All scores are **retrieval-only** — no LLM reader in the evaluation loop. We measure whether retrieval places correct evidence in the top results.

### Running benchmarks from a fresh clone

Benchmarks need extra dependencies beyond the core MCP server. Install them via the `benchmarks` extra:

```bash
git clone https://github.com/cdeust/Cortex.git
cd Cortex
pip install -e ".[postgresql,benchmarks,dev]"
```

This pulls in everything needed:
- `datasets` — HuggingFace loader (BEAM, LoCoMo, LongMemEval auto-download)
- `sentence-transformers` — `all-MiniLM-L6-v2` embeddings (~90 MB on first run)
- `flashrank` — cross-encoder reranking (`ms-marco-MiniLM-L-12-v2`, ~30 MB)
- `psycopg[binary]` + `pgvector` — PostgreSQL driver and vector similarity

Then make sure PostgreSQL 15+ is running with `pgvector` and `pg_trgm` extensions, and `DATABASE_URL` points to it. The default is `postgresql://localhost:5432/cortex` — create the database with:

```bash
createdb cortex
psql cortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql cortex -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

Run a benchmark:

```bash
# BEAM (ICLR 2026) — 100K split, 20 conversations, ~10 min
python benchmarks/beam/run_benchmark.py --split 100K

# BEAM 10M split (hardest), 10 conversations, ~50 min baseline / ~2h assembler
python benchmarks/beam/run_benchmark.py --split 10M

# BEAM with structured context assembly (any split)
CORTEX_USE_ASSEMBLER=1 python benchmarks/beam/run_benchmark.py --split 10M

# LoCoMo (ACL 2024) — 1986 questions, ~40 min
python benchmarks/locomo/run_benchmark.py

# LongMemEval (ICLR 2025) — 500 questions, ~45 min
python benchmarks/longmemeval/run_benchmark.py --variant s
```

**If you skip the `[benchmarks]` extra**, you'll see catastrophically low scores because the embedder falls back to a hash-based stub (no semantic understanding) and FlashRank reranking is disabled. Always install the extra before running benchmarks.

### Reported scores

| Benchmark | Split | Metric | WRRF baseline | Assembler | Paper best | Paper |
|---|---|---|---|---|---|---|
| LongMemEval | S | R@10 | **97.8%** | — | 78.4% | Wang et al., ICLR 2025 |
| LongMemEval | S | MRR | **0.882** | — | — | |
| LoCoMo | — | R@10 | **92.6%** | — | — | Maharana et al., ACL 2024 |
| LoCoMo | — | MRR | **0.794** | — | — | |
| BEAM | 100K | MRR | 0.591 | **0.602** | 0.329 (LIGHT QA) | Tavakoli et al., ICLR 2026 |
| BEAM | **10M** | MRR | 0.353 | **0.429 (+21.5%)** | 0.266 (LIGHT QA) | Tavakoli et al., ICLR 2026 |

**Structured Context Assembly (April 2026):** The Assembler column uses a 3-phase stage-aware context assembly architecture originating from [ai-prd-builder](https://github.com/cdeust/ai-prd-builder) (public, September 2025 — [`ContextManager.swift`](https://github.com/cdeust/ai-prd-builder/commit/462de01), one month before the BEAM paper). The architecture was designed to generate coherent 9-page PRDs on Apple Intelligence's 4096-token context window via per-section token-budgeted context assembly with provider-specific limits, slot-based budget allocation, and section-keyword relevance filtering. Ported to Python and complemented with HippoRAG PPR (Gutiérrez NeurIPS 2024) and submodular coverage (Krause & Guestrin 2008). At 10M tokens per conversation, it improves 8 of 10 BEAM abilities over flat WRRF retrieval. See [research post](docs/research-post-context-assembly.md) for full provenance, methodology and per-category results.

> **Note on BEAM scores:** BEAM (Tavakoli et al., ICLR 2026) does not define a retrieval MRR metric — the paper's evaluation is nugget-based LLM-as-judge. Our "MRR" is a retrieval-proxy metric (rank of first substring-matching memory). The "LIGHT QA" scores in the "Paper best" column are end-to-end QA scores, not directly comparable to our retrieval MRR but shown for directional reference.

> **Measurement protocol (April 2026):** All BEAM scores measured on a fresh `cortex_bench` database (DROP + CREATE per run), TRUNCATE all data tables between conversations, verified FlashRank preflight, deterministic within ±0.01 MRR. BEAM-10M turn IDs remapped to globally unique via cumulative plan offsets (raw dataset has plan-relative IDs that collide). See `scripts/bench_variance.sh` and `benchmarks/lib/bench_db.py` for protocol details.

> **Prior score corrections:** Previously reported BEAM MRR of 0.627 was measured on a polluted database (cross-conversation entity leakage). The 0.546 was measured with per-conversation entity contamination that inflated cross-session categories. Both have been superseded by the clean-DB measurements above.

<details>
<summary>Ablation log — approaches tried and results</summary>

**Emotional memory processing (BEAM +0.038 MRR, shipped)**

| Change | Paper | Result |
|---|---|---|
| Emotional retrieval signal (time-dependent multiplicative boost) | Yonelinas & Ritchey 2015 | +0.035 MRR, +5.1pp R@10 |
| Time-dependent decay resistance | Yonelinas & Ritchey 2015 | Included in above |
| Reconsolidation emotional boost + PE gate + age factor | Lee 2009, Osan-Tort-Amaral 2011, Milekic & Alberini 2002 | Included in above |

**Event ordering + summarization intent (BEAM +0.003 MRR, shipped)**

| Change | Paper | Result |
|---|---|---|
| EVENT_ORDER intent + chronological RRF reranking | ChronoRAG (Chen 2025), Cormack et al. (SIGIR 2009) | event_ordering 0.339→0.349 |
| SUMMARIZATION intent detection | — | summarization 0.379→0.391 |

**MMR diversity reranking (no improvement, disabled)**

| Lambda | Summarization MRR | Overall MRR | Verdict |
|---|---|---|---|
| No MMR | **0.391** | **0.543** | Baseline |
| 0.5 | 0.367 | 0.540 | Regression |
| 0.7 | 0.381 | 0.538 | Regression |

MMR (Carbonell & Goldstein, SIGIR 1998) trades precision for coverage. BEAM's MRR metric rewards first-hit position, so any diversity reranking hurts. Module kept (`mmr_diversity.py`) for future QA-based evaluation.

**Instruction/preference typed retrieval (no improvement, stashed)**

Six approaches tried to improve instruction_following (0.244) and preference_following (0.374):

| Approach | Paper | Instruction | Preference | Overall | Verdict |
|---|---|---|---|---|---|
| Baseline (no type work) | — | 0.244 | 0.374 | 0.543 | — |
| Tag boost in PL/pgSQL (weight 0.4) | ENGRAM | 0.245 | 0.370 | 0.540 | No help |
| Tightened regex + gated type pool | ENGRAM, Searle 1969 | **0.245** | **0.390** | **0.546** | Best |
| Centroid classifier (Snell 2017) + gated pool | Prototypical Networks | 0.241 | 0.357 | 0.544 | Slight regression |
| Centroid ungated + insert at rank 1 | ENGRAM | 0.203 | 0.295 | 0.434 | **Destructive** |
| Centroid ungated + append | ENGRAM | 0.241 | 0.372 | 0.545 | Neutral |
| Centroid ungated + pre-rerank inject | ENGRAM | 0.241 | 0.375 | 0.544 | Neutral |

**Root cause analysis:** BEAM instruction/preference queries look like normal questions ("Could you show me how to implement a login feature?") — not instruction-seeking queries. Intent classification cannot detect them because there's no instruction signal in the query. The answer should come from a stored instruction memory that is semantically close to the topic, but the standard WRRF retrieval already finds those memories — they just don't rank higher than episodic memories about the same topic. The problem is not recall (memories are found) but discrimination (instruction memories are indistinguishable from episodic memories by embedding similarity alone).

**Open problem:** Instruction/preference retrieval requires either (a) a query-side classifier that detects "this question would benefit from instruction context" without keyword signals, or (b) a fundamentally different approach like ENGRAM's LLM-based routing at ingestion time. See [cortex-abstention](https://github.com/cdeust/cortex-abstention) for the community-driven model approach.

</details>

<details>
<summary>Per-category breakdowns</summary>

**BEAM (10 abilities, 395 questions, 100K split)**

| Ability | MRR | R@10 |
|---|---|---|
| temporal_reasoning | 0.903 | 100.0% |
| contradiction_resolution | 0.892 | 100.0% |
| knowledge_update | 0.867 | 97.5% |
| multi_session_reasoning | 0.742 | 95.0% |
| information_extraction | 0.570 | 77.5% |
| summarization | 0.391 | 66.7% |
| preference_following | 0.374 | 72.5% |
| event_ordering | 0.349 | 62.5% |
| instruction_following | 0.244 | 52.5% |
| abstention | 0.100 | 10.0% |

**LongMemEval (6 categories, 500 questions)**

| Category | MRR | R@10 |
|---|---|---|
| Single-session (assistant) | 0.982 | 100.0% |
| Multi-session reasoning | 0.936 | 99.2% |
| Knowledge updates | 0.921 | 100.0% |
| Temporal reasoning | 0.857 | 97.7% |
| Single-session (user) | 0.806 | 94.3% |
| Single-session (preference) | 0.641 | 90.0% |

**LoCoMo (5 categories, 1982 questions)**

| Category | MRR | R@10 |
|---|---|---|
| adversarial | 0.855 | 93.9% |
| open_domain | 0.835 | 95.0% |
| multi_hop | 0.760 | 88.8% |
| single_hop | 0.700 | 92.9% |
| temporal | 0.539 | 77.2% |

</details>

---

## Architecture

Cortex follows Clean Architecture — the brain (core logic) never touches the outside world (database, files, network). Everything flows through strict layers:

<p align="center">
<img src="docs/diagram-architecture.svg" alt="Clean Architecture layers" width="80%"/>
</p>

| Layer | What lives here | Count | Rule |
|---|---|---|---|
| **core/** | All the neuroscience + retrieval logic | 118 modules | Pure math and algorithms. No database calls, no file reads. |
| **context_assembly/** | The structured context assembler (new) | 10 modules | Stage-aware 3-phase retrieval + priority-budgeted prompt assembly |
| **infrastructure/** | PostgreSQL, embeddings, file I/O | 33 modules | The only layer that talks to the outside world |
| **handlers/** | MCP tools (remember, recall, consolidate...) | 62 tools | Wires core logic to infrastructure — the "plugs" |
| **hooks/** | Automatic lifecycle actions | 7 hooks | Fires on session start/end, tool use, compaction |
| **shared/** | Utility functions | 12 modules | Text processing, similarity, hashing — no dependencies |

**Why this matters:** Any mechanism can be tested in isolation (no database needed), swapped without breaking others, and audited against its paper without reading infrastructure code.

**Storage:** PostgreSQL 15+ with pgvector (HNSW vector index) and pg_trgm (fuzzy text matching). All retrieval runs as PL/pgSQL stored procedures — the database does the heavy lifting, not Python.

---

## How Cortex Remembers — The Science in Plain Language

Every mechanism in Cortex traces to published neuroscience or information retrieval research. Here's what each system does, why it works, and what it contributes to benchmark scores.

### Structured Context Assembly — the headline result

**What it does:** Instead of searching for the 10 most similar memories (which fails when thousands of memories look similar), Cortex breaks the conversation into *stages* (distinct topics or time periods) and assembles context in three phases: (1) retrieve from the current stage, (2) follow entity connections to related stages, (3) fall back to summaries of everything else. Each phase gets a budget. If something has to be cut, the system tells the AI what was removed so it can reason about missing information.

**Why it works:** Your brain doesn't search all memories equally — it focuses on the current context first, then follows associations to related episodes, then uses general knowledge as backup. This is the same structure.

**Result:** +21.5% improvement on BEAM-10M (10 million token conversations). 8 of 10 memory abilities improved.

**Origin:** Designed September 2025 for generating 9-page product documents on Apple Intelligence's 4096-token context window ([ai-prd-builder](https://github.com/cdeust/ai-prd-builder), commit [`462de01`](https://github.com/cdeust/ai-prd-builder/commit/462de01)). Complemented with Personalized PageRank from HippoRAG (Gutiérrez, NeurIPS 2024) and submodular coverage selection (Krause & Guestrin, JMLR 2008).

### Retrieval — finding the right memory

| System | What it does | Analogy | Paper |
|---|---|---|---|
| **5-signal fusion** | Combines vector similarity, keyword matching, fuzzy matching, importance, and recency into one score | Like using Google AND a librarian AND a friend's recommendation at once | Bruch et al. 2023 (ACM TOIS) |
| **Cross-encoder reranking** | A second AI re-scores the top candidates for relevance | Getting a second opinion on your search results | Nogueira & Cho 2019; FlashRank |
| **Spreading activation** | When you recall "Python", related memories ("Flask", "debugging") light up too | How thinking of a word makes related words come to mind faster | Collins & Loftus 1975 |
| **Titans momentum** | Memories that surprise the system (unexpected content) get boosted | Paying more attention when something doesn't match your expectations | Behrouz et al. NeurIPS 2025 |
| **Cognitive map** | Tracks which memories are accessed together, building a navigation graph | Like knowing that thinking about "morning coffee" often leads to "project planning" | Stachenfeld et al. 2017 |

### Encoding — deciding what to remember

| System | What it does | Analogy | Paper |
|---|---|---|---|
| **Predictive coding gate** | Only stores memories that are genuinely new — rejects duplicates and predictable content | Your brain doesn't remember every step you take, only the surprising ones | Friston 2005; Bastos et al. 2012 |
| **Emotional tagging** | Emotionally charged memories (frustration, excitement) get stronger encoding | You remember your wedding day better than last Tuesday's lunch | Wang & Bhatt 2024; Yerkes-Dodson 1908 |
| **Neuromodulation** | Four chemical signals (dopamine, norepinephrine, acetylcholine, serotonin) tune how aggressively the system learns | Your brain's "pay attention" vs "relax and absorb" modes | Doya 2002; Schultz 1997 |

### Consolidation — organizing memories over time

| System | What it does | Analogy | Paper |
|---|---|---|---|
| **Sleep replay** | During idle periods, the system replays important memories to strengthen them | How your brain replays the day's events during sleep to build long-term memory | Foster & Wilson 2006; Buzsáki 2015 |
| **Compression cascade** | Old memories compress from full text → summary → keywords over weeks | Like how you remember the gist of a conversation from last year, not every word | Kandel 2001; Ebbinghaus 1885 |
| **Episodic → semantic transfer** | Repeated experiences merge into general knowledge | After 100 code reviews, you just "know" what good code looks like — you don't remember each individual review | McClelland et al. 1995 |
| **Schema formation** | Groups of related memories form reusable templates | Like learning that "bug-fix sessions" follow a pattern: reproduce → diagnose → fix → test | Tse et al. 2007; Gilboa & Marlatte 2017 |
| **Synaptic tagging** | When an important memory arrives, it retroactively boosts recent weak memories that share entities | A breakthrough discovery makes you realize yesterday's "boring" observation was actually important | Frey & Morris 1997 |

### Maintenance — keeping memory healthy

| System | What it does | Analogy | Paper |
|---|---|---|---|
| **Thermodynamic decay** | Unused memories cool down over time; frequently accessed ones stay hot | Like how a restaurant you visit weekly stays top-of-mind, but one from 5 years ago fades | ACT-R (Anderson & Lebiere 1998) |
| **Pattern separation** | Prevents similar memories from blurring together | Your brain keeps "Tuesday's standup" distinct from "Wednesday's standup" even though they're similar | Leutgeb et al. 2007; Yassa & Stark 2011 |
| **Homeostatic plasticity** | Automatically adjusts sensitivity — prevents the system from becoming either too eager or too conservative about storing | Like adjusting your thermostat when the season changes | Turrigiano 2008; Abraham & Bear 1996 |
| **Microglial pruning** | Removes weak, unused connections between entities to keep the knowledge graph clean | Like pruning dead branches so the tree grows healthier | Wang et al. 2020 |

### Every constant is justified

Every threshold, weight, and parameter in Cortex either comes from a paper's equations, from our own measured ablation data, or is explicitly labeled as an engineering default. Nothing is guessed. See `tasks/paper-implementation-audit.md` for the full module-by-module audit (12 FAITHFUL implementations with exact paper equations, 12 DOCUMENTED engineering adaptations, 8 HONEST labeled heuristics).

<details>
<summary>Full paper index (41 citations)</summary>

**Information Retrieval:** Bruch et al. 2023 (ACM TOIS), Nogueira & Cho 2019, Joren et al. 2025 (ICLR), Collins & Loftus 1975, Gutiérrez et al. 2024 (NeurIPS, HippoRAG), Krause & Guestrin 2008 (JMLR)

**Encoding:** Friston 2005, Bastos et al. 2012, Wang & Bhatt 2024, Doya 2002, Schultz 1997

**Consolidation:** Kandel 2001, McClelland et al. 1995, Frey & Morris 1997, Josselyn & Tonegawa 2020, Dudai 2012, Borbely 1982

**Retrieval & Navigation:** Behrouz et al. 2025 (NeurIPS), Stachenfeld et al. 2017, Ramsauer et al. 2021, Kanerva 2009

**Plasticity & Maintenance:** Hasselmo 2005, Buzsáki 2015, Leutgeb et al. 2007, Yassa & Stark 2011, Turrigiano 2008, Abraham & Bear 1996, Tse et al. 2007, Gilboa & Marlatte 2017, Hebb 1949, Bi & Poo 1998, Perea et al. 2009, Kastellakis et al. 2015, Wang et al. 2020, Ebbinghaus 1885, Anderson & Lebiere 1998

**Team Memory:** Wegner 1987, Zhang et al. 2024, McGaugh 2004, Adcock et al. 2006, Bar 2007, Smith & Vela 2001
</details>

### Ablation Data

All ablation results committed to `benchmarks/beam/ablation_results.json`.

| Parameter | Tested Values | Optimal | Source |
|---|---|---|---|
| rerank_alpha | 0.30, 0.50, 0.55, 0.70 | **0.70** | BEAM 100K ablation |
| FTS weight | 0.0, 0.3, 0.5, 0.7, 1.0 | 0.0 (BEAM), 0.5 (balanced) | Cross-benchmark |
| Heat weight | 0.0, 0.1, 0.3, 0.5, 0.7 | 0.7 (BEAM), 0.3 (balanced) | Cross-benchmark |
| Adaptive alpha | CE spread QPP | **Rejected** | Regressed LoCoMo -5.1pp R@10 |

### Engineering Defaults

Values without paper backing, explicitly documented:

| Constant | Value | Location | Status |
|---|---|---|---|
| FTS weight | 0.5 | `pg_recall.py` | Balanced across benchmarks |
| Heat weight | 0.3 | `pg_recall.py` | Balanced across benchmarks |
| CE gate threshold | 0.15 | `reranker.py` | Engineering default |
| Titans eta/theta | 0.9/0.01 | `titans_memory.py` | Paper uses learned params |

---

## Security

Cortex runs locally (MCP over stdio, PostgreSQL on localhost, visualization on 127.0.0.1). No data leaves your machine unless you explicitly configure an external database.

### Audit Score: 91/100

| Category | Score | Notes |
|---|---|---|
| Data Flow | 90 | No external data exfiltration. Embeddings computed locally. |
| SQL Injection | 95 | All queries parameterized (psycopg `%s`). Dynamic columns use `sql.Identifier()`. |
| Auth & Access Control | 85 | Docker PG uses `scram-sha-256` on localhost. MCP over stdio (no network auth needed). |
| Dependency Health | 80 | Floor-pinned deps. Background install version-bounded. |
| Network Behavior | 92 | Model download on first run only. Viz servers bind `127.0.0.1`. |
| Code Quality | 90 | Pydantic validation on all tools. Input length limits on `remember`/`recall`. Path traversal protected. |
| Prompt Injection | 88 | Memory content escaped in HTML rendering. Session injection uses data delimiters. |
| Secrets Management | 90 | `.env`/credentials in `.gitignore`. No hardcoded secrets. Docker credentials via env vars. |

<details>
<summary>Hardening measures</summary>

- SQL parameterization across all 7 `pg_store` modules (psycopg `%s` placeholders)
- `sql.Identifier()` for dynamic column names (no f-string SQL)
- ILIKE patterns escape `%`, `_`, `\` from user input
- CORS allows `*` (localhost-only servers, no external exposure)
- Docker PostgreSQL uses `scram-sha-256` auth on `127.0.0.1/32`
- `trust_remote_code` removed from embedding model loading
- Input length validation: `remember` content capped at 50KB, queries at 10KB
- Path traversal protection via `.resolve()` in `sync_instructions`
- HTML escaping (`esc()`) on all user-generated content in visualization
- Background `pip install` version-bounded (`>=2.2.0,<4.0.0`)
- Secrets patterns (`.env`, `*.credentials.json`, `*.pem`, `*.key`) in `.gitignore`

</details>

---

## Development

```bash
pytest                    # 2080 tests
ruff check .              # Lint
ruff format --check .     # Format
```

---

## License

MIT

## Citation

```bibtex
@software{cortex2026,
  title={Cortex: Persistent Memory for Claude Code},
  author={Deust, Clement},
  year={2026},
  url={https://github.com/cdeust/Cortex}
}
```
</div>
