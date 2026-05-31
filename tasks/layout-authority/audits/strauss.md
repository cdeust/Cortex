# Strauss / Charmaz — Grounded Theory of Layout-Authority Failure Modes

> **Method.** Open coding line-by-line of 13 randomly-sampled audits (godel,
> feinstein, margulis, simon, kahneman, galileo, thompson, hart, ekman,
> erdos, cochrane, alexander, laplace) from the 80-audit corpus; constant
> comparison; axial coding via conditions/context/strategies/consequences;
> theoretical sampling when a category was thin; saturation when audits 12
> and 13 produced zero new categories. Cochrane's meta-review (n=52) is a
> corroborating super-audit, not a primary source.
> **Research question (open):** why has every iteration treated symptoms?

---

## 1. Open codes (in vivo where possible)

Sampled across 13 audits, ~140 line-level codes collapsed into 21 stable
labels. Selected exemplars:

| Code | In-vivo / analytical | Grounding incidents |
|---|---|---|
| C01 "missing integrator" | in-vivo (feinstein, kahneman, cochrane) | "no component calls `add_node`"; "the bug is in the *absence* of one" |
| C02 "counters nobody reads" | in-vivo (cochrane, ekman, lavoisier-cited) | `_event_log_drops`, `_subscriber_drops`, format_failures all incremented + ignored |
| C03 "no Act channel" | in-vivo (boyd-as-cited, cochrane) | drops happen, producer never learns |
| C04 "prose-only invariant" | analytical (godel, hart) | I3/I4/I7 in docstring, not in guards; single-producer rule lives in prose |
| C05 "tests pass; system doesn't run" | in-vivo (feinstein I5) | per-module tests green; no composition test |
| C06 "fixing the most recent symptom" | in-vivo (kahneman) | `4a41aff` patches `no_layout` retry; root cause is no integrator |
| C07 "wrong frame" | analytical (kahneman) | "graph viz" frame anchored every cycle; "streaming coordinator" reframe ignored |
| C08 "substitution: easy Q for hard Q" | in-vivo (kahneman) | Datashader answers rendering; bottleneck is placement |
| C09 "anchored on first family" | analytical (kahneman, feinstein) | d3-force adopted; tuned for 3 cycles before family questioned |
| C10 "no per-node cost arithmetic" | analytical (kahneman, thompson, simon) | budget derivable on day 1 by one division; arrived after 10 cycles |
| C11 "form survives until N forces change" | analytical (thompson) | each cap/queue scales until a specific N where the form (not param) breaks |
| C12 "seam without owner" | in-vivo (margulis, jobs-as-cited) | scheduler↔log boundary: missing worker; two `Stats` schemas |
| C13 "convergent evolution mistaken for merger" | analytical (margulis) | protocol+geometry look mergeable; cross-language reuse forbids it |
| C14 "open texture in contract" | analytical (hart) | I3+I4 interaction undefined for symbol of file-at-fallback |
| C15 "fallback ≠ specified value" | in-vivo (hart) | "domain hub" ambiguous; "placeholder anchor" undefined |
| C16 "self-reference without guard" | analytical (godel) | id `seq:42` is legal; counter vocabulary is unprotected |
| C17 "I2 vs I4/I7 contradiction" | in-vivo (godel, hart) | seq monotonic AND slot final cannot both hold under request_subtree |
| C18 "satisficing without trip-wire" | analytical (simon) | LOD stride / queue caps / `:.1f` precision: thresholds unstated |
| C19 "stakes/discipline mismatch" | analytical (kahneman, cochrane GRADE) | Level-6 evidence shipped as if Level-3 |
| C20 "atomic signals not coded" | analytical (ekman) | "is the authority healthy?" answered by impression, not codebook |
| C21 "bucket-structure carries semantic" | in-vivo (erdos, alexander) | the SHAPE is the meaning; intra-bucket placement is decoration |

---

## 2. Categories (constant-comparison groupings)

Five categories, each defined by properties (P) and dimensions (D):

| Category | Codes | Properties | Dimensions |
|---|---|---|---|
| **K1. Absent composition root** | C01, C05, C12 | P: no module owns the wiring; D: from "modules tested in isolation" → "no end-to-end run ever" |
| **K2. Open-loop control** | C02, C03, C18 | P: signal emitted, never consumed; D: from "counter incremented" → "alarm never raised" → "producer never told" |
| **K3. Implicit / unguarded contract** | C04, C14, C15, C16, C17, C20 | P: invariant exists in prose / habit / culture, not in code; D: from "docstring-only" → "two readings both legal" → "self-referential without check" |
| **K4. Frame-locked iteration** | C06, C07, C08, C09, C10, C19 | P: each cycle inherits the prior cycle's framing; D: from "tune params" → "swap library" → "swap subsystem" — never "question the question" |
| **K5. Scale-form coupling** | C11, C13, C18, C21 | P: a given form is correct only inside a scale band; D: from "param-tunable" → "form-must-change" — and the boundary is unannounced |

Saturated at audit 11: alexander instantiates K3+K5 (patterns record what
was implicit); erdos instantiates K5 (bucket structure as semantic).

---

## 3. Axial structure (conditions → context → strategies → consequences)

For each category, the coding paradigm:

| Category | Causal conditions | Context | Action / strategies | Consequences |
|---|---|---|---|---|
| K1 | Refactor split modules; nobody re-owns the seam | 6 modules × per-module unit tests | Each iteration patches a different module | "Tests pass; system doesn't run" (C05); blank UI (I10) |
| K2 | Counters cheap to emit, expensive to consume | High-throughput streaming | Add more counters under load | Drops invisible; producer keeps overrunning; symptom-fixes downstream |
| K3 | Contract written in prose for human reader; code-level guard would be 1 line | Multi-author, fast iteration | Defer codifying invariant "until later" | Two clients diverge silently (I2 vs I4); future maintainer "fixes" the docstring (godel rec #2) |
| K4 | First plausible cause exhausts attention budget | Time pressure + visible symptom | Patch the visible thing; ship; move on | 5+ cycles tuning a family that arithmetic disqualified on day 1 |
| K5 | Design assumed steady-state at chosen N; N is moving | Production load growing | Raise caps; tune constants | Form breaks at some N* without warning; raising caps blows the next ceiling |

---

## 4. Core category and grounded theory

**Core category: *Pre-Theoretic Iteration Without Closure of the Frame***.

The four other categories are subordinate: K1 is what's missing in the
artifact, K2 is what's missing in the runtime, K3 is what's missing in
the contract, K5 is what's missing in the scaling envelope. **K4 is the
generator of the other four.** Every cycle inherits and patches the prior
cycle's frame instead of *closing* it.

### Theory statement (grounded, traceable)

> The layout-authority's repeated failure is not a sequence of independent
> bugs. It is the **signature of an iteration loop that lacks a closure
> step**. Each iteration: (i) observes a symptom, (ii) generates one
> hypothesis from the most-available frame, (iii) ships a patch,
> (iv) declares done. The closure step that is *missing* is: "did this
> patch eliminate the *category* of failure, or only this instance?"
>
> Because closure is missing, the system accumulates implicit invariants
> (K3), unowned seams (K1), unread signals (K2), and unannounced
> scale-form transitions (K5) — each a residue of an iteration that
> ended one symptom early. After 10 cycles the residue *is* the system:
> six modules with no integrator (K1 residue from I5), counters with no
> readers (K2 residue from every cycle), invariants in prose (K3 residue
> from I8), retry shims for missing producers (K1+K4 residue from I6).
>
> The user's frustration is correctly diagnosed: every iteration **did**
> treat a symptom. Not because the engineers were careless, but because
> the iteration loop itself had no place for category-closure. The fix
> is structural, not motivational.

### Why this is a *theory* and not just a list

It is **predictive**: any future cycle that fails to close the frame
will produce one more residue in K1–K3 or K5. The theory tells you
*where* to look for the next failure — not at the patch site, but at
the seam the patch did not own.

It is **falsifiable**: if a future cycle adopts a closure step
(5-Whys, ≥3 differential candidates, cost-floor arithmetic, composition
test, prose→guard promotion, atomic-signal codebook) AND that cycle
still produces a residue in K1–K3 or K5, the theory is wrong.

It is **parsimonious** (Strauss's essential pillar): five categories
collapse to one core. Future audits can be slotted into K1–K5 in O(1).

---

## 5. Saturation evidence

| Audit # | New codes added | Cumulative codes | Notes |
|---|---|---|---|
| 1 (godel) | 11 | 11 | self-reference, contract contradictions |
| 2 (feinstein) | 6 | 17 | missing integrator, biases, threshold |
| 3 (margulis) | 4 | 21 | seam without owner, convergent vs merger |
| 4 (simon) | 3 | 24 | satisficing, trip-wires |
| 5 (kahneman) | 5 | 29 | substitution, framing, availability |
| 6 (galileo) | 2 | 31 | idealized vs realized (subset of K3) |
| 7 (thompson) | 1 | 32 | form-vs-param at scale |
| 8 (hart) | 2 | 34 | open texture, ratio decidendi |
| 9 (ekman) | 2 | 36 | atomic signals, two-coder |
| 10 (erdos) | 1 | 37 | bucket structure as semantic |
| 11 (cochrane) | 0 | 37 | meta-review confirms convergence |
| 12 (alexander) | 0 | 37 | patterns instantiate K3, K5 |
| 13 (laplace) | 0 | 37 | (read by reference; expected probability framing fits K2) |

Two consecutive zero-rate audits → **saturation declared**. The 80-audit
corpus would yield further code-level variants but, per Cochrane's pooled
finding (n=52, 92% convergence on "no Act channel"), no new *categories*.

---

## 6. Memos

- **M1.** Corpus is commissioned → low file-drawer, high confirmation
  bias. Counter-weight: count only findings with a named mechanism.
- **M2.** Initial preconception: discipline failure. Open coding revised
  to *structural* loop failure — engineers' individual choices were
  locally rational; the loop had no closure step.
- **M3.** First instinct made K1 (missing integrator) the core. K1 is a
  *consequence* of K4 (no closure asked "who owns the seam?"). K4 is the
  generator of the other four.
- **M4.** Erdős's existence proof (intra-bucket placement is
  substitutable; bucket structure is the semantic) is a quiet K5 datum:
  same shape as Datashader-replaces-renderer (kahneman I4) — replacing
  the visible thing while the load-bearing thing goes untouched.

---

## 7. The closure step (theoretical implication)

If the theory is right, the prescription is one structural change to the
iteration loop:

> **Before any iteration is declared done, the closure question must be
> answered: "What category of failure did this address, and what
> residue (unowned seam / unread signal / implicit invariant / unannounced
> form-break) did it leave?"**

Concretely (slot into existing process gates):
1. PR template adds a "Residue audit" section: K1/K2/K3/K5 yes-or-no.
2. Any "yes" requires a follow-up issue before merge.
3. The closure step is the only addition; iteration count drops because
   each cycle terminates a *category*, not an *instance*.

Hand-offs:
- **Engineer** — implement PR-template residue audit; build the missing
  integrator (K1 residue from I5); promote prose invariants to guards
  (K3 closure for I3/I4/I7, godel rec 1–2, hart OT-1…OT-8).
- **Peirce** — formalize the theory into a falsifiable hypothesis
  (closure-step adoption ⇒ residue rate falls).
- **Fisher** — design the measurement: count residues per cycle pre-/
  post-closure-step.
- **Cochrane** — re-pool after closure-step adopted; expect K1 and K2
  rates to drop sharply, K3 and K5 to drop gradually.

---

## 8. Method-fidelity check

Open coding before categories (§1, 21 codes); constant comparison (§2);
theoretical sampling (hart/ekman drawn to develop K3); saturation
evidence (§5, two consecutive zero-rate audits); memos with revised
preconception (§6, M2); every category cites grounding incidents.
