# Eco Audit — The Model Client of the Layout Authority Wire

> Method: profile the Model Reader (Model Client) the artifact
> presupposes; separate what the wire *carries* from what the consumer
> must already *know*; classify each implicit-knowledge dependency as
> (a) make explicit, or (b) delete. Open/closed named per dimension.
> Sources: Eco, *The Role of the Reader* (1979); *The Open Work* (1962);
> *The Limits of Interpretation* (1990).

Artifact: SSE stream from `layout_authority_wire.py`. Producer:
`_geometry.py` + `_protocol.py`. Consumer: any renderer subscribing
to `event: slot` / `event: edge` / `event: done`.

---

## 1. Profile of the Model Client

The wire `id|x|y|kind|domain_id` tells the consumer almost nothing on
its own. The Model Client is *heavily competent* — pre-equipped with
out-of-band convention:

- **MC-A Coordinates.** Knows `(x, y)` are pixels in a 1000×1000
  authority frame, y-down screen convention. `_protocol.py:117`
  documents it; the wire does not.
- **MC-B Kind vocabulary.** Knows the 12 `NODE_KINDS` values and which
  maps to which color (`KIND_COLOR` in `workflow_graph.js:19-32`). Wire
  ships the kind string; the kind→color dictionary lives only in JS.
- **MC-C Domain grouping.** Knows `domain_id` references a node with
  `kind == 'domain'` (I7), that members share `domain_id`, that the
  canonical render groups/colors by domain. Wire ships the id; the
  **meaning of membership** is convention.
- **MC-D Geometric frame** (load-bearing). Knows radii (`SETUP_R=70,
  TOOL_R=140, FILE_R=220, DISC_R=150, MEM_R=150, MCP_R=50`), sector
  half-widths, Fibonacci `_PHI = π·(3−√5)`, and `TOOL_LOCAL_ANGLE`.
  Required because the renderer draws **L-band rings and sector labels
  on top of the emitted points** (`workflow_graph.js:33-38, 43-84`).
  Both ends carry the constants independently —
  `_geometry.py:28-52` vs. `workflow_graph.js:43-84`. **Noether H2.**
- **MC-E Sequence/idempotency.** Knows `seq` is monotone (I2), later
  supersedes earlier, `done` means stop polling.
- **MC-F Edges.** Knows edges are straight lines between placed slots
  and `kind` is one of 14 styling tags, not a routing instruction.

---

## 2. What a naive client can discover from the stream alone

Discoverable: `node_id` uniqueness, an empirical `(x, y)` bounding box,
the finite kind alphabet (after enough samples), spatial clustering
of `domain_id`. **Not** discoverable: canvas size, y-axis convention,
kind→color mapping, that `domain_id` references a sibling node, the
L-band ring structure, `request_subtree` invalidation semantics, the
guarantee that edge endpoints eventually land.

---

## 3. Implicit-knowledge dependencies — table

| # | Dependency | Producer source | Consumer source | Classification | Recommendation |
|---|---|---|---|---|---|
| D1 | Canvas size & y-down convention | `_protocol.py:117` | renderer assumption | implicit | **Make explicit** — `meta` event. |
| D2 | Kind-vocabulary (12 values) | `_protocol.py:30` | renderer enum | implicit | **Make explicit** — `meta` event. |
| D3 | Kind → color mapping | absent server-side | `workflow_graph.js:19-32` | one-sided convention | **Move to wire** if server cares about palette; otherwise **declare client-owned** (delete the dependency from the producer's mental model). |
| D4 | Radii (`SETUP/TOOL/FILE/DISC/MEM/MCP_R`) | `_geometry.py:28-36` | `workflow_graph.js:43-48` | **dual-source duplication (Noether H2)** | **Make explicit** — emit once in `meta`. |
| D5 | Sector half-widths & angles | `_geometry.py:39-41` | `workflow_graph.js:63-65` | dual-source duplication | **Make explicit** — `meta`. |
| D6 | `_PHI` and Fibonacci formula | `_geometry.py:55,76` | `workflow_graph.js:326` | dual-source duplication | **Delete dependency** — server already emits `(x, y)`; client needs the constant **only** to draw the L-band rings. Either (a) emit ring radii in `meta`, or (b) emit the rings as first-class slot events. |
| D7 | `TOOL_LOCAL_ANGLE` map | `_geometry.py:44-52` | `workflow_graph.js:76-84` | dual-source duplication | **Delete dependency** — same logic as D6. The client never needs this if the authority is the sole layout author. |
| D8 | `domain_id` ⇒ exists-a-domain-node | I7 (`_protocol.py:212`) | renderer assumption | structural | **Make explicit** — emit `domain` slots before any member slot, or include a `domain_present: bool` hint. |
| D9 | `seq` monotonicity & supersession | I2 | renderer assumption | structural | Already in SSE `id:` line; **document at handshake** in `meta`. |
| D10 | `done` ⇒ stop polling | wire convention | renderer assumption | structural | Already explicit; OK. |
| D11 | Edge endpoints land eventually | I5 buffer | renderer assumption | temporal | **Make explicit** — include drop-counter snapshot in `done` payload. |
| D12 | Pixel-precision: `.1f` floats (sub-pixel discarded) | `wire.py:110` | renderer assumption | encoding | OK to leave implicit; it is loss-tolerant. |

**The dependencies that hurt now: D4, D5, D6, D7.** *Dual-source* —
identical numeric constants in two languages with no test pinning
them. Change `FILE_R = 220` in Python without matching JS and the
renderer draws labels at the wrong ring while points sit at the right
one. Precisely Noether H2.

---

## 4. Open vs. closed classification (per dimension)

| Dimension | Classification | Deliberate? | Verdict |
|---|---|---|---|
| Wire payload (`id\|x\|y\|kind\|domain_id`) | **closed** — fixed shape, no extension | yes (Shannon discipline, §1 of `wire.py`) | appropriate |
| Kind alphabet | **closed** — 12 values frozen in `_protocol.py` | yes | appropriate |
| Color palette | **open** — client decides | accidental (no server statement either way) | **clarify** — declare in ADR which side owns it |
| Layout geometry | **closed at producer**, **echoed at consumer** | accidental | **make closed at producer only** — emit constants in `meta` |
| `request_subtree` semantics | **closed**, but invisible to passive subscribers | yes | OK; document in handshake |

The accidentally-open dimensions (palette, geometry-echo) are where
producer and consumer drift independently. Eco's rule: when two
parties must agree on a code, the mediating artifact must *carry*
the code, not assume it.

---

## 5. Recommendation — the `meta` event (highest leverage fix)

Add one event kind, emitted **first on every stream**, before any
`slot` or `edge`:

```
event: meta
data: {"canvas":[1000,1000],"y_axis":"down","node_kinds":[…12…],
       "edge_kinds":[…14…],"radii":{"SETUP_R":70,"TOOL_R":140,
       "FILE_R":220,"DISC_R":150,"MEM_R":150,"MCP_R":50},
       "sectors":{"setup_half":1.208,"side_half":0.483,
                  "side_angle":2.262},"phi":2.39996,
       "tool_local_angle":{"Edit":0.0,"Write":-0.262,…},
       "protocol_version":"layout-authority/1.0"}
```

This collapses D1, D2, D4, D5, D7, D9 into one self-describing
preamble. The new Model Client is much weaker — a renderer that knows
only "JSON in `meta`, pipe-separated in `slot`/`edge`" works. D6 is
then resolvable: keep `_PHI` implicit (mathematically derived) or fold
ring radii into `meta.radii` so the client never needs `_PHI` unless
it wants extra spiral guides.

D3 (kind→color) needs an explicit ADR: either server publishes
`KIND_COLOR` in `meta`, or the spec states "palette is client-owned."
Either is valid; *unstated* is not.

---

## 6. Limits of interpretation (what this audit is **not** licensing)

The wire's structure (intentio operis) does **not** support these
readings:

- "`kind=symbol` implies the symbol is a function" — `kind` is a
  layout/visual category, not a semantic-type tag.
- "Two slots with similar `(x, y)` are semantically related" — only
  the underlying graph (which the wire does not transmit) supports
  that claim. Spatial proximity is a *side-effect* of layout.
- "`done` means the graph is complete" — `done` means *this stream
  segment* is complete; `request_subtree` can re-emit at any time.

These are overinterpretations to refuse, not features to add.

---

## 7. Hand-offs

- **Shannon** — quantify the byte cost of the proposed `meta` event;
  it is a one-shot ~400-byte payload, amortizes to near-zero on any
  non-trivial stream.
- **Noether** — H2 (dual-source constants) is resolved by D4/D5
  becoming wire-explicit; add a golden-vector test that hashes
  `meta.radii ∪ meta.sectors ∪ meta.tool_local_angle` against a
  fixture committed alongside `_geometry.py`.
- **Engineer** — add `format_meta()` to `layout_authority_wire.py`,
  invoke it once at subscribe time before draining the queue.
- **Liskov** — restate the Model Client contract as a typed protocol;
  any renderer that handles `meta` first satisfies it.
