# Read-Path Dormant Mechanisms — Ablation Audit

**Context**: E1 verification campaign exposes per-mechanism causal deltas on
the longmemeval-s benchmark. Several mechanisms have module-level
`is_mechanism_disabled()` guards (commit `099ba1e`) but produce **+0.000**
deltas because their call sites are not reached on the production recall
path (`mcp_server/handlers/recall.py` → `mcp_server/core/pg_recall.recall()`).

This document is the honest accounting of which mechanisms are dormant on
the read-path of the longmemeval-s benchmark, and why. The §6.3 ablation
table in the paper marks these rows "(dormant on read-only benchmark)".

## Production Recall Path (longmemeval-s)

```
handler.recall._handler_impl
  └── pg_recall.recall(...)         # all retrieval lives here
        ├── classify_query_intent()
        ├── compute_pg_weights()    # ADAPTIVE_DECAY guard wired here
        ├── store.recall_memories() # PL/pgSQL WRRF fusion (server-side)
        ├── rerank_results()        # FlashRank ONNX (client-side)
        ├── search_by_tag_vector()  # ENGRAM typed pool guarantee
        ├── _chronological_rerank() # iff EVENT_ORDER intent
        └── titans.update()         # SURPRISE_MOMENTUM (state-only)
  ├── inject_triggered_memories()
  ├── _apply_co_activation()        # CO_ACTIVATION guard wired here
  ├── _apply_rules_and_order()
  └── _track_recall_replay()
```

The `mcp_server/handlers/recall_helpers.collect_signals()` function
(which contains `compute_hopfield_hdc`, `compute_graph_signals`,
`_compute_sa`, etc.) **has no caller** in production code. It exists for
legacy / experimental retrievers. On the longmemeval-s benchmark the
production path goes through `pg_recall.recall()` only.

## Dormant Mechanisms (read path of longmemeval-s)

| Mechanism | Module guard | Production read-path call site | Dormant reason | Where would it show up |
|---|---|---|---|---|
| **HOPFIELD** | `core/hopfield.py:100` | None — `compute_hopfield_hdc` lives in unused `recall_helpers.collect_signals` | The Hopfield retrieve step is part of the legacy multi-signal scoring path, not the PG-WRRF path | A retrieval pipeline that explicitly fuses Hopfield attention scores with WRRF (legacy `dispatch_recall` mode); recall paths exercising `compute_hopfield_hdc` directly |
| **HDC** | `core/hdc_encoder.py:229` | None — `compute_hdc_scores` lives in unused `recall_helpers.collect_signals` | HDC scoring is a legacy signal; PG WRRF does not call HDC | A retrieval pipeline using `collect_signals`; query-expansion paths that bind HDC vectors |
| **SPREADING_ACTIVATION** | (not yet wired in `_compute_sa`) | None on PG path — `_compute_sa` is in `compute_graph_signals` which `pg_recall` does not call | The `store.spread_activation_memories()` PL/pgSQL is reachable but not invoked in `pg_recall.recall()` | A benchmark that calls `recall_helpers.collect_signals`; an ablation that explicitly injects SA results into WRRF |
| **DENDRITIC_CLUSTERS** | (no guard added) | None | No dendritic-modulation step in the read path; this mechanism is purely a write-path priming mechanism (`dendritic_clusters.py`) | Write-heavy benchmarks where dendritic priming influences encoding strength |
| **SURPRISE_MOMENTUM** | `core/titans_memory.py:168` | `pg_recall.recall()` step 10 calls `titans.update()` | The update mutates internal state (`momentum_state["momentum"]`) but does NOT reorder candidates — the return value is discarded for ranking purposes | A retriever that uses `momentum_state` as an input signal to scoring; longer-running session where Titans state accumulates and influences subsequent recalls |

## Active Read-Path Mechanisms (genuine deltas expected)

| Mechanism | Guard location | Effect when ablated |
|---|---|---|
| **ADAPTIVE_DECAY** | `core/pg_recall.compute_pg_weights()` | `weights["heat"] = 0` → WRRF fusion ignores thermodynamic heat → ranking degenerates to vector + FTS + ngram |
| **CO_ACTIVATION** | `handlers/recall.py:_apply_co_activation` (line 188) | Skips Hebbian post-recall edge strengthening — affects subsequent recalls' SR signal (which is itself dormant on this path), so on a single benchmark pass the effect is minimal |

## Honest Reporting in the Paper

The ablation table in §6.3 must distinguish three categories:

1. **Active read-path** — non-zero deltas expected: ADAPTIVE_DECAY.
2. **State-only read-path** — guarded but no ranking effect on a single
   benchmark pass: SURPRISE_MOMENTUM, CO_ACTIVATION.
3. **Dormant on read-only benchmark** — guarded module exists, but no
   call site on this benchmark's recall path: HOPFIELD, HDC,
   SPREADING_ACTIVATION, DENDRITIC_CLUSTERS.

A future write-heavy benchmark, or a benchmark that explicitly drives
the legacy `recall_helpers.collect_signals()` path, will produce
non-zero deltas for the dormant mechanisms.

## Source

- `tasks/verification-protocol.md` E1 (per-mechanism ablation campaign)
- Commit `099ba1e` (module-level guards added)
- This commit (handler-level guard for ADAPTIVE_DECAY + dormancy audit)
