# Feinstein/Sackett Differential — Layout-Authority Iterations

**Method.** Each of today's 10 iterations is treated as a clinical
presentation. For each: ranked differential, discriminating sign, test
that would have decided. Meta-analysis at the end identifies the
candidate the team kept off the differential entirely until the very
end: **"missing integrator — no component calls `add_node`."**

I1–I6 are explicit corpus events (kahneman.md ledger, git log). I7–I10
are intermediate cycles implied by feynman.md / popper.md (geometry
tweaks, contract patches, queue-cap fixes, end-to-end blank UI) that
landed without distinct commits. **Dx** = differential. **LR+** ≈
likelihood ratio for the leading candidate given the discriminating
sign. Priors sum to ~1.

---

## I1 — d3-force on full graph. CC: stalls at ~5k nodes.

| # | Candidate | Prior |
|---|---|---|
| 1 | Wrong family: O(N log N)/tick × hundreds of ticks | 60% |
| 2 | Force params (alpha, link strength) mistuned | 25% |
| 3 | DOM/SVG render bottleneck, not the sim | 10% |
| * | **Must-not-miss**: target N is 6 OOM beyond family's regime | 5% |

**Sign:** `T_per_node = T/N = 1 ns` at design target — any per-tick iteration consumes >>1 ns/node. **Test:** one division on day 0. **LR+ ≈ 50.** Threshold crossed by arithmetic alone.

## I2 — `prepareTopology` per phase. CC: seconds per recompute at 50k.

| # | Candidate | Prior |
|---|---|---|
| 1 | O(N+E) recompute called per event | 70% |
| 2 | E grows superlinearly | 15% |
| 3 | Phase detection itself slow | 10% |
| * | Insert #N costs more than insert #1 (cost-model invariant 2) | 5% |

**Sign:** wall-clock grows monotone in N per insert. **Test:** time at N=10⁴ vs 10⁵. **LR+ ≈ 20.**

## I3 — force-graph + spatial index rebuild. CC: insert spikes per batch.

| # | Candidate | Prior |
|---|---|---|
| 1 | Quadtree rebuilt on insert (O(N log N) construction) | 65% |
| 2 | GC pauses from index churn | 20% |
| 3 | Render contention | 10% |
| * | Same family as I1–I2 with new wrapper (anchoring) | 5% |

**Sign:** insert-cost ∝ N log N. **Test:** log-log slope across three N. **LR+ ≈ 15.**

## I4 — Datashader pivot (`dba2f16`). CC: can't render 10⁶ nodes.

| # | Candidate | Prior |
|---|---|---|
| 1 | **Substitution**: solving rendering when bottleneck is placement | 50% |
| 2 | Genuine render bottleneck post-placement | 30% |
| 3 | Identity loss (no per-node pickability) acceptable | 15% |
| * | Pixel pipeline does not answer "where does node #10⁹ go?" | 5% |

**Sign:** can the system return `(x,y)` of `file:abc` after the pivot? **No.** **Test:** identity round-trip at N=10⁵. **LR+ ≈ 8.**

## I5 — Six `layout_authority_*.py` modules. CC: tests pass; system doesn't run.

| # | Candidate | Prior |
|---|---|---|
| 1 | **Missing integrator** — `layout_authority.py` absent; nothing calls `add_node` | 55% |
| 2 | Wire/protocol field mismatch (`slot.id` vs `node_id`) | 20% |
| 3 | idx/total counters orphaned across modules | 15% |
| 4 | Tests cover modules-in-isolation, not composition | 10% |

**Sign:** `grep -r build_authority mcp_server/` returns only the protocol declaration. **Test:** `import layout_authority` → `ModuleNotFoundError`. **LR+ ≈ 100.** *This is the iteration where "missing integrator" should have entered the differential. It did not.*

## I6 — Tilemap auto-recover (`4a41aff`). CC: `/api/quadtree` returns `no_layout`.

| # | Candidate | Prior |
|---|---|---|
| 1 | Frontend doesn't retry on transient not-ready | 55% |
| 2 | **Layout was never produced** — `compute_slot` never called | 30% |
| 3 | Race: query landed before build completed | 10% |
| 4 | Endpoint contract: should be 404 not `no_layout` | 5% |

**Sign:** does `/api/quadtree` *ever* succeed for this graph? **Test:** poll 60s; if always `no_layout`, retry shim cannot help. **LR+ for #2 ≈ 30.** Patch shipped on hypothesis #1; root cause was #2.

## I7 — Geometry parameter retuning. CC: nodes overlap / cluster wrong.

| # | Candidate | Prior |
|---|---|---|
| 1 | Constants drifted from `workflow_graph.js` reference port | 40% |
| 2 | Domain anchor placeholder (I7 invariant: no retroactive reseat) | 35% |
| 3 | `hub_angle` undefined when `parent_id=None` (silent fallback) | 15% |
| * | Tuning is moot if integrator never calls `compute_slot` | 10% |

**Sign:** golden-image diff vs JS reference on identical input. **LR+ ≈ 10.**

## I8 — Wire field-name fix. CC: `AttributeError` at the wire boundary.

| # | Candidate | Prior |
|---|---|---|
| 1 | Wire reads `slot.id`; protocol exposes `node_id` (popper.md §1) | 70% |
| 2 | Two parallel slot dataclasses drifted — no canonical owner | 20% |
| 3 | Serialization library version drift | 10% |

**Sign:** `format_slot(SlotAssignment(...))` raises. **Test:** unit test against the protocol dataclass directly. **LR+ ≈ 30.** Underlying: nobody owns the canonical schema — because no integrator owns anything.

## I9 — Scheduler queue-cap drops. CC: some nodes never appear.

| # | Candidate | Prior |
|---|---|---|
| 1 | P2 queue (cap 16k) full; submit returns False; bool ignored | 50% |
| 2 | Strict-priority starvation of P2 by P0/P1 | 25% |
| 3 | idx/total drift → silent geometry placeholder | 15% |
| * | Caller-ignores-bool **is** the integrator's job | 10% |

**Sign:** `_stats.dropped[2] > 0` with no log. **Test:** instrument; assert `dropped[2]==0` for <16k workload. **LR+ ≈ 25.**

## I10 — End-to-end "passes" but UI blank. CC: green build, empty quadtree, blank tiles.

| # | Candidate | Prior |
|---|---|---|
| 1 | **No integrator → no `add_node` call → no slots → empty quadtree** | 75% |
| 2 | Slots written to wrong store / schema mismatch | 10% |
| 3 | Tilemap stale cache | 8% |
| 4 | Auth/route on `/api/quadtree` | 7% |

**Sign:** `SELECT count(*) FROM layout_slots` = 0 after green build. **Test:** one DB query post-build. **LR+ ≈ 50.** Threshold crossed without further investigation; all roads lead back to building the integrator.

---

## Meta-analysis — the candidate the team kept missing

> **"There is no component that calls `add_node`. The placement pipeline is not slow; it does not exist."**

| Iter | Implicit #1 hypothesis | "Missing integrator" position |
|---|---|---|
| I1 | wrong force params | not on list |
| I2 | recompute too slow | not on list |
| I3 | spatial index too slow | not on list |
| I4 | renderer too slow | not on list |
| I5 | modules not yet wired (vague) | adjacent, unnamed |
| I6 | frontend retry missing | not on list |
| I7 | geometry constants wrong | not on list |
| I8 | schema drift | adjacent (no canonical owner) |
| I9 | queue too small | adjacent (caller behavior unowned) |
| I10 | tile cache stale | forced onto list by zero-row evidence |

### Five biases (Sackett/Kassirer) that produced the blind spot

1. **Anchoring** — "graph viz" frame anchored every iteration on *replacing or tuning a placement library*. The hypothesis "no placement library is being called at all" was never generated.
2. **Premature closure** — each cycle found a plausible local cause and stopped before exhausting the differential.
3. **Availability** — the most recent visible failure (`no_layout`, `AttributeError`, blank tile) dominated each cycle.
4. **Base-rate neglect** — mid-refactor, "required component renamed/split and caller never rebuilt" is the single most common defect class; its prior should have been ≥30% on every cycle, was implicitly 0%.
5. **Confirmation** — green per-module unit tests were read as system-works evidence. No test exercised composition (popper.md §"Notable findings" #2).

### Treatment threshold — when to have acted

By **I5** at latest. Discriminating test (`grep -r build_authority mcp_server/`) takes 200 ms. LR+ ≈ 100 — the module's absence is deterministic, not probabilistic. False-positive cost (~1 engineer-day building the integrator) << false-negative cost (the five subsequent failed iterations actually observed). Threshold crossed by inspection. The team did not act because the hypothesis was not on the differential.

### Evidence grading on shipped symptom-fixes

| Commit | Claim | Level | Required (Sackett) |
|---|---|---|---|
| `dba2f16` | "renderer is the bottleneck" | 6 (expert opinion) | 3 (cohort: place-vs-render time at three N) |
| `54f443d` | "this is the right control flow" | 6 | 2–3 (controlled: slot writes precede tile reads) |
| `4a41aff` | "transient `no_layout` is recoverable" | 6 | 4 (case-control: does endpoint *ever* succeed?) |

All three shipped on Level-6 evidence. None would have shipped under the hierarchy if the missing-integrator hypothesis had been formally listed and tested.

### Process gates that would have caught I1–I10

| Bias | Gate |
|---|---|
| Anchoring | Each iteration: ≥3 differential candidates **including one "missing component"** candidate. |
| Premature closure | Patch PR cannot land while ≥1 differential candidate remains untested. |
| Availability | 5-Whys in PR description (kahneman.md §3). |
| Base-rate neglect | During refactor: assume P(missing caller) ≥ 0.3 on every defect. |
| Confirmation | Every module-test PR must add one composition test exercising ≥2 modules via the public API. |

## Hand-offs

- **Build the integrator** (`mcp_server/server/layout_authority.py`: composes six modules, owns counters, calls `compute_slot`, handles `submit` drops) → engineer.
- **Composition test** that fails red until integrator exists → popper / engineer.
- **PR-template gates** (5-Whys, ≥3 candidates incl. "missing component") → adopt from kahneman.md §3.
- **Cost-model row** for "missing-component" defect class so future cycles include it by default → cost-model.md §6.
