# Peirce abductive audit — Layout Authority

**Procedure.** A surprising fact C is observed. Hypothesis A is admissible only if (i) it would make C a matter of course, (ii) it is testable, (iii) it is the cheapest of the candidates that survive. Abduction does not conclude — it elects a candidate for inquiry.

---

## 1 — The five surprising facts (restated as one corpus)

| # | Anomaly | Source audits |
|---|---|---|
| C1 | Workers have no closed feedback channel back to producers | Boyd §4, Beer S3/S4, Maxwell |
| C2 | The integrator (`layout_authority.py`) was absent for the entire session; the six suffixed modules existed in isolation | Feynman §1.2, Polya |
| C3 | Every quantitative threshold (queue caps, miss=200, log=500k, 0.8 overload, LOD slope ±0.05) is an estimate, not a measurement | Curie C12–C30 |
| C4 | The "neural graph" framing promises perceptual richness the slot geometry cannot deliver beyond ~10⁵ nodes | Midgley |
| C5 | The same `slot.id` vs `slot.node_id` field-name bug surfaced independently in four audits | Feynman §1.7, Aristotle, Bateson, Alexander |

These are not five problems. The Peircean question: *what single hypothesis would make all five a matter of course?*

---

## 2 — Candidate hypotheses (the abductive field)

I refuse to commit before the field is enumerated. Six candidates:

- **H1 — "The geniuses missed something earlier."** Rejected by the user's framing and by the data: the audits are catching the anomalies *now*, faithfully. This hypothesis explains nothing it doesn't explain by tautology.
- **H2 — Time pressure.** Would explain C2 and C5 (rushing → forget the wiring file, copy the wrong field). Does not explain C1 (a structural absence, not an oversight) or C3 (numbers chosen, not measured — that is a *category* of decision, not a hurry).
- **H3 — Skill/competence gap.** Refuted by the artifacts: the six modules are individually well-formed (Beer S1/S2/S5 verdict). A skill gap would produce uniformly weak modules; we see strong modules with absent connective tissue.
- **H4 — Premature commitment to a metaphor ("neural graph") before the operational contract was specified.** Promising — see §3.
- **H5 — Specification was written downward (top-level vision → modules) but never closed upward (modules → integration test → producer feedback → measured numbers).** Strongest candidate — see §3.
- **H6 — The system was built as a *catalogue of capabilities* rather than as a *control loop*.** Reformulation of H5 in cybernetic vocabulary; same predictions.

H4, H5, H6 are not independent. H4 is the *occasioning cause*; H5/H6 is the *structural cause*. The cheapest test (§4) discriminates among them.

---

## 3 — The single hypothesis: **the project was specified open-loop and never closed**

> **H\*: The artefacts were produced by descending one level at a time from a metaphor ("neural graph of methodology") to modules, without ever ascending back through an integration loop that would have forced producer-feedback, integrator-existence, measurement, scale-honesty, and field-name agreement to be resolved as preconditions of shipping a single end-to-end node.**

If H\* is true, then each of C1–C5 is a matter of course:

| Anomaly | Why H\* makes it expected |
|---|---|
| C1 (no producer feedback) | Closing the loop is precisely what the open-loop spec *omits*. A closed loop is not a module — it is a constraint on the relationship between modules. Module-by-module specification cannot generate it. |
| C2 (integrator absent) | The integrator is the upward-closure artefact. It exists only when someone runs `add_node` end-to-end and is forced to wire the modules. Open-loop specification produces six well-formed *parts* and zero *wholes*. |
| C3 (estimates, not measurements) | Measurements require an instrument running against a real load. The open-loop path never instantiates a real load — there is no producer-→-authority-→-subscriber circuit to measure. So every number is the author's prior, not a posterior. Curie's C7 is the lone exception (one ran benchmark) — and it is also the lone module-internal measurement, requiring no integration. |
| C4 (metaphor over-promises) | The metaphor was the *seed* of the open-loop descent. It was never tested against the geometry's actual capacity because the only test that would force the comparison is an end-to-end render of a real corpus at scale — which requires the integrator (C2). The metaphor stays unfalsified because the loop stays open. |
| C5 (field-name bug repeats) | `wire.format_slot` reads `slot.id`; `geometry` produces `slot.node_id`. This bug *cannot exist* the first time anyone calls `format_slot(geometry.compute_slot(...))`. It exists for exactly as long as that call is never made. The four-fold independent rediscovery is itself evidence: every audit that traced a real path *had* to encounter it; no audit that ran the code did, because no code runs the path. |

H\* makes all five a matter of course. No competing hypothesis does.

---

## 4 — Predictions (deductive, falsifiable)

If H\* is correct, then:

- **P1** — The repository contains *no* test that constructs a `NodeDelta`, runs it through `submit → pop → compute_slot → format_slot → SSE frame → subscriber decode`. (Cheapest test: `grep -r "format_slot" tests/`.)
- **P2** — Every benchmark that exists is module-internal (geometry only, scheduler only). None spans modules. (Test: read `bench_layout_authority.py`.)
- **P3** — The numbers in `cost-model.md` will not match a measurement when one is run, in a *predictable direction*: the geometry numbers are roughly right (one real run exists, C7); the integration numbers (C9–C11) will be *worse*, not better, than the unmeasured estimates, because integration overhead is invisible to module benchmarks.
- **P4** — There is no `degraded` event type, no producer-throttle channel, no overload-entered/exited edge event in `_log.py`. (Already confirmed by Boyd §1.)
- **P5** — The `slot.id` vs `slot.node_id` mismatch will be one of *several* such mismatches once the integrator is written. Predicted siblings: edge `source_id`/`src`, sequence `seq`/`seq_no`, kind `kind`/`node_kind`. (Test: diff field names across the six modules.)

P1, P2, P4 are free. P5 costs one `grep`. P3 costs one benchmark. **The hypothesis is testable in under an hour.**

---

## 5 — Why this is not "the geniuses missed something"

The geniuses are operating *correctly*. Open-loop specification *forbids* the integrator's absence from being noticed at any single module's level — that's the definition of open-loop. Each module's audit is sound on its own terms. The anomaly is visible only when audits are *composed*, which is what this prompt does. Peirce's point: abduction operates on the cross-product of observations, not on each observation singly. The geniuses delivered the substrate; the abductive step is taken here.

---

## 6 — The economy-ordered remedy

Do not fix C1–C5 in parallel. They are symptoms of one cause; fix the cause:

1. **Close the loop first** (cheapest, ~1 day): write the integrator. Make `add_node('file:x')` produce one real SSE frame to one real subscriber. This single act will *force* C5 to surface (the field-name bug bites at first run), force C2 to be resolved (the integrator exists), and create the *only* instrument that can later resolve C3.
2. **Instrument the closed loop** (~2 days, after step 1): producer→authority RTT, drops/sec, subscriber miss rate, end-to-end latency p50/p95/p99. These are the measurements that retire C3's estimates and create the feedback channel C1 demands.
3. **Re-test the metaphor against measured scale** (~1 week, after step 2): render the actual Cortex corpus. Find the node count at which the geometry-as-perception story breaks. Replace the metaphor with the measured ceiling. C4 dissolves.

Doing 2 or 3 before 1 is wasted — open-loop measurements measure a fiction.

---

## 7 — Pragmatic-maxim check

What practical difference does H\* make versus H1 ("missed something")?

- Under H1, the action is *more audits*. Under H\*, the action is *one integrator + one end-to-end test*.
- Under H1, the field-name bug is fixed in isolation; under H\*, the integrator's first run finds it *and* its siblings (P5) at zero marginal cost.
- Under H1, future modules are added the same way and reproduce the same five anomalies. Under H\*, the closed loop becomes the gate: no module ships until it traverses the loop.

The two hypotheses produce *different* concrete next moves. The distinction is not verbal. H\* is the load-bearing one.

---

## 8 — Refusal conditions

I refuse to upgrade H\* from candidate to belief until P1, P2, P5 have been checked (free) and P3 has been measured (one benchmark run). Until then H\* carries the status `untested-candidate`. Hand off:

- **Fisher** — design the integration benchmark that decides P3.
- **Pearl** — confirm the causal direction (open-loop spec → all five anomalies, not the reverse).
- **Feynman** — integrity-audit the integrator once it exists.

The abductive inference elects the candidate. It does not close the case.
