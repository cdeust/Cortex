# Kahneman Audit — System-1 Traps in the Layout-Authority Session

Scope: cognitive-bias post-mortem of the iteration sequence that produced the
six `layout_authority_*.py` modules, the Datashader pivot, the tilemap
auto-recovery patch, and the still-missing integrator. Stakes: **High**
(irreversible-ish architectural commitments, ten fix cycles, no convergence —
Pólya §1). Method: name the trap, point at the iteration that suffered, state
what System-2 would have caught, prescribe a counter-procedure.

Iteration ledger (reconstructed from git + audit corpus):

| # | Iteration | Artifact / commit | Outcome |
|---|---|---|---|
| I1 | d3-force on full graph | early `workflow_graph.js` ticks | Stalled at ~5k nodes |
| I2 | `prepareTopology` per phase | `workflow_graph.js:308–700` | O(N+E) per recompute, blocked |
| I3 | force-graph + spatial index rebuild | force-graph experiments | O(N log N) per insert |
| I4 | Datashader server-tile pivot | `dba2f16` | Renders pixels; loses node identity |
| I5 | Six `layout_authority_*` modules | current tree | Parts exist, integrator missing (Feynman §1.2) |
| I6 | Tilemap auto-recover on `no_layout` | `4a41aff` | Symptom-fix; root cause = no integrator |

---

## Trap 1 — Anchoring on the first solution that "looked right" (force-graph)

**Where it bit:** I1–I3. d3-force was adopted because it was *the* visible
default for graph viz; subsequent iterations adjusted parameters (alpha, link
strength, spatial index) instead of questioning the family. The cost-model
shows d3-force at N=10⁹ costs ~3·10¹² ops — **six orders of magnitude over
budget** (cost-model §1). That number was derivable on day 1.

**System-1 signature:** "graph → force simulation" associative retrieval. WYSIATI
— the demo that worked at N=10³ was treated as evidence the family scales.

**System-2 catch:** compute T_per_node = T/N **before** picking the family. At
1 ns/node (cost-model §1), any iterative or O(N log N)-per-tick algorithm is
disqualified by arithmetic. The family must be O(1) per node, closed-form. The
disqualification is one division, not an experiment.

**Counter-procedure (preventive, not cognitive):**
1. **Budget-first checklist** at architecture entry: write
   `T_per_node = T_target / N_target` and `bytes_per_node = M_target / N_target`
   on line 1 of any viz design doc. Reject any candidate whose per-node cost
   exceeds the budget by inspection.
2. **Reference-class forecast:** before adopting library X, list 3 prior projects
   that used X at the target N. If none exist, X is unproven at scale — treat
   the inside-view demo as N=10³ evidence, not N=10⁹ evidence.

---

## Trap 2 — Substitution: easy question for hard question

**The hard question:** "Does this layout pipeline place node #10⁹ in the same
time as node #1, within 8 MB working set, deterministically, while streaming?"

**The easy questions System-1 answered instead, in order:**
- I1–I3: "Can I make d3-force converge for the demo graph?" (≈ 100 nodes)
- I4: "Can I render 10⁶ pixels per second?" (Datashader — answers a *rendering*
  question, not a *placement* question; node identity / pickability lost)
- I5: "Are the six modules each internally consistent?" (Feynman audit confirms
  yes — but the integrator is missing, so the system cannot run)
- I6: "Can I make the symptom go away when `/api/quadtree` returns `no_layout`?"
  (Auto-recover patch — the `no_layout` IS the symptom of the missing
  integrator; auto-recovery hides the root cause)

**System-2 catch:** Pólya's Phase 1 — *restate the unknown*. The audit corpus
restates it correctly (cost-model §1, Pólya §1, Feynman §1.2): the unknown is
a **streaming coordinator with O(1)-per-node deterministic placement**, not a
renderer, not a module set, not a 404 handler.

**Counter-procedure:**
1. **Question-substitution log.** At every iteration boundary, write the
   question being answered on this iteration on one line. Compare it to the
   problem statement. If they differ, you are substituting. (Kahneman 2011
   Ch. 9 protocol.)
2. **Acceptance test gates the symptom-fix.** A symptom-fix PR (like I6) must
   cite the root-cause issue ID. If no root-cause issue exists, the PR is
   refused — open the issue first.

---

## Trap 3 — Availability bias: fixing the most recent symptom

**Where it bit:** I6 (`4a41aff` "tilemap auto-recovers when /api/quadtree
returns no_layout"). The visible failure was the tilemap stalling on
`no_layout`. The fix made the *retry* work. The actual cause — the integrator
that should have *produced* the layout in the first place doesn't exist
(Feynman §1.2: "today nothing calls `add_node` at all") — was not addressed.

The Datashader pivot (I4) has the same shape: the most recent visible failure
was rendering blowing up at N=10⁶, so the fix replaced the renderer. But the
placement pipeline (the actual bottleneck under cost-model §1) was never built.

**System-1 signature:** "the most vividly broken thing is the most important
thing." Recency overrides root-cause analysis.

**System-2 catch:** Pólya §1 — "the bug is not in any file; the bug is in the
*absence* of one." A 5-Whys chain run at I6 lands on "no integrator" within 3
hops:
- Why does the tilemap need to auto-recover? → because `/api/quadtree` returns `no_layout`.
- Why does it return `no_layout`? → because no `compute_slot` has been called.
- Why has no `compute_slot` been called? → because no integrator exists to call it.

**Counter-procedure:**
1. **5-Whys before any symptom-level patch.** The PR description must include
   the 5-Whys chain; if it bottoms out in "missing component," the patch is
   refused until the component is built.
2. **Pre-mortem on the fix:** "Imagine this patch is merged and the same bug
   recurs in a different form in 2 weeks. Why?" If the answer is "because the
   real cause was elsewhere," you are patching a symptom.

---

## Trap 4 — Inside-view estimation, no reference class

The cost model (§5) is the *only* place in this session where an outside-view
benchmark exists (5.55 M ops/s pure Python, measured). Every iteration prior
to that — I1, I2, I3, I4 — adopted a family on inside-view reasoning ("this
should work for our graph") with no reference-class data on (a) similar libs
at similar N, (b) similar pipelines under streaming load. The cost-model
arrived after ~10 cycles; it should have been iteration zero.

**Counter-procedure:** **No architecture commit without a per-node-cost
table.** The first artifact in any large-N viz task is the cost-floor doc
(`tasks/layout-authority/cost-model.md` is the template). PRs that introduce
a placement family without citing the cost-floor row that justifies it are
refused.

---

## Trap 5 — Framing: "graph viz" vs. "streaming coordinator"

The session was framed as "graph visualisation" throughout I1–I4. Under that
frame, force-graph and Datashader are natural candidates. Under the reframe
"unbounded streaming events with deterministic projection" (Pólya §2.1, IoT
analogy), the candidate set is entirely different: WAL + projection +
coordinator, ~150 LOC, already prior art.

The reframe was available from day 1 — the user supplied the IoT analogy.
System-1 anchored on "graph viz" because the artifact (a graph) dominated the
frame. System-2 would have asked: *what is the dataflow shape*, not *what is
the artifact shape*.

**Counter-procedure:** **Two-frame restatement** at architecture entry.
Restate the problem in (a) artifact terms ("graph viz") and (b) dataflow
terms ("streaming events with projection"). If the candidate solution sets
diverge, the artifact frame is misleading — pick the dataflow frame.

---

## 6. Devil's-advocate role for this codebase

Standing assignment: every architecture PR for the layout authority gets one
named reviewer whose job is to argue the opposite. Specifically required to:
1. Run the cost-floor arithmetic and cite a row that disqualifies the proposal,
   OR concede the budget passes.
2. Name a substitution candidate ("this PR answers Q', not Q").
3. Run the 5-Whys on the motivating bug.
The reviewer is empowered to refuse merge until 1–3 are answered in writing.

---

## 7. What to escalate, to whom

- **Fat-tail / burst stressors** (queue sizing, dead-subscriber storms) →
  Taleb (already covered in `taleb.md`).
- **Concurrency obligations of the missing integrator** (single-producer,
  seq monotonicity) → Dijkstra (`dijkstra.md` §0–§1, already specified).
- **Reframing to the IoT coordinator pattern** → Pólya (`polya.md` §2.1,
  already prescribed: ~150 LOC, copy verbatim).

This audit's contribution: the **process** changes (budget-first checklist,
question-substitution log, 5-Whys gate, two-frame restatement, devil's
advocate) that prevent the *next* ten cycles from repeating the last ten.
Cognitive awareness alone does not remove these biases (Lilienfeld 2009);
the gates above are structural so the bias cannot reach merge.
