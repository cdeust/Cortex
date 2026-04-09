# Cortex — Scientific Foundation

> Moved from README to keep the main page focused. Every mechanism traces to published research. [Back to README](../README.md).

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
