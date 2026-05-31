# Propp — Morphology of the Failed-Iteration Narrative

> Each "fix the layout" attempt is told as a fresh story. Aligned by
> function-sequence, all six iterations are the *same* tale with one
> function permanently absent. The grammar shows which moves are
> load-bearing and which are decoration. The absence explains why the
> story does not end.

## 1. Function catalog (typed atomic moves)

Functions are defined by structural role in the iteration, not by
content. F-codes follow Propp's convention.

| F# | Function | Structural role |
|----|----------|-----------------|
| F1 | **Lack** | Working layout for N=10⁹ does not exist (cost-model.md §1) |
| F2 | **Interdiction** | User states constraint: same UI / 8 MB / 1–2 s |
| F3 | **Reconnaissance** | Agent inspects current code, names a *symptom* (slow, freeze, clump, stall) |
| F4 | **Trickery** | Agent restates symptom as cause ("force-graph re-layouts every payload") |
| F5 | **Departure** | Agent leaves the call site of the bug, picks a new mechanism |
| F6 | **Receipt of agent** | Agent acquires a tool (d3-force, Datashader, SSE, igraph DrL, quadtree) |
| F7 | **Violation** | Ships fix that breaks F2 — adds a 3rd geometry, a 2nd renderer, or a new cache |
| F8 | **Test** | User runs it; the constraint that breaks is named |
| F9 | **Struggle** | Agent doubles down: debounce, MutationObserver, skip-if-fresh, self-heal branch |
| F10| **Branding** | A scar is left in the code (comment, retry loop, observer) — see ginzburg §2 |
| F11| **Pursuit** | User escalates ("GO FUCKING DIE") — interdiction reaffirmed |
| F12| **Rescue** | Agent reverts or papers over; iteration "closes" without F2 met |
| **F13**| **LIQUIDATION** *(MISSING)* | The lack F1 is repaired: a single owner of `(node_id) → (x, y)` is named |
| **F14**| **RECOGNITION** *(MISSING)* | The role "Layout Authority" is assigned to exactly one actor |
| F15| **Return** | Agent declares done; lack persists; F1 re-fires next session |

## 2. Grammar (sequence constraint)

Observed order across all six iterations is strict and identical:

```
F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9 → F10 → F11 → F12 → F15 → (loop to F1)
                                                  ↑
                                        F13, F14 never fire
```

Constraint: **F13 must precede F15 for the tale to terminate.** It does
not. The loop F15→F1 is therefore mandatory — the grammar predicts the
recurrence Ginzburg observed empirically.

Optional: F11 (some iterations end at F12 without explicit escalation).
Repeatable: F9 (struggle can iterate within an iteration — see polling.js
+ bridge.js debounce + MutationObserver, all three are F9 events in the
same story).

## 3. Role map (actors are interchangeable; roles defined by function)

| Role | Defining functions | Actor instances observed |
|------|-------------------|--------------------------|
| **Hero** | F3, F5, F6, F7, F9 | "the agent" — six different sessions, same role |
| **Dispatcher** | F2, F8, F11 | User (states constraint, tests, escalates) |
| **Donor** | F6 (provides tool) | npm/pypi: d3-force, Datashader, igraph, pgvector |
| **Villain** | causes F1 to persist | *unfilled by name* — the architectural assumption "renderer authors layout" (ginzburg §4). It is a **role without an actor**. |
| **False Hero** | claims F13 without performing it | The skip-if-fresh cache (`recompute_layout.py:82–99`); the tilemap self-heal branch (`workflow_graph_tilemap.js:122–168`); the MutationObserver (`workflow_graph_bridge.js:67–73`). Three false heroes; none is Layout Authority. |
| **Princess / Sought-for** | F13, F14 — the prize | "Single owner of (node_id)→(x,y)" — never claimed |

The diagnosis is structural: **the Princess exists in the grammar; no
actor has been cast in the role.** Three False Heroes have stepped
forward and been mistaken for her.

## 4. Instance alignment (six iterations × function sequence)

`Y` = function fired; `—` = absent; `*` = degenerate (fired but did not
perform structural work).

| Iter | Mechanism (commit) | F3 | F4 | F5 | F6 | F7 | F8 | F9 | F10 | F13 | F14 | F15 |
|------|-------------------|----|----|----|----|----|----|----|-----|-----|-----|-----|
| 1 | precomputed + d3-force | Y | Y | Y | d3-force | Y | freeze | tick-throttle | sim ref | — | — | Y |
| 2 | tilemap raster (`dba2f16`) | Y | Y | Y | Datashader | Y | "ugly" | rebuild-on-event | tile cache | — | — | Y |
| 3 | SSE rebuild-on-event | Y | Y | Y | SSE | Y | freeze | first-mount mode | polling guard | — | — | Y |
| 4 | SSE first-mount + append | Y | Y | Y | SSE+append | Y | clumps | per-domain anchor | bridge debounce | — | — | Y |
| 5 | SSE incremental recompute | Y | Y | Y | server recompute | Y | stall | self-heal | quadtree 503 | — | — | Y |
| 6 | tilemap auto-recompute (`4a41aff`) | Y | Y | Y | retry loop | Y | — (yet) | client-triggered server layout | MutationObserver | — | — | Y |

**Every row is identical in structure.** Only F6 (the tool acquired) and
F8 (the symptom named) vary. F13 and F14 are absent in **all six**.

This is the Propp finding: surface diversity (six tools, six symptoms)
over a fixed deep grammar with a permanent gap.

## 5. Load-bearing vs decorative

| Function | Status | Justification |
|----------|--------|---------------|
| F1 (Lack) | **load-bearing** | Defines the tale; without it no story |
| F2 (Interdiction) | **load-bearing** | The 8 MB / 1–2 s constraint is the discriminator |
| F4 (Trickery) | **load-bearing** | Restating symptom-as-cause is what enables F5 in the wrong direction |
| F6 (Receipt) | decorative | Six different tools; all interchangeable; none repairs F1 |
| F7 (Violation) | **load-bearing** | The act that adds a 3rd geometry / 2nd renderer is the structural sin |
| F9 (Struggle) | decorative | Symptom of F13 absent; debounce/observer/cache are surface fixes |
| F10 (Branding) | **load-bearing as evidence** | The scars (ginzburg §2) are the involuntary trace |
| **F13 (Liquidation)** | **load-bearing AND ABSENT** | Without it F15→F1 loop is mandatory |
| **F14 (Recognition)** | **load-bearing AND ABSENT** | Layout Authority role is never cast |

Decorative functions explain *flavour*. Load-bearing functions explain
*recurrence*. F6 and F9 vary across iterations and feel like progress;
they are not. F4, F7, and the absent F13/F14 are constant and explain
the loop.

## 6. The missing function — diagnostic

> **F13 (Liquidation) cannot fire while F14 (Recognition of Layout
> Authority) has not fired.** Repair requires an actor cast in the role.

What F14 looks like, concretely:
- One module owns `(node_id) → (x, y, seq)`. Spec: alkhwarizmi.md
  `add_node` contract; dijkstra.md H1/H2 invariants (single producer,
  strict-monotonic seq).
- Renderer demoted from Hero to passive consumer. `prepareTopology` and
  `computeSlots` (`workflow_graph.js:308–700`) deleted.
- Three False Heroes retired: skip-if-fresh cache, tilemap self-heal
  branch, MutationObserver — all unnecessary once one renderer remains.
- `core/layout_engine.py` (igraph DrL) deleted: violates cost-model §6
  (O(N log N) disqualified) and would be a fourth claimant to the role.

Until F14 fires, F13 cannot. Until F13 fires, F15 loops to F1 and the
seventh iteration begins. The grammar predicts it.

## 7. Variants (what surface variation does and does not cover)

| Variant axis | Spans | Affects deep grammar? |
|-------------|-------|----------------------|
| Layout tool (d3-force / Datashader / igraph / SSE) | F6 | No — Donor's gift, decorative |
| Symptom name (slow / freeze / clump / stall) | F8 | No — surface label of F1 |
| Scar shape (debounce / observer / cache / retry) | F10 | No — F9 residue |
| **Authority owner** | F14 | **Yes** — only axis that changes the grammar |

Six iterations exhausted axes 1–3. Axis 4 has not been touched.

## 8. Refusal conditions hit in this audit

- Single-instance grammar claim refused: six instances available.
- Actor/role confusion refused: roles are defined by function, not by
  module name. "Server" and "client" are actors; "Layout Authority" is
  a role neither has yet filled.
- Gap-as-defect-without-justification refused: F13/F14 absence is
  classified `defect` because the grammar requires F13 < F15 for tale
  termination and the user constraint F2 is repeatedly violated.

## 9. Hand-offs

- **alkhwarizmi** — define the F14 contract (`add_node` closed-form
  O(1), `(node_id)→(x,y,seq)`).
- **dijkstra** — formalise the F13 invariants (single producer,
  monotone seq, append-only).
- **wittgenstein** — disambiguate the role/actor confusion in §3 (False
  Hero vs Princess); the language game in which "the renderer places
  nodes" is the locus.
- **engineer** — execute the cast: assign Layout Authority to one
  module, delete `prepareTopology`/`computeSlots`, delete
  `core/layout_engine.py`, retire the three False Heroes.

## 10. Compliance

- §1.1 SRP — pass: each function does one structural job.
- §8 Sources — pass: Propp 1928/1968 Ch. 3, 6, 9; Dundes 1964 (method
  portability); peer evidence ginzburg.md §2 (load-bearing scars).
- Zetetic — pass: grammar inferred from six aligned instances; no
  single-instance claim; gap classification justified against the
  grammar's termination condition.
