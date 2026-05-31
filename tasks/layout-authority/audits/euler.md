# Layout Authority — Notation-as-Infrastructure Audit (Euler)

**Method:** read the six `layout_authority_*.py` modules as if their identifiers were a notational system. Names that compose cleanly (e.g. `compute_slot(kind, ctx)` reads like math; `priority_for_node(kind)` is a function lookup) are RIGHT. Names that overload one word with multiple meanings, or that drop a qualifier the reader needs to disambiguate, are WRONG — and like the `slot.id` vs `slot.node_id` audit cost, they compound.

The standard is Euler's: notation is infrastructure. The right name makes the next four audits cheap; the wrong name makes them quadratic.

---

## 1. The notation that is RIGHT (keep verbatim)

These read like math. Do not touch them.

- `compute_slot(node_kind, ctx)` (geometry.py:183) — pure dispatch; reads as `slot = f(kind, ctx)`.
- `domain_anchor(index, total_domains, cx, cy, base_r)` — every parameter has a unit; `total_domains` is unambiguous.
- `slot_for_setup` / `_tool_hub` / `_file` / `_symbol` / `_discussion` / `_memory` / `_mcp` — verb-prefixed family; the shared prefix `slot_for_*` IS the notation.
- `priority_for_node(kind)` / `priority_for_edge()` — symmetric pair; function name encodes the dispatch.
- `NodeDelta`, `EdgeDelta`, `SlotAssignment` — suffix declares the role: `Delta` = input verb, `Assignment` = output event.
- `NODE_KINDS`, `EDGE_KINDS`, `TOOL_LOCAL_ANGLE`, `PRIORITY_DOMAIN..._SUBTREE` — UPPER_CASE lookup tables; the table IS the notation.

---

## 2. The notation that is WRONG — concrete renames

### 2.1 `total` is overloaded six ways (Wittgenstein-flagged)

`total` means a different thing in nearly every signature it appears in. This is the worst offender — every consumer of these functions has to re-derive what `total` counts.

| Site | What `total` actually means | Proposed name |
|---|---|---|
| `slot_for_setup(anchor, outward, idx, total)` (geometry.py:96) | total nodes in the (domain, setup-kind) bucket | `n_in_setup_sector` |
| `slot_for_discussion(anchor, outward, idx, total)` (132) | total discussions in this domain | `n_discussions_in_domain` |
| `slot_for_memory(…, total)` (146) | total memories in this domain | `n_memories_in_domain` |
| `slot_for_mcp(…, total)` (159) | total mcp nodes in this domain | `n_mcps_in_domain` |
| `slot_for_file(anchor, hub_angle, idx_in_hub, total_in_hub)` (121) | already disambiguated — KEEP | (keep `total_in_hub`) |
| `slot_for_symbol(file_slot, idx_in_file, total_in_file)` (170) | already disambiguated — KEEP | (keep `total_in_file`) |
| `format_done(seq, total_slots, total_edges)` (wire.py:139) | global cumulative count — KEEP | (keep) |
| `Stats.queued: dict[int, int]` / `Stats.dropped` (scheduler.py:123) | per-priority cumulative — fine | (keep) |

**Rule:** every numeric parameter named `total` must answer *"total of what, scoped where?"* with a qualifier in the name. The two functions that already do this (`total_in_hub`, `total_in_file`) prove the pattern works. Apply it to the other four.

The same rule applies to `idx`: `idx_in_hub` and `idx_in_file` are right; bare `idx` in `slot_for_setup`/`_discussion`/`_memory`/`_mcp` should become `idx_in_sector` / `idx_in_lane`.

### 2.2 `kind` versus `node_kind` versus implicit kind in name

- `compute_slot(node_kind, ctx)` uses `node_kind` (geometry.py:183).
- `priority_for_node(kind)` uses bare `kind` (scheduler.py:97).
- `NodeDelta.kind` and `EdgeDelta.kind` are bare `kind` on a typed object (protocol.py:71, 100).
- `SlotAssignment.kind` is bare `kind` on the output (protocol.py:128).
- `visible_at_zoom(node_id, kind, zoom)` is bare `kind` (lod.py:87).

The dataclass attributes (`NodeDelta.kind`) are FINE — the type prefix is the qualifier. The free-function parameters that take a node kind should standardise on **`node_kind`** (the geometry module's choice). Edges have their own `kind` parameter set; `edge_kind` should be the convention there.

| Site | Rename |
|---|---|
| `priority_for_node(kind)` → `priority_for_node(node_kind)` | scheduler.py:97 |
| `visible_at_zoom(node_id, kind, zoom)` → `visible_at_zoom(node_id, node_kind, zoom)` | lod.py:87 |
| `_validate_kind(value)` → `_validate_kind_token(value)` | wire.py:75 (it validates either node_kind or edge_kind; it's a token-level check, not a kind-typed check) |

This costs one rename per call site and removes a lookup the next reader has to perform.

### 2.3 `seq` versus `since` versus `event_seq` (the cursor is one thing)

The wire/log layer has a single cursor concept used four ways:

- `SlotAssignment.seq` — the assigned sequence number (protocol.py:124).
- `_event_seq` (module global) — the producer's monotonic counter (log.py:53).
- `replay_since(since: int)` — the consumer's resume cursor (log.py:165).
- `Last-Event-ID` header — the wire form of the same cursor.

The reader has to mentally connect four words for one quantity. Recommend:

| Site | Current | Proposed |
|---|---|---|
| `_event_seq` (module global) | `_event_seq` | keep — it IS the producer's seq |
| `replay_since(since)` | parameter `since` | rename parameter to `cursor_seq` (return tuple stays; function name stays) |
| docstrings | "Last-Event-ID" / "since" / "seq" mixed | standardise on **"event seq"** wherever a number references this cursor |

Tiny patch, high readability gain — the next audit immediately sees that `Last-Event-ID == cursor_seq == event seq`.

### 2.4 `kind` event-tagging in the log conflicts with `node.kind`

In `log.py`, `Event = Tuple[int, str, bytes]` and `emit(kind, payload)` use `kind` ∈ {`'slot'`, `'edge'`, `'done'`} — these are EVENT kinds, not NODE kinds, so `grep "kind"` interleaves two taxonomies. Rename `emit(kind, …)` → `emit(event_kind, …)` and document the `Event` tuple slot as `event_kind`. Five-line patch; cleanly separates the namespaces.

### 2.5 `_DECIMATED` / `_FAR_REDUCED` / `_ALWAYS_VISIBLE` — name the rule, not the verdict

The three frozensets in `lod.py` are predicates on node kinds; their current names describe the OUTCOME, not the membership rule, so reading `visible_at_zoom` forces a back-lookup at each branch. Rename to:

- `_ALWAYS_VISIBLE` → `_KINDS_NEVER_DECIMATED`
- `_DECIMATED` → `_KINDS_DECIMATED_BY_ZOOM`
- `_FAR_REDUCED` → `_KINDS_REDUCED_AT_FAR_ZOOM` (parallels `_FAR_ZOOM_THRESHOLD`)

Then `visible_at_zoom` reads top-to-bottom and the set name IS the conditional.

### 2.6 `field` (parameter) shadows `dataclasses.field`

In `_validate_id(value: str, field: str)` (wire.py:64) and `_validate_finite(v: float, field: str)` (wire.py:82) the parameter `field` shadows `dataclasses.field` (which `scheduler.py` imports). Rename to `field_name` — costs five characters per site, removes a name-collision footgun.

### 2.7 `n` reused as both "domain count" and "current bucket count"

In `geometry.py` the local `n = max(<something>, 1)` recurs across five functions, sometimes meaning "total domains", sometimes "items in this bucket". Local scope contains the damage; optional rename to `safe_n_<scope>`.

---

## 3. The notation that is MISSING (introduce, don't rename)

### 3.1 No name for "(domain, kind) bucket counter"

The geometry module repeatedly uses an implicit pair `(domain_id, node_kind)` indexing a counter. The bucket is unnamed. The `compute_slot` ctx dict carries `idx` and `total` for it but the TYPE has no name. Introduce in `protocol.py`:

```python
@dataclass(frozen=True, slots=True)
class BucketKey:
    domain_id: str
    node_kind: str
```

…and let the scheduler / authority store `dict[BucketKey, int]` for the running counter. Three benefits:

1. A type the next reader can grep for.
2. The "O(domains × kinds)" memory claim in `geometry.py`'s docstring becomes literal: `len(counters) == |BucketKey set|`.
3. `request_subtree(domain_id)` becomes naturally describable as "all `BucketKey` with this `domain_id`".

### 3.2 No vocabulary for "domain-anchor cache" vs "tool-hub-angle cache"

The geometry comments mention that the caller "stores [the tool-hub angle] for files to orbit" (geometry.py:117). Files orbit a `hub_angle`, symbols orbit a `file_slot`. These are two derived quantities the authority must cache. Today they're implicit in the ctx dict. Recommend the authority expose them as named slots:

```python
@dataclass(frozen=True, slots=True)
class DomainGeometry:
    anchor: tuple[float, float]
    outward: float
    base_r: float

@dataclass(frozen=True, slots=True)
class ToolHubAnchor:
    bucket: BucketKey
    hub_angle: float
```

Then the `compute_slot` dispatcher can take typed inputs instead of a free-form `dict`, and the "out-of-order arrival" tolerance described in invariant I4 has a natural place to live (the `ToolHubAnchor` is None until the hub arrives; the file slot derives from `DomainGeometry` only as a fallback).

This is a larger change — flag as a separate refactor PR, not the small notation-cleanup PR below.

---

## 4. Recommended notation-cleanup PR (small, mechanical)

Scope it tightly. These are all rename-only edits with mechanical test impact.

| File | Change | Lines touched |
|---|---|---|
| `layout_authority_geometry.py` | `total` → qualified name in 4 functions; `idx` → `idx_in_sector` / `idx_in_lane` | ~20 |
| `layout_authority_scheduler.py` | `priority_for_node(kind)` → `(node_kind)` | 3 |
| `layout_authority_lod.py` | `visible_at_zoom(node_id, kind, zoom)` → `(…, node_kind, …)`; rename three frozensets | ~25 |
| `layout_authority_log.py` | `Event` second slot named `event_kind`; `emit(kind, payload)` → `emit(event_kind, payload)`; `replay_since(since)` → `replay_since(cursor_seq)` | ~10 |
| `layout_authority_wire.py` | `field` parameter → `field_name` in two helpers; `_validate_kind` → `_validate_kind_token` | ~8 |
| Tests | follow renames (mechanical) | ~30 |

**Total:** roughly 90–100 lines of mechanical change. No behavioural change. Single commit, single PR, single review pass.

**Skip in this PR (separate work):** the `BucketKey` / `DomainGeometry` / `ToolHubAnchor` typed-context refactor (§3) — that one changes the geometry dispatch surface and deserves its own discussion.

---

## 5. Compliance against the Euler standard

- **Move 1 (notation as infrastructure):** seven concrete renames eliminate re-derivation at the call site.
- **Move 4 (productive generalization):** `total` → `total_in_<scope>` is a family-level fix; same pattern fixes `idx` and `n`.
- **Refusal trigger respected:** every rename has a named call-site cost and a named utility. No ornament.
