# Darwin Variation-Enumeration Audit — Layout Authority

**Method:** Catalogue every kind of "specimen" the layout authority must accept, predict its behaviour from the contracts (`layout_authority_protocol.py`, `layout_authority_geometry.py`, `layout_authority_wire.py`), and leave the **observed** column open for the engineer's integration to fill in. The Darwin discipline: patient enumeration of every variant — typical, edge, pathological — before any single specimen is granted theoretical weight.

**Sources of predicted behaviour**
- `layout_authority_protocol.py` lines 30–69 (NODE_KINDS, NodeDelta preconditions, I1–I7).
- `layout_authority_geometry.py` lines 183–218 (`compute_slot` dispatcher, fallback to `anchor`).
- `layout_authority_wire.py` lines 58–85 (`_MAX_KIND=32`, pipe / `\n` / `\r` rejection, finite-float check at emission).

**Notation**
- *Predicted* = behaviour required by the contracts as currently written.
- *Observed* = to be filled by the engineer once `layout_authority.py` (the reference impl wiring `add_node` → counters → `compute_slot` → `SlotAssignment` → wire) lands and the integration tests run.
- `BUFFER` means the delta is queued in the pending-edges/pending-symbols buffer pending I3/I4/I5 resolution.
- `REJECT@protocol` means `ValueError` raised in `add_node` per the precondition (lines 60–65).
- `REJECT@wire` means accepted by the authority but rejected at SSE emission per wire validators (lines 71–79).

---

## Specimen catalogue

### A. Typical specimens (the centre of the distribution)

| # | Variant | Predicted behaviour | Observed |
|---|---|---|---|
| A1 | `domain` node, `node_id == domain_id == "Cortex"` | `compute_slot` → `domain_anchor(index, total, cx, cy, base_r)`; one `SlotAssignment` emitted, finite (x,y). | _to fill_ |
| A2 | `tool_hub` node, `tool_name="Edit"`, known domain_id | `slot_for_tool_hub` along outward axis; finite, deterministic. | _to fill_ |
| A3 | `file` node with `parent_id` = a known tool_hub | `slot_for_file` orbiting hub_angle; finite, monotonic seq. | _to fill_ |
| A4 | `file` with **5 symbols** under it, symbols arrive after file | Each symbol → `slot_for_symbol(file_slot, idx, total=5)`; petal cloud at SYM_CLUMP_R. | _to fill_ |
| A5 | `memory`, `discussion`, `mcp` ordinary insertions | Respective `slot_for_*` helpers; all O(1). | _to fill_ |

### B. Edge specimens — within-spec but stressing the contracts

| # | Variant | Predicted behaviour | Observed |
|---|---|---|---|
| B1 | `file` with **0 symbols** | File placed normally; no symbol assignments emitted. No call to `slot_for_symbol` (guard at `total_in_file <= 0` returns `file_slot` if ever invoked — geometry.py line 174). | _to fill_ |
| B2 | `file` with **1000 symbols** | Each symbol gets a deterministic angle `2π·(i+0.5)/1000`; all finite; clumped within SYM_CLUMP_R petal. State cost: one int counter; no per-symbol allocation. | _to fill_ |
| B3 | Unicode in `node_id` (e.g. `"Cørtex/файл.py"`) | **Accepted at protocol** (no charset check in NodeDelta). **Accepted at wire** unless it contains `\|`, `\n`, `\r` (wire.py line 71). UTF-8 bytes pass through. | _to fill_ |
| B4 | `node_id` of length 256 (no delimiter) | Accepted at protocol and wire (no length cap on `node_id`; `_MAX_KIND` applies only to `kind`). | _to fill_ |
| B5 | `node_id` of length 4096 | Accepted; SSE frame grows linearly. No bound enforced today — flag for engineer: **contract gap**, no max-id-length is documented. | _to fill_ |
| B6 | `symbol` arrives **before** parent file | Per I3: buffered in pending-symbols until file lands, then emitted. Authority MUST NOT compute symbol from domain anchor directly. | _to fill_ |
| B7 | `file` arrives before its tool_hub | Per I4: file placed at domain hub fallback; slot is **FINAL**, no retroactive reseat when tool_hub later lands. | _to fill_ |
| B8 | `domain` node arrives **after** its members | Per I7: members computed against placeholder anchor, slots are FINAL. Late-arriving domain node gets its own anchor; existing member slots NOT updated. (This is documented behaviour but visually surprising — note for engineer.) | _to fill_ |
| B9 | `request_subtree(domain_id)` for known domain | Re-emits all slots in subtree with **higher seq** (I2); clients update by seq. | _to fill_ |
| B10 | `request_subtree(domain_id)` for unknown domain | Returns silently (idempotent — protocol line 166). | _to fill_ |

### C. Pathological specimens — out-of-spec; contract dictates rejection or graceful degradation

| # | Variant | Predicted behaviour | Observed |
|---|---|---|---|
| C1 | `kind` not in `NODE_KINDS` (e.g. `"frobnicator"`) | `REJECT@protocol`: `ValueError` per protocol line 158. (If the impl forwards instead of validating, geometry's dispatcher falls back to `anchor` — geometry.py line 218 — which masks the bug. The reference impl MUST validate first.) | _to fill_ |
| C2 | `kind = "domain"` but `node_id != domain_id` | `REJECT@protocol`: precondition line 63. | _to fill_ |
| C3 | `kind = "tool_hub"` with `tool_name = None` or `""` | `REJECT@protocol`: precondition line 64. | _to fill_ |
| C4 | `kind = "symbol"` with `parent_id = None` | `REJECT@protocol`: precondition line 65. | _to fill_ |
| C5 | `node_id = ""` (empty) | `REJECT@protocol`: precondition line 61. | _to fill_ |
| C6 | `domain_id = ""` (empty) | `REJECT@protocol`: precondition line 62 + I7. | _to fill_ |
| C7 | `node_id` containing `\|` (pipe) | Accepted at protocol (no delimiter check). **`REJECT@wire`** at emission (wire.py line 71). The slot computation runs but the assignment cannot be serialised. **Contract gap:** this means a slot is computed and counters incremented, but no event reaches clients. Engineer must decide: validate at protocol entry (preferred) or accept the silent drop. | _to fill_ |
| C8 | `node_id` containing `\n` | Same as C7 — protocol accepts, wire rejects. Same gap. | _to fill_ |
| C9 | `kind` length > 32 chars | If `kind` is in `NODE_KINDS`, this cannot occur (longest is "discussion"=10). If a non-NODE_KINDS string sneaks past C1, wire rejects via line 78. Defence in depth holds. | _to fill_ |
| C10 | Duplicate `node_id` submitted twice (same kind, same domain) | Authority MUST be idempotent OR emit two assignments with same (x,y) and increasing seq. Contract is **unspecified** here — flag as gap. Reasonable behaviour: dedupe and ignore the second; otherwise counter double-increments and breaks O(1) determinism for siblings. | _to fill_ |
| C11 | Duplicate `node_id` re-submitted with **different kind** | Contract unspecified. Recommended: reject; otherwise position would change for a node already painted on the client. Flag as gap. | _to fill_ |
| C12 | `parent_id` pointing to a node that was never `add_node`'d | For `symbol`: per I3, buffered indefinitely (or until pending buffer drops it per I5). For `file`: per I4, fallback to domain anchor — slot is FINAL. | _to fill_ |
| C13 | `parent_id` pointing to a previously-deleted node | **No delete verb exists** in the protocol (lines 3–10 list only add_node / add_edge / request_subtree). Deletion is out of scope. Flag if engineer adds one — it would break I2/I3/I4. | _to fill_ |
| C14 | `domain_id` self-loop (`domain_id == node_id` but `kind != "domain"`) | Protocol does not forbid this directly (only line 63 enforces the converse). The node would be placed as a member of a domain whose anchor is itself — i.e. depending on order: if the "domain" with that id never arrives, the placeholder anchor is used. Visually nonsensical but not crashing. **Contract gap:** add a precondition "if kind != 'domain' then domain_id != node_id". | _to fill_ |
| C15 | NaN-attempting context (e.g. `total_domains = 0`) | `base_radius` / `domain_anchor` use `max(n, 1)` (geometry.py lines 67, 75). NaN cannot arise from division. I1 holds. | _to fill_ |
| C16 | Float overflow attempt (huge canvas, e.g. `cx = 1e308`) | `r * cos(theta)` may overflow to ±inf. Wire emission rejects via `math.isfinite` (line 84). Authority must clamp `cx, cy, base_r` at construction OR rely on wire rejection. **Contract gap:** authority does not currently bound canvas dimensions. | _to fill_ |
| C17 | `kind = "entity"` (in NODE_KINDS line 32 but not handled in `compute_slot`) | Falls through to `ctx.get("anchor", (cx, cy))` — line 218. Slot = domain anchor (or origin). Does not crash; produces a degenerate but finite assignment. **Contract gap:** "entity" is in NODE_KINDS but has no geometry — either remove from NODE_KINDS or add a slot helper. | _to fill_ |
| C18 | Edge with unknown source or target | Per protocol line 162: queued in pending-edges buffer (bounded, I5 default 100k). When second endpoint arrives, edge flushed. On overflow: oldest dropped, drop counter incremented. | _to fill_ |
| C19 | Edge with `kind` not in `EDGE_KINDS` | `REJECT@protocol` line 161: ValueError. | _to fill_ |
| C20 | `add_node` called from a thread other than the build worker | Per protocol line 145: only `request_subtree` and `subscribe`/`unsubscribe` are documented thread-safe. `add_node` from a foreign thread is undefined. Engineer must either widen the contract or add a lock. **Contract gap.** | _to fill_ |

---

## Predicted-behaviour summary by category

| Category | Count | Disposition |
|---|---:|---|
| Typical (A) | 5 | All produce one finite, deterministic SlotAssignment in O(1). |
| Edge within-spec (B) | 10 | All resolved by I3/I4/I7 buffering rules; slots are FINAL. |
| Pathological well-defined (C1–C6, C9, C12, C15, C18–C19) | 11 | Either `REJECT@protocol`, `REJECT@wire`, or buffered per I5 — all behaviours specified. |
| Pathological with **contract gaps** (C7, C8, C10, C11, C13, C14, C16, C17, C20) | 9 | Behaviour is **unspecified** in the current protocol. The reference implementation must choose, and the choice must be documented as a new invariant. |

---

## Contract gaps surfaced by enumeration (hand-off to engineer)

1. **C7/C8** — pipe / newline in `node_id`: silent drop at wire after counter incremented. Validate at protocol entry instead.
2. **C10/C11** — duplicate `node_id` submission: idempotent? double-emit? reject? Spec it.
3. **C13** — no delete verb; if added later it breaks I2–I4. Document the explicit decision to forbid deletion.
4. **C14** — `domain_id == node_id` for non-domain kinds: add a precondition.
5. **C16** — finite-canvas guarantees rely on wire rejection; consider bounding canvas dimensions at authority construction.
6. **C17** — `"entity"` is in `NODE_KINDS` (line 32) but has no geometry helper. Either remove or implement.
7. **C20** — `add_node` thread-safety is documented as build-worker-only. If subscribers can ever produce, add a lock.
8. **B5** — no maximum length on `node_id` is documented. SSE frames grow unboundedly. Pick a cap (e.g. 1024 bytes UTF-8 encoded).

---

## Stopping rule

This audit catalogues the variants the contracts permit me to enumerate from the protocol and geometry sources alone. The hardest case for the theory "the layout authority is O(1) and finite for every input it accepts" is **C16 + C17 jointly**: a kind in `NODE_KINDS` that has no geometry helper combined with extreme canvas values produces a degenerate-but-finite slot at origin — technically within I1 but visually a crash. Both cases are explicit contract gaps.

The audit ships in this state because every entry has either a predicted behaviour grounded in a cited line of the protocol/geometry/wire modules, or an explicit "contract gap" flag. Further refinement requires the reference `layout_authority.py` to land so the *observed* column can be filled — the Darwin stopping rule (Move 6).

## Hand-offs

- Reference impl + integration tests filling the *Observed* column → **engineer**.
- Empirical RSS / latency under each variant at scale → **Curie** (instrumented isolation).
- Quantitative power analysis on which variants matter most → **Fisher**.
- Falsification tests for the 9 contract gaps once spec'd → **Popper**.
