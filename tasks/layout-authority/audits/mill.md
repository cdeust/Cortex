# Mill / Ragin Audit — Layout Authority

**Method:** J.S. Mill's joint method of agreement and difference (Mill 1843,
*A System of Logic*, Book III Ch. VIII §§1–3), extended with Ragin's
necessary/sufficient distinction (Ragin 1987, *The Comparative Method*, Ch. 5).

**Question:** across the ~10 visualization iterations this session, what
condition is **necessary** for streaming to work and **absent** from every
failure?

## 1. Outcome definition

- **Outcome present (Y=1):** large-graph (≥1M-node) viewport renders, pans
  and zooms without freeze; node positions stable across reloads;
  append-only growth without re-layout flash.
- **Outcome absent (Y=0):** browser stalls, OOM, layout flicker on each
  poll, or coordinates drift between renders.

## 2. Candidate conditions

| Code | Condition | Definition |
|---|---|---|
| A | Server-owned layout | Coordinates assigned by Python authority, persisted in PG, served via `/api/quadtree` |
| B | Renderer-owned layout | Coordinates computed in JS (`prepareTopology` / d3-force) at render time |
| C | Deterministic geometry | Slot is a pure function of `(domain, kind, idx, total_in_kind)` — no RNG, no force step |
| D | Append-only growth | Existing nodes' coordinates never change when new nodes arrive |
| E | Viewport tile streaming | Renderer requests only visible tiles, not the full graph |
| F | Full-graph fetch | Renderer pulls every node before drawing |

## 3. Case table (the ~10 iterations)

| # | Iteration | A | B | C | D | E | F | Y |
|---|---|---|---|---|---|---|---|---|
| 1 | d3-force in workflow_graph.js | 0 | 1 | 0 | 0 | 0 | 1 | 0 |
| 2 | prepareTopology client-side, full fetch | 0 | 1 | 1 | 0 | 0 | 1 | 0 |
| 3 | prepareTopology + polling diff | 0 | 1 | 1 | 0 | 0 | 1 | 0 |
| 4 | Client cache + recompute on add | 0 | 1 | 1 | 0 | 0 | 1 | 0 |
| 5 | Tilemap viewport, client layout | 0 | 1 | 1 | 0 | 1 | 0 | 0 |
| 6 | **Tilemap viewport, server slots (early)** | **1** | **0** | **1** | **1** | **1** | **0** | **1** |
| 7 | Server slots + client re-layout overlay | 1 | 1 | 1 | 0 | 1 | 0 | 0 |
| 8 | Datashader CPU path, client layout | 0 | 1 | 1 | 0 | 1 | 0 | 0 |
| 9 | Quadtree handler, no authority | 0 | 1 | 1 | 0 | 1 | 0 | 0 |
| 10 | **Server quadtree + layout authority (latest)** | **1** | **0** | **1** | **1** | **1** | **0** | **1** |

(Iteration labels reconstructed from `tasks/tilemap-frontend-plan.md`,
`tasks/tile-server-plan.md`, `tasks/layout-cache-plan.md`, and the
session's git log.)

## 4. Method of agreement (over Y=1 cases: rows 6, 10)

| Condition | Present in case 6 | Present in case 10 | Shared? |
|---|---|---|---|
| A — server-owned layout | 1 | 1 | **yes** |
| B — renderer-owned layout | 0 | 0 | shared as ABSENT |
| C — deterministic geometry | 1 | 1 | yes |
| D — append-only growth | 1 | 1 | **yes** |
| E — viewport tile streaming | 1 | 1 | yes |
| F — full-graph fetch | 0 | 0 | shared as ABSENT |

Conditions present in *every* success: **A, C, D, E**. Condition *absent*
in every success: **B, F**.

## 5. Method of agreement (over Y=0 cases: rows 1–5, 7–9)

| Condition | Present in all 8 failures? |
|---|---|
| A — server-owned layout | NO (only row 7 has it) |
| **B — renderer-owned layout** | **YES — present in all 8 failures** |
| C — deterministic geometry | NO (row 1 is non-deterministic) |
| D — append-only growth | NO (absent in all 8 failures) |
| E — viewport tile streaming | NO (rows 1–4 lack it) |
| F — full-graph fetch | NO (rows 5, 7–9 lack it) |

The single condition present in every failure: **B (renderer-owned layout)**.

## 6. Method of difference (most-similar pair: rows 5 vs 6)

Rows 5 and 6 share E (tile streaming), C (deterministic), and ¬F
(no full fetch). They differ on the layout authority axis only.

| Condition | Row 5 (Y=0) | Row 6 (Y=1) | Differs? |
|---|---|---|---|
| A — server-owned layout | 0 | 1 | **YES** |
| B — renderer-owned layout | 1 | 0 | **YES** |
| C | 1 | 1 | no |
| D — append-only | 0 | 1 | **YES** |
| E | 1 | 1 | no |
| F | 0 | 0 | no |

The variables that flip between the matched failure and the matched
success are **A, B, D** — all three express the same underlying claim:
**layout authority lives on the server, and writes are append-only**.

Row 7 reinforces this. Row 7 has A=1 (server slots) but the renderer
*also* re-laid-out on top of them (B=1, D=0). Outcome reverted to Y=0.
This rules out "server layout merely available" as sufficient — the
renderer must not overwrite it.

## 7. Necessity / sufficiency (Ragin)

| Claim | Test | Verdict |
|---|---|---|
| A is necessary for Y | Every Y=1 case has A | **Necessary** (rows 6, 10) |
| B precludes Y | Every Y=1 case has ¬B; row 7 shows A∧B → Y=0 | **¬B is necessary** |
| D is necessary for Y | Every Y=1 case has D | **Necessary** |
| A alone sufficient? | Row 7 has A but Y=0 | **Not sufficient alone** |
| A ∧ ¬B ∧ D ∧ C ∧ E sufficient? | Holds in rows 6 and 10; no counter-case | **Sufficient (within observed cases)** |

Boolean minimization of the truth table over rows 1–10:

```
Y = A · ¬B · C · D · E · ¬F
```

C, E, ¬F co-vary with A·¬B·D in all observed positive cases, so they
cannot be separated within this dataset (limited diversity, Ragin Ch. 7).
The minimal **distinguishing** core, isolated by the difference test
between rows 5–6 and the failure of row 7, is:

```
Y ⇐ A · ¬B · D
   ≡  server-owned ∧ renderer-not-overriding ∧ append-only
```

## 8. Conclusion

- **Necessary cause (agreement + difference):** layout authority must
  reside on the server, the renderer must not recompute or overlay
  positions, and writes must be append-only so existing coordinates
  never change.
- **Brief successes (rows 6 and 10)** are the only configurations that
  satisfy this conjunction.
- **Every failure (rows 1–5, 7–9)** violates at least one of A, ¬B, D.

This matches the user's stated finding. The Boolean formula
`A · ¬B · D` is the minimal configuration the architecture must
preserve; any future iteration that re-introduces client-side layout
(B=1) or non-append writes (D=0) is predicted by this audit to revert
to Y=0.

## 9. Blind spots and hand-offs

- **Limited diversity.** C, E, ¬F never vary against the success rows;
  their individual necessity cannot be isolated here. Hand off to a
  Curie / Fisher experimental run that toggles C, E, F independently
  while holding A·¬B·D fixed.
- **Mechanism vs configuration.** Mill identifies the *what*; the *why*
  (cache locality, GC pressure on full-graph fetch, browser layout
  thrash on B=1) belongs to a Pearl causal-graph audit.
- **Single session.** All 10 cases come from one session; external replication would strengthen the necessity claim.
