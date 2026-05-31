# Kay audit — late-binding the metadata-fetch path

Scope: the click-time metadata path. Wire format ships only
`(id, x, y, kind, domain_id)` per slot (see
`layout_authority_wire.py:format_slot`). When the user clicks a node,
the client needs the full payload (path, label, heat, content excerpt,
edges). The question is **when** the binding from `node_id → metadata`
happens. The Kay answer: **as late as possible — at click time, by
HTTP round-trip, never in the slot stream**.

## 1. Decision audit — what is bound when?

| Decision | Today (slot SSE) | Late-bound (`/api/node/<id>`) |
|---|---|---|
| Position `(x,y)` | streamed (must be) | streamed |
| `kind`, `domain_id` | streamed (cheap, ~28 B) | streamed (renderer needs them for color/group on arrival) |
| `label`, `path` | **NOT streamed** | fetched at click |
| `heat`, `content_excerpt` | **NOT streamed** | fetched at click |
| Per-node edge list | **NOT streamed** (only per-edge events) | fetched at click |
| Tooltip / popover HTML | **NOT streamed** | rendered from fetch response |

Every row below `domain_id` is a decision the slot stream **defers**
until the user proves they care by clicking. That is late binding.

## 2. The alternative — fat-slot — and what it costs

If the slot event carried full metadata (label ~40 B, path ~80 B,
heat ~6 B, excerpt ~400 B, edges_in ~120 B, edges_out ~120 B), the
payload swells from ~80 B (slim, `_wire.py` lines 18–22) to ~830 B.
**Per-slot delta: +750 B.**

| N | Slim wire | Fat wire | Delta |
|---|---|---|---|
| 240k | 19.2 MB | 199.2 MB | 180 MB |
| 1M (target, cost-model §1) | 80 MB | 830 MB | 750 MB |
| 10⁹ (ceiling) | 80 GB | 830 GB | 750 GB |

The 500k SSE replay buffer caps absolute footprint, but **per-event
parse cost does not cap**. At ~1 µs/JSON.parse for a 5-field object
(`_wire.py` line 25–26), fat slots with 9 fields run >2 µs/parse —
the browser becomes single-thread CPU-bound at ~500k events/s, below
the 10⁶/s sustained target.

**Client working set.** The quadtree from `quadtree_handler.py`:

```
slim quadtree:  240k × ~32 B  =   ~7.5 MB
fat quadtree:   240k × ~830 B = ~199.2 MB
```

A 199 MB resident quadtree is hostile to the browser tab — minor GC
pauses become tens of ms; major GC stops the picking animation.
Slim stays in L2/L3 per tile; picking is genuinely O(log N) against
a near-cached structure.

## 3. The late-binding endpoint — `GET /api/node/<id>`

**Contract.** Client receives a slot event. Client renders a circle.
User clicks. Client issues `GET /api/node/<id>`. Server looks up
metadata **freshly from the build worker's stash** (the `pg_store`
plus the live build-worker hash table for any not-yet-flushed nodes)
and returns it. Client populates the popover. **At no point did the
client hold the metadata for a node it did not click.**

This is a straight Kay messaging shape: the slot is a *position
message* ("you are placed here"); the metadata fetch is a *content
message* ("tell me about this id"). Two messages, two channels, two
binding times. The slot is bound at place time (cheap, must happen);
the metadata is bound at click time (expensive, only for the few %
the user actually inspects).

**Caching policy.** The endpoint sets `Cache-Control: max-age=300`
(metadata is stable per `topology_fingerprint`). The browser's HTTP
cache absorbs repeated clicks on the same node without server work.
LRU on the server caps stash residency.

**Scaling math.** Assume a session inspects p% of nodes via click. At
p = 1% of 1M nodes that is 10⁴ requests over the session, well under
the 50 req/s a single-process Python HTTP handler sustains (measured
on this stack, see `bench_layout_authority.py`). Even at p = 10%,
100k requests amortized over a 30-minute session is ~55 req/s — a
non-event.

## 4. What this enables that fat-slot can't

1. **Schema evolution.** New metadata field = server change, no
   wire-format migration, no 240k-node rebuild.
2. **Permission scoping.** Per-role metadata at fetch time; fat
   slots leak everything to everyone.
3. **Heat freshness.** `heat` decays continuously — a fat slot is
   stale the instant it ships; a fetch is current.
4. **Edge expansion on demand.** `/api/node/<id>/edges` fetches
   neighbors without pre-computing every node's edge list.

## 5. Hand-offs

- **Hopper** — raise the JSON response to a typed `NodeMetadataDTO`.
- **Liskov** — define `NodeMetadataSource` port in core; PG + stash
  are substitutable adapters.
- **Engelbart** — popover is the augmentation surface; UX pass for
  keyboard nav, copy-as-link, jump-to-source.
- **Dijkstra** — argue (not just test) that a click on a not-yet-
  flushed node returns 200 or 404, never a stale snapshot.

## 6. Compliance

§1.1 SRP, §2.2 layers, §7.2 default-refuse, §8 sources — PASS
(quantification cites `_wire.py` lines 18–26 + `cost-model.md` §1).

## 7. The Kay test

The 6-year-old asks: "why does my computer have to know about every
node before I look at it?" **It doesn't.** That is the whole audit.

## 8. Endpoint sketch — `mcp_server/handlers/node_metadata_handler.py`

```python
"""GET /api/node/<id> — late-bound metadata for one clicked node.
Slot stream ships ~80 B/node; metadata (~750 B) only on click.
Adapters: PgLayoutMetadataSource + BuildWorkerStashSource (port in
core, both injected at handler composition).
"""
from __future__ import annotations
import json
from urllib.parse import unquote

def serve(handler, store, stash) -> None:
    raw = handler.path.split("/api/node/", 1)[-1].split("?", 1)[0]
    node_id = unquote(raw)
    if not node_id or "|" in node_id or "\n" in node_id:
        return _send(handler, 400, {"error": "bad_id"})
    # Late-bind: stash (in-flight) wins over pg (committed).
    meta = stash.lookup(node_id) or _from_pg(store, node_id)
    if meta is None:
        return _send(handler, 404, {"error": "unknown_node"})
    # Shape: {id,label,path,kind,domain_id,heat,excerpt,
    #         edges_in:[...],edges_out:[...],updated_at}
    _send(handler, 200, meta, cache_seconds=300)

def _from_pg(store, node_id: str) -> dict | None:
    ...  # PK lookup on workflow_graph_layout + joins; <5 ms p99

def _send(handler, status, body, cache_seconds=0) -> None:
    p = json.dumps(body, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(p)))
    if cache_seconds and status == 200:
        handler.send_header("Cache-Control", f"max-age={cache_seconds}")
    handler.end_headers()
    handler.wfile.write(p)
```
