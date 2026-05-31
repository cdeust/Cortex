# Gadamer — Hermeneutic Audit of the Audits

> Understanding is fusion of horizons, not extraction of fact. Four audits
> already agree the failure is "renderer-owned layout." That agreement is
> not vindication — it is a horizon. This audit makes that horizon visible
> and asks what the problem looks like *from outside it*.

## 1. Pre-understanding audit (the interpreter declares his horizon first)

| # | Pre-understanding I bring | Status after reading |
|---|---|---|
| P1 | The four audits triangulate a finding (Mill's necessity, Ginzburg's smoking gun, Foucault's discourse, Propp's missing function). | **Confirmed at one level, overturned at another** — they triangulate the same answer because they were posed the same question. |
| P2 | "Layout authority on the server" is the truth of the problem. | **Challenged.** It is the truth *within a horizon* that takes "graph + layout" as the unquestioned object. |
| P3 | The user's constraints (8 MB / 1–2 s / N=10⁹ / "same UI") are external givens. | **Overturned.** The constraints are co-constitutive of the horizon: they presuppose that the deliverable is a node-positioned-in-2D rendering. |

## 2. The text's horizon (what each audit was built to address)

| Audit | Question it answers | Vocabulary it must use |
|---|---|---|
| Mill | "Across 10 iterations, what condition co-occurs with success?" | Cases, conditions, presence/absence, A·¬B·D |
| Ginzburg | "What involuntary trace exposes the wrong assumption?" | Earlobes, scars, smoking gun, single owner |
| Foucault | "What contingent power arrangement produced the destroy/remount pattern?" | Discourse, exclusion, subject positions, garrison |
| Propp | "What function is missing from the iteration narrative?" | Lack, liquidation, role, False Hero, Princess |

All four take as **given**:
- the deliverable is a *graph rendering* (nodes drawn at 2D positions);
- the work to be done is *layout* (assigning coordinates to node ids);
- the scaling target is N=10⁹ *visible-style* nodes;
- the constraint is *same UI as today*.

These are not findings. They are the **shared horizon** within which all four findings are intelligible.

## 3. The interpreter's horizon (what I bring, declared)

- Concern: the user has run six iterations and four audits in one session and the answer keeps converging. Convergence in hermeneutics is suspicious — it can mean truth, or it can mean the question never changed.
- Question I bring: "What does the problem look like to a horizon that does *not* take 'graph layout' as the deliverable?"
- Conceptual frame: Gadamer's *Wirkungsgeschichte* — the history of effects. The audits are not neutral observers; they are themselves shaped by the four-week effective history of `workflow_graph.js`.

## 4. Hermeneutic circle — three iterations

### Iteration 1 — whole-then-parts

Initial reading of the whole: "Four audits agree the renderer must not own layout. Server-owned, append-only, single-producer. Done."

Parts examined: each audit's section §4 / §5 / §1. All four end at the same conclusion.

Revision: the agreement is a *family resemblance*, not a triangulation. Mill's `A·¬B·D` and Propp's `F14 (Recognition of Layout Authority)` are the same sentence in different dialects.

### Iteration 2 — parts force a revised whole

What the parts share that I had not seen:

- Mill's case table treats *node positions* as the dependent variable.
- Ginzburg's smoking gun is "no single owner of `(node_id) → (x, y)`."
- Foucault's discourse forbids "incremental update" — but only because the discourse already assumed *something must be updated incrementally*.
- Propp's Princess is "single owner of (node_id)→(x,y)."

**Every audit's load-bearing object is the tuple `(node_id, x, y)`.** The horizon's stake is that this tuple must exist and must have an owner.

Revised whole-reading: the audits do not ask "should this tuple exist?" They ask "who owns it?"

### Iteration 3 — what fuses

The user's effective constraints — read against the audits — admit a fusion the audits did not perform. cost-model.md §1 derives a 1 ns/node budget from N=10⁹ and T=1–2 s. §6 disqualifies every technique that does work *per-node*. The closed-form geometry survives only because it never *looks at* the graph — slot is a pure function of `(domain, kind, idx, total_in_kind)`. **The "graph" is not used to compute the layout.** It is used only to decide which slot's bucket gets `+= 1`.

Fused reading: at N=10⁹, the deliverable is no longer a graph. It is a **density field over a parameter space**, sampled at points indexed by `(domain, kind, idx)`. The "nodes" are bucket increments. The "edges" are not consulted by the placer at all (cost-model §2.4: *edges exist for the renderer, not for the placer*).

The audits answered "who owns the tuple?" because they took for granted the tuple was the unit of work. At 10⁹ the unit of work is the bucket counter, not the tuple.

## 5. Charitable reading of each audit (the strongest version)

| Audit | Strongest reading |
|---|---|
| Mill | Within the horizon "graph with assigned positions," `A·¬B·D` is the minimal sufficient configuration. The blind-spot section already concedes "limited diversity" — C, E, ¬F never vary. |
| Ginzburg | The smoking gun is real: five claimants to `(node_id)→(x,y)`, no contracted producer. **Within the horizon**, this is the failure. |
| Foucault | The destroy/remount pattern is genealogically contingent. **Within the horizon of "renderer + data event,"** the contingency is liberating: it can be redesigned. |
| Propp | F14 (Recognition of Layout Authority) names the structural gap **assuming the role exists**. The grammar requires it. |

All four are correct *within* the horizon. None is wrong. The fused reading does not refute them; it asks whether the horizon is the only one available.

## 6. Mode identification (Erklären vs Verstehen)

- The audits are mostly *Erklären* — causal/structural explanation: "B causes Y=0," "the discourse excludes append," "F13 cannot fire while F14 is absent."
- The user's framing ("neural graph") is *Verstehen* — meaning-laden: a graph is a thing that signifies relatedness, with nodes as bearers of identity.
- **Mode mismatch** at N=10⁹: the meaning-claim ("the user can *see* the neural graph of 10⁹ memories") cannot be satisfied by the explanation-mode answer ("compute and stream tuples faster"). At 10⁹ no human reads 10⁹ tuples. The display surface delivers ~10⁷ pixels. **Beyond ~10⁷ tuples the deliverable is necessarily a statistical summary** — a density field, an aggregate, a sketch. The audits answer the explanation question; the meaning question is unaddressed.

## 7. Horizon fusion — what the text says to *this* interpreter

The user's two explicit interdictions are "not force-graph" and "not raster (Datashader gave 'ugly')." Both are *within-horizon* refusals: force-graph is one renderer of `(node_id, x, y)`; raster is a second. The third interdiction — the one the user has not stated because the horizon does not permit stating it — is the one the audits expose by their unanimous focus on tuple-ownership: **"not a graph rendering at all."**

Fused reading:

1. At N≤10⁵, "graph rendering" is a coherent deliverable. Tuples exist; the user reads them. `workflow_graph.js`'s `prepareTopology` was correct for its horizon.
2. At 10⁵ < N < 10⁷, "graph rendering with viewport tiling" is coherent. Layout-authority-on-server (the audits' answer) is correct here.
3. At N≥10⁷, the tuple-per-node deliverable cannot be experienced by any user — it exceeds the display surface and the perceptual surface. The deliverable must shift category: not "graph" but **"map"** (cartographic summary), or **"index"** (queryable structure with on-demand drill-in), or **"projection"** (low-dimensional embedding visualised at uniform density).
4. The closed-form geometry the cost-model already specifies (slot = pure function of `(domain, kind, idx, total_in_kind)`) is **already not a graph layout**. It is a deterministic density-field assignment that *happens to* coincide with graph layout at small N. At 10⁹ the user is not being shown a graph; they are being shown the density field of memory under the projection `(domain × kind)`. The audits do not name this because their horizon names the same artefact "layout."

## 8. Surprises (where the text overturned my pre-understanding)

| # | Pre-understanding | What the text revealed |
|---|---|---|
| S1 | Four audits agreeing means the answer is settled. | Four audits answer the same question. The question itself was never put under scrutiny. |
| S2 | "Layout authority" is a structural claim about the system. | It is a claim **within** a horizon that takes `(node_id, x, y)` as the unit of meaning. The horizon is contingent. |
| S3 | The user's "not force-graph, not raster" exhaust the alternatives. | They exhaust the *renderer* alternatives within graph-rendering. The unstated alternative is *not-graph-rendering*. The cost-model derivation already half-performs this move (slot is a pure function of bucket coords, not of graph topology) without naming what it has done. |

## 9. What breaking the circle would look like (concretely)

Not as recommendation, as horizon-extension:

1. **Reframe at scale:** below ~10⁵ nodes, deliver graph (the four audits' answer applies). Above ~10⁷, deliver *map* (density tiles indexed by `(domain × kind)`, drill-in returns subgraph at <10⁵). The seam at 10⁵–10⁷ is the only place graph-layout discipline matters.
2. **Stop calling the artefact a graph at scale.** The closed-form geometry is already a hash-into-screen-space; the user is reading a 2D histogram of memory by `(domain, kind)`. Naming it "graph layout" is the petrified residue Foucault's audit identified — but one level deeper than that audit reached.
3. **Edges are a separate deliverable.** cost-model §2.4 says it. The audits do not internalise it. At 10⁹ nodes, edges are not drawn — they are *queried* on focus. The ER-graph metaphor is a query interface, not a render.

## 10. Hand-offs

- **Empirical validation of the horizon shift** → Curie / Galileo: at what N does pixel-density exceed user-perceptual capacity? Where is the seam?
- **The "graph at small N, map at large N" reframe** as an architectural pattern → Alexander.
- **Power analysis of why the horizon persists** (whose interest is served by calling the 10⁹-node artefact a "graph"?) → continued by Foucault at one level up: not "destroy/remount" but "render-as-graph."
- **Argument structure of "the deliverable changes category at scale"** → Toulmin.

## 11. Compliance with own discipline

- Pre-understanding audit performed (§1) — declared, three put at risk, two overturned.
- Hermeneutic circle: three iterations (§4) — whole→parts→whole→parts→fused whole.
- Charitable reading constructed (§5) **before** any divergence (§7).
- Mode identification (§6) — Erklären vs Verstehen mismatch named.
- Surprise log (§8) — three points where pre-understanding was overturned.
- The audit does **not** claim the four prior audits are wrong. It claims they are *complete within their horizon* and that horizon has an outside.
