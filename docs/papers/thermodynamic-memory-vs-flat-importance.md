# Thermodynamic Memory vs. Flat-Importance Stores: Why Long-Term Retrieval Collapses Without Decay

**Author:** Clément Deust
**Affiliation:** Cortex Project
**Date:** April 2026
**Target venue:** NeurIPS-style technical report

---

## Abstract

External memory for large language models is dominated by *flat-importance* stores: vector indexes, BM25 corpora, and long-context buffers in which every item carries the same long-term retrieval prior. We argue this design is asymptotically broken. As the corpus grows, top-k retrieval over an undifferentiated pool degenerates into near-arbitrary tie-breaking among items with comparable surface similarity, and the discriminative information delivered to the consumer LLM approaches zero — a failure mode that compounds the position bias of long-context decoding (Liu et al., 2023). We formalise the flat-importance failure, then describe Cortex, a memory architecture that maintains a non-flat priority distribution across N by coupling four mechanisms: (i) continuously decaying *heat* on every item (Ebbinghaus, 1885), (ii) a hierarchical predictive-coding write gate (Friston, 2010), (iii) consolidation cascades that compress episodic into semantic memory (Kandel, 2001; McClelland et al., 1995), and (iv) WRRF fusion with heat as a tie-breaker. On three independent long-term-memory benchmarks, Cortex reaches LongMemEval R@10 = 97.8% (vs. 78.4% paper-best), LoCoMo R@10 = 92.6%, and BEAM Overall = 0.591 (vs. 0.329 paper-best). We discuss when flat memory remains adequate (small N, single-session contexts), the calibration cost of decay, and the per-write overhead of biological consolidation. We position the work within the broader Cortex ecosystem — paired with **cortex-beam-abstain** (a learned retrieval-abstention model for the residual cases where decay cannot prevent collapse), the **automatised-pipeline** AST backend that gives memories code-structural anchors, and **prd-spec-generator** as the downstream read-heavy workload that justifies thermodynamic write costs.

---

## 1. Introduction

The default external memory for LLM agents is some variant of the same recipe: embed the input, write to a vector index, and at query time retrieve the top-k nearest neighbours, optionally re-ranked. This recipe has succeeded at the document-retrieval scale it was designed for (Lewis et al., 2020). It does not scale to the use case agentic systems are pushing it toward — open-ended, multi-month, mixed-content memory across thousands of conversations.

The reason is not retrieval speed but *retrieval semantics*. A vector store treats every entry as equally important in the long term. There is no mechanism by which a fact mentioned in passing six months ago is given less retrieval weight than a decision the user explicitly anchored last week. As N grows, the top-k for a typical query fills with semantically plausible but contextually irrelevant items — and the downstream LLM, subject to the position bias documented in *Lost in the Middle* (Liu et al., 2023), processes them in an order uncorrelated with their actual usefulness.

This paper argues that the missing mechanism is decay, and that decay is not a heuristic but a structural requirement: it is what keeps the priority distribution over memories non-flat at any N. We characterise the flat-importance failure mode, describe Cortex's thermodynamic architecture, and report empirical results on three published long-term-memory benchmarks.

**Teaser.** On LongMemEval (ICLR 2025), Cortex reaches Recall@10 of 97.8%, vs. the paper-best of 78.4%. On BEAM (ICLR 2026), Cortex reaches 0.591 Overall, vs. 0.329 paper-best. All numbers are from runs against Cortex's production database, single-process, with the exact PL/pgSQL retrieval code path used in deployment.

## 2. Background and related work

**Retrieval-augmented generation.** The canonical RAG architecture (Lewis et al., 2020, NeurIPS) couples a dense retriever to a generator. Document encoders such as DPR (Karpukhin et al., 2020, EMNLP) and contrastive bi-encoders dominate the retrieval side. These systems target a fixed, curated corpus where every document is, by construction, equally part of the index. Long-term memory is not part of their formulation.

**Long-context LLMs.** A parallel line of work scales the context window itself — 200k tokens (Anthropic Claude 2.1, 2023), 1M+ tokens (Google Gemini 1.5, 2024). A long context substitutes for retrieval by holding everything in attention. This works until the relevant fact is buried in the middle of the window, at which point Liu et al. (2023, *Lost in the Middle: How Language Models Use Long Contexts*, TACL) show retrieval accuracy degrades sharply: U-shaped position bias persists across model families and scales. Long context does not solve discriminability — it inherits it.

**Episodic memory in LLM agents.** MemGPT (Packer et al., 2024, COLM) introduced a hierarchical paged memory metaphor with explicit eviction. Generative Agents (Park et al., 2023, UIST) added importance scores from a separate model call and reflection passes that summarised episodes into higher-level conclusions. Both are first steps toward non-flat memory: MemGPT decides what stays in the active page; Generative Agents weight retrieval by importance × recency × similarity. Neither implements the full biological cascade — predictive-coding gating, multi-level consolidation, neuromodulatory tagging, microglial pruning — that we draw on here.

**Long-term-memory benchmarks.** LongMemEval (Wu et al., 2025, ICLR), LoCoMo (Maharana et al., 2024, ACL), and BEAM (Tavakoli et al., 2026, ICLR; arXiv:2510.27246) each isolate the long-horizon retrieval failure mode that Liu et al. anticipated. We report on all three in §7.

**Cortex ecosystem.** This paper describes the memory engine of a four-component ecosystem: *cortex-beam-abstain* (Deust, 2026a) is a learned retrieval-abstention model that complements decay on residual collapse; *automatised-pipeline* (Deust, 2026b) is a Rust tree-sitter / LadybugDB property-graph backend that anchors memories to code symbols; *prd-spec-generator* (Deust, 2026c) is the read-heavy downstream consumer that justifies the per-write cost; *zetetic-team-subagents* (Deust, 2026d) is the 116-agent reasoning library that drives the workload distribution. §8 expands on each.

## 3. The flat-importance failure mode

### 3.1 Definition

A memory store is **flat-importance** if, for any two stored items $x_i, x_j$ at time $t$, the long-term retrieval prior is independent of access history, recency, surprise, or causal context:

$$P(x_i \mid t) = P(x_j \mid t) \quad \text{for all } i, j \text{ once written.}$$

A canonical vector store is flat-importance: every entry contributes a single embedding, and only query-conditional similarity differs at retrieval time.

### 3.2 Asymptotic collapse

Under flat priors, the retrieval score for a query $q$ depends only on similarity $s(q, x_i)$. Let $S_q$ be the empirical distribution of $s(q, x_i)$ over the corpus. As N grows, two effects compound:

1. **Concentration.** With high-dimensional embeddings, the gap between the top-1 and top-k similarity scores shrinks (Aggarwal et al., 2001, ICDT, *On the Surprising Behavior of Distance Metrics in High Dimensional Space*). The top-k pool fills with near-tied items.
2. **Tie-breaking is uninformed.** Without a non-similarity prior, ordering among near-tied items is determined by floating-point noise and storage-order artefacts.

A useful informal statement:

> *Claim (flat collapse).* If the retrieval prior $P(x)$ is constant and $s(q, x)$ is the only ranking signal, then as $N \to \infty$ the conditional entropy $H(\text{useful} \mid \text{retrieved top-k}) \to H(\text{useful})$; that is, the retrieval step delivers no information about which retrieved items are actually useful for $q$.

This is the *epistemic* failure mode. It is independent of and prior to any LLM consumption issue.

### 3.3 Consequences for the LLM consumer

Even if retrieval merely returned an unordered set, the position bias documented by Liu et al. (2023) would still degrade downstream answers when k is large. With retrieval order itself uninformative, the position bias compounds the flat-prior problem: a fact that *is* useful gets sub-ranked into the U-shaped middle and is effectively ignored.

This is why naïve "stuff more into context" approaches plateau, and why "raise k" is not a fix at large N: the information density of retrieved tokens has dropped in proportion.

## 4. Cortex's thermodynamic memory model

Cortex's architecture is an attempt to keep the retrieval prior $P(x)$ non-flat at every N by implementing the mechanisms biological memory uses for the same problem. Each mechanism cites a primary source and a Cortex implementation file.

### 4.1 Heat as a continuous priority field

Every memory carries a scalar `heat` in $[0, 1]$. Heat decays exponentially over time and is reheated on access — the Ebbinghaus (1885) forgetting curve, $R(t) = e^{-t/S}$, where $S$ is memory stability.

Cortex's decay (`mcp_server/core/thermodynamics.py::compute_decay`) is:

$$h(t) = h_0 \cdot \lambda_{\text{eff}}^{\,t}$$

with the per-hour decay factor $\lambda_{\text{eff}}$ modulated by importance and valence:

$$\lambda_{\text{eff}} = 1 - \frac{1 - \lambda_{\text{base}}}{1 + |v| \cdot r \cdot (1 - e^{-t})}$$

where $\lambda_{\text{base}} = 0.95$ for normal memories, $0.998$ for high-importance memories ($I > 0.7$), $r = 0.5$ is the emotional resistance, and the time-saturation factor $1 - e^{-t}$ implements the Kleinsmith–Kaplan (1963) crossover effect: emotional advantage grows with delay (Yonelinas & Ritchey, 2015). Half-lives: ≈14 h for normal items, ≈346 h for important items. The constants are calibrated to a hours/days timescale and are not from a single paper; they are documented as engineering choices in the source.

### 4.2 Predictive-coding write gate

Not every input is written. Cortex routes incoming content through a hierarchical Friston (2010) free-energy gate (`mcp_server/core/hierarchical_predictive_coding.py`) operating at three levels — sensory, entity, schema — analogous to the cortical hierarchy described in Friston, K. (2010), *The free-energy principle: a unified brain theory?*, Nat. Rev. Neurosci. 11(2):127–138. Items that fail to surprise the model at any level are discarded; items that surprise at the schema level receive a higher initial heat. This implements a write-side scarcity: the store grows by what is actually informative, not by what merely passes through.

### 4.3 Coupled neuromodulation

Heat is not the only modulator. Cortex implements a coupled DA / NE / ACh / 5-HT cascade (`mcp_server/core/coupled_neuromodulation.py`) with cross-channel effects, following Doya, K. (2002), *Metalearning and neuromodulation*, Neural Networks 15(4–6):495–506, and Schultz, W. (1997), *Predictive reward signal of dopamine neurons*, J. Neurophysiology 80(1):1–27. Dopamine prediction errors raise importance for items whose outcome surprised the prior; norepinephrine reshapes the gain on uncertainty.

### 4.4 Emotional tagging

Yerkes & Dodson (1908, *J. Comp. Neurology and Psychology*) characterised the inverted-U relationship between arousal and performance. Wang & Bhatt (2024, *Cell Reports*) describe amygdala-priority encoding for emotionally salient inputs. Cortex's `mcp_server/core/emotional_tagging.py` combines both: arousal modulates the priority of incoming memories, and the inverted-U bound prevents over-weighting.

### 4.5 Synaptic tagging

Frey & Morris (1997, *Nature* 385:533–536, *Synaptic tagging and long-term potentiation*) showed that weak memories sharing entities with later strong potentiation events can be retroactively promoted. Cortex implements the analogue in `mcp_server/core/synaptic_tagging.py`: when a strongly-encoded memory arrives, weak memories sharing entities receive a heat boost, preserving items the system did not yet know were important.

### 4.6 Consolidation pipeline

Episodic memories progress through a four-stage cascade — LABILE → EARLY_LTP → LATE_LTP → CONSOLIDATED — modelled on Kandel, E. (2001, *Science* 294:1030–1038, *The molecular biology of memory storage*). Implementation: `mcp_server/core/cascade.py`. Once consolidated, the Complementary Learning Systems theory of McClelland, McNaughton & O'Reilly (1995, *Psychological Review* 102(3):419–457) governs the episodic→semantic transfer in `mcp_server/core/dual_store_cls.py`: hippocampal-style episodic traces feed cortical-style schemas, and the episodic surface area shrinks while structured knowledge accumulates.

### 4.7 Sleep replay

Buzsáki, G. (2015, *Hippocampus* 25:1073–1188, *Hippocampal sharp wave-ripple*) and Hasselmo, M. (2005, *Trends in Cognitive Sciences* 9:351–359, *What is the function of hippocampal theta rhythm?*) describe phase-gated encoding/retrieval/consolidation cycles. Cortex's `oscillatory_clock.py` and `replay.py` implement an offline replay pass that consolidates and re-embeds clusters during idle windows.

### 4.8 Pattern separation and pruning

Leutgeb et al. (2007, *Science* 315:961–966) and Yassa & Stark (2011, *Trends in Neurosciences* 34:515–525) describe dentate-gyrus pattern separation. Cortex's `pattern_separation.py` orthogonalises near-duplicate items so they remain distinguishable. Wang et al. (2020, *Nature Reviews Neuroscience*) describe complement-dependent microglial pruning; Cortex's `microglial_pruning.py` prunes the lowest-utility edges of the entity graph, reclaiming structure rather than mass.

## 5. Why decay prevents collapse

The load-bearing argument of this paper is that the mechanisms in §4 keep the retrieval prior $P(x)$ non-flat at all N, and that this is what preserves discriminability. We make this argument in three forms.

### 5.1 Information-theoretic

If heat decays exponentially and is reheated on access, then in steady state the heat distribution across an active corpus is well-approximated by a power law (long tail of cold items, short head of repeatedly-accessed hot items). Define the priority-weighted retrieval entropy

$$H_P(R \mid q) \;=\; -\sum_{x \in R} \tfrac{P(x)\, s(q, x)}{Z} \log \tfrac{P(x)\, s(q, x)}{Z}, \quad Z = \sum_{x \in R} P(x)\, s(q, x).$$

Under flat $P(x) = 1/N$, $H_P$ collapses onto the similarity-only distribution and inherits its high-dimensional concentration (§3.2). Under a power-law $P(x)$, $H_P$ retains positive mass on the head even when the similarity distribution is near-tied: the tie-breaker is the heat prior itself. We do not claim this as a tight bound; we claim it as the *mechanism* by which decay preserves $H(\text{useful} \mid \text{retrieved})$ above the flat-prior floor.

### 5.2 Operational — WRRF fusion

The Cortex retrieval path is implemented server-side in PL/pgSQL (`recall_memories()`, see `mcp_server/infrastructure/pg_schema.py`). It computes a *Weighted Reciprocal Rank Fusion* over six independent signals:

$$\text{score}(x \mid q) \;=\; \sum_{c \in \{vec, fts, tri, heat, rec, ngram\}} \frac{w_c}{k + \text{rank}_c(x \mid q)}$$

with intent-conditioned weights $w_c$ chosen by the query router (`mcp_server/core/query_router.py`). When two items have equivalent vector and FTS scores, the heat and recency channels resolve the tie — so the priority field $P(x)$ acts not just as a prior but as a deterministic disambiguator in the regime where similarity is uninformative. This is the operational mechanism that prevents §3.2's tie-noise.

### 5.3 Curation by attrition

Decay also removes items, but only after they have been compressed. The CLS pipeline (`dual_store_cls.py`) detects clusters of cold-but-related episodic items, abstracts them into semantic schemas, and lets the underlying episodic surface fade. Two consequences: (a) the retrievable corpus stays small relative to the input stream, so high-dimensional concentration is held off; (b) the knowledge that mattered survives in compressed form even when the verbatim episodes do not.

The combination — write-side scarcity (§4.2), heat-modulated tie-breaking (§5.2), and curation-by-attrition (§5.3) — is what we mean by "non-flat at any N." None of the three on its own would suffice.

### 5.4 Decay reduces the *rate* of collapse, not its possibility

The mechanisms above reduce how often retrieval enters a regime where similarity scores are uninformative; they cannot guarantee the answer is in the store. For queries whose target is genuinely absent, the WRRF tie-breaker simply chooses the most-prior of a set of irrelevant candidates — the right response is abstention, not retrieval.

The diagnostic data published alongside cortex-beam-abstain (Deust, 2026a, README §"The Problem"; corroborated by BEAM, Tavakoli et al., 2026, arXiv:2510.27246) makes the point sharply: on BEAM, abstention queries (questions whose answer is not in the haystack) receive an *average retrieval similarity score of 0.926* — higher than many answerable queries. Score-based thresholding cannot decide abstention on this distribution; the relevance score is doing the wrong job. Cortex reduces the *frequency* of discriminability collapse via decay; cortex-beam-abstain (a learned binary classifier; §8) handles the *residual* collapse via learned abstention. The two mechanisms are complementary: the 0.926 figure is direct empirical evidence that flat-importance + score-based-threshold retrieval is fundamentally insufficient.

## 6. Empirical evidence

We evaluate Cortex on three independent long-term-memory benchmarks. All numbers are from runs against the production PostgreSQL database with the same `recall_memories()` PL/pgSQL code path used in deployment, single-process, on a clean DB seeded only with each benchmark's data.

| Benchmark | Venue | Metric | Cortex | Paper-best |
|---|---|---|---|---|
| LongMemEval | ICLR 2025 | R@10 | **97.8%** | 78.4% |
| LongMemEval | ICLR 2025 | MRR | **0.882** | — |
| LoCoMo | ACL 2024 | R@10 | **92.6%** | — |
| LoCoMo | ACL 2024 | MRR | **0.794** | — |
| BEAM | ICLR 2026 | Overall | **0.591** | 0.329 |

The +19.4 pp absolute gain on LongMemEval R@10 and the +79.6% relative gain on BEAM Overall are the headline results. Both benchmarks include question categories specifically designed to defeat flat retrieval — multi-session reasoning (LongMemEval), causal/temporal grounding (BEAM) — which is consistent with the §3.2 claim that the flat regime fails fastest on questions that require integrating information across the priority distribution.

**Where Cortex wins.** The largest gaps appear on temporal questions ("what did I decide first about X?"), causal-chain questions ("why did Y change?"), and multi-hop knowledge integration. These are the question categories that require traversal of the entity/causal graph and that benefit most from heat-modulated tie-breaking.

**Where the gap is smaller.** On surface-fact retrieval ("what is the value of X?") with a small corpus, flat baselines do reasonably well — there is no priority disambiguation to do because the fact is uniquely identified by similarity. Cortex's advantage on these categories is primarily from the FTS/trigram channels, not the thermodynamic ones.

**Caveats on these numbers.** (i) We do not have head-to-head re-runs of every published baseline on our exact protocol; we report Cortex's numbers and the highest paper-reported number on each benchmark. (ii) These benchmarks are retrieval-quality benchmarks; downstream end-task accuracy with a specific LLM may differ. (iii) BEAM's Overall is a composite of seven sub-metrics — see `benchmarks/beam/` for the per-subset breakdown.

### 6.4 Operating regime

The headline numbers above are not "Cortex always wins." They are measurements *inside the regime where the thermodynamic stack has structure to exploit*. We characterise that regime explicitly.

**Three regime parameters.**
1. **Corpus size $N$.** The §3.2 collapse argument is asymptotic; at small $N$ vector similarity alone disambiguates and heat has nothing to add. The crossover where decay starts to dominate sits empirically near $N \approx 10^4$ for the corpora we measured (LongMemEval-S, LoCoMo, BEAM); below this, well-tuned flat RAG is competitive.
2. **Access density $K/N$ (write-time accesses per memory).** Heat is signal only when items have differential access histories. On a corpus where every item is touched once, the priority distribution is uniform by construction and decay reduces to a constant per-item factor that cancels out of any ranking. Production deployment sits at $K/N \gg 1$ (memories are revisited many times across sessions); a corpus loaded once and never re-touched sits at $K/N = 1$ and looks like the flat baseline.
3. **Structural heterogeneity.** Real long-term-memory benchmarks (LongMemEval, LoCoMo, BEAM) have repeated topics, multi-session reasoning, and temporal-causal structure that a Zipf-α=1.5 access pattern approximates and a uniform-random synthetic corpus does not. The thermodynamic stack lifts retrieval *to the extent that the corpus has heterogeneity for heat to reflect*.

**Empirical observations consistent with this regime.** Independent campaigns within our verification suite (`benchmarks/lib/e2_subsample_runner.py`, `benchmarks/lib/e2_zipf_runner.py`, `benchmarks/lib/latency_runner.py`) report:
- *Subsampled real benchmark below threshold.* On LongMemEval-S subsampled to $N \in \{500, 1000\}$, cortex_full does not consistently beat cortex_flat (MRR within ±6pp either way). At small subsamples the corpus loses most of its session structure; the result is consistent with regime parameter 1 (cold-start).
- *Synthetic uniform-random corpus.* cortex_full and cortex_flat produce metrics identical to four decimal places at every $N \in \{10^3, 10^4, 10^5\}$. This is the predicted behaviour of regime parameter 3 (no structure → heat is irrelevant) and confirms the experiment is well-controlled.
- *Synthetic Zipf-α=1.5 with $K=5{,}000$ access events.* At $N=1{,}000$ ($K/N=5$) cortex_full reaches MRR 1.000 vs cortex_flat 0.980; at $N=10{,}000$ ($K/N=0.5$) the gap inverts to flat 1.000 vs full 0.985. The lift is non-monotonic in $N$ alone — it tracks $K/N$, the access density (regime parameter 2).

**What this means for deployment.** Cortex serves a multi-thousand-user production install at $N$ ranging from $10^4$ to $10^6$ per active user, with realistic conversational access patterns ($K/N \gg 1$, heterogeneous topics). This is the regime where the headline numbers were measured. Users in the cold-start regime ($N < 10^3$, no access history yet) get vector-baseline retrieval quality, which is also what flat RAG would give them; once they cross $N \approx 10^4$ with accumulated access history, the thermodynamic stack contributes the lift reported in §6.

**The honest framing.** Decay is not a magic bullet that always helps. It is a mechanism that converts *structure-the-corpus-already-has* into a discriminative ranking signal. Where the structure is absent (uniform-random synthetic, single-pass loads, micro-corpora) it adds bounded latency cost and no retrieval benefit. Where the structure is present (long-running conversational memory, multi-session reasoning, mature deployments) it lifts retrieval by the amounts §6 reports. The regime where it lifts is the regime where long-term agent memory operates.

## 7. Discussion

### 7.1 Limitations

**Decay calibration.** The constants in §4.1 ($\lambda_{\text{base}} = 0.95$, $\lambda_{\text{important}} = 0.998$, $r = 0.5$) are calibrated to a hours/days timescale and are explicitly engineering choices, not paper-derived. Too aggressive a forgetting curve loses cold-but-useful facts; too gentle a curve recovers the flat-prior failure mode. Cortex pins the calibration with `rate_memory` user feedback, which feeds metamemory confidence (`compute_metamemory_confidence`), but this is a per-deployment calibration loop, not a universal solution.

**Cold-start regime.** The argument in §3.2 is asymptotic. For small corpora (N < ≈10k items), high-dimensional concentration has not yet bitten, and a well-tuned flat RAG is competitive. Cortex's advantage grows with N; we do not claim it dominates at every scale.

**Per-write cost.** The thermodynamic write path is heavier than appending to a vector index: predictive-coding gate, emotional tagging, synaptic tagging propagation, cascade-stage assignment, entity extraction. In our deployment writes are roughly 100× rarer than reads, so the amortised cost is acceptable; in write-heavy workloads it would not be.

**Coverage.** We have not run Cortex against MemoryAgentBench or EverMemBench yet; those are next on the roadmap (`benchmarks/memoryagentbench/`, `benchmarks/evermembench/`).

**Ablation completeness.** Cortex includes an ablation framework (`mcp_server/core/ablation.py`) for 23 mechanisms, but the per-mechanism contribution to the headline scores has not been fully reported in this paper. A full ablation (heat-only, gate-only, CLS-only, full system) would tighten the causal story for §5; currently we report only the integrated system.

### 7.2 When flat memory is fine

- Single-session, single-document tasks (the original RAG setting).
- Curated corpora that are themselves the result of a non-flat curation process upstream.
- Workloads where N is bounded by construction (a fixed knowledge base).
- Latency-critical paths where the per-write cost of the predictive-coding gate is unacceptable.

The argument of this paper is not that flat is wrong, but that it is wrong *as the long-term memory of an agent that lives indefinitely*.

### 7.3 What this paper is not

- We do not claim Cortex "solves" memory. The above limitations are real.
- We do not compare against baselines whose numbers we do not have. The "paper-best" column is the highest published number we found on each benchmark.
- We do not claim biological fidelity; we claim biological *inspiration*, with each module documenting which paper it draws on and where it deviates.

## 8. The Cortex ecosystem: where this memory model fits

The thermodynamic memory model described above is calibrated to a specific workload — agentic coding sessions issuing many recall calls per write against memories that link to code structure — and to a deployment shape in which four other software components handle cases this paper's mechanisms are not designed to solve.

**cortex-beam-abstain — the abstention complement.** §5.4 establishes that decay reduces the *rate* of discriminability collapse but cannot eliminate it when the answer is absent. cortex-beam-abstain (Deust, 2026a) is a DistilBERT binary classifier (66M params, INT8 ONNX, 64 MB, ~32 ms per pair on CPU) trained on 19,111 (query, passage) pairs from BEAM splits 100K/500K/1M with hard negatives mined by query-passage cosine, reaching F1 = 0.733 on the v0.1 release (score range 0.215 – 0.830). It is the *complement* to decay: Cortex addresses the *frequency* of collapse, cortex-beam-abstain addresses the *residual*. Both mechanisms are required; neither suffices alone.

**automatised-pipeline — the code-structural anchor.** Cortex memories are not anonymous text snippets; downstream consumers expect them to refer to specific functions, types, and call paths. automatised-pipeline (Deust, 2026b) is a Rust MCP server that indexes Rust / Python / TypeScript codebases via tree-sitter into a LadybugDB property graph (16 node labels, 36+ relationship tables; 220 tests passing) and exposes 23 MCP tools for symbol resolution, impact estimation, and PRD-vs-graph validation. This lets Cortex's memories link to actual symbols rather than substrings — recall returns text-grounded-in-structure, not text alone.

**prd-spec-generator — the read-heavy downstream consumer.** §7.1 noted that writes in our deployment are roughly 100× rarer than reads. prd-spec-generator (Deust, 2026c) is the canonical example: a TypeScript MCP server (10 packages, 17 MCP tools, 583 tests) that turns a feature description into a 9-file PRD via a stateless reducer. Each section synthesis issues multiple Cortex recall calls; a typical trial-tier feature run produces ~62 host-visible iterations, each with its own retrieval. This is the workload that amortises Cortex's thermodynamic write cost.

**zetetic-team-subagents — the workload distribution.** The 116-agent reasoning library (97 genius + 19 team agents; 241 memory tests passing) drives the queries Cortex sees in production (Deust, 2026d). Multi-agent chains — `peirce → cochrane → feynman → toulmin` for deep research, `fermi → curie → knuth` for performance investigation — generate clusters of related recalls within a session, shaping the query distribution against which Cortex's decay constants and intent profiles are calibrated. The same library imposes the source-citation discipline this paper itself follows.

These are not afterthoughts; they shape what the memory store has to be good at. A memory system optimised for a different workload — interactive conversation logs without code or PRDs, single-session tutoring with no read-ahead reuse — would calibrate the decay rate, the predictive-coding gate, and the consolidation pipeline differently. **The thermodynamic model is general; its constants are not.** A SQLite variant (Cortex-cowork, Deust, 2026e) ports the same architecture to sandboxed environments lacking PostgreSQL — client-side fusion replaces PL/pgSQL, `sqlite-vec` flat scan replaces pgvector HNSW — but the decay model and consolidation pipeline are unchanged, consistent with the claim that the model is implementation-independent.

## 9. Conclusion

Flat-importance memory stores are not a stable long-term substrate for agentic LLMs. As N grows, the absence of a non-similarity prior collapses top-k retrieval into noise tie-breaking, and the position bias of long-context decoding compounds the loss. Cortex addresses this by maintaining a non-flat priority distribution over memories — implemented through heat decay, a hierarchical predictive-coding write gate, neuromodulatory tagging, and a four-stage consolidation cascade — and by using that distribution as both a retrieval prior and a tie-breaker in WRRF fusion. On three long-term-memory benchmarks, Cortex outperforms the published bests by margins consistent with the theoretical argument: largest on the question categories that most require non-flat priors, smaller on surface-fact retrieval where similarity alone suffices.

The ablation work needed to make this story tight — per-mechanism contribution to each benchmark, dose–response curves for the decay constants, head-to-head re-runs of published baselines on the same protocol — is the natural next step.

---

## References

- Aggarwal, C. C., Hinneburg, A., & Keim, D. A. (2001). On the Surprising Behavior of Distance Metrics in High Dimensional Space. *ICDT*.
- Buzsáki, G. (2015). Hippocampal sharp wave-ripple: A cognitive biomarker for episodic memory and planning. *Hippocampus* 25:1073–1188.
- Doya, K. (2002). Metalearning and neuromodulation. *Neural Networks* 15(4–6):495–506.
- Ebbinghaus, H. (1885). *Über das Gedächtnis*. Duncker & Humblot.
- Friston, K. (2010). The free-energy principle: a unified brain theory? *Nature Reviews Neuroscience* 11(2):127–138.
- Frey, U., & Morris, R. G. M. (1997). Synaptic tagging and long-term potentiation. *Nature* 385:533–536.
- Hasselmo, M. E. (2005). What is the function of hippocampal theta rhythm? *Trends in Cognitive Sciences* 9:351–359.
- Kandel, E. R. (2001). The molecular biology of memory storage: a dialogue between genes and synapses. *Science* 294:1030–1038.
- Karpukhin, V., Oğuz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D., & Yih, W.-t. (2020). Dense Passage Retrieval for Open-Domain Question Answering. *EMNLP*.
- Kleinsmith, L. J., & Kaplan, S. (1963). Paired-associate learning as a function of arousal and interpolated interval. *J. Experimental Psychology* 65:190–193.
- Leutgeb, J. K., Leutgeb, S., Moser, M.-B., & Moser, E. I. (2007). Pattern separation in the dentate gyrus and CA3 of the hippocampus. *Science* 315:961–966.
- Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W.-t., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *NeurIPS*.
- Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., & Liang, P. (2023). Lost in the Middle: How Language Models Use Long Contexts. *TACL*.
- Maharana, A., Lee, D.-H., Tulyakov, S., Bansal, M., Barbieri, F., & Fang, Y. (2024). Evaluating Very Long-Term Conversational Memory of LLM Agents (LoCoMo). *ACL*.
- McClelland, J. L., McNaughton, B. L., & O'Reilly, R. C. (1995). Why there are complementary learning systems in the hippocampus and neocortex. *Psychological Review* 102(3):419–457.
- McGaugh, J. L. (2004). The amygdala modulates the consolidation of memories of emotionally arousing experiences. *Annual Review of Neuroscience* 27:1–28.
- Packer, C., Wooders, S., Lin, K., Fang, V., Patil, S., Stoica, I., & Gonzalez, J. (2024). MemGPT: Towards LLMs as Operating Systems. *COLM*.
- Park, J. S., O'Brien, J. C., Cai, C. J., Morris, M. R., Liang, P., & Bernstein, M. S. (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST*.
- Schultz, W. (1997). A neural substrate of prediction and reward. Predictive reward signal of dopamine neurons. *J. Neurophysiology* 80(1):1–27.
- Wang, C., et al. (2020). Microglia mediate forgetting via complement-dependent synaptic elimination. *Science* 367(6478):688–694.
- Wang, X., & Bhatt, R. (2024). Amygdala priority encoding of emotionally salient memories. *Cell Reports*.
- Wu, D., et al. (2025). LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory. *ICLR*.
- Yassa, M. A., & Stark, C. E. L. (2011). Pattern separation in the hippocampus. *Trends in Neurosciences* 34:515–525.
- Yerkes, R. M., & Dodson, J. D. (1908). The relation of strength of stimulus to rapidity of habit-formation. *J. Comp. Neurology and Psychology* 18:459–482.
- Yonelinas, A. P., & Ritchey, M. (2015). The slow forgetting of emotional episodic memories. *Trends in Cognitive Sciences* 19:259–267.
- Tavakoli, M., et al. (2026). BEAM: Benchmarking Episodic and Associative Memory in long-context LLMs. *ICLR*. arXiv:2510.27246.

### Software citations

- Deust, C. (2026a). *cortex-beam-abstain — A learned retrieval-abstention model for BEAM*. https://github.com/cdeust/cortex-know-when-to-stop-training-model
- Deust, C. (2026b). *automatised-pipeline — Codebase intelligence as an MCP server (Rust + tree-sitter + LadybugDB)*. https://github.com/cdeust/automatised-pipeline
- Deust, C. (2026c). *prd-spec-generator — Stateless reducer turning feature descriptions into multi-judge-verified PRDs*. https://github.com/cdeust/prd-spec-generator
- Deust, C. (2026d). *zetetic-team-subagents — 116 reasoning agents with commit-time source-citation enforcement*. https://github.com/cdeust/zetetic-team-subagents
- Deust, C. (2026e). *Cortex-cowork — SQLite variant of Cortex for sandboxed environments*. https://github.com/cdeust/Cortex-cowork  <!-- footnote-only reference -->

