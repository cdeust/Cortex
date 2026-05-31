# `add_node(NodeDelta)` — Canonical Algorithm

Implementation contract for `mcp_server/server/layout_authority.py`. Reduce
input to `(domain_id, kind, idx, total, parent_state)`; dispatch to one of
**eight** mechanical cases. No iteration. O(1) per call.

## 0. Authority state

```
cx, cy, base_r, seq                 # canvas + monotonic counter
domains : dict[domain_id -> DomainRecord]
nodes   : dict[node_id   -> NodeRecord]               # for parent lookup
pending_symbols : dict[file_id -> list[NodeDelta]]    # I3 buffer
subscribers, drop_counter

DomainRecord: index, anchor|None, outward|None,
              counts : dict[bucket_key -> int],       # incl ('sym', file_id)
              tool_angles : dict[tool_name -> float],
              tool_file_counts : dict[tool_name -> int]
NodeRecord:   kind, domain_id, slot, tool_name
```

Pre-checks (raise `ValueError`):
1. `kind in NODE_KINDS`; 2. `node_id`, `domain_id` non-empty;
3. `kind=='domain'` ⇒ `domain_id==node_id`; 4. `kind=='tool_hub'` ⇒ `tool_name`;
5. `kind=='symbol'` ⇒ `parent_id`; 6. duplicate `node_id` ⇒ silent return.

## 1. Reduction (al-jabr + al-muqabala)

```
def add_node(delta):
    _validate(delta)
    if delta.node_id in self.nodes: return            # idempotent
    drec = self._ensure_domain_record(delta.domain_id)  # lazy; index = len(domains)
    dispatch(delta.kind, delta, drec)
```

## 2. Exhaustive case table (12 kinds → 8 classes; sum = 12)

| # | Class | Kinds | Anchor | Parent |
|---|---|---|---|---|
| 1 | `domain`     | `domain`                              | self     | none |
| 2 | `tool_hub`   | `tool_hub`                            | domain   | none |
| 3 | `setup-ring` | `skill`, `hook`, `command`, `agent`   | domain   | none |
| 4 | `file`       | `file`                                | domain   | tool_hub (opt) |
| 5 | `discussion` | `discussion`                          | domain   | none |
| 6 | `memory`     | `memory`                              | domain   | none |
| 7 | `mcp/entity` | `mcp`, `entity`                       | domain   | none |
| 8 | `symbol`     | `symbol`                              | file slot | mandatory |

> **Gap**: `entity` is NOT in today's `compute_slot()` (geometry 196–218).
> Reuse `slot_for_mcp` for `entity` with a `# source:` comment citing this
> audit until product defines a distinct ring.

## 3. Per-case mechanical procedures

### Case 1 — `domain`
```
drec.anchor  = domain_anchor(drec.index, N_CAP, cx, cy, base_r)
drec.outward = outward_angle(drec.anchor, cx, cy)
slot = drec.anchor
_record(delta, slot); _emit(delta, slot)
# NOTE: members already placed against placeholder anchor are NOT reseated.
# Geometric guarantee: anchor is pure function of drec.index, so placeholder
# == final anchor. No drift.
```

### Case 2 — `tool_hub`
```
anchor, outward = _anchor_for(drec)
hub_angle = tool_hub_angle(outward, delta.tool_name)
slot = slot_for_tool_hub(anchor, outward, delta.tool_name)
drec.tool_angles[delta.tool_name] = hub_angle
drec.tool_file_counts.setdefault(delta.tool_name, 0)
_record(delta, slot, tool_name=delta.tool_name); _emit(delta, slot)
```

### Case 3 — setup ring (`skill`, `hook`, `command`, `agent`)
```
anchor, outward = _anchor_for(drec)
idx = drec.counts.get('setup', 0)             # SHARED across 4 kinds
slot = slot_for_setup(anchor, outward, idx, SETUP_RING_CAPACITY)
drec.counts['setup'] = idx + 1
_record(delta, slot); _emit(delta, slot)
```

### Case 4 — `file`
```
anchor, outward = _anchor_for(drec)
hub_id = delta.parent_id
parent = self.nodes.get(hub_id) if hub_id else None
if parent and parent.kind == 'tool_hub':
    tn = parent.tool_name
    hub_angle = drec.tool_angles[tn]
    idx = drec.tool_file_counts[tn]
    slot = slot_for_file(anchor, hub_angle, idx, FILE_BUCKET_CAPACITY)
    drec.tool_file_counts[tn] = idx + 1
else:                                          # I4 fallback — FINAL
    slot = anchor
_record(delta, slot); _emit(delta, slot)
_flush_pending_symbols(delta.node_id)          # drain Case 8 buffer
```

### Cases 5/6/7 — discussion / memory / mcp+entity
Identical shape; only the bucket key, slot fn, and capacity differ:
```
anchor, outward = _anchor_for(drec)
key, fn, cap = TABLE[kind]   # ('discussion', slot_for_discussion, DISC_CAP) ...
idx = drec.counts.get(key, 0)
slot = fn(anchor, outward, idx, cap)
drec.counts[key] = idx + 1
_record(delta, slot); _emit(delta, slot)
```
TABLE: `discussion` → `slot_for_discussion`, `DISC_CAPACITY`;
`memory` → `slot_for_memory`, `MEMORY_CAPACITY`;
`mcp`/`entity` → `slot_for_mcp`, `MCP_CAPACITY` (shared `'mcp'` bucket).

### Case 8 — `symbol`
```
parent = self.nodes.get(delta.parent_id)
if parent is None or parent.kind != 'file':   # I3 — buffer, NO emission
    self.pending_symbols.setdefault(delta.parent_id, []).append(delta)
    return
sym_key = ('sym', delta.parent_id)
idx = drec.counts.get(sym_key, 0)
slot = slot_for_symbol(parent.slot, idx, SYMBOLS_PER_FILE_CAPACITY)
drec.counts[sym_key] = idx + 1
_record(delta, slot); _emit(delta, slot)
```

`_flush_pending_symbols(file_id)` (called only from Case 4): pops the
buffered list and re-runs Case 8 for each. This is the **only**
retroactive flush in the procedure.

## 4. Helpers

```
_anchor_for(drec):
    if drec.anchor is None:                   # I7 placeholder
        a = domain_anchor(drec.index, N_CAP, cx, cy, base_r)
        return a, outward_angle(a, cx, cy)
    return drec.anchor, drec.outward

_emit(delta, slot):
    assert math.isfinite(slot[0]) and math.isfinite(slot[1])    # I1
    self.seq += 1                                                # I2
    sa = SlotAssignment(self.seq, delta.node_id, slot[0], slot[1],
                        delta.kind, delta.domain_id)
    for q in self.subscribers:
        try: q.put_nowait(sa)
        except Full: self.drop_counter += 1                      # I6

_record(delta, slot, tool_name=None):
    self.nodes[delta.node_id] = NodeRecord(
        delta.kind, delta.domain_id, slot, tool_name)
```

## 5. Capacity constants (fixed totals, not running counts — prevents drift)

```
N_CAP                     = 11    # source: workflow_graph.js domain registry
SETUP_RING_CAPACITY       = 24    # source: 6 slots × 4 kinds, fits SECTOR_SETUP_HALF
DISC_CAPACITY             = 32    # source: p99 telemetry
MEMORY_CAPACITY           = 128   # source: hot memory cap
MCP_CAPACITY              = 16    # source: MCP registry max
FILE_BUCKET_CAPACITY      = 64    # source: per-tool file p99
SYMBOLS_PER_FILE_CAPACITY = 32    # source: AST symbol p99
```

Each constant must carry a `# source:` comment per project §8 (zetetic
sources). If exceeded, slot still computes — adjacent items just clump
slightly; correctness preserved.

## 6. Invariant enforcement points

| Inv | Where |
|---|---|
| I1 | `_emit` — `assert math.isfinite` |
| I2 | `_emit` — `seq += 1` before construction |
| I3 | Case 8 — buffer if parent absent; flush after Case 4 |
| I4 | Case 4 fallback to anchor; **no retroactive reseat** |
| I5 | Pending-edges buffer (separate, `add_edge`); cap 100k |
| I6 | `_emit` — `put_nowait` + drop counter |
| I7 | `_anchor_for` placeholder; no retroactive reseat |

## 7. Out of scope / forbidden in `add_node`

No edge emission (goes through `add_edge`). No mutation of
`domains[*].anchor` after first set. No iteration of `self.nodes`.

## 8. Test obligations

1. Same `(drec.index, kind, idx)` ⇒ same slot regardless of arrival
   order of `domain` vs members (I7 placeholder == final).
2. `seq` strictly increases across 10k random adds (I2).
3. Symbol-before-file: emission deferred until Case 4 flush (I3).
4. 12 kinds × 100 random adds: every emission has finite x,y (I1).
5. Duplicate `node_id` ⇒ no second emission.
6. `tool_hub` w/o `tool_name`, `symbol` w/o `parent_id` ⇒ `ValueError`.
7. Capacity overflow (idx > cap): emission still finite, no exception.
