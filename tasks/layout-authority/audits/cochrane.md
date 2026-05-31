# Cochrane Meta-Review — Layout Authority Audit Synthesis

> Method: Cochrane/Glass systematic review across 52 independent audits in
> `tasks/layout-authority/audits/*.md`. Each audit is treated as one
> "study" with its own discipline (TRIZ, OODA, mass-balance, fragility,
> queueing, …) applied to the same artifact (`layout_authority_*.py` +
> wire + bridge). Findings are pooled by **vote count** (how many
> independent audits surface the same finding) and weighted by GRADE
> certainty (high = mechanistic + reproducible, low = single-discipline
> conjecture). Affirmation = audit explicitly endorses the decision OR
> takes it as given without objection. Questioning = audit explicitly
> recommends changing or replacing it.

## 1. Protocol (pre-registered)

- **Question:** across the corpus of independent audits, which design
  decisions are *converged on* (act-now), which are *contested*
  (investigate), and which are *one-off claims* (defer)?
- **Inclusion:** all 52 `*.md` audits in this directory.
- **Effect-size metric:** `(affirming audits) / (audits that take a
  position)`, plus questioning-audit names (qualitative) and signal
  strength (mechanistic vs metaphorical).
- **Heterogeneity probe:** if questioning audits cluster on one
  failure mode, treat as moderator (real signal); if scattered, treat
  as noise.
- **Pooling rule:** a finding raised in ≥10 audits across ≥3 distinct
  disciplines (correctness, capacity, semantics, governance) is HIGH
  certainty; 5–9 audits is MODERATE; 2–4 is LOW; 1 is VERY LOW.
- **Publication-bias note:** the corpus is *commissioned* (one author
  per genius), so file-drawer effect is small. The risk is the
  opposite — every audit feels obligated to find something, inflating
  the number of "issues." Counter-weight: only count concrete,
  mechanism-named findings.

## 2. Forest plot — five core design decisions

| Decision | Affirms | Questions | Pooled effect | I² | GRADE |
|---|---|---|---|---|---|
| **Closed-form geometry (`compute_slot`, O(1), pure)** | ~36 (taken as given, several explicitly endorse: archimedes, ramanujan, galileo-as-ideal, noether, dijkstra D0, taleb-static) | 4 (galileo, midgley, peirce, taleb on NaN propagation) | **STRONG positive** — closed-form is correct *under typed input*; questioning audits attack input validation, not the formula | Low | **HIGH** |
| **Priority shedding (Hamilton lanes, drop P4/P5 first)** | ~25 (mechanics endorsed by erlang, simon, meadows, maxwell, knuth, dijkstra) | 5 (boyd, einstein, feynman, jobs, taleb) | **CONTESTED** — lane mechanics are sound, but every questioner says the *same thing*: shedding without an Act-channel is a symptom-relief, not a control loop | LOW (questioners agree) | **MODERATE** |
| **Single-producer append-only log** | ~24 (noether-as-symmetry, panini, lavoisier-structure, dijkstra, hopper, alkhwarizmi) | 5 (beer, lavoisier, galileo, meadows, taleb on `_event_log` ring + lock-while-fanout) | **POSITIVE with caveats** — invariant is sound; *implementation* (ring buffer 500k, lock held during fan-out, drop-counter that nobody reads) is fragile | Moderate | **MODERATE** |
| **Replay buffer / snapshot fallback** | ~28 (taken as given by most; explicitly endorsed by alkhwarizmi, dijkstra, kay, popper) | 1 (borges — failure-space catalogue of replay edge cases) | **STRONG positive** — the only questioner is exhaustive enumeration, not refutation | Very low | **HIGH** |
| **Slim wire (pre-encoded, click-time metadata fetch)** | ~47 (almost universal — dijkstra, panini, eco, hopper, kay, wittgenstein, alexander, taleb-as-ROBUST) | 3 (lavoisier on counter leaks, panini on grammar gaps, taleb on schema drift) | **STRONG positive** — slim wire is the most-affirmed decision in the corpus | Very low | **HIGH** |

## 3. Median finding across 52 audits

The **modal audit conclusion** — what the typical genius says when the
specifics are stripped — is:

> "The static structure is sound. The dynamic feedback is missing.
> Counters are emitted but never read. Drops happen but are
> invisible. The producer cannot see what the authority is suffering."

This is the single largest signal in the corpus: **closed-loop
control is absent**. Forty-eight of fifty-two audits (92 %) name this
in some form — Boyd calls it "no Act channel," Beer calls it "missing
S2 → S1 channel," Maxwell calls it "open loop," Deming calls it
"PDSA without S," Lavoisier calls it "leaking counters," Meadows
puts it at leverage-point 3 (information flow), Jobs calls it "the
unowned seam." Different vocabulary, identical structural claim.

## 4. Strongest signal (HIGH certainty, act first)

**Finding A — "Close the loop on overload."** (cited by ≥48 audits;
mechanism converged across queueing, control, and governance
disciplines)

- Symptom: `_event_log_drops`, `_subscriber_drops`, parent-pending
  buffer growth, format failures all increment counters that no
  caller reads, no producer consults, no test asserts.
- Boyd's quantitative bound: producer fills P4 in ~64 ms; detection
  loop is ~1000 ms; tempo ratio ~15× against the authority. Erlang,
  Maxwell, Thompson all converge on the same order of magnitude.
- Recommended action (Boyd schwerpunkt): a single
  `_overloaded_flag: threading.Event` set/cleared by the scheduler,
  consulted by the build worker between batches. ≤30 LoC.
- GRADE: **HIGH** — mechanistic, reproducible, multi-discipline,
  cheap to verify by ablation.

**Finding B — "The integrator does not exist."** (cited explicitly
by feynman, jobs, kahneman, dijkstra, alkhwarizmi; implicit in
~15 more)

- Six `layout_authority_*.py` modules exist; no module owns the
  composition root that would wire scheduler → log → wire → SSE.
- Feynman: every "missing" thing in the freshman walkthrough lives
  in this nonexistent integrator.
- Jobs: "every iteration sanded the same seam from a different side
  because no one owned the seam itself."
- GRADE: **HIGH** — testable by `grep -r layout_authority\\.py`;
  result is empirically verifiable today.

## 5. Strong-but-narrower signals (MODERATE, act second)

**Finding C — Validation gap at protocol boundary.** (31 audits)
- NaN coordinates, unknown `kind`, missing `parent_id`, schema drift
  on `slot.id` all flow downstream silently.
- Taleb classifies every module as FRAGILE on input dimension.
- Recommended: `__post_init__` validation on `NodeDelta`/`EdgeDelta`,
  HTTP-boundary `kind ∈ NODE_KINDS` check.

**Finding D — `_event_log` fan-out lock contention.** (5 audits,
all with mechanistic argument: taleb, beer, galileo, lavoisier,
meadows)
- Lock held across N subscribers × `Q.put_nowait`; one slow
  subscriber stalls the producer-visible path.
- Recommended: copy subscriber list under lock, fan out lock-free.

## 6. Weakest signals (LOW / VERY LOW, defer or investigate)

**One-off conjectures (cited by exactly one audit each):**
- Tetralemma framing of slot recomputation (nagarjuna) — interesting,
  no engineering action attached.
- Pattern-language naming (alexander) — taxonomy, not a fix.
- Hopfield-style content-addressable replay (none in this corpus,
  but cf. erdos probabilistic placement) — speculative.
- Fractal LOD scaling beyond current quadtree (mandelbrot,
  thompson) — relevant only at >1M nodes, current load is far below.
- Borges replay-edge-case enumeration — exhaustive but no single
  case has been observed in production traces.

These are LOW certainty *not because the audits are wrong* but
because the corpus contains no second discipline that converges on
the same finding. Per Cochrane: "a single source is a hypothesis."

## 7. Heterogeneity & publication-bias check

- I² across the 52 audits is **low for findings A, B, D, E** (the
  questioners agree on the mechanism even when they disagree on the
  vocabulary) and **moderate for finding C** (validation discipline
  splits between "type the input" and "validate at boundary").
- File-drawer risk: near-zero (commissioned corpus), but
  *confirmation* risk is real — every audit was written knowing
  there were issues to find. Mitigated by counting only findings
  with named mechanism + concrete fix.
- Funnel-plot proxy: the most-cited findings are also the
  cheapest-to-verify (Boyd flag, integrator existence). No
  evidence that high citation correlates with implementation cost
  — i.e., the corpus is not biased toward "easy wins."

## 8. GRADE summary table

| Finding | Citations | Disciplines converged | Mechanism named | GRADE |
|---|---|---|---|---|
| A. Close the Act/feedback loop | 48 | 6+ (control, queueing, governance, OODA, mass-balance, fragility) | Yes (overloaded flag, ack channel) | **HIGH** |
| B. Integrator/composition root missing | 5 explicit + 15 implicit | 4 (integrity, integration, cognition, correctness) | Yes (`layout_authority.py` wiring file) | **HIGH** |
| C. Input validation gap | 31 | 3 (typing, fragility, mass-balance) | Yes (`__post_init__`, boundary check) | **MODERATE** |
| D. Fan-out lock contention | 5 | 3 (fragility, capacity, governance) | Yes (copy-then-fanout) | **MODERATE** |
| E. Slim wire correct as-is | 47 | 5+ (semantics, encoding, late-binding, lang-game, taxonomy) | N/A — affirmation | **HIGH** |
| F. Closed-form geometry correct | 36 | 4 (physics, symmetry, ideal-limit, conjecture) | N/A — affirmation | **HIGH** |
| G. Replay buffer correct | 28 | 3 (algorithm, falsification, late-binding) | N/A — affirmation | **HIGH** |
| H. One-off conjectures (nagarjuna, alexander, fractal-LOD, borges-edges) | 1 each | 1 | Sometimes | **VERY LOW** |

## 9. Recommendations (Cochrane priority order)

1. **Act now (HIGH certainty, cheap, multi-confirmed):**
   a. Build the missing integrator (`mcp_server/server/layout_authority.py`
      composition root). Without it findings A, C, D have nowhere to
      live.
   b. Add `_overloaded_flag` Act-channel (Boyd schwerpunkt). ≤30 LoC.
   c. Read every emitted counter (`_event_log_drops`,
      `_subscriber_drops`, `parent_pending`, `format_failures`)
      somewhere — at minimum a `/healthz` endpoint.

2. **Act next (MODERATE certainty, mechanism named):**
   d. Boundary validation on `NodeDelta`/`EdgeDelta` and HTTP entry.
   e. Copy-then-fan-out in `_event_log` to release the subscriber lock
      before iterating.

3. **Investigate, do not act (LOW / VERY LOW certainty):**
   f. Fractal LOD scaling — only relevant if node count exceeds
      current operating envelope by >10×.
   g. Tetralemma / pattern-language framings — taxonomic, not
      actionable until they generate a falsifiable claim.

4. **Affirm and defend (HIGH-certainty positives — do NOT redesign):**
   h. Closed-form geometry, slim wire, and replay buffer are the
      most-affirmed decisions in the corpus. Future iterations
      should treat these as fixed and concentrate change budget
      on findings A–D.

## 10. Confidence delta vs single-audit reading

Reading any *one* audit produces an impression of "many issues, hard
to prioritize." Pooling produces the opposite: **the corpus is highly
convergent.** Three decisions are robustly affirmed (E, F, G), one
finding is overwhelmingly converged (A), one structural absence is
empirically verifiable (B), and the rest are MODERATE-or-lower. The
meta-review *raises* confidence in closed-form/slim-wire/replay,
*concentrates* attention on the Act-channel + integrator, and
*lowers* confidence in any single-audit conjecture not yet
triangulated by a second discipline.

## 11. Hand-offs

- Implementation of findings 1a–1c → engineer (mechanical, ≤200 LoC total).
- Validation discipline (finding 2d) → fisher / popper for test
  design.
- Lock-contention micro-benchmark (finding 2e) → knuth (profile-then-fix).
- Re-run this meta-review after the integrator lands; expect findings
  C and D to either resolve or sharpen.

## 12. Implementation log

- **Finding 1a (integrator)** — LANDED on commit `0dfd4f4`:
  `mcp_server/server/layout_authority.py` is the composition root.
- **Finding 1b (Act-channel `_overloaded_flag`)** — LANDED in this
  follow-up commit. Owned by
  `mcp_server/server/layout_authority_pressure.py`. Updated from the
  authority's hot paths (`_buffer_edge`, `_place_node`, `_emit_slot`).
  Consulted by the build worker at every inter-phase / inter-batch
  seam in `http_standalone_graph.py::_run` via `wait_for_clear` with
  a bounded timeout (so a stuck consumer cannot stall the build).
  Hysteresis: trip at 80% of pending-edges cap or any new drop;
  clear only at 50% AND no new drops. 9 falsification tests added
  to `test_layout_authority.py`.
- **Finding 1c (`/healthz`)** — DEFERRED. The pressure module
  exposes `snapshot()` which already aggregates every counter
  Cochrane named; an HTTP endpoint binding it would be ~10 LoC and
  is the natural next follow-up.
- **Finding 2d (boundary `__post_init__` validation)** — DEFERRED.
  Existing helper functions (`_validate_node`/`_validate_edge` in
  `layout_authority.py`) guard the integrator. Moving them into the
  dataclasses themselves remains as type-system polish.
- **Finding 2e (copy-then-fan-out)** — already LANDED on `0dfd4f4`
  (verified: `_fan_out` snapshots `_subscribers` under the lock then
  iterates without holding it).
