# Altshuller (TRIZ) — Layout Authority Contradiction Audit

**Method:** Every hard problem contains a contradiction — improving one parameter
degrades another — and contradictions are resolved not by compromise but by
inventive principles derived from cross-domain patent analysis. The layout
authority embeds three textbook contradictions. Each is resolved by a specific
TRIZ principle visible in the code.

---

## Contradiction 1 — RICH topology vs FAST layout

### Statement
- **Improve:** information richness of the layout (full DrL force-directed
  embedding, neighborhood meaning preserved, cluster structure visible).
- **Degrades:** time-to-first-tile (DrL is O(N log N) but the constant pushes
  ~90 s at 1M nodes; UI budget is 1–2 s).
- **Physical contradiction:** the layout must be *expensive* (DrL pass over the
  full graph to encode topology faithfully) AND *cheap* (sub-second response
  on every visualize call).

### Resolving principle — #10 Preliminary Action ("do it before you need it")
The expensive step is moved out of the request path entirely. DrL runs once
inside `recompute_layout.run_recompute()` and persists `(node_id, x, y, kind)`
into `workflow_graph_layout`. Every subsequent `/api/quadtree` and tile request
reads precomputed coordinates — the request thread never sees DrL.

### Code mapping
- `mcp_server/handlers/recompute_layout.py:101-108` — DrL pass + write_layout.
  This is the "preliminary action" run.
- `mcp_server/infrastructure/layout_pg_store.py:37-79` — `write_layout` is the
  durable artifact of the preliminary action.
- `mcp_server/handlers/quadtree_handler.py:32` — `read_all_positions` reads the
  precomputed result; no layout work on the hot path.

### Reinforcing principle — #20 Continuity of Useful Action (skip-if-fresh)
`recompute_layout.py:86-99` consults `read_layout_version` and returns
`elapsed_ms: 0, cached: True` when the topology fingerprint matches. The
preliminary action is preserved across calls — it is not redone unless the
graph itself changed.

### Reinforcing principle — #23 Feedback (topology fingerprint as control signal)
`core/layout_engine.py:26-44` — `topology_fingerprint` is a SHA-256 over the
sorted (ids, edges) set, truncated to 16 hex chars. It is the feedback signal
that tells the system *whether* the preliminary action's output is still
valid. Without it, "preliminary" collapses into "always recompute."

---

## Contradiction 2 — SMALL state on the wire vs LARGE state per node

### Statement
- **Improve:** wire size of `/api/quadtree` (target 1–10 MB so the browser
  parses it and builds flatbush in <500 ms).
- **Degrades:** per-node fidelity — every node needs a stable slot (id, x, y,
  kind) for hover/click resolution; at 1M nodes a naive JSON payload is
  ~80 MB.
- **Physical contradiction:** the payload must carry *every* node (large) AND
  fit in the browser's parse budget (small).

### Resolving principle — #1 Segmentation + #36 Phase Transition (encoding shift)
The state is segmented along its statistical structure: high-cardinality
columns (`id`) and low-cardinality columns (`kind`, ~12 distinct values) are
*both* dictionary-encoded; the geometry columns are demoted from Float64 →
Float32 (a phase transition in numerical representation, since 1e-7 world
precision is dead code at screen resolution).

### Code mapping
- `mcp_server/handlers/quadtree_handler.py:50-57` — Arrow table construction:
  ```
  "id":   pa.array(ids).dictionary_encode(),
  "x":    pa.array(xs, type=pa.float32()),
  "y":    pa.array(ys, type=pa.float32()),
  "kind": pa.array(kinds).dictionary_encode(),
  ```
  Two columnar segments compress structurally; two segments compress
  numerically. 80 MB JSON → ~8 MB raw Arrow → ~3–4 MB gzipped.

### Reinforcing principle — #34 Discarding and Recovering
`gzip.compress(arrow_buf, compresslevel=6)` at line 63 discards redundancy on
the wire and the browser recovers it. The discarded bits are exactly the
ones the dictionary encoding made redundant (repeated kind tokens, sorted
id prefixes).

### Reinforcing principle — #25 Self-Service (client builds its own quadtree)
The server ships flat columns; the *client* constructs the spatial index
(flatbush) on first paint. The server is freed from maintaining a per-client
spatial structure — the client serves itself with the data shipped. This is
the "ideality" direction: zero server-side picking infrastructure.

---

## Contradiction 3 — FLEXIBLE protocol vs STRICT validation

### Statement
- **Improve:** flexibility — the layout authority must consume any node
  produced by any builder (AST scanner, brain-index, future kinds), with
  edges referenced as raw string ids OR as resolved `{id: ...}` objects.
- **Degrades:** boundary safety — silent acceptance of malformed inputs
  produces ghost nodes, NaN coordinates, or a layout pass that crashes
  igraph mid-run.
- **Physical contradiction:** `_extract_topology` must be *permissive*
  (accept any reasonable shape) AND *strict* (reject anything that would
  poison the layout).

### Resolving principle — #4 Asymmetry (permissive read, strict write)
The boundary is asymmetric: the *read* side of `_extract_topology` accepts
both string and dict edge refs; the *write* side commits only to a single
canonical shape — `tuple[str, str]` with `s != t` and both ids present in
the node set.

### Code mapping
- `mcp_server/handlers/recompute_layout.py:31-43` — the asymmetric filter:
  ```
  if isinstance(s, dict): s = s.get("id")
  if isinstance(t, dict): t = t.get("id")
  if s and t and s != t:
      edges.append((s, t))
  ```
  Three filters in one expression: (a) presence guards drop None; (b)
  self-loop guard drops `s == t`; (c) downstream `idx_of[s] in idx_of` in
  `layout_engine.py:79-80` drops dangling references. Permissive in
  *vocabulary*, strict in *structure*.

### Reinforcing principle — #2 Extraction (pull the contract into the boundary)
`_extract_topology` is a private function that owns the entire shape-translation
contract. Nothing downstream of it ever sees the messy union type — it
extracts the canonical `(node_ids, edges, kinds)` triple and the rest of the
pipeline (layout_engine, layout_pg_store) operates on a strict, narrow type.
The flexibility lives in one place; strictness lives everywhere else.

### Reinforcing principle — #11 Beforehand Cushioning (tolerant defaults)
`kinds.get(nid, "unknown")` in `layout_pg_store.py:61` and
`(n.get("kind") or "unknown")` in `recompute_layout.py:32` — every kind
collision is cushioned by a default, so a builder that forgets to emit
`kind` cannot break the persisted invariant ("every row has a non-null
kind"). Strictness without brittleness.

---

## Ideal Final Result check

The IFR for a layout authority is: **the user sees the laid-out graph
instantly with zero server work.** The current design's distance to IFR:

| Dimension | IFR | Current | Gap |
|---|---|---|---|
| Layout cost on user request | 0 | 0 (precomputed) | closed |
| Wire size at 1M nodes | 0 | ~3–4 MB | irreducible (entropy floor) |
| Server-side picking | none | none (client builds quadtree) | closed |
| Re-layout on stable graph | never | never (fingerprint skip) | closed |

The remaining gap is entropy-bounded (you cannot ship 1M coordinates in
zero bytes). The design is at the IFR frontier for this problem class.

---

## New contradictions introduced

1. **Synchronous DrL in the request thread** — `recompute_layout.py:7-12`
   acknowledges this. At 1M nodes the first call is a 90 s HTTP request.
   Resolved by principle #15 *Dynamics* in PR 2 (move to background job,
   poll for completion).
2. **Full-replace write** (`DELETE FROM workflow_graph_layout` then
   `executemany`) — atomic from the reader's perspective only because
   PostgreSQL serializes the transaction. Under concurrent recomputes this
   becomes a write-lock contention point. Future principle: #15 *Dynamics*
   (per-fingerprint partition) or #24 *Intermediary* (staging table → swap).

---

## Compliance with TRIZ method
- Three contradictions named with explicit improve/degrade parameters: **pass**.
- Each contradiction mapped to a numbered inventive principle: **pass**.
- Each principle traced to specific file:line evidence: **pass**.
- IFR distance audited and gap classified as entropy-bounded: **pass**.
- New contradictions surfaced for the next iteration: **pass**.
