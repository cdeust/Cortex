# Ranganathan Audit — PMEST Faceted Classification of the Layout Authority

The layout authority's design space is multi-dimensional. A single hierarchy
(e.g. "by file" or "by kind") loses entries from every other access path.
This audit decomposes the design along five orthogonal facets — Personality,
Matter, Energy, Space, Time — declares what each facet *covers*, and names
the *gaps*: the values the facet implies but the code does not realise.

Source schema: Ranganathan, S. R. (1937), *Prolegomena to Library
Classification*, Ch. 23 "Fundamental Categories."

## P — PERSONALITY (the kind of node — what the entry IS)

Authoritative enumeration: `NODE_KINDS` (`layout_authority_protocol.py:30-33`).

| Value | Slot helper | Coverage |
|---|---|---|
| `domain` | `domain_anchor` | full |
| `tool_hub` | `slot_for_tool_hub` | full |
| `file` | `slot_for_file` | full (tool_hub-orbiting; falls back to outward axis when parent unknown — I4) |
| `symbol` | `slot_for_symbol` | full (parent-file-relative petal; I3-buffered) |
| `discussion` | `slot_for_discussion` | full |
| `memory` | `slot_for_memory` | full |
| `mcp` | `slot_for_mcp` | full (inward of domain) |
| `skill`,`hook`,`command`,`agent` | `slot_for_setup` (shared) | **conflated** — four PERSONALITY values share one shell at r=70; they are distinguishable in NODE_KINDS but indistinguishable in geometry |
| `entity` | none — falls through `compute_slot:218` to `ctx.get("anchor", …)` | **GAP** — declared kind, no branch, collides with the `domain` slot |

**P-gaps:**
1. `entity` has no slot helper. Either give it an L6 cross-domain shell (mirror of `mcp`), or remove it from NODE_KINDS.
2. The L3 setup ring conflates four kinds. If a future requirement is "show me only hooks," the geometry has lost the distinction — only the wire payload retains it.
3. Predicted-but-absent kinds (cross Mendeleev): `super_domain`, `project_hub`, `shared_skill`, `discussion_hub`, `memory_hub`, `cross_entity`. Add them only if a producer exists.

## M — MATTER (the content carried — what the entry CONTAINS)

Authoritative payloads: `NodeDelta` (`layout_authority_protocol.py:46-74`),
`SlotAssignment` (`:103-129`), `EdgeDelta` (`:77-100`), wire frames
(`layout_authority_wire.format_slot/format_edge`).

| Field | Where | Coverage |
|---|---|---|
| `node_id` | NodeDelta, SlotAssignment, frame | full |
| `kind` | both, frame | full |
| `domain_id` | both, frame | full |
| `parent_id` | NodeDelta only | **stripped at emit** — present on input, absent from SlotAssignment and frame; renderer cannot reconstruct file→symbol parentage from the stream alone |
| `tool_name` | NodeDelta only | **stripped at emit** — same gap; renderer cannot tell which tool a `tool_hub` represents |
| `x`, `y` | SlotAssignment, frame | full (`:.1f` truncated, finite-checked at wire) |
| `seq` | SlotAssignment, frame | full (monotonic, I2) |
| metadata (timestamp, size, label, color) | — | **GAP** — no field carries human-facing metadata; UI must look it up out-of-band |
| edge `kind` | EdgeDelta, frame | full |
| edge endpoints | EdgeDelta, frame | full |
| edge weight / direction marker | — | **GAP** — every edge is unweighted, undirected at the wire level |

**M-gaps:**
1. The wire frame is `id|x|y|kind|domain_id` — `parent_id` and `tool_name` exist in the input but are dropped on emit. Renderer reconstructs hub angles by re-deriving them. Either add them to the frame or document they are renderer-derivable.
2. No metadata channel. Labels, colors, sizes are out-of-band — fine if the renderer has a side store, fragile if SSE is the only channel.
3. Edges carry no weight. Cannot animate edge strength.

## E — ENERGY (the operations — what the entry DOES)

Authoritative verbs: `LayoutAuthority` Protocol (`layout_authority_protocol.py:142-178`)
+ `layout_authority_log` module-level functions.

| Verb | Surface | Coverage |
|---|---|---|
| `add_node` | input — build worker → authority | full (validates, places, emits) |
| `add_edge` | input | full (validates, buffers if endpoints missing — I5) |
| `request_subtree(domain_id)` | input — re-emit known slots for domain | partial — re-emits *current* slots; cannot reseat without invalidate-then-rebuild |
| `subscribe` / `unsubscribe` | output channel | full |
| `done()` | terminator | full |
| `emit` (slot/edge) | internal — log layer | full |
| `replay_since(seq)` | recovery | full (with `oldest_seq` gap signal) |
| `reset()` | lifecycle | full (prose: keep global seq across resets) |
| `stats()` | observability | partial — counters only; no per-priority lane stats surfaced from authority (scheduler has them) |
| `request_node(node_id)` | targeted re-emit | **GAP** — only subtree-granularity reseats |
| `forget(node_id)` / `remove_node` | retraction | **GAP** — append-only stream; no node removal verb |
| `update_metadata(node_id, …)` | partial update | **GAP** — same as above |
| `pause` / `resume` producer-side | flow control | **GAP** — Hamilton 1202 pattern shifts back-pressure to the priority dropper, but there is no explicit pause hook |

**E-gaps:**
1. The system is monotonic by design (Pattern 2: slot-stable). Verbs that *retract* are deliberately absent. If retraction is ever needed, it must enter as a new ENERGY value with its own invariants, not retrofitted into `add_node`.
2. `request_subtree` is the only re-emit verb. Single-node viewport refresh requires emitting the whole domain.

## S — SPACE (the canvas, anchors, shells — WHERE the entry sits)

Authoritative geometry: `layout_authority_geometry.py`.

| Spatial element | Constant / function | Coverage |
|---|---|---|
| canvas | `width × height` (default 1000×1000) at `LayoutAuthority.__init__` | full but **fixed** — no resize handler in the authority |
| domain anchor | Fibonacci spiral, `domain_anchor()` | full; *frozen* at first sighting (`_DomainRegistry`) |
| outward axis | `outward_angle()` | full (with center-bias for domains within 5px of center) |
| L1 setup shell | `SETUP_R = 70`, `SECTOR_SETUP_HALF` | full |
| L2 tool-hub ring | `TOOL_R = 140`, `TOOL_LOCAL_ANGLE` | full (7 named tools; unknown tool → 0.0 angle) |
| L3 file orbit | `FILE_R = 220` | full |
| L4 discussion lane | `DISC_R = 150`, `+SECTOR_SIDE_ANGLE` | full |
| L4 memory lane | `MEM_R = 150`, `−SECTOR_SIDE_ANGLE` | full |
| L? mcp shell | `MCP_R = 50`, inward (outward + π) | full |
| L6 symbol petal | `SYM_CLUMP_R = 18`, around parent file | full |
| z-axis / 3D | — | **GAP** — 2D only; the `unified-viz.html` 3D path is not authority-driven |
| sub-canvas tiling | — | **GAP** — `viewport-of-interest` dynamic tiling lives in `quadtree_handler`, not the authority |
| coordinate scaling for renderer viewport | — | client-side; authority emits absolute pixels in its own 1000×1000 frame |
| anchor for `entity` | — | **GAP** (mirrors P-gap above) |

**S-gaps:**
1. Canvas size is constructor-fixed; window resize forces a `request_subtree` storm or new build. No `set_canvas(w, h)` verb.
2. No explicit z-axis. 3D rendering reuses (x, y) and synthesises z elsewhere.

## T — TIME (the event seq, build phases, replay window — WHEN the entry is)

Authoritative timeline: `layout_authority_log._event_seq` + `cascade` of build-phase signals (out-of-band) + ring buffer.

| Temporal element | Surface | Coverage |
|---|---|---|
| event sequence number | `_event_seq` (global, monotonic across `reset()`) | full (I2) |
| replay window | 500k-event ring buffer (`layout_authority_log`) | full; `oldest_seq` gap-detected in `replay_since` |
| Last-Event-ID resume | `replay_since(since)` | full |
| build phase markers | `done` event at end | partial — only end marker; **no phase-start markers** mid-stream (e.g. "scanning files done, tool_hubs starting") |
| reset (new build) | `_log.reset()` | full (prose-vs-code reconciled in `reset`'s docstring: prose wins, seq continues) |
| wall-clock timestamp | — | **GAP** — `seq` is logical time, no wall-clock on events |
| event ordering across producers | — | not required (single-producer invariant), but **undefined** if invariant ever broken |
| TTL / expiry on slots | — | **GAP** — slots are immortal until next `reset()` |
| heartbeat / keepalive | `format_keepalive()` | full (wire-layer SSE comment frame) |

**T-gaps:**
1. Mid-stream phase boundaries are invisible. UI cannot say "now placing files" because the protocol does not announce phases. Either add a `phase` event kind or accept that the sequence is featureless until `done`.
2. No wall-clock. Replay is by `seq` only — fine for resume, useless for "what arrived in the last 5 seconds" without a side-channel timestamp.
3. No TTL: slots remain placed across the entire build until `reset()` zeroes the world. Memory-bounded only by the worker's not emitting more.

## Summary table of GAPS

| Facet | Gap | Severity | Fix shape |
|---|---|---|---|
| P | `entity` kind has no slot helper | high — silent collision at domain anchor | add `slot_for_entity` (L6 cross-domain) or remove from NODE_KINDS |
| P | L3 conflates skill/hook/command/agent | low — geometry-only | accept; wire-frame `kind` keeps the distinction |
| M | `parent_id`, `tool_name` stripped at emit | medium — renderer re-derives | extend wire frame OR document derivation |
| M | No metadata channel | medium — out-of-band fragile | optional `meta` event kind |
| M | Edges unweighted/undirected | low | add weight field if a producer needs it |
| E | No `forget` / `remove_node` | by design | none — retraction is forbidden by Pattern 2 |
| E | Per-node re-emit absent | low | `request_node(id)` if viewport refresh becomes a hot path |
| S | Canvas size fixed at construction | medium — resize is a full rebuild | `set_canvas(w, h)` + scheduled `request_subtree` per domain |
| S | No 3D / z-axis | low — out of scope | 3D synth lives in renderer |
| T | No mid-stream phase markers | medium — UX opacity | `phase` event kind |
| T | No wall-clock on events | low | wire-layer optional `ts` field |

## Closing note

The authority's faceted coverage is excellent on **P, S, T** (one missing kind,
one missing axis, one missing phase marker) and complete on **E** for the
verbs that are intentionally in scope. The biggest deficit is **M**: the
input carries `parent_id` and `tool_name`, but the wire frame drops them.
Renderer correctness depends on rederiving what was already known. That is
either a deliberate compression (document it) or a leak (close it).
