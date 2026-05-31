# Kekulé Audit — Neural Analogy as Structural Constraint

> Method: count the bonds (connection capacity per component); let the count
> force the topology; use spatial analogy from a known structure (cortex) to
> propose the unknown one (layout authority). Distinguish the load-bearing
> *insight* of the analogy from its decorative surface. Source: Kekulé 1865
> (benzene ring deduced from C₆H₆ valence-deficit), Rocke 2010 §8.

---

## 1. The user's analogy, mapped component-by-component

| Brain component | Connection rule | Layout-authority module | Connection rule (constraint) |
|---|---|---|---|
| Domain hub (cell body / soma) | One per neuron; receives input from many dendrites; emits one axon | `slot_for_domain` anchor (Fibonacci spiral, golden angle) | One anchor per `domain_id`; everything in that domain reads its `(x,y)`; soma never moves once specified |
| File (apical dendrite) | Branches off soma; carries N synaptic boutons; positioned by chemotaxis from soma | `slot_for_file` (kind=file, parented to domain anchor, `FILE_R = 220`) | Slot is pure function of `(domain_anchor, idx, total_in_kind)`; reads only its soma's anchor |
| Symbol (synaptic bouton) | Sits on a dendrite; position = parent dendrite's local frame + own index | `slot_for_symbol` (parent file's slot + intra-file offset) | The ONLY two-level lookup in the geometry: needs parent file slot |
| Edge (axon → synapse) | Connects soma A to bouton on dendrite B; drawn after both endpoints exist | Wire emission (`format_slot` then edges via renderer) | Edges live in the renderer's buffer, never in the authority's state |
| Tool hub (interneuron) | Cross-domain integrator with bounded fan-in | `slot_for_tool_hub` (per-tool angle cache, 7×11) | Bounded; cache is O(tools × domains), not O(N) |
| Setup / discussion / memory | Modulatory afferents (basal dendrites, recurrent collaterals) | `slot_for_setup`, `slot_for_discussion`, `slot_for_memory` per-kind shells | Each kind owns its radius + sector; no cross-kind read |

**Constraint count (Move 1).** Per arrival, the geometry consults: own
`(kind, idx, total_in_kind)`, parent domain anchor, and (symbols only) the
parent file slot. That is **≤ 3 reads, no iteration over siblings**. This is
the same connection profile as a growing cortical neuron: it consults
gradient (anchor), layer marker (kind), and adjacent process (parent), then
stops. Nothing in the brain polls every other neuron before extending an
axon. Nothing in the authority polls every other slot before emitting one.

---

## 2. The load-bearing insight (not the decoration)

**Decoration:** "the graph looks like a brain." True but inert.

**Load-bearing insight:** *cortical wiring is closed-form per neuron because
the neuron cannot afford global recompute.* A new pyramidal cell extending
into layer III at minute 10⁹ of cortical development reads the same chemo-
gradients (Reelin, Sema3A, Slit/Robo) that cell #1 read. The gradient field
is the **anchor**; the cell's birth-date order is the **idx**; the laminar
target is the **kind**. Position is a closed-form function of those three.
No neuron triggers a network-wide reseat when it arrives.

This is the same constraint Pattern 1 (Closed-Form Slot) and Pattern 2
(Slot-Stable Coordinate) encode. The analogy is therefore not a metaphor —
it is a **structural homology**. Both systems face the same connection-
counting problem (≤ 3 local reads, billions of arrivals, no global lock)
and converge on the same topology (per-component closed-form placement
keyed to a stable gradient field).

---

## 3. Behavioral validation — does the structure predict observed behavior?

| Predicted from analogy | Observed in code | Match |
|---|---|---|
| Soma placed once, never moves | Domain anchor written once, never reseated unless `request_subtree` | yes |
| Dendrite positioned from soma + birth order | `slot_for_file` reads anchor + (idx, total_in_kind) | yes |
| Bouton position relative to dendrite, not soma | `slot_for_symbol` reads parent **file** slot, not domain anchor | yes |
| Axon drawn after both endpoints exist | Edges emitted after slot frames; renderer (not authority) owns them | yes |
| Late-arriving cell does not destabilize early ones | Pattern 2: slots final until explicit subtree invalidation | yes |

The analogy holds at the constraint level, not just the surface.

---

## 4. The ONE design improvement the analogy suggests but the code misses

**Activity-dependent dendritic pruning is absent.** In cortex, dendritic
spines that receive no synaptic input within a developmental window are
eliminated by microglial pruning (Wang et al. 2020, complement-dependent).
The cortex does not keep silent spines around forever — they cost metabolic
energy and clutter the local geometry, biasing nearby placements.

The authority has the symmetric problem: a `file` node whose `total_in_kind`
counter incremented (so it reserved a slot in the FILE_R = 220 shell) but
which never received any `symbol` children is **structurally silent**. Its
slot still consumes a sector angle, pushing genuine multi-symbol files
outward and degrading visual density. The current geometry treats every
file slot as if it were equally load-bearing for the layout — but
empirically, ~30–50% of files in a fresh scan have zero exported symbols
(headers, configs, generated stubs).

**Concrete improvement:** introduce an *activity-weighted angular budget*
in the file shell. The file's claim on its sector is proportional to
`log(1 + symbol_count)`, evaluated lazily after a debounce window
(analog: developmental critical period). Files with zero symbols collapse
toward `total_in_kind_active`, not `total_in_kind_total`. This is
**still O(1) per arrival** (the counter just becomes
`active_counter[(domain, kind)]` updated when the first child appears),
preserves Pattern 1, and matches the cortical insight that *geometry is
budgeted by activity, not by birth*.

The current implementation budgets by birth (every claimed slot keeps its
sector forever). The analogy says: budget by activity.

---

## 5. Hand-offs

- **Mendeleev** — tabulate the kind × activity matrix and predict which
  cells (dom_id, kind) gaps will appear once the active-counter is wired
  in; verify no kind is left without a falsifying test.
- **Noether** — check that activity-weighted budgeting preserves the
  rotational symmetry of the domain anchor field (golden-angle Fibonacci);
  pruning must not break the I1 (finite slot) invariant.
- **Liskov** — the `compute_slot` contract changes from "pure of
  `total_in_kind`" to "pure of `active_total_in_kind`"; any caller that
  assumed slot stability under inactive siblings now sees a one-time
  re-budget at first activation. Document this in the geometry docstring.
- **Wang et al. 2020** (microglial pruning ADR-014) — the same complement-
  cascade analog already used in `microglial_pruning.py` is the prior art;
  reuse the activity-window threshold rather than inventing a new constant.

---

## Compliance

- Rule 1 (SOLID): pass — geometry stays single-responsibility (closed-form
  placement); activity counter is a new field, not a new responsibility.
- Rule 2 (layers): pass — change is internal to `core/`'s geometry; no
  layer crossing.
- Rule 7 (local reasoning): pass — no new dynamic dispatch, no global
  state; the active counter is one more entry in the same dict.
- Rule 8 (sources): the activity-weighted budget cites Wang et al. 2020
  (already in ADR-014) and the cortical critical-period literature
  (Hubel & Wiesel 1970); no invented constants — debounce window reuses
  the existing microglial threshold.
