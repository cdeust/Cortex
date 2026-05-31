# Noether Audit — Symmetries Behind the Layout Authority Invariants

> Method: every conserved quantity has an underlying continuous symmetry of the
> action (here: the `add_node` / `_emit` reduction). Where the symmetry is global,
> the invariant is a true conservation law (Theorem I). Where the symmetry is
> local (gauge), the invariant is an *identity* of the equations of motion
> (Theorem II) — it constrains structure, not a flowing quantity.
> Sources: Noether 1918 §§1–3; Tavel 1971 translation.

The "action" of the authority is the trajectory of `(seq, node_id, x, y, kind, domain_id)`
emissions produced by serialising deltas through `_emit`. Symmetries are the
transformations of input streams that leave the *observable emission stream*
(modulo sequence) invariant.

---

## 1. Declared invariants — symmetry / charge / falsifier

### I1 — Every emission has finite (x, y)
- **Symmetry.** Translation invariance of the emission predicate: a node's
  finiteness depends only on its slot computation, not on absolute time or
  prior emissions. Global, continuous (in the trivial sense — the property
  is preserved under all admissible inputs).
- **Conserved charge.** `Σ 1[¬finite(slot)] = 0` over the entire stream
  (Theorem I, applied to a constant Lagrangian density `L = 1[finite]`).
- **Falsifier.** Inject a delta whose ancestor chain forces `compute_slot`
  through a degenerate branch (zero radius, NaN angle, anchor=None at flush).
  If any emitted SA carries `math.isnan` or `math.isinf` in x or y, I1 is
  broken. Test: 12 kinds × 100 random adds with a fault-injected anchor.

### I2 — `seq` strictly monotone, contiguous from 1
- **Symmetry.** Time-translation invariance of `_emit`: the operation
  `seq ← seq+1; emit(SA(seq, …))` does not depend on wall-clock time or
  prior `seq` values beyond the immediate successor relation. This is the
  classical Noether case — time-translation ⇒ a conserved "Hamiltonian".
- **Conserved charge.** The successor functional `H = seq_{n+1} − seq_n − 1`,
  conserved at value `0` for every adjacent pair. Equivalently, `seq` is the
  Noether charge of time-translation.
- **Falsifier.** Two-thread emission without serialisation: observe a gap
  or a duplicate seq across 10k concurrent adds. Or observe a subscriber
  receiving SAs in non-monotone order — that breaks the *delivery-side*
  reading of I2 and is a separate failure (see hidden H1).

### I3 — Symbol arrives only after its parent file
- **Symmetry.** Partial-order invariance under any topological re-ordering of
  the input stream that respects parent→child edges. The emission stream is
  invariant under permutations of the input that preserve the dependency
  DAG. This is a *gauge* symmetry — local relabelling of independent
  branches must give equivalent outputs.
- **Conserved identity (Theorem II).** "For every emitted symbol SA_s with
  parent p, ∃ earlier emitted SA_p with kind=file and node_id=p." Not a
  flowing charge — an identity among emission steps (a Bianchi-type
  constraint on the stream).
- **Falsifier.** Submit `add_node(symbol, parent=F)` before `add_node(file=F)`.
  Confirm the symbol is buffered (`pending_symbols[F]`) and only emitted
  *after* F's emission. Failure: any SA(symbol, parent=F) appears before
  SA(file=F) in the seq order.

### I4 — Tool-bucket fallback is final (no retroactive reseat)
- **Symmetry.** Discrete history invariance: once a slot is assigned, the
  function `node_id → slot` is fixed for the lifetime of the authority. The
  symmetry is "no time-reversal of the slot map." This is *not* continuous
  — strictly speaking it gives a selection rule, not a Noether charge.
  (See Blind-spots §1: discrete symmetries do not yield conservation laws.)
- **Conserved quantity (selection rule form).** The map
  `M : node_id ↛ (x, y)` is monotone-once-defined: `M(n)` defined ⇒
  `M(n)` immutable. Equivalently `dM/dt = 0` on the support of `M`.
- **Falsifier.** Add a node when its tool-bucket is unknown (Case 4
  fallback to anchor), then later add the missing tool metadata. If a
  second SA is emitted for the same node_id with a different (x, y),
  I4 is broken. Test: replay-stream comparison of `M` before/after late
  metadata arrival.

### I5 — Pending edges bounded (cap 100k)
- **Symmetry.** Scale invariance is *deliberately broken* here — the cap
  introduces an explicit length scale. So I5 is not a Noether conservation
  law; it is a regulator. The relevant "symmetry" is a soft bound: the
  authority is invariant under bursts of edge submission below the cap.
- **Conserved quantity.** `|pending_edges| ≤ 100_000` — an inequality, not
  an equality. Treat as a homeostatic constraint, not a charge.
- **Falsifier.** Submit 100_001 edges whose endpoints are absent. The
  100_001st must be either dropped (with `drop_counter++`) or rejected.
  Silent unbounded growth falsifies.

### I6 — Subscriber backpressure: drop, never block
- **Symmetry.** Producer-side time-translation invariance under consumer
  slowness: the producer's emission rate is invariant w.r.t. any subscriber's
  drain rate. This is the "no back-action" symmetry — a gauge choice that
  decouples the producer from the consumer's frame.
- **Conserved quantity.** The producer's emission cadence (Δseq / Δt of
  `_emit` invocations) is independent of `q.put_nowait` outcomes.
  Equivalently, `drop_counter + delivered = seq` for each subscriber —
  a per-subscriber conservation of *attempts*.
- **Falsifier.** Stall one subscriber's queue; measure producer wall-time
  per emission. If it grows with queue saturation, I6 is broken.
  Secondary falsifier: `delivered + drops ≠ seq` on subscriber audit.

### I7 — Domain placeholder anchor == final anchor
- **Symmetry.** Order-of-arrival gauge invariance: the assignment
  `(drec.index, kind, idx) → slot` is invariant under permutations that
  swap "domain delta arrives first" with "member delta arrives first."
  This is a local (gauge) symmetry of the input stream.
- **Conserved identity (Theorem II).** `anchor(drec.index)` is a function
  of `drec.index` alone, not of when `drec.anchor` was first computed.
  An identity, not a flowing charge — same form as I3.
- **Falsifier.** Two replay runs: (A) members first, (B) domain first.
  Compare `(x, y)` for every shared node_id. Any mismatch falsifies I7.
  This is the test alkhwarizmi.md §1 already names — keep it.

---

## 2. Hidden invariants — undeclared but load-bearing

### H1 — Single-producer (single-thread) on `_emit`
- **Symmetry observed but undeclared.** I2's monotonicity *requires* a
  total order on `seq ← seq+1`. The only continuous symmetry that produces
  this is "evolution under a single Hamiltonian" — i.e. one writer.
- **Conserved quantity.** `∀ t : |{threads currently inside _emit}| ≤ 1`.
- **Falsifier.** Two-thread fuzz on `add_node` → observe duplicate or
  missing seq. **beer.md line 100 already flags this as a Medium gap.**
  Declare it as I8.

### H2 — Geometry constants byte-identical across Python ↔ JS
- **Symmetry.** Coordinate-frame invariance between the producer
  (`mcp_server/server/layout_authority_geometry.py`) and any client
  renderer (e.g. `ui/unified/js/*`). The slot a client *renders* must
  equal the slot the authority *emitted*; this is invariance under change
  of language frame.
- **Conserved quantity.** `(N_CAP, base_r, cx, cy, domain_anchor formula,
  outward_angle formula, tool_hub_angle formula)_python ≡ (…)_js`,
  bit-for-bit for the integer/rational parts and within ε for floats.
- **Falsifier.** Snapshot `domain_anchor(i, N, cx, cy, r)` for
  `i ∈ {0..N-1}` in both runtimes; diff. Any non-ε divergence breaks
  the contract — clients will draw at one slot, the authority will reason
  about another. **Currently undeclared and unenforced.** Recommend a
  golden-vector test fixture committed in both languages.

### H3 — Replay determinism (idempotent reduction of the input log)
- **Symmetry.** Re-running `add_node` over an identical input log produces
  an identical output stream (modulo wall-clock fields). This is
  permutation-invariance restricted to the identity permutation —
  determinism as a symmetry under "re-execution."
- **Conserved quantity.** `H(emission_stream) = f(input_log)` —
  emission entropy is a pure function of input.
- **Falsifier.** Hash the SA stream for two runs of the same log; diff
  must be empty (after stripping timestamps). Hidden RNG, hash-iteration
  order, or `dict` insertion-order leakage breaks this.

### H4 — Bounded slot universe (`compute_slot` codomain ⊂ ℝ²-finite)
- A weaker form of I1 stating not just finiteness but *boundedness* within
  the canvas. Without it, "finite" admits 1e308 outliers that crash JS
  rendering. Falsifier: add `assert |x|,|y| ≤ R_MAX` and fuzz.

### H5 — `node_id` is a primary key (no two distinct deltas share it)
- alkhwarizmi.md §test 5 ("duplicate node_id ⇒ no second emission")
  relies on this but it is not declared as I-anything. Promote to I9.

---

## 3. Symmetry-breaking observations (Move 6 — what the breaks teach)

| Expected symmetry | Where it breaks | Diagnosis |
|---|---|---|
| I5 scale-invariance | Cap = 100k | Not a bug — a deliberate regulator. Document as "homeostatic," not as conservation. |
| I4 time-reversal | Fallback to anchor when bucket unknown | Deliberate finality. The break *is* the invariant. |
| H1 single-producer | Currently unenforced | Genuine gap — declare I8 and add an assertion. |
| H2 cross-language parity | No golden test | Genuine gap — add fixture. |

---

## 4. Hand-offs

- **Lamport** — formalise H1 (single-producer) and H3 (replay determinism)
  as TLA+ state-transition invariants.
- **Shannon** — quantify H2: define the bit-exact equivalence of the
  geometry constants and propose a fixture format.
- **Curie** — instrument I6 to *measure* `delivered + drops vs seq` per
  subscriber; the residual is a carrier of the symmetry-breaking term.
- **Engineer** — promote H1, H2, H5 to I8/I9/I10 in `_protocol.py` (the file
  is referenced by beer.md S5 but `find` returned no match in the tree).
