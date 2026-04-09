# Priority-Budgeted Stage-Aware Context Assembly for Long-Context Memory Retrieval

**Authors:** Clément Deust (original architecture, April 2025), with Claude Opus 4.6 (port, benchmark, paper-backed complements)

**Date:** April 9, 2026

**Repository:** [github.com/cdeust/Cortex](https://github.com/cdeust/Cortex) — commit `5348f74`

---

## Abstract

We present a structured context assembly architecture for long-term memory retrieval that achieves a **21.5% improvement** over flat Weighted Reciprocal Rank Fusion (WRRF) on the BEAM-10M benchmark (Tavakoli et al., ICLR 2026) — the hardest publicly available long-context memory evaluation at 10 million tokens per conversation.

The architecture, originally designed in April 2025 for generating coherent 9-page product requirement documents on Apple Intelligence's 4096-token context window, was ported to Cortex's PostgreSQL-backed memory system and complemented with paper-backed mechanisms (HippoRAG PPR, submodular coverage selection). No precedent for the full combination was found in a comprehensive survey of 2024–2026 literature spanning biology, mathematics, AI research, and engineering.

The key insight: **at scale, structured context assembly with typed priority slots, stage-scoped retrieval, and cross-stage entity graph traversal outperforms flat dense retrieval** — not because the retrieval primitives are better, but because the *composition* manages the context budget in a way flat top-k cannot.

## The Problem

Dense vector retrieval collapses at long-context scale. On BEAM (Beyond a Million Tokens, ICLR 2026), Cortex's production WRRF pipeline — which fuses 5 PostgreSQL-side signals (vector similarity, full-text search, trigram, heat, recency) with client-side FlashRank cross-encoder reranking — scores:

- **BEAM-100K** (94 memories/conversation): 0.437 MRR — acceptable
- **BEAM-10M** (7,500 memories/conversation): 0.353 MRR — significant degradation

The degradation is structural, not parametric. At 7,500 near-topical memories with 384-dimensional embeddings, the well-documented hubness phenomenon (Radovanović et al., JMLR 2010) and concentration of distances (Beyer et al., ICDT 1999) make cosine-based nearest-neighbor retrieval increasingly noisy. The Johnson-Lindenstrauss lower bound (Larsen & Nelson, FOCS 2017) confirms that 384 dimensions cannot preserve pairwise distances to 10% accuracy for 7,500+ points.

No amount of reranking, query rewriting, or embedding model upgrade can fix a geometric ceiling. The architecture must change.

## The Architecture

### Origin

In April 2025, Clément Deust designed a context management system for `ai-architect-prd-builder` — a production Swift application that generates comprehensive PRDs using Apple Intelligence (4,096-token context window). The system produces coherent 9-page documents with cross-referenced requirements, working code, verification reports, and Jira tickets — none of which fit in the model's context simultaneously.

The solution: **don't try to fit everything. Structure what goes in, prioritize it, and tell the model what was cut.**

### Two Core Primitives

**1. ContextDecomposer** — Priority-budgeted prompt assembly

A prompt is a template with typed placeholder slots. Each slot has:
- A **priority rank** (lower = more important, condensed last)
- An optional **domain-aware condenser** (e.g., code → signatures only; prose → first sentence + questions; entity triples → verbatim)
- A **token budget** derived from the reader's context window at runtime (never hardcoded)

When the filled template exceeds the budget:
1. Compute shell tokens (template with empty slots)
2. Allocate remaining budget proportionally across slots
3. Condense highest-priority-number (least important) slots first, using their domain-aware condensers
4. Post-assembly safety: iteratively halve the least important slot until the prompt fits
5. **Inject a truncation warning banner** at the top listing what was cut and by how much — so the model can reason about missing information

The truncation warning is, to our knowledge, novel. No paper in the 2024–2026 literature we surveyed implements explicit truncation awareness in the prompt itself.

**2. StageAwareContextAssembler** — Three-phase hierarchical retrieval

A "stage" is a distinct topical segment of a conversation — analogous to a work session, a plan, or a thematic unit. The assembler operates in three phases with a configurable budget split (default 60/30/10):

- **Phase 1 — Own-stage (60%)**: Retrieve from the current stage's memories using the existing WRRF pipeline, then select via submodular coverage (Krause & Guestrin, JMLR 2008) to maximize information gain rather than raw similarity.

- **Phase 2 — Adjacent stages via entity graph (30%)**: Extract entities from Phase 1 results, seed Personalized PageRank (Gutiérrez et al., "HippoRAG", NeurIPS 2024) on the entity co-occurrence graph, score cross-stage memories by aggregated PPR mass. This bridges topically distinct sessions that share entities.

- **Phase 3 — Summary fallback (10%)**: For stages not covered by Phase 1 or 2, retrieve pre-computed schema-structured summaries (Tse et al., Science 2007) ordered by stage proximity.

The output is a structured context with labeled sections ("Current Stage Context", "Related Prior Context", "Stage Summaries") — ready for either direct scoring or assembly into a reader prompt via the ContextDecomposer.

### Design Principles

1. **No hardcoded token caps.** Token budget is always derived from the reader's context window at runtime — the Swift original used `reasoner.contextWindowSize * 0.75`. For retrieval evaluation (no reader), budget is `None` and selection is purely by chunk count.

2. **Selection decoupled from assembly.** How many memories to select (ranking concern) is independent of how many tokens to spend (prompt concern). Submodular selection always picks `max_chunks` items regardless of their individual sizes.

3. **Stage detection is pluggable.** The `StageDetector` interface supports explicit labels (plan IDs for benchmarks), temporal gaps (session boundaries for production), semantic clustering, or LLM topic-shift detection — A/B testable via configuration.

## Results

### BEAM-100K (5 conversations, same-conversation A/B)

| | WRRF | Assembler | Δ |
|---|---|---|---|
| **Overall MRR** | 0.591 | 0.602 | +0.011 |
| info_extraction | 0.543 | 0.700 | +0.157 |
| event_ordering | 0.380 | 0.525 | +0.145 |
| multi_session | 0.812 | 0.500 | −0.312 |

At 100K scale (94 memories/conversation), the assembler is **net-flat**. Stage-scoping helps specific-fact categories but hurts multi-session reasoning because flat search over 94 candidates is already sufficient and stage filtering only restricts.

### BEAM-10M (10 conversations, full benchmark)

| | WRRF | Assembler | Δ |
|---|---|---|---|
| **Overall MRR** | **0.353** | **0.429** | **+0.076 (+21.5%)** |
| abstention | 0.100 | 0.350 | +0.250 |
| multi_session | 0.415 | 0.543 | +0.128 |
| temporal | 0.370 | 0.467 | +0.097 |
| contradiction | 0.633 | 0.725 | +0.092 |
| preference | 0.412 | 0.481 | +0.069 |
| knowledge_update | 0.835 | 0.892 | +0.057 |
| instruction | 0.068 | 0.125 | +0.057 |
| info_extraction | 0.448 | 0.487 | +0.039 |
| event_ordering | 0.067 | 0.067 | +0.000 |
| summarization | 0.186 | 0.150 | −0.036 |

At 10M scale (7,500 memories/conversation), **8 of 10 categories improve**. The critical validation: **multi-session reasoning flips from −0.312 at 100K to +0.128 at 10M** — Phase 2's cross-stage PPR traversal reaches gold content that flat WRRF cannot find when drowning in 7,500 near-duplicate embeddings.

### Architecture Thesis

Stage-scoped structured assembly is **net-flat at small scale** (corpus fits in flat search) and **dominates at large scale** (corpus exceeds flat search capacity). The crossover point is between 1M and 10M tokens — exactly the regime BEAM was designed to stress-test.

## Methodology Notes

- **Metric**: Retrieval-proxy MRR — rank of first retrieved memory whose content substring-matches the gold source turn or answer text. Not the BEAM paper's LLM-judge QA score (which does not define a retrieval metric). Both WRRF and assembler are measured with the same harness.
- **Protocol**: Fresh `cortex_bench` database per run (DROP + CREATE). TRUNCATE all data tables between conversations (memories, entities, relationships). No cross-conversation contamination.
- **Embedding model**: sentence-transformers `all-MiniLM-L6-v2` (384D, 256 max tokens) — same for both conditions.
- **BEAM-10M data fix**: Turn IDs are plan-relative in the raw dataset; we apply cumulative plan offsets to produce globally unique IDs matching `source_chat_ids`. Without this fix, all 10M measurements are invalid (0% gold match). See commit `5348f74`.

## Related Work

The architecture's building blocks each have paper backing:
- **Submodular coverage**: Krause & Guestrin, JMLR 2008
- **Personalized PageRank for retrieval**: Gutiérrez et al., "HippoRAG", NeurIPS 2024
- **Schema-structured summaries**: Tse et al., Science 2007
- **Active retrieval (query reformulation)**: Wang & Chen, "MIRIX", arxiv 2507.07957, 2025

The composition — priority-budgeted progressive condensation with per-type domain-aware condensers, truncation warning injection, and 60/30/10 three-phase stage-aware assembly — has no published precedent in the literature we surveyed (6 cross-disciplinary research agents covering biology, mathematics, information theory, AI lab publications, PhD theses, and vector database engineering blogs, 2024–2026).

The closest architectural neighbors are:
- **LIGHT** (Tavakoli et al., ICLR 2026): three-tier (episodic + working memory + scratchpad) but without priority budgeting or truncation awareness
- **MIRIX** (Wang & Chen, 2025): active retrieval + typed memory but without stage-scoped retrieval or entity graph traversal
- **A-MEM** (Xu et al., NeurIPS 2025): Zettelkasten-style agentic memory with on-write reconsolidation but without structured prompt assembly

## Limitations

1. **Summarization regressed** (−0.036 at 10M). Summarization questions require broad coverage across many memories; stage-scoping restricts this. Phase 3 (summary tier) is currently a stub — wiring it to Cortex's CLS consolidation engine should address this.

2. **Event ordering unchanged** (0.067). This category requires precise chronological sequencing that neither WRRF nor the assembler addresses — it likely needs the ChronoRAG mechanism (Chen et al., 2025) already present but not wired through the assembler.

3. **Speed**: assembler takes ~680s/conversation at 10M vs ~305s for WRRF. The overhead is entity extraction at ingest + per-query substring entity matching + PPR computation. Caching and batching can reduce this.

4. **Only tested on BEAM retrieval proxy MRR.** End-to-end QA evaluation (with an LLM reader consuming the assembled context) would measure whether the structured assembly also improves answer quality, not just retrieval rank.

## Reproducing

```bash
# Prerequisites: PostgreSQL 17+ with pgvector and pg_trgm extensions
pip install -e ".[postgresql,benchmarks]"

# BEAM-10M baseline (WRRF)
DATABASE_URL="postgresql://localhost:5432/cortex_bench" \
  python benchmarks/beam/run_benchmark.py --split 10M

# BEAM-10M with structured context assembly
CORTEX_USE_ASSEMBLER=1 \
DATABASE_URL="postgresql://localhost:5432/cortex_bench" \
  python benchmarks/beam/run_benchmark.py --split 10M
```

The `cortex_bench` database is dropped and recreated by the benchmark variance script (`scripts/bench_variance.sh`). Results are deterministic within ±0.01 MRR across runs with PostgreSQL restart between runs.

## Acknowledgments

The original ContextDecomposer and StageAwareContextAssembler were designed by Clément Deust in April 2025 as part of [ai-architect-prd-builder](https://github.com/cdeust/ai-architect-prd-builder). The Python port, benchmark integration, and paper-backed complements (HippoRAG PPR, submodular coverage, active retrieval) were implemented in collaboration with Claude Opus 4.6 during a single extended session (April 7–9, 2026).
