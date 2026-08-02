# Reproducing the Cortex benchmarks

Every published Cortex retrieval number comes from the scripts in this
directory, run against the **production code path**: data is ingested
through `mcp_server.core.memory_ingest`, retrieval goes through the same
PL/pgSQL `recall_memories()` + FlashRank reranking that serves live MCP
calls. There is no benchmark-only retriever.

## One command reproduces everything

There is **one** entry point — `make reproduce` (→ `benchmarks/reproduce.sh`).
Every other target is a thin scope-narrowed shortcut into that same script, so
any invocation runs the identical clean-DB / production-recall pipeline and
yields the same numbers. Take it, hit play, reproduce.

Requirements: Docker, [uv](https://docs.astral.sh/uv/), ~1.5 GB free disk
(datasets + embedding models), no API keys.

```bash
make reproduce-smoke     # ALL benchmarks + ablation sweep, tiny limits — a few minutes
make reproduce           # ALL benchmarks + ablation sweep, full — several hours
```

`make reproduce` provisions a single ephemeral PostgreSQL + pgvector container
on a fresh, kernel-assigned port (it never touches an existing Cortex
install), then against that one clean database:

Every run gets its OWN container name and port — `cortex-bench-pg-<pid>-<hex>`,
port chosen by the kernel and discovered via `docker port`, both logged at
startup and recorded in `MANIFEST.json`. This is deliberate: two `reproduce.sh`
runs from different worktrees used to share one fixed container/port
(`cortex-bench-pg` on 55432) and could silently cross-contaminate each
other's scores with no visible error (measured 2026-07-11: 0.9163 isolated
vs. 0.78-0.86 under concurrency). Concurrent runs from different worktrees
are now safe. Pin a specific port with `CORTEX_BENCH_PORT` only if you
specifically need one — you take on the collision risk that existed to
prevent.

1. runs each retrieval benchmark through the production `recall_memories()`
   path — **LongMemEval-S, LoCoMo, BEAM-100K**;
2. runs the **ablation sweep** (baseline + the 13-mechanism v4.0 group) through
   the *same* harnesses via `benchmarks/lib/ablation_runner.py`;
3. writes every result as JSON under `benchmarks/results/repro/<timestamp>/`
   with a `MANIFEST.json` (git sha, dataset sha, image, package versions),
   prints one consolidated table, and tears the container down.

Each harness self-cleans (`BenchmarkDB` purges `is_benchmark` rows on open and
deletes its own on close), so the phases are independent and the whole run is
deterministic.

**Scoping flags** (compose; anything else passes through to the harnesses):

| Flag | Effect |
|---|---|
| `--only longmemeval,locomo,beam` | run only these benchmarks |
| `--no-ablation` / `--ablation-only` | skip the sweep / skip the plain benchmarks |
| `--ablate-on locomo\|beam\|longmemeval` | which benchmark the sweep drives (default `locomo`) |
| `--quick` | small per-benchmark limits (fast end-to-end check) |
| `--limit N` | explicit per-benchmark cap |
| `--keep-db` | leave the container up for inspection |

```bash
make reproduce ARGS=...           # or call the script directly:
bash benchmarks/reproduce.sh --only locomo,beam --ablate-on beam
bash benchmarks/reproduce.sh --only longmemeval --no-ablation   # == make longmemeval
```

Scoped shortcuts still exist and all delegate to `reproduce.sh`:

```bash
make longmemeval          # LongMemEval-S only, no ablation (~40 min)
make longmemeval-smoke    # 10-question sanity run
```

Measured wall-clock for the full LongMemEval run alone: **39.6 min** on Apple
Silicon with CPU embeddings (`benchmarks/results/a3_longmemeval_post_refactor.md`).

## What the numbers mean (metric scope)

Cortex reports **session-level retrieval Recall@10 and MRR**: for each
of the 500 questions, all haystack sessions are loaded into the store,
production recall runs, and the run scores whether the answer-bearing
session(s) appear in the top 10.

- The comparable published baseline is the best retrieval configuration
  in the LongMemEval paper itself (Wu et al., ICLR 2025): **Recall@10
  78.4%**. Cortex: **98.2%**, MRR **0.9167** (n=500; clean-DB run
  `results/repro/20260714-v4.14.1-pretag/longmemeval-s.json`, code SHA
  `28145f0b7a113fc06e22568de6feea7f8444eaf5`, dirty=false).
- This is **not** the end-to-end QA accuracy that LLM-answering
  leaderboards report (an LLM answers from the retrieved context and a
  judge scores the answer). Retrieval recall and QA accuracy are
  different measurements; do not compare one to the other.
- The same scoping discipline applies to BEAM: see the BEAM note in
  `CLAUDE.md` — the retrieval-proxy MRR there is used only for
  within-system comparisons, never as a head-to-head claim.

If your numbers differ from the published ones, open an issue with the
printed reproducibility manifest and we will publish the discrepancy.

## Other benchmarks

| Benchmark | Runner | Dataset |
|---|---|---|
| LongMemEval (ICLR 2025), 500 Q | `longmemeval/run_benchmark.py` | auto-downloaded by the harness |
| LoCoMo (ACL 2024), 1,986 Q | `locomo/run_benchmark.py` | see runner's download hint |
| BEAM (ICLR 2026) | `beam/run_benchmark.py --split 100K` | see runner's download hint |
| MemoryAgentBench, EverMemBench, Episodic | respective `run_benchmark.py` | see runner's download hint |

Ablation studies (per-mechanism lesion runs) live in
`benchmarks/lib/ablation_runner` and their results under
`benchmarks/results/ablation/`.
