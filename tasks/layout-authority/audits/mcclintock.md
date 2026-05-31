# McClintock single-specimen audit — `domain:cortex`

**Method.** Pick ONE node. Trace it across every module. Long looking, not statistics.
**Specimen.** `NodeDelta(node_id="domain:cortex", kind="domain", domain_id="domain:cortex", parent_id=None, tool_name=None)` arriving as the first `add_node` call on a fresh `build_authority()` with default 1000×1000 canvas.

## 1. Wire-arrival shape

Frozen `slots=True` dataclass, ~80 B. The `kind=='domain'` contract (`_protocol.py:63`) collapses two ids into one string: **`domain_id == node_id`**. This is the only kind with self-referential identity. The `"domain:"` prefix is build-worker convention, not protocol-enforced. The colon is not a forbidden delimiter (`|`, `\n`, `\r` only).

## 2. `_validate_node` (`layout_authority.py:121`)

Five gates: kind-in-set; node_id non-empty; domain_id non-empty; **gate 4** `kind=='domain'` → `domain_id == node_id` (both `"domain:cortex"`, pass); tool_hub/symbol gates short-circuit. Gate 4 is the only kind-distinguishing gate that fires for our specimen — it is also the gate that would *fail loudly* for any malformed domain. If `kind` were `'file'` instead, gate 4 would not fire and the same string pair would skate through unchanged.

## 3. `_DomainRegistry.index_for` (`layout_authority.py:78`)

First sighting → `idx = 0`, reservation = `_DEFAULT_DOMAIN_RESERVATION = 16`. No growth. Then:

- `base_r = base_radius(1000, 1000, 16) = max(420.0, (2·220+60)·sqrt(16/π)·0.65) = max(420.0, 733.5) = 733.5` (spacing-driven floor wins).
- `anchor = domain_anchor(0, 16, 500, 500, 733.5)`: `r = 733.5·sqrt(0.5/16) = 129.66`, `theta = 0·_PHI = 0`, → **`(629.66, 500.0)`**.
- `outward = atan2(0, 129.66) = 0.0` — exactly due-east.

**The first surprise.** Index 0 always gives `theta = 0`, so `domain:cortex`-when-first lands precisely on the +x axis. Fibonacci spirals are praised for even spread; the index-0 point is the one place where the spread is undefined. The renderer always has one anchor pinned horizontally to the right. The protocol/audits do not call this out — I3/I4/I7 cover ordering races, not this geometric degeneracy.

**The second surprise.** If `domain:cortex` arrives *second* (because `domain:claude_code` registered first), the same specimen lands at `theta = _PHI ≈ 137.5°` (northwest quadrant). Position is a function of arrival order, frozen forever (I7). **The visual identity of the specimen is non-deterministic across runs unless the build worker imposes a stable enumeration order.** The aggregate invariant "anchors are deterministic from index" is true; the per-specimen claim "this domain has a stable visual home" is false.

## 4. `_place_node` → `_compute_assignment` (`layout_authority.py:244, 262`)

Not symbol → no buffering. `idx = _counts.get(("domain:cortex","domain"), 0) = 0`, then increment to 1. **This counter never increments again** — there is at most one domain-kind node per domain_id. `_geometry_ctx` returns `{index: 0, total_domains: 16, cx: 500, cy: 500, base_r: 733.5}`.

**The third surprise.** `total_domains=16` is the *reservation*, not the population (1). Reservation grows in chunks of 16 when exhausted; existing anchors are *not* recomputed. So a 17th domain arriving later is placed using N=33 spiral math, while `domain:cortex` keeps its frozen 16-domain anchor. **Two domains placed in different reservation epochs live in different metric coordinate systems.** I4/I7 cover this for ordering but never name the metric drift.

`compute_slot("domain", ctx)` is pure — same numbers as step 3. Returned `SlotAssignment(seq=0, ..., x=629.66, y=500.0)` with `seq=0` placeholder.

## 5. `_emit_slot` → wire (`layout_authority.py:345`, `_wire.py:91`)

Peek-before-emit: `seq = _log._event_seq + 1 = 1`. Re-seal with seq=1. Wire frame:

```
id: 1\nevent: slot\ndata: domain:cortex|629.7|500.0|domain|domain:cortex\n\n
```

**The fourth surprise.** The data payload contains the id twice — `node_id` and `domain_id` are the same string for every domain node. The pipe encoder cannot deduplicate (non-domain nodes need both fields), so every domain frame pays ~20 B of redundancy on the wire. Cheap at our scale, but the wire spec doesn't acknowledge it.

`_log.emit` increments `_event_seq` to 1, appends to the 500k ring, fans out, asserts `actual_seq == peeked_seq` (single-producer invariant under `self._lock`). `_slots["domain:cortex"] = sealed`. Slot is final. No `kind == "file"` flush. `_try_flush_pending_edges_for` is a no-op (empty buffer).

## 6. Resident footprint of the specimen

After this one call, `"domain:cortex"` is mentioned in five places:

| Module | Key | Value |
|---|---|---|
| `_DomainRegistry._index_of` | `"domain:cortex"` | `0` |
| `_DomainRegistry._anchors` | `"domain:cortex"` | `(629.66, 500.0)` |
| `_DomainRegistry._outwards` | `"domain:cortex"` | `0.0` |
| `LayoutAuthority._counts` | `("domain:cortex", "domain")` | `1` |
| `LayoutAuthority._slots` | `"domain:cortex"` | `SlotAssignment(seq=1, …)` |

~400 B. The specimen is the **coordinate origin** for an entire subtree: every later node with `domain_id="domain:cortex"` reads `_registry.anchor("domain:cortex")` and composes its position relative to (629.66, 500.0). Modify this one anchor and the whole subtree shifts; the slots themselves never recompute.

## 7. Counterfactual: `kind = 'file'` with the same string pair

- Validator: gate 4 does not fire. Pass.
- `_compute_assignment`: `idx = _counts.get(("domain:cortex","file"), 0) = 0`.
- `_geometry_ctx` calls `reg.anchor("domain:cortex")` — **and this triggers `index_for` lazily**, registering `"domain:cortex"` as a domain *anyway*, anchor (629.66, 500.0). No slot is emitted for the domain itself — it is a phantom registration.
- `parent_id is None` → `hub_angle = outward = 0.0`.
- `slot_for_file(anchor=(629.66,500), hub_angle=0, idx=0, total=1)`: arc=0.095, t=0, r=216 → file lands at **(845.66, 500.0)**.

**The fifth surprise.** Reading `reg.anchor(domain_id)` for a non-domain node *creates* a domain registration as a side effect, with a frozen anchor and no SlotAssignment ever emitted. A later real `add_node` for that domain succeeds and emits the slot at the same anchor (counters are per-(domain,kind) so no collision). But: a typo'd domain_id permanently consumes a spiral index that no other domain can take, and there is no phantom-domain reconciliation. **The system tolerates domain-after-children (I7 promise) but is silent about domain-never.**

## 8. Counterfactual: `domain_id = 'domain:something_else'`

`kind='domain', node_id='domain:cortex', domain_id='domain:something_else'` fails gate 4 → `ValueError`. Domains are roots; the protocol forbids "a domain belonging to another domain."

But: **node_id global uniqueness is assumed but not asserted.** `_slots` is keyed by node_id alone. A second `add_node` with `node_id="domain:cortex"` and any kind silently overwrites `_slots["domain:cortex"]` (I see no guard in `_place_node` against `delta.node_id in self._slots`). The protocol docstring says "stable, unique" — there is no enforcement. This is a real gap.

## 9. Direct-vs-aggregate disagreement

Existing audits cover aggregate invariants — O(1) placement, no NaN ever reaches the wire, seq monotonic. These hold for our specimen. But the specimen reveals **identity-shaped facts** that aggregation smooths away:

- `domain:cortex` *as a string* is the seed of an entire coordinate subtree.
- Its placement depends on arrival order across runs (I7-compatible, but visually surprising).
- Its node_id collides with its domain_id *by contract* (gate 4).
- The registry is a write-once store the rest of the system reads many times.
- The lazy-anchor side effect makes the registry creatable from non-domain code paths.

The aggregate view "domain nodes are like other nodes with one extra gate" is wrong. They are the privileged kind, and the typically-first-arriving one is doubly privileged: it sits at exactly `(629.66, 500.0)` on a 1000×1000 canvas, deterministic to floating precision.

## 10. Findings (specimen-scoped, not generalized)

- Specimen lands at `(629.66, 500.0)` when first into a fresh 1000×1000 authority. Slot is final.
- Five resident-state entries; no unbounded growth.
- Wire frame is 74 B; pipe encoding works; the id repeats by construction.
- Five surprises surfaced: index-0 axis degeneracy; arrival-order dependence; reservation/population metric drift; wire-redundant domain_id; lazy-registry phantom domains.
- One real gap: **node_id collision is unguarded.**

## 11. Hand-offs

- **node_id collision guard** → engineer: add `assert delta.node_id not in self._slots` in `_place_node`, or document overwrite as intentional.
- **Phantom-domain via lazy anchor read** → Feynman integrity check: intentional or oversight?
- **Index-0 degeneracy & arrival-order non-determinism** → Curie: instrument the build worker to enforce stable domain enumeration order; verify visually.
- **Reservation/population metric drift** → Darwin: long-horizon, track visual layout evolution across many builds as new domains accrete.

---

*Specimen: one. Modules traversed: six. Anomalies surfaced: five. Real gaps: one. The microscope was the source code; the maize was `domain:cortex`.*
