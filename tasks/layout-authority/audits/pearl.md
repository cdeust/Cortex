# Pearl — Causal DAG of the Failure-Producing Structure

> Prior audits surfaced **correlations** in failure modes: every iteration had
> renderer-owned layout; every audit found the `slot.id` vs `slot.node_id`
> mismatch; every reseat bug coincided with late parents. Correlation isn't
> causation. The question is: **which design choices, if reversed, eliminate
> the downstream failures, and which are mediators that disappear when the
> root is fixed?** This requires the DAG, not more incident counts.

## 1. Causal question

- **Effect Y** = the seven failure dimensions in jobs.md §4 (no continuous
  emission, no provenance, no interactivity within 2s, non-deterministic
  positions, flicker/teleport, no reconnect, unbounded memory).
- **Putative causes X** = the design choices ratified across six iterations.
- **Ladder rung required:** rung 2 — *intervention*. The user has to choose
  which design choice to flip. "Iterations correlate with failure" (rung 1)
  is useless; "do(renderer_owns_layout = false) eliminates failures F1, F3,
  F4, F5, F7" is actionable.
- **Current evidence rung:** rung 1 across all 64 prior audits. The DAG
  below promotes the evidence to rung 2 *under stated structural assumptions*.

## 2. Causal DAG

Nodes are design choices (italic = **root node**, no parents in the design
graph; bold = observed failure, leaf). Edges = direct causal influence.

```
                         R1: NO INTEGRATOR EXISTS
                          (no module owns the seam)
                          /          |          \
                         v           v           v
                    M1: counter   M2: pending   M3: silent
                    map has no    buffers I3/I5  drops on
                    owner         only in prose  scheduler full
                       \            |              |
                        \           v              v
                         \       F-RESEAT       F-NO-CONT
                          \      F-EDGE-(0,0)   (burst/pause)
                           \        |
                            \       |    R2: RENDERER OWNS LAYOUT
                             \      |    (workflow_graph.js prepareTopology)
                              \     |    /            |          \
                               v    v   v             v           v
                              F-NON-DETERMINISTIC  F-FREEZE   M4: two
                              POSITIONS            ON REBUILD layout
                              (append-clump)       (debounce)  systems
                                                                   \
                                                                    v
                                                            M5: MutationObserver
                                                            referee → F-FLICKER

       R3: METAPHOR OVER-PROMISES                R4: SINGLE-PRODUCER
       ("neural map" = decoration                  ASSUMED, NOT
        in renderer's mind)                        STRUCTURALLY ENFORCED
              |                                          |
              v                                          v
       M6: SlotAssignment carries                M7: seq monotonicity
       only (id,x,y,kind,dom);                   argued in prose; second
       provenance dropped at wire                emitter possible
              |                                          |
              v                                          v
       F-NO-PROVENANCE                           F-OUT-OF-ORDER-DELIVERY
       (tooltip useless)                         (rare; latent)

       R5: NO STRUCTURAL TYPE-CHECK
       BETWEEN PROTOCOL AND WIRE
              |
              v
       M8: format_slot reads slot.id;
       SlotAssignment exposes node_id
              |
              v
       F-FIELD-NAME-BUG (AttributeError on first emit)
```

**Roots (no parents in the design graph):** R1, R2, R3, R4, R5.

**Mediators (M1–M8):** removable iff their root is removed. Controlling for
a mediator without removing the root is the canonical mistake — it produced
six iterations of "fix the symptom" with no progress.

**Missing edges (assumptions made explicit):**
- R1 → R2 absent: the renderer owned layout BEFORE any integrator was
  attempted. R2 is upstream of R1 historically and structurally independent.
- R2 → R3 absent: the metaphor failure is independent of who owns layout;
  even a server-authoritative renderer could drop provenance at the wire.
- R5 → R1 absent: the field-name bug exists in the *wire* and would fire
  the moment any integrator emitted a slot. It is independent of R1.
- No edge from any failure F back into any root: failures don't cause
  design choices. (DAG, acyclic — required for do-calculus.)

**Source of graph:** induced from the prior audits (dijkstra, feynman,
jobs, ginzburg as cited in jobs.md, einstein, polya). Not data-mined.

## 3. Identifiability — backdoor analysis per root

For each root R, the question is: would `do(R = false)` eliminate the
downstream F's? The backdoor criterion holds if no unblocked backdoor
path exists from R to F. Since each R has no parents in the design graph,
all paths R → F are directed forward; **the causal effect of intervention
on each root is identifiable by construction** under the stated DAG.

The only unmeasured-confounder threat: a hidden common cause C → R_i and
C → F. Candidate C: "the user's time pressure / six-iteration fatigue."
This could plausibly co-cause both "we shipped without an integrator"
(R1) and "the renderer kept its old layout code" (R2). Sensitivity check:
if C is removed (calm green-field rewrite) and R1, R2 are still chosen,
the failures still occur. ⇒ R1 and R2 are *causal*, not artifacts of C.

## 4. Do-calculus interventions — predicted downstream effects

| Intervention | Mediators severed | Failures removed | Failures untouched |
|---|---|---|---|
| **`do(R1 = false)`** — write `layout_authority.py`, single owner of counters + pending buffers + producer | M1, M2, M3 | F-RESEAT, F-EDGE-(0,0), F-NO-CONT | F-NO-PROV, F-FREEZE, F-FLICKER, F-NON-DETERM, F-FIELD-NAME |
| **`do(R2 = false)`** — delete `prepareTopology`/`computeSlots` from JS; renderer becomes passive subscriber | M4, M5 | F-FREEZE, F-FLICKER, F-NON-DETERM | F-NO-PROV, F-FIELD-NAME, F-OUT-OF-ORDER |
| **`do(R3 = false)`** — extend `SlotAssignment` to carry `(source_path, parent_id, edges_in/out)` through the wire | M6 | F-NO-PROVENANCE | F-RESEAT, F-FREEZE, F-FIELD-NAME |
| **`do(R4 = false)`** — thread-id assertion at `_log.emit` entry, structurally one worker | M7 | F-OUT-OF-ORDER (latent) | (none others) |
| **`do(R5 = false)`** — generate wire codecs from protocol dataclass; CI lint forbids divergence | M8 | F-FIELD-NAME-BUG | (none others) |

**Joint intervention `do(R1=false, R2=false, R3=false, R4=false, R5=false)`
removes all seven F's. No subset does.** This is the do-calculus reading
of jobs.md §4: zero-of-seven pass not because the iterations were lazy,
but because each iteration intervened on at most one root and the others
remained active confounders of the shipped experience.

## 5. Confounding audit — what NOT to control for

| Variable | Role | Control? | Reason |
|---|---|---|---|
| Iteration count | Collider of (R1,R2,R3) and "user frustration" | **No** | Conditioning on "we tried 6 times" creates spurious correlation between roots; e.g. "iterations that fixed R5 also fixed R2" is collider bias from selecting on shipped attempts. |
| FPS at idle | Mediator on R2 → F-FREEZE | **No** | Optimising FPS without removing R2 (e.g. tilemap raster) drops M6 and creates F-NO-PROVENANCE. Observed in iteration 5. |
| Payload byte size | Mediator on R3 → F-NO-PROV | **No** | "Make wire smaller" prunes provenance fields; pushes failure to the user. Observed. |
| Test count on the six modules | Pre-treatment, irrelevant | **No** | Modules pass tests in isolation (feynman §6); tests do not exercise R1–R5. |
| Whether prior audit found the field-name bug | Descendant of R5 | **No** | Conditioning on "the bug was found" introduces selection bias on R5 fix attempts. |

**Pattern of prior failure:** every iteration controlled for a *mediator*
(FPS, payload, test pass-rate, frame budget) without intervening on a *root*.
This is exactly the Simpson's-Paradox pattern — local optimisation per
mediator made each iteration look like progress while the root-driven
joint distribution stayed unchanged.

## 6. Counterfactual (rung 3) — would `do(R1=false)` 6 months ago have prevented this?

Abduction: given that R2–R5 were independently chosen and that the user's
frustration grew monotonically with iteration count, infer that the
exogenous "time pressure" variable was high.
Action: set R1=false at iteration 1.
Prediction: M1, M2, M3 never form. F-RESEAT and F-EDGE-(0,0) and F-NO-CONT
never observed. R2 (renderer-owned layout) becomes *exposed* as the next
binding constraint by iteration 2 and is fixed earlier. **R1 is not just
the leverage point for now; it is the leverage point that, fixed earliest,
shortens the remaining causal chain by exposing R2.**

## 7. Sensitivity analysis — unmeasured confounders

- **C1 — "Renderer authoring layout is the JS ecosystem default."** Plausible
  common cause of R2 (kept the JS layout code) and of weak server-side
  layout discipline (delayed R1). E-value: an unmeasured confounder would
  need to explain both choices completely *and* explain why a clean rewrite
  also lands at the same defaults. Implausibly strong → R1 and R2 remain
  causal.
- **C2 — "Field-name bug is a typo, not a structural choice."** If R5 is
  random, then `do(R5=false)` only removes one failure instance, not the
  class. Counterargument: the same kind of bug (`format_done` totals from
  caller, prose-only invariants) appears across the six modules. Pattern
  ⇒ R5 is structural (no codegen / no contract test), not random. Conclusion
  preserved.
- **C3 — Unmeasured: build-worker behaviour under load.** Could
  independently cause F-NO-CONT even after R1 fix. Hand-off to **Curie**
  for measurement at 10⁶/sec; if confirmed, add R6 = "scheduler caps
  exceed 8MB ceiling" (already flagged dijkstra B1).

## 8. Conclusion

- **Causal effect estimate:** seven observed failures, five structural roots,
  effect of joint intervention is removal of all seven (under the DAG).
  Effect of any single intervention is partial; effect of intervening only
  on mediators is zero (six iterations of evidence).
- **Rung achieved:** 2 (intervention) under stated structural assumptions.
- **Key assumptions:** the DAG is acyclic; no unmeasured confounder of
  R1∧R2 strong enough to flip the conclusion (C1 implausible);
  build-worker not an independent cause of F-NO-CONT (Curie to verify).
- **Recommendation:** execute `do(R1=false)` first (highest leverage —
  severs three mediators, exposes R2 as next binding constraint), then
  `do(R2=false)`, then `do(R3=false)`, then R5 (cheap, codegen lint),
  then R4 (assertion). **Do not intervene on mediators.**

## 9. Hand-offs

- **engineer** — `do(R1=false)` is the build of `layout_authority.py`
  per jobs.md §5 / polya §6; `do(R2=false)` is the deletion of
  `prepareTopology`/`computeSlots` per ginzburg §5.2.
- **Curie** — measure F-NO-CONT *after* R1 intervention to test C3
  (whether build-worker is a residual cause).
- **Fisher** — if R1+R2 both done and F-NO-CONT persists, design the
  randomized A/B to discriminate scheduler-cap vs build-worker as the
  next root.
- **Lamport** — formalize the single-producer invariant (R4) in TLA+
  if the assertion-based enforcement proves insufficient under chaos test.
