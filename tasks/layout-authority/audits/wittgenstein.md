# Wittgenstein — Language-Game Audit of the Layout Authority

> "For a large class of cases... the meaning of a word is its use in the language." — *Philosophical Investigations* §43

Five modules share a vocabulary. The same words play different roles in
different modules. Each polysemy is a future bug. This audit enumerates
them and fixes a single canonical glossary the engineer MUST enforce on
integration. Where a confirmed Liskov-style mismatch already exists, it
is flagged **CRITICAL**.

---

## 1. Polysemies found (the confusions)

### 1.1 `id` — CRITICAL Liskov mismatch on `SlotAssignment`

| Module     | Use site                  | Meaning                            |
|------------|---------------------------|------------------------------------|
| protocol   | `SlotAssignment.node_id`  | str — the node identifier          |
| wire       | `slot.id` (line 103, 110) | str — same intent, **wrong attr**  |
| wire       | `parse_slot` local `node_id` | str — round-trips correctly      |

`format_slot` reads `slot.id`; `SlotAssignment` defines `node_id`. **An
`AttributeError` at first emission.** Protocol is the contract; wire is
the violator. Fix in wire.

### 1.2 `kind` — same word, two unrelated games

| Module     | Use site                 | Meaning                                |
|------------|--------------------------|----------------------------------------|
| protocol   | `NodeDelta.kind`         | one of NODE_KINDS (node taxonomy)      |
| protocol   | `EdgeDelta.kind`         | one of EDGE_KINDS (edge taxonomy)      |
| protocol   | `SlotAssignment.kind`    | echo of the node taxonomy              |
| geometry   | `node_kind` parameter    | node taxonomy                          |
| scheduler  | `priority_for_node(kind)`| node taxonomy                          |
| log        | `emit(kind, payload)`    | **event taxonomy** ('slot'/'edge'/'done') |
| log        | `Event = (seq, kind, _)` | event taxonomy                         |
| wire       | `_validate_kind`         | node OR edge taxonomy (callers vary)   |

Two distinct enums share one English word. The log layer plays a
different language game than every other module. Rename or scope.

### 1.3 `seq` — counter ownership conflict

| Module     | Definition                                              |
|------------|---------------------------------------------------------|
| protocol   | I2: "strictly monotonically increasing per authority instance" |
| log        | "global ``_event_seq``... continues across resets"      |
| wire       | parameter to `format_slot` / `format_edge` / `format_done` |

Protocol says per-instance; log says global-across-reset. The log's
`reset()` docstring explicitly chooses **global** to keep
`Last-Event-ID` resume working. Protocol's I2 must defer to log: there
is exactly ONE `seq`, owned by `layout_authority_log`, monotonic across
the process lifetime, never reset.

### 1.4 `slot` — three different things

| Module     | Use site                            | Meaning                       |
|------------|-------------------------------------|-------------------------------|
| protocol   | `SlotAssignment` dataclass          | (seq, node_id, x, y, kind, domain_id) |
| geometry   | `Tuple[float, float]` returns       | bare (x, y) pair              |
| log        | `'slot'` literal string             | event-kind tag                |
| wire       | `format_slot(seq, slot)` argument   | the dataclass again           |
| scheduler  | (does not use the word)             | —                             |

Geometry's "slot" is a coordinate pair; protocol's is a placement
record; log's is a string tag. Three games, one word.

### 1.5 `domain_id` — keyed differently across boundaries

| Module     | Use site                        | Notes                              |
|------------|---------------------------------|------------------------------------|
| protocol   | `NodeDelta.domain_id` etc.      | str, refers to a domain node       |
| geometry   | `compute_slot('domain', ctx)`   | uses `ctx['index']`, `ctx['total_domains']`, `cx`, `cy`, `base_r` — **no `domain_id` key** |
| scheduler  | `coalesce_subtree(domain_id)`   | str, used as set key               |
| wire       | data field 5 of slot frame      | str                                |

Geometry's domain placement is keyed by integer `index`, not by
`domain_id`. The mapping `domain_id -> index` lives implicitly in the
authority composition root. Make it explicit.

### 1.6 `total` — five overloaded meanings in one dispatcher

`compute_slot(node_kind, ctx)` reads `ctx['total']`. Across helpers:

| Helper                  | What `total` counts                |
|-------------------------|------------------------------------|
| `slot_for_setup`        | total skills+hooks+commands+agents in domain |
| `slot_for_file`         | total files **in this hub** (`total_in_hub`) |
| `slot_for_symbol`       | total symbols **in this file** (`total_in_file`) |
| `slot_for_discussion`   | total discussions in domain        |
| `slot_for_memory`       | total memories in domain           |
| `domain_anchor`         | `total_domains` (different name!)  |

One key in the dispatcher dict, six distinct populations. The caller
must know which to supply per branch. This is exactly the family-
resemblance failure §66-71 warns about: there is no common essence,
only overlapping similarities ("a count of siblings"). Enforce the
distinct names at the helper level; the dispatcher is fine.

### 1.7 `done` — undeclared in protocol, defined in wire

`layout_authority_log` accepts `kind='done'`. `wire.format_done` builds
the frame. **Protocol module does not declare a `DoneDelta` or document
who emits `done` or when.** The "build complete" signal is a third
event kind with no contract. Add it to protocol.

### 1.8 `priority` — implicit on every NodeDelta

`PriorityScheduler.submit(priority, item)` accepts any int in
`QUEUE_SIZES`. `priority_for_node(kind)` derives it from the node
taxonomy. The contract that "P0=domain, P4=symbol" lives only in the
scheduler module's docstring. The protocol module is silent. This is
fine *iff* only the authority's worker submits, but the typing is
loose.

---

## 2. Canonical glossary (NORMATIVE)

The engineer integrating these modules MUST use these names. Renames
required to fix existing mismatches are marked **[FIX]**.

| Canonical name      | Type / shape                          | Owner module     | Definition                                                      |
|---------------------|---------------------------------------|------------------|-----------------------------------------------------------------|
| `node_id`           | `str`, non-empty, no `\| \\n \\r`     | protocol         | Stable unique node identifier. **NEVER `id`.**                  |
| `domain_id`         | `str`, non-empty                      | protocol         | The `node_id` of a node whose `node_kind == 'domain'`.          |
| `parent_id`         | `Optional[str]`                       | protocol         | For `'symbol'`: parent file's `node_id`. For `'file'`: tool_hub. |
| `node_kind`         | `str` ∈ NODE_KINDS                    | protocol         | Taxonomy of nodes. **NEVER bare `kind` outside dataclasses.**   |
| `edge_kind`         | `str` ∈ EDGE_KINDS                    | protocol         | Taxonomy of edges.                                              |
| `event_kind`        | `Literal['slot','edge','done']`       | log              | Wire-event taxonomy. **[FIX]** rename log's `kind` arg.         |
| `seq`               | `int`, strictly monotonic, global     | log              | Single global counter. **[FIX]** drop "per-instance" from I2.   |
| `slot_xy`           | `Tuple[float, float]`                 | geometry         | Bare coordinate pair returned by helpers. **[FIX]** rename from "slot". |
| `SlotAssignment`    | dataclass(seq, node_id, x, y, node_kind, domain_id) | protocol | The placement record. `.node_id`, never `.id`. **[FIX]** wire.  |
| `NodeDelta`         | dataclass(node_id, node_kind, domain_id, parent_id, tool_name) | protocol | Add-node input. **[FIX]** rename `kind` → `node_kind` everywhere. |
| `EdgeDelta`         | dataclass(source_id, target_id, edge_kind) | protocol    | Add-edge input. **[FIX]** rename `kind` → `edge_kind`.          |
| `DoneDelta`         | dataclass(total_slots: int, total_edges: int) | protocol  | **[FIX]** new — terminal build-complete event.                  |
| `priority`          | `int` ∈ {0..6}                        | scheduler        | P0..P6, lower = more critical.                                  |
| `total_domains`     | `int ≥ 1`                             | geometry         | Count of domain nodes; key on `compute_slot` ctx for kind='domain'. |
| `total_in_domain`   | `int ≥ 1`                             | geometry         | Sibling count within a domain (setup / discussion / memory / mcp). |
| `total_in_hub`      | `int ≥ 1`                             | geometry         | File count within one tool_hub.                                 |
| `total_in_file`     | `int ≥ 1`                             | geometry         | Symbol count within one file.                                   |
| `idx_in_*`          | `int ≥ 0`                             | geometry         | Position within the matching `total_in_*`. **[FIX]** drop bare `idx`/`total` from `compute_slot` ctx in favor of explicit names. |
| `index` (domain)    | `int ≥ 0`                             | geometry         | Domain placement index in Fibonacci spiral. Mapping `domain_id → index` is owned by the authority composition root and MUST be exposed. |
| `tool_name`         | `str`                                 | protocol         | Required iff `node_kind == 'tool_hub'`.                         |
| `hub_angle`         | `float` (radians)                     | geometry         | Cached per-tool axis; carried in ctx for files orbiting a hub.  |
| `outward`           | `float` (radians)                     | geometry         | Domain's radially-outward axis from canvas center.              |
| `anchor`            | `Tuple[float, float]`                 | geometry         | A domain's (x, y); the parent reference for everything inside.  |

Pseudo-problems dissolved by this glossary:

- "Why does wire crash on first emit?" — `slot.id` vs `slot.node_id`. Not a real bug class; a pure naming slip.
- "Should `seq` reset across builds?" — protocol I2 vs log reset. Resolved by declaring log the owner; protocol I2 reworded.
- "What is `total`?" — depends on the call site. The dispatcher's `ctx['total']` is the genuine bug; six distinct names fix it.
- "Where is the `done` contract?" — undeclared. Add `DoneDelta` to protocol.

Real problems that survive vocabulary clarification (NOT dissolved):

- The `domain_id → index` mapping is genuine missing state — the
  authority composition root must own it (separate audit).
- Pending-edges buffer ordering vs. seq monotonicity (I5 vs I2) is a
  genuine race the log's single-producer rule alleviates but does not
  eliminate.

---

## 3. Mandatory edits (engineer integration checklist)

1. **wire.py**: replace `slot.id` with `slot.node_id` (2 occurrences). Update `_validate_id(slot.id, "slot.id")` to `_validate_id(slot.node_id, "slot.node_id")`. Update `parse_slot` docstring to call the field `node_id` (it already does locally).
2. **protocol.py**: rename `NodeDelta.kind` → `node_kind`, `EdgeDelta.kind` → `edge_kind`, `SlotAssignment.kind` → `node_kind`. Update I2: drop "per authority instance"; add "owned by `layout_authority_log`, never reset."
3. **protocol.py**: add `DoneDelta(total_slots: int, total_edges: int)` dataclass and document who emits it (the build worker, after the last add_node/add_edge).
4. **log.py**: rename `emit(kind, payload)` → `emit(event_kind, payload)`. Type hint `event_kind: Literal['slot', 'edge', 'done']`.
5. **geometry.py**: rename helper params `total` → `total_in_hub` / `total_in_file` / `total_in_domain`; same for `idx`. Update `compute_slot` dispatcher to read the explicit keys per branch (no shared `ctx['total']`).
6. **scheduler.py**: type-annotate `submit(priority: int, item: NodeDelta | EdgeDelta | str)` so the priority/item invariant is checked at the boundary.
7. **Composition root** (forthcoming `layout_authority.py`): expose the `domain_id → index` mapping as an explicit field on the authority instance; geometry's `compute_slot` for `'domain'` reads `ctx['index']` from it.

The glossary in §2 is the **integration contract**. Refuse merges that
reintroduce `slot.id`, bare `kind` on Node/Edge/SlotAssignment, or
shared `ctx['total']`.
