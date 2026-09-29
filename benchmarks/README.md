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
(datasets + embedding models), no API keys. (The separate, offline token
count described under *Per-query journal* is the one step that needs an
Anthropic credential; it never runs inside a scoring leg.)

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
| `--only longmemeval,locomo,beam` | run only these benchmarks; `decision-ids` is also accepted, and the artifact names `longmemeval-s` and `beam-100K` are aliases. An unknown or empty token fails closed with exit 2 before anything runs |
| `--no-ablation` / `--ablation-only` | skip the sweep / skip the plain benchmarks |
| `--ablate-on locomo\|beam\|longmemeval` | which benchmark the sweep drives (default `locomo`) |
| `--quick` | small per-benchmark limits (fast end-to-end check) |
| `--limit N` | explicit per-benchmark cap |
| `--keep-db` | leave the container up for inspection |
| `--only longmemeval-cleaned` | opt-in leg on the 2025-09 cleaned LongMemEval-S release, pinned by revision and sha256 (`benchmarks/lib/dataset_pins.py`); artifact `longmemeval-s-cleaned.json`, never judged against the floors measured on the original file. An empty `--only` keeps the historical set |
| `--query-log-content` | passes through to the runners: store each retrieved item's text in the per-query journal (needed for token counting) |

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
| BEAM (ICLR 2026) | `beam/run_benchmark.py --split 100K` | `Mohammadta/BEAM` at the pinned revision `BEAM_REVISION` (`benchmarks/lib/dataset_pins.py`) |
| MemoryAgentBench, EverMemBench, Episodic | respective `run_benchmark.py` | see runner's download hint |

Every result JSON now carries `manifest.dataset` (repository, revision,
file, bytes, sha256 as that leg knows them), and the run-level
`MANIFEST.json` gathers them under `datasets`.

## Per-query journal, tokens and energy

With `--results-out`, the LongMemEval, LoCoMo and BEAM runners also write,
next to `<stem>.json`:

- `<stem>.queries.jsonl` — one line per scored query: the retrieved items'
  ids, sources, scores, UTF-8 bytes, code points and sha256 (and the text,
  with `--query-log-content`). LongMemEval lines also carry the bytes of the
  question's whole haystack.
- `<stem>.phases.jsonl` — wall-clock start and end of every `ingest` and
  `recall` phase.

Both are written after `recall` returns; retrieval and scores are unchanged
(`tests_py/benchmarks/test_query_log_scores_unchanged.py`).

**Tokens** are counted offline, after scoring, with Anthropic's
token-counting endpoint for one pinned model (never an estimate from
characters, never tiktoken):

```bash
uv run --extra benchmarks --with anthropic \
    python benchmarks/tokens/count_tokens.py \
    --queries RESULTS_DIR/locomo.queries.jsonl --out RESULTS_DIR/locomo.tokens.json
# LongMemEval: add --lme-dataset benchmarks/longmemeval/longmemeval_s_cleaned.json
# to count each question's full history as well (retrieved vs full-history ratio).
```

It reports, per query, the retrieved texts (`t_retrieved`) and the
bench-equivalent recall payload in `json` and `tabular` form
(`benchmarks/tokens/payload.py`: the handler's own `bound_payload` /
`encode_within_budget`, without the live handler's over-fetch and enrichment
stages). The payload is not what the auto-recall hook injects; that hook is a
different, FTS-only path.

**Energy** per scored query comes from the same phase timeline, under the
existing sensor lifecycle: see *Benchmark phases* in
`benchmarks/energy/README.md`.

Ablation studies (per-mechanism lesion runs) live in
`benchmarks/lib/ablation_runner` and their results under
`benchmarks/results/ablation/`.
