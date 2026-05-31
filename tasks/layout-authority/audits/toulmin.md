# Toulmin argument-structure audit — `cost-model.md`

**Method.** Decompose the cost-model's headline argument into the six
Toulmin parts (Claim, Data, Warrant, Backing, Qualifier, Rebuttal),
diagram them, and locate where the warrant fails to carry the claim.
The model is a *quality-control* tool: it makes the inferential
skeleton visible so the load-bearing joint can be inspected.

---

## 1. The headline argument as written

> **Claim (C):** the layout authority places **N = 10⁹ nodes** in
> **1–2 s** within an **8 MB** working set on a single machine.
> *(cost-model.md §1, lines 5–6.)*
>
> **Data (D):**
> - D1: per-node geometry is `compute_slot(domain_anchor, kind, idx,
>   total_in_kind)` — closed-form trig, no iteration, no graph
>   traversal. *(§2 implications 1–4; geometry constants §4.)*
> - D2: per-domain counter state is `11 × 6 × 8 B = 528 B`; per-tool
>   angle cache `7 × 11 × 16 B ≈ 1.2 KB`. *(§3.)*
> - D3: pure-Python single-core measurement on this machine —
>   180–300 ns/slot, 3.4–5.6 M slots/s across 5 kinds. *(§5,
>   lines 80–87.)*
>
> **Warrant (W):** *if* the per-node cost is O(1) closed-form, *and*
> the per-module state is bytes-not-megabytes, *then* the system
> budget is dominated by per-node compute × N, and that product is
> bounded by (Python ns/slot ÷ vectorisation speedup ÷ core count) × N.
> Equivalently: **"the geometry module's local cost profile is the
> system's cost profile."**
>
> **Backing (B):**
> - B1: the closed-form derivation in §2 (no iteration ⇒ no
>   superlinear term).
> - B2: the measured 1M-slot benchmark in §5 (the 180–300 ns figure).
> - B3: the projection that numpy + 8-core delivers ~30× more.
>
> **Qualifier (Q, as written):** "amortised", "in geometry only" —
> appears in §1 footnote phrasing but **not** attached to the headline
> claim. The headline reads as an absolute system bound.
>
> **Rebuttal (R, as written):** §6 lists what the design rules out
> (d3-force, prepareTopology, force sims). It does **not** list the
> conditions under which the headline claim *itself* fails.

---

## 2. Diagram

```
                                                B1 §2 closed-form
                                                B2 §5 1M-slot bench
                                                B3 §5 numpy+8-core projection
                                                       │
                                                       ▼  (backs)
   D1 O(1) per-node geometry  ┐
   D2 528 B counter state     ├──► W "geometry-local cost = system cost"
   D3 180-300 ns/slot measured┘                         │
                                                        ▼  (with qualifier Q)
                          [Q: amortised, geometry only]
                                                        │
                                                        ▼
                                              C: 10⁹ nodes in 1–2 s
                                                 within 8 MB

                          ┌────── R (declared §6): rules out d3-force,
                          │       prepareTopology, force sim, spatial
                          │       index rebuild  (rules out RIVALS,
                          │       not failure conditions of C itself)
                          │
                  ┌───────┴─── R (missing, supplied by other audits):
                  │             • Curie C9–C11: numpy/multi-core
                  │               speedup is unmeasured speculation
                  │             • Ibn Khaldun K1: scheduler 19 MB +
                  │               event log 40–56 MB + sub queues
                  │               11 MB → ~70–90 MB system RSS
                  │             • Ibn Khaldun K2: wire + render
                  │               dominate; 80 GB over SSE at
                  │               10–100 MB/s ⇒ 10³–10⁴ s
                  │             • Archimedes Caveat: DISC↔MEM
                  │               angular collision at 10⁹ N
```

---

## 3. Where the warrant does not support the claim

The argument is internally tidy — D1, D2, D3 each support **a**
claim. They do not support **the headline claim**, because W
silently substitutes "geometry-module cost" for "system cost". This
is a **scope-shift fallacy** dressed as an inference rule.

| # | Gap | Evidence the warrant fails |
|---|---|---|
| G1 | D1 (O(1) per-node) supports "compute is linear in N", not "wall-time is 1–2 s". Wall-time = max(compute, wire, render). The warrant elides wire and render. | Ibn Khaldun K2: 80 GB SSE payload at realistic 10–100 MB/s ⇒ 10³–10⁴ s; browser ≤10⁵ evt/s ⇒ 10⁴–10⁵ s. |
| G2 | D2 (528 B) supports "the geometry module's per-domain table fits in bytes", not "system RSS ≤ 8 MB". Counter state is one of ≥4 live allocations (counters, scheduler queues, event log, subscriber queues, numpy buffers). | Ibn Khaldun K1 + Curie C13/C18: scheduler 19 MB, event log 40–56 MB, sub queue 11 MB ⇒ ~70–90 MB. The cost-model's own scheduler doc says 19.4 MB — the spec contradicts itself. |
| G3 | D3 (180–300 ns/slot, single-machine, single-run, no IQR) is the only measured datum. B3 (numpy ~30–50 ns + 8-core ~5–8×) is **projection, not measurement**. The warrant treats the projection as load-bearing. | Curie §4 explicitly tags C9–C11 as "unmeasured speculation" requiring `bench_geometry_numpy` and `bench_geometry_parallel` before promotion. |
| G4 | Q ("amortised", "in geometry only") is the qualifier that, *if attached to C*, would make the argument honest. As written, it sits in body prose and is dropped from the headline. A claim whose qualifier does not travel with it is **rhetorically unqualified**. | Toulmin 1958 Ch. III §3: a claim without a travelling qualifier is either trivial or dishonest. |
| G5 | R as declared rules out **rival approaches** (d3-force, etc.). It does not state the conditions under which **C itself** fails. A Toulmin rebuttal must answer "when is my own claim wrong?", not "why are competitors wrong?" | Three independent audits supply the missing R: Curie (no measurement), Ibn Khaldun (scope shift), Archimedes (geometric collision at 10⁹). The cost-model has not absorbed any of them. |

---

## 4. The honest restatement

Splitting C into the parts the data actually supports:

| Restated claim | Qualifier | Supported by |
|---|---|---|
| **C′₁** Geometry compute for 10⁹ slots completes in 1–2 s. | "presumably, IF vectorised via numpy AND parallelised across 8 cores — neither yet measured." | D1 + D3 + B3 (B3 still hypothesis). |
| **C′₂** The geometry module's per-domain state is ≤ 1.8 KB (528 B counters + 1.2 KB angle cache). | "exactly, by arithmetic." | D2. |
| **C′₃** End-to-end placement-and-render of 10⁹ nodes through SSE to a live browser completes in 1–2 s within 8 MB system RSS. | **Reject.** Refuted by Fermi/Ibn Khaldun K2 (10³–10⁵ s wire+render) and K1 (~70–90 MB RSS). |

C in the document conflates C′₁ with C′₃ and inherits the credibility
of C′₂. That is the load-bearing error.

---

## 5. Field-dependent standards

This is a **systems-engineering** argument, not a closed-form-math
argument. Its field's standards demand:

- *Evidence:* end-to-end measurement on the production transport,
  not micro-benchmarks of one stage.
- *Warrant:* a system bound is `max` of stage costs, not `sum` of
  one stage's cost. Substituting compute-time for wall-time is a
  category error in this field.
- *Qualifier:* every system claim travels with its measurement
  envelope (machine, dataset, run count, IQR).
- *Rebuttal:* every system claim names the regime in which it
  breaks (e.g. "fails when wire bandwidth < X MB/s" or "fails when
  RSS includes log + scheduler").

`cost-model.md` meets the closed-form-math field's standards for
C′₁ and C′₂. It does not meet the systems-engineering field's
standards for C as written.

---

## 6. Required edits (Toulmin-form)

1. Split C into C′₁, C′₂, C′₃ with their own qualifiers; demote C′₃
   to a separate "system budget" ADR per Ibn Khaldun §6.
2. Attach Q ("IF vectorised, IF parallelised, IF tile-served not
   live-streamed") to every surviving headline.
3. Add an explicit **Rebuttal** section to cost-model.md naming the
   conditions under which each surviving claim fails — sourced from
   Curie §3, Ibn Khaldun §1, Archimedes Caveat.
4. Tag B3 (numpy/multi-core projection) `// HYPOTHESIS — no
   measurement`, per Curie §4.

---

## 7. Hand-offs

- **Curie** — supplies the measurement protocols that turn B3 from
  hypothesis into backing (`bench_geometry_numpy`,
  `bench_memory_residency`).
- **Ibn Khaldun** — supplies the structural rebuttal (system RSS,
  wire+render dominance) that the new R section must cite.
- **Engineer** — performs §6 edits to cost-model.md; opens the
  separate system-budget ADR.
- **Pearl** — if the wire/render dominance is contested, supply a
  causal-graph audit of the SSE consumer chain.

---

## 8. One-line verdict

The cost-model's data and warrant are sound *for the geometry
module*. Promoting them to a system claim violates the warrant's
scope, drops the qualifier in transit, and substitutes a
"rules-out-rivals" list for a real rebuttal — three Toulmin defects
that converge on the same fix: scope C, attach Q, write R.
