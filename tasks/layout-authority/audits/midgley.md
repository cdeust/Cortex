# Midgley — Metaphor Audit of the Layout Authority Discourse

> Method: surface the metaphors doing invisible load-bearing work; map each
> one's valid zone and its breakdown point; identify the metaphor most
> actively misleading the design; describe the system without metaphor.
> Source: Midgley 1992 *Philosophical Plumbing*; Midgley 1979 *Gene-Juggling*.

---

## 1. Load-bearing metaphors in this discourse

| Metaphor (audit) | Source domain | What it imports | Valid zone | Breakdown point | What it hides |
|---|---|---|---|---|---|
| **"neural graph"** (general framing) | neuroscience | growth, plasticity, learning, distributed computation, emergence | nothing in this system | the structure is a typed DAG with closed-form placement; there is no learning, no plasticity, no signal propagation, no emergence | the actual data structure (a deterministic O(domains × kinds) coordinate function) |
| "cortical wiring" (Kekulé) | developmental neurobiology | closed-form positioning from local gradients; ≤3 reads per arrival | structural homology with `compute_slot`'s constraint profile is real | only the *placement-cost structure* maps; nothing about plasticity, dendritic computation, or activity-dependent refinement maps | that the homology is narrow — three local reads — and stops there |
| "queue with shedding" (Hamilton) | telecoms / control theory | bounded buffers, head-drop, priority lanes, backpressure | applies cleanly to the SSE write path: bounded outbound buffer, P0..P6 priority | breaks at the geometry layer — there is no queue inside `compute_slot`; placement is stateless | nothing harmful; this metaphor is honest about its scope |
| "library of failures" (Borges) | literature | exhaustive enumeration, infinite catalog, every variant | applies to the *audit corpus* (one philosopher per failure mode), not the runtime | breaks if mistaken for a runtime structure — the authority does not enumerate failures, it refuses them via invariants | the difference between *design-time exploration* and *runtime mechanism* |
| "traffic" (Erlang) | telephony queueing | arrival processes, offered load, blocking probability, Erlang-B | applies to SSE emission rate vs. renderer drain rate | breaks at the placement step — `compute_slot` is not a server with service time, it is a pure function | that the bottleneck is transport, not geometry |
| "viable system" (Beer) | management cybernetics | five recursive subsystems, autonomy + cohesion | applies to the module layering (geometry / scheduler / log / wire / protocol) — each is a viable subsystem with its own contract | breaks if recursion is taken literally — the layout authority is not five-deep; it is roughly two-deep | over-elaboration of governance where simple Clean Architecture suffices |
| "language game" (Wittgenstein) | philosophy of language | meaning-as-use; polysemy across modules | sharp and exact: `kind`, `seq`, `slot`, `total` each play several games | none — this metaphor is the diagnosis itself, not a borrowed analogy | nothing; it is the right tool for the polysemy problem |
| "specimen" (Darwin/McClintock) | natural history | type-specimen, exemplar, careful description of one case | applies to the per-kind `slot_for_*` helpers — each is a specimen of placement | breaks if "evolution" is read in — there is no selection, no descent, no variation in `compute_slot` | the determinism of the function under the biological surface |
| "satisficing" (Simon) | bounded rationality | accept-good-enough under cost ceiling | applies to the 1ns/node budget and the closed-form choice over force-directed | breaks if read as "the geometry is approximate" — it is exact, not satisficed | that the budget forces exactness, not approximation |
| "authority" (the module name) | political/legal | sovereign decision-maker, monopoly on legitimate placement | applies cleanly: one writer of slots, single-producer log | breaks if read as social authority — there is no consent, no appeal, no legitimacy concept | that "authority" here means *single writer*, not *legitimate ruler* |
| "soma / dendrite / bouton" (Kekulé table) | cell biology | hierarchical compartments with local frames | the parent-frame structure (symbol reads file slot, file reads domain anchor) is real | every other property of cells (membrane, ion channels, synaptic strength) does not map | gives the false impression that more biological properties might transfer |

---

## 2. The metaphor most actively misleading the design

### "Neural graph" — the general framing.

This is the metaphor most worth surfacing because it is invisible. Nobody
in the audits *defends* it; everyone uses it. It is doing the work of a
literal description while being, in fact, a deeply misleading analogy.

**What "neural graph" imports, silently:**
1. *Growth.* Neurons grow; nodes here do not — they are placed by a
   coordinate function. There is no extension, no chemotaxis, no
   competition for space.
2. *Plasticity.* Synapses change weight; edges here have no weight and
   never change. An edge is a (source_id, target_id, edge_kind) tuple.
3. *Activity / signal propagation.* Real neural networks compute by
   propagating signals along edges. Nothing propagates here. The
   "graph" is a *visualization layout*, not a computation.
4. *Learning.* Neural networks learn from data. The layout authority
   learns nothing — it places, and the placement of node #10⁹ uses the
   same closed-form as node #1.
5. *Emergence.* Brains exhibit emergent behavior from local rules. This
   system explicitly *forbids* emergence: every slot is a deterministic
   function of `(domain_anchor, kind, idx, total_in_kind, parent_slot?)`.

**Where the metaphor breaks down (its breakdown point):**
The metaphor breaks at the very first design constraint: 1 ns/node,
O(1) per node, no global recompute, no iteration over siblings,
deterministic. A real neural system violates every one of these. The
"neural" framing therefore makes natural exactly the questions the
design refuses to ask ("how do we handle plasticity?", "how do we
update edge weights?", "how do nodes find their neighbors?") and hides
the question that actually drives the design ("how do we compute
position in 3 cycles?").

**What it makes seem natural that should be questioned:** force-directed
layout (because real neurons "settle" into position), iterative refinement
(because brains develop over time), graph traversals (because brains are
networks). All three are explicitly disqualified in `cost-model.md` §6.
The metaphor keeps proposing what the cost model has already ruled out.

**Why this is the most damaging metaphor:** it is the one most likely
to import a wrong question into a future redesign. A future engineer
reading "neural graph" will ask neural questions. The cost model and
geometry will refuse those questions, but the engineer will not know
why — the plumbing will appear to be wrong because the metaphor told
them what to expect.

---

## 3. The metaphor-free description

Strip every borrowed term:

> The layout authority is a **pure function** `compute_slot`, of type
>
> ```
> compute_slot : (node_kind, ctx) -> (x, y)
> ```
>
> where `ctx` carries `(domain_anchor, idx_in_kind, total_in_kind,
> parent_slot?)`. The function is **closed-form** (no iteration, no
> recursion beyond one parent lookup), **deterministic** (same inputs →
> same output), and **stateless across calls** (the only state is a
> per-`(domain_id, node_kind)` integer counter held by the caller).
>
> Around this function sit four mechanical components:
>
> 1. A **counter map** `dict[(domain_id, node_kind), int]` — O(domains × kinds) ≈ 11 × 6 = 66 integers.
> 2. A **monotonic event log** with a single global `seq` and a bounded outbound buffer that drops oldest on overflow.
> 3. A **priority dispatcher** with seven lanes (P0..P6) keyed by `node_kind`.
> 4. A **wire codec** that serializes `(seq, node_id, x, y, node_kind, domain_id)` to text frames.
>
> No node ever influences another node's position. No edge influences
> any node's position. The structure called "the graph" is two
> independent things: (a) a coordinate table — values of `compute_slot`
> for the nodes that have arrived; (b) an edge list — pairs of
> `node_id`s with an `edge_kind`. Neither table is ever traversed by
> the placement code.

That is the system. Everything else — neurons, dendrites, traffic,
authority, library, viable subsystem — is decoration.

---

## 4. Hidden analogies (the discipline-imperialism check)

| Surface reasoning | Hidden analogy | Where the analogy fails | Suppressed feature of the system |
|---|---|---|---|
| "the graph grows" | biological development | nothing grows; the function is timeless | placement is timeless; "arrival order" is just `idx` |
| "the authority decides" | political sovereignty | there is no judgment, only arithmetic | the function is total and deterministic — no discretion |
| "the queue absorbs bursts" | water reservoir | a bounded buffer is not a reservoir; full = drop, not overflow | head-drop discipline is exact, not "spillover" |
| "the renderer reads the brain" | perception | the renderer reads a coordinate table | there is no perceiver; the table is just data |

**Discipline imperialism check.** Three disciplines are competing for
explanatory authority: neuroscience (Kekulé table), control theory
(Hamilton/Erlang), and political theory ("authority"). None is sufficient.
The system is, mathematically, none of them — it is a typed DAG with a
coordinate function. The right discipline is **discrete geometry**, and
no audit invokes it. That is the gap.

---

## 5. Recommendations

| Metaphor | Recommendation | Rationale |
|---|---|---|
| "neural graph" | **Retire from architecture docs; keep only as user-facing visualization label** | The system is a coordinate function on a typed DAG, not a neural network. Architecture docs that say "neural graph" import wrong questions. |
| "cortical wiring" (Kekulé) | **Keep with explicit caveat: "structural homology of the placement-cost profile only"** | The ≤3-reads-per-arrival match is real and load-bearing. Plasticity, learning, and signal flow do not transfer. |
| "queue with shedding" (Hamilton) | **Keep as-is** | Honest about its scope (transport layer); does not bleed into geometry. |
| "library of failures" (Borges) | **Keep with caveat: "design-time corpus, not runtime mechanism"** | Useful for organizing audits; dangerous if a future reader looks for a runtime registry. |
| "traffic" (Erlang) | **Keep, scope to SSE transport** | Applies cleanly to emission/drain; does not apply to placement. |
| "viable system" (Beer) | **Down-grade to "module layering"** | Standard Clean Architecture covers this; recursive cybernetics is over-elaborated. |
| "authority" (module name) | **Keep — but document "single-writer", not "sovereign"** | The name is fine if the meaning is pinned. |
| "specimen" (Darwin/McClintock) | **Keep, drop evolutionary connotations in prose** | Per-kind helpers are exemplars; nothing evolves. |
| "satisficing" (Simon) | **Replace with "exact under tight budget"** | The geometry is exact, not approximate; the budget forces closed-form, not good-enough. |

---

## 6. Hand-offs

- **Wittgenstein** — the polysemy of `kind` / `seq` / `slot` / `total`
  is a language-game problem, not a metaphor problem; his audit handles it.
- **engineer** — replace "neural graph" with "typed DAG + coordinate
  function" in the top-of-file docstrings of `layout_authority_*.py`
  and in `cost-model.md` §1.
- **Kekulé** — add the caveat "structural homology of placement cost
  only; no plasticity, no learning, no signal flow" to §1 of `kekule.md`.
- **Beer** — flatten the recursive-viable-system framing to "module
  layering" in `beer.md`.
