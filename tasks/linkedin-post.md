# LinkedIn Post

**Attach:** `docs/neural-graph.png` (the 3D neural graph visualization)

---

I've been building Cortex — a persistent memory and cognitive profiling system for Claude Code — and just hit a milestone worth sharing.

We ran the LongMemEval benchmark (Wu et al., ICLR 2025): 500 human-curated questions buried in ~115k tokens of conversation history. The task is simple — find the right memory. The challenge is that it sits in a haystack of ~50 sessions.

Results:
- Recall@10: 98.6% (vs 78.4% best in the original paper — +20.2pp)
- MRR: 0.865

What makes this interesting isn't just the numbers — it's how we get there.

Most memory systems use a single retrieval signal. Cortex fuses 9 signals in a first stage (BM25, TF-IDF, heat decay, temporal proximity, n-gram matching, user-content focus, semantic embeddings, entity density) then reranks with a cross-encoder. Intent detection routes each query to tuned weight profiles — a temporal question boosts time signals, a preference question boosts semantic + user content. No LLM in the retrieval loop. Fully local, fully reproducible.

But retrieval is only half the story.

The part I'm most excited about is the cognitive profiling layer. Cortex doesn't just store memories — it tracks how you reason across sessions. Entry points, recurring patterns, blind spots, cross-domain bridges. It builds a behavioral profile that evolves over time. When you start a new session, it pre-loads the context that matters for how *you* work, not just what you worked on.

Under the hood, the system implements 20+ neuroscience-inspired mechanisms: predictive coding write gates (Friston free energy), coupled neuromodulation cascades (dopamine/norepinephrine/acetylcholine/serotonin), oscillatory phase gating, synaptic plasticity with LTP/LTD, microglial pruning of stale connections, pattern separation, schema-accelerated consolidation. These aren't metaphors — they're computational models grounded in the literature (Hasselmo 2005, Kandel 2001, Bi & Poo 1998, Turrigiano 2008, etc.).

58 core modules. 1740 tests. Clean architecture where core logic has zero I/O dependencies. The benchmark script is in the repo — anyone can reproduce the results.

Open source: https://github.com/cdeust/Cortex

If you're working with Claude Code and want memory that actually persists and improves — or if you're interested in biologically-inspired AI architectures — take a look. Contributions welcome.

#AI #MachineLearning #NLP #InformationRetrieval #Neuroscience #OpenSource #ClaudeCode #LLM
