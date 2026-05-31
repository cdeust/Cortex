# Braudel — Three-Timescale Audit of the Layout Authority

**Method.** Braudel 1949/1958. Decompose into **longue durée** (structure,
slow), **conjoncture** (cycle, medium), **événement** (event, fast).
Structure ≫ cycle ≫ event. Single-cause explanations of multi-timescale
phenomena are rejected.

**Session pathology this audit names.** Événement bugs were repeatedly
read as conjoncture failures. A field-name typo (événement) bricked every
render and was diagnosed as "the build doesn't render" (conjoncture).
Three timescales kept collapsing into one. The governors below stay
separated.

---

## 1. The decomposition

| Scale | Period | What changes | What is invariant |
|---|---|---|---|
| **Longue durée** | months | kinds taxonomy; closed-form geometry; wire shape; L0→L6 stratigraphy; P0–P4 priority ladder | a single build run; a single add_node |
| **Conjoncture** | min–hours | which domain is being swept; queue depths; throttle state; phase order; per-(domain,kind) counters | geometry constants; protocol field set; kind taxonomy |
| **Événement** | µs | one delta's `(kind, idx, total_in_kind)`; one slot's `(x, y)`; one SSE frame | counters across this call; queue depths; geometry; everything else |

Hierarchy of explanation: structure ≫ cycle ≫ event. A bad slot at µs is
overwhelmingly explained by geometry constants and kind taxonomy (longue
durée), then by which phase is sweeping (conjoncture), and only
marginally by the specific node (événement).

---

## 2. Longue durée — structures that outlive every session

Change on timescale of months. The *geography*; everything else flows
along its channels.

1. **Closed-form geometry.** Fibonacci-spiral anchors (φ = π(3 − √5));
   shells `SETUP_R=70, TOOL_R=140, FILE_R=220, DISC_R=150, MEM_R=150`;
   sectors `π/2.6, π/6.5`. Source `workflow_graph.js:308–700` →
   `layout_authority_geometry.py` (cost-model §4). Bedrock.
2. **Stratigraphy L0→L6.** Origin → setup → tool-hubs → files →
   discussions → memories → symbols (`layout_authority_geometry.py`
   93–169). The stratigraphy *is* the kind taxonomy ordered by radius.
3. **Priority ladder P0–P4** (`layout_authority_scheduler.py` 15–23).
   Defines what the system *can* show under load.
4. **Wire / protocol.** `NodeDelta` field set, SSE contract,
   `(domain_id, kind, idx, total_in_kind)` invariant
   (`layout_authority_protocol.py`, `_wire.py`). The 2026-04-28 typo was
   événement *only because* the protocol is a structural contract.
   **The structure made the typo dangerous; the typo did not make the
   structure.**
5. **Per-node O(1).** Slot = pure function of
   `(domain_anchor, kind, idx, total_in_kind)` (cost-model §2). Any
   sibling iteration kills the 10⁹-in-2 s budget; no event-fix recovers.

**Metrics:** protocol-stability ratio; geometry-constant edit distance
per quarter; layer-import violations; structural-ADR : event-patch ratio.

**Anti-metric:** per-call latency (that is événement; reading structure
through latency mistakes foam for current).

**Failure if confused with shorter scales:** "make it faster" lives at
conjoncture (batching) or événement (numpy). Mutating geometry to chase
speed destroys the property tuned over months.

---

## 3. Conjoncture — one L0→L6 sweep (minutes to hours)

A single sweep produces a stream of slots, climbs the stratigraphy in
priority order, then settles.

**What changes:** per-`(domain, kind)` counter (cost-model §2); queue
depths per priority; throttle state (engaged at 0.8, released after 3
polls below 0.6 — maxwell.md §3–§4); current phase; `is_overloaded`
sensor; drop-rate vs. retry-rate; domain-anchor cache warm-up.

**What is invariant:** all longue-durée items §2.1–§2.5. Geometry,
taxonomy, protocol — all frozen across batches.

**Meaningful metrics:**

- `μ` (drain rate, ~200k items/s, `bench_layout_authority.py`);
- `λ` (producer rate, ~500k/s on aggressive build);
- queue residency time per priority;
- phase completion order (did P4 ever emit, or was it shed?);
- `k_retry` — per drop, how many re-emits follow (Maxwell
  positive-feedback constant).

**Anti-metric:** "did this single node land in the right place?" — that
is événement. A cycle is judged by *shape of the produced slot stream*.

**Failure if confused with shorter scale:** treating a stuck build as
"this delta was bad." Session example exact: a typo at événement-scale
presented as conjoncture failure ("nothing renders"); the diagnosis
chased the cycle (rerun, clear queue, restart worker) instead of the
event (one wrong field name). Conjoncture metrics — queue depth,
throttle, drain — *looked fine.* The cycle was not the problem.

**Failure if confused with longer scale:** treating transient overload
as structural defect. A P4 backlog from a slow phase does not mean the
priority ladder is wrong. Maxwell §5 was built to damp the cycle without
touching structure.

---

## 4. Événement — one `add_node` call (microseconds)

One delta passes through validation → scheduler `submit()` → queue →
`pop()` → geometry `compute_slot()` → slot write → SSE frame. ~10–300 µs.

**What changes:** one row of state (`counters[(dom_id, kind)] += 1`);
one queue push and pop; one `(x, y)` written; one SSE frame; one log
line.

**What is invariant:** geometry constants; protocol fields; kind
taxonomy; priority ladder; domain-anchor cache; queue depths; μ, λ.

**Meaningful metrics:**

- per-call latency (~180–300 ns pure Python; target ~10 ns via numpy/SSE,
  cost-model §5);
- protocol conformance (every `NodeDelta` field validates);
- post-condition: is `(x, y)` inside the predicted bucket geometry;
- correctness of `(kind, idx, total_in_kind)` at this call.

**Anti-metric:** queue depth, drain rate, drop count. Those describe the
*cycle the event lives in*, not the event itself.

**Failure if confused with longer scales — the session pathology.** A
typo in a `NodeDelta` field is événement. It manifests as
protocol-conformance failure on *every* call — a structural-looking
symptom (every event fails identically), which mimics conjoncture
failure (the cycle never produces output). The shape of the failure
tempts the diagnostician to climb the ladder. **Braudel's rule:
identical-failure-on-every-event is the signature of an event-class
bug, not a structural one.** If the geometry were wrong, *some* events
would land correctly (those in the still-valid region); 100 % failure
is an événement bug with structural blast radius.

---

## 5. The session diagnosis — what went wrong

**Symptom.** Build doesn't render. Hours at conjoncture: "queue wrong /
worker stuck / SSE backed up." Reality: a typo at événement, amplified
by the structural fact that every event uses the same protocol.

**Braudel violation.** Visibility (every render broken, dramatic) read
as depth (must be structural). Vivid symptoms often have shallow
causes. The structure was *amplifier*, not cause; the cause was one
character.

**Triage rule:**
- **100 % identical failure →** événement first (typo / wrong field).
- **Some pass, some fail →** conjoncture (load, ordering, race).
- **Correct slots, wrong shape →** longue durée (geometry, taxonomy).

---

## 6. Hand-offs and refusals

- **Maxwell** — conjoncture stability (speed-controller, shedding,
  deadband).
- **Hamilton** — longue-durée priority ladder; what gets shed *is* what
  the system is.
- **Curie** — *separate* dashboards per scale: (a) protocol-conformance
  per event, (b) μ / λ / k_retry / queue depth per cycle,
  (c) geometry drift / layer violations / ADR rate per quarter. One
  panel per scale; never mix.
- **Erlang** — re-derive M/M/1 utilisation at conjoncture using μ from
  `bench_layout_authority.py`; don't let event-scale latencies leak
  into the cycle model.

**Refusals:**

- Refuse fixes that touch geometry constants on événement/conjoncture
  symptoms — require shape-of-output evidence.
- Refuse postmortems naming a single cause for failures with
  multi-scale evidence — require one row per timescale.
- Refuse "the build is slow." Require: at which scale?
