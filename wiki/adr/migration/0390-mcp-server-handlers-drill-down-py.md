# ADR-0390: mcp_server/handlers/drill_down.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/drill_down.py`; original SHA-256 `a4a377263ee64df8a8f3f6951fdc5eebbe05d5f5bf48cf24be46a970963a6ef7`.

## Original comment, lines 112–114

````text
# No-domain path: same 500-row bound as the domain path above. The
    # previous full-table materialization + Python heat filter was the
    # last uncapped scan in this handler (bounded-I/O audit 2026-06-09).
````

## Original comment, lines 216–217

````text
# Telemetry-instrumented public entry. Records latency / byte volume
# / result count per call (Popper C6 read/write ratio audit).
````

## Original schema description, interim lines 28–43

````text
Descend one level into a fractal memory cluster previously returned by `recall_hierarchical`: an L2 root cluster expands to its L1 sub-clusters; an L1 cluster expands to the individual memories it contains (full content, heat, tags). Cluster IDs use the form `L<level>-<index>`. Use this for interactive top-down exploration — start broad with `recall_hierarchical`, then drill the most-relevant cluster repeatedly until you reach memories. Distinct from `recall` (flat ranked list, no hierarchy), `navigate_memory` (graph BFS via co-access edges, not cluster tree), and `recall_hierarchical` (entry point that builds the tree). Not read-only: every surfaced memory is recorded as a hippocampal replay event — access_count/replay_count increment and hippocampal_dependency decays (CLS-B, Ketz et al. 2023) — so repeat calls are not idempotent (`track_replay_event`, `replay_tracking.py`). Latency <100ms. Returns {cluster_id, level, children: [{id, label, members?, content?}]}.
````

