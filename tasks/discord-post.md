# Discord Post -- Claude Code Community

**Attach:** `docs/neural-graph.png`

---

**Cortex -- Persistent Memory + Cognitive Profiling for Claude Code**

Just shipped a major update: 20 neuroscience-inspired mechanisms + reproducible benchmarks that beat the state of the art.

**LongMemEval Benchmark (ICLR 2025) -- 500 questions, ~115k tokens of conversation history:**

| Metric | Cortex | Best in paper |
|---|---|---|
| **Recall@10** | **98.6%** | 78.4% |
| **MRR** | **0.865** | -- |

+20.2pp above best published R@10. No LLM in the retrieval loop -- 9-signal fusion + cross-encoder reranking, fully local.

**What makes it different:**
- 2-stage retrieval: BM25 + TF-IDF + heat decay + temporal + n-gram + semantic embeddings + entity density -> cross-encoder reranking
- 20 biological mechanisms: predictive coding write gates, neuromodulation cascades, oscillatory phase gating, synaptic plasticity, microglial pruning, pattern separation, schema theory...
- Cognitive profiling: Cortex tracks your reasoning patterns across sessions -- entry points, blind spots, cross-domain bridges. It learns how *you* work.
- 1893 tests, 103 core modules, clean architecture (core = pure logic, zero I/O)

**Benchmark is fully reproducible:**
```
pip install sentence-transformers
python3 benchmarks/longmemeval/run_benchmark.py --variant s
```

GitHub: https://github.com/cdeust/Cortex
