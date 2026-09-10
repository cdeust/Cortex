# ADR-0443: mcp_server/handlers/replay_tracking.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/replay_tracking.py`; original SHA-256 `00dab568af49b19770c4cd19af14aa190d3b223ac2362cfb37b9dae87f21cc08`.

## Original docstring, lines 1–17

````text
"""Handler: replay_tracking — shared per-event CLS-B hippocampal decay.

Every recall-family handler (recall, recall_hierarchical, navigate_memory,
drill_down) treats a memory surfacing in its results as a hippocampal replay
event (McClelland et al. 1995). Each such event should:

  1. bump access_count / replay_count (existing behaviour), and
  2. decrement hippocampal_dependency by exactly one C-HORSE transfer delta
     (Ketz et al. 2023, eLife 12:e77185) — the CLS-B producer this module
     wires into the shared replay path so it fires identically at all four
     call sites instead of being re-derived per handler.

Policy (whether/how much to decay) lives here, in the handler layer.
Persistence (reading the post-increment row, writing the new dependency)
lives in the infra store methods this module calls — the store never decides
*when* to decay, only *how* to read/write a row.
"""
````

