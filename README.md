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

Cortex runs as an MCP server alongside Claude Code. It captures what you work on, consolidates it while you're away, and resurfaces the right context when you need it.

### Memory is Invisible

You don't manage memory. Cortex does.

**Session start** — hot memories, anchored decisions, and team context inject automatically. No manual recall needed.

**During work** — PostToolUse hooks capture significant actions (edits, commands, test results). Decisions are auto-detected and protected from forgetting. File edits prime related memories via spreading activation so they surface in subsequent recall.

**Session end** — a "dream" cycle runs automatically: decay old memories, compress verbose ones, and for long sessions, consolidate episodic memories into semantic knowledge (CLS).

**Between sessions** — memories cool naturally (Ebbinghaus forgetting curve). Important ones stay hot. Protected decisions never decay.

### Retrieval Pipeline

Six signals fused server-side in PostgreSQL, then reranked client-side:

<p align="center">
<img src="docs/diagram-retrieval-pipeline.svg" alt="Retrieval pipeline: Intent → TMM fusion → FlashRank reranking" width="80%"/>
</p>

| Signal | Source | Paper |
|---|---|---|
| Vector similarity | pgvector HNSW (384-dim) | Bruch et al. 2023 |
| Full-text search | tsvector + ts_rank_cd | Bruch et al. 2023 |
| Trigram similarity | pg_trgm | Bruch et al. 2023 |
| Thermodynamic heat | Ebbinghaus decay model | Ebbinghaus 1885 |
| Recency | Exponential time decay | — |

### Hooks

Seven hooks integrate with Claude Code's lifecycle (managed via `plugin.json`, no manual setup):

| Hook | Event | What It Does |
|---|---|---|
| **SessionStart** | Session opens | Injects anchors + hot memories + team decisions + checkpoint |
| **UserPromptSubmit** | Before response | Auto-recalls relevant memories based on user's prompt |
| **PostToolUse** | After Edit/Write/Bash | Auto-captures significant actions as memories |
| **PostToolUse** | After Edit/Write/Read | Primes related memories via heat boost (spreading activation) |
| **SessionEnd** | Session closes | Runs dream cycle (decay, compress, CLS based on activity) |
| **Compaction** | Context compacts | Saves checkpoint; restores context after compaction |
| **SubagentStart** | Agent spawned | Briefs agent with prior work + team decisions |

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

| Benchmark | Metric | Cortex | Best in Paper | Paper |
|---|---|---|---|---|
| LongMemEval | R@10 | **97.8%** | 78.4% | Wang et al., ICLR 2025 |
| LongMemEval | MRR | **0.882** | — | |
| LoCoMo | R@10 | **92.6%** | — | Maharana et al., ACL 2024 |
| LoCoMo | MRR | **0.794** | — | |
| BEAM | Overall MRR | **0.546** | 0.329 (LIGHT) | Tavakoli et al., ICLR 2026 |

> **Correction (April 2026):** Previously reported BEAM MRR of 0.627, LoCoMo MRR of 0.840, and LongMemEval MRR of 0.880 were measured on a polluted database — stale benchmark memories from prior runs were not properly purged between conversations, inflating retrieval scores with cross-conversation leakage. The root cause was a psycopg prepared statement cache invalidation bug (`cached plan must not change result type`) that silently prevented the benchmark cleanup function from executing after schema migrations. The bug has been fixed (stale plan recovery via `_execute()` wrapper + `DEALLOCATE ALL` after DDL). All scores above are from clean-database runs with verified per-conversation isolation.

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

Clean Architecture with strict dependency rules. Inner layers never import outer layers.

<p align="center">
<img src="docs/diagram-architecture.svg" alt="Clean Architecture layers" width="80%"/>
</p>

| Layer | Modules | Rule |
|---|---|---|
| **core/** | 118 | Pure business logic. Zero I/O. Imports only `shared/`. |
| **infrastructure/** | 33 | All I/O: PostgreSQL, embeddings, file system. |
| **handlers/** | 62 tools | Composition roots wiring core + infrastructure. |
| **hooks/** | 7 | Lifecycle automation (SessionStart/End, PostToolUse, etc.) |
| **shared/** | 12 | Pure utilities. Python stdlib only. |

**Storage:** PostgreSQL 15+ with pgvector (HNSW) and pg_trgm. All retrieval in PL/pgSQL stored procedures.

---

## Scientific Foundation

### The Zetetic Standard

Every algorithm, constant, and threshold traces to a published paper, a measured ablation, or documented engineering source. Nothing is guessed. Where engineering defaults exist, they are labeled as such.

### Paper Index (41 citations)

<details>
<summary>Information Retrieval</summary>

| Paper | Year | Venue | Module |
|---|---|---|---|
| Bruch et al. "Fusion Functions for Hybrid Retrieval" | 2023 | ACM TOIS | `pg_schema.py` |
| Nogueira & Cho "Passage Re-ranking with BERT" | 2019 | arXiv | `reranker.py` |
| Joren et al. "Sufficient Context" | 2025 | ICLR | `reranker.py` |
| Collins & Loftus "Spreading-activation theory" | 1975 | Psych. Review | `spreading_activation.py` |

</details>

<details>
<summary>Neuroscience — Encoding (5 papers)</summary>

| Paper | Year | Module |
|---|---|---|
| Friston "A theory of cortical responses" | 2005 | `hierarchical_predictive_coding.py` |
| Bastos et al. "Canonical microcircuits for predictive coding" | 2012 | `hierarchical_predictive_coding.py` |
| Wang & Bhatt "Emotional modulation of memory" | 2024 | `emotional_tagging.py` |
| Doya "Metalearning and neuromodulation" | 2002 | `coupled_neuromodulation.py` |
| Schultz "Prediction and reward" | 1997 | `coupled_neuromodulation.py` |

</details>

<details>
<summary>Neuroscience — Consolidation (6 papers)</summary>

| Paper | Year | Module |
|---|---|---|
| Kandel "Molecular biology of memory storage" | 2001 | `cascade.py` |
| McClelland et al. "Complementary learning systems" | 1995 | `dual_store_cls.py` |
| Frey & Morris "Synaptic tagging" | 1997 | `synaptic_tagging.py` |
| Josselyn & Tonegawa "Memory engrams" | 2020 | `engram.py` |
| Dudai "The restless engram" | 2012 | `reconsolidation.py` |
| Borbely "Two-process model of sleep" | 1982 | `session_lifecycle.py` |

</details>

<details>
<summary>Neuroscience — Retrieval & Navigation (4 papers)</summary>

| Paper | Year | Module |
|---|---|---|
| Behrouz et al. "Titans: Learning to Memorize at Test Time" | 2025 | `titans_memory.py` |
| Stachenfeld et al. "Hippocampus as predictive map" | 2017 | `cognitive_map.py` |
| Ramsauer et al. "Hopfield Networks is All You Need" | 2021 | `hopfield.py` |
| Kanerva "Hyperdimensional computing" | 2009 | `hdc_encoder.py` |

</details>

<details>
<summary>Neuroscience — Plasticity & Maintenance (14 papers)</summary>

| Paper | Year | Module |
|---|---|---|
| Hasselmo "Hippocampal theta rhythm" | 2005 | `oscillatory_clock.py` |
| Buzsaki "Hippocampal sharp wave-ripple" | 2015 | `oscillatory_clock.py` |
| Leutgeb et al. "Pattern separation in dentate gyrus" | 2007 | `pattern_separation.py` |
| Yassa & Stark "Pattern separation in hippocampus" | 2011 | `pattern_separation.py` |
| Turrigiano "The self-tuning neuron" | 2008 | `homeostatic_plasticity.py` |
| Abraham & Bear "Metaplasticity" | 1996 | `homeostatic_plasticity.py` |
| Tse et al. "Schemas and memory consolidation" | 2007 | `schema_engine.py` |
| Gilboa & Marlatte "Neurobiology of schemas" | 2017 | `schema_engine.py` |
| Hebb *The Organization of Behavior* | 1949 | `synaptic_plasticity.py` |
| Bi & Poo "Synaptic modifications" | 1998 | `synaptic_plasticity.py` |
| Perea et al. "Tripartite synapses" | 2009 | `tripartite_synapse.py` |
| Kastellakis et al. "Synaptic clustering" | 2015 | `dendritic_clusters.py` |
| Wang et al. "Microglia-mediated synapse elimination" | 2020 | `microglial_pruning.py` |
| Ebbinghaus *Memory* | 1885 | `thermodynamics.py` |

</details>

<details>
<summary>Team Memory & Preemptive Retrieval (6 papers)</summary>

| Paper | Year | Module |
|---|---|---|
| Wegner "Transactive memory" | 1987 | `memory_ingest.py`, `session_start.py` |
| Zhang et al. "Collaboration Mechanisms for LLM Agents" | 2024 | `memory_ingest.py` |
| McGaugh "Amygdala modulates consolidation" | 2004 | `memory_ingest.py` |
| Adcock et al. "Reward-motivated learning" | 2006 | `memory_ingest.py` |
| Bar "The proactive brain" | 2007 | `preemptive_context.py` |
| Smith & Vela "Context-dependent memory" | 2001 | `agent_briefing.py` |

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
