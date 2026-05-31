# Fleming Audit — Structured-Serendipity Catalog

> Method: anomalies arrive uninvited during routine work. The five sister
> audits were each pursuing their own hypothesis (single specimen, periodic
> table, bilingual decoding, neural analogy, genealogy). Each surfaced
> *something they were not looking for*. The Fleming discipline: do not
> clean up; investigate; publish; route. Source: Fleming 1929 BJEP 10(3),
> 226–236; Hare 1970 Ch. 3.

The contaminated plate is the audit itself. Five plates, five contaminations.

---

## 1. The catalog

| # | Anomaly | Surfaced by | Discovered while looking for | Reproducible? | Specific? | Triage |
|---|---|---|---|---|---|---|
| F1 | **Lazy-registry phantom domains** — reading `reg.anchor(domain_id)` from a non-domain code path *creates* a domain registration with frozen anchor and no SlotAssignment ever emitted. A typo'd domain_id permanently consumes a spiral index. | McClintock §7 | Tracing one specimen through every module | yes (deterministic; exhibited via `kind='file'` counterfactual) | yes (only `_DomainRegistry.index_for` triggers it; only `kind != 'domain'` paths exhibit) | **investigate** |
| F2 | **Reservation/population metric drift** — domains placed in different reservation epochs (n=16 vs n=33) live in different metric coordinate systems; existing anchors never recompute. | McClintock §4 | Same single-specimen trace | yes (deterministic across reservation crossings) | yes (only at reservation-boundary crossings, n=16, 32, 48, …) | **investigate** |
| F3 | **Index-0 axis degeneracy** — the first domain to register lands at exactly `theta=0` (due-east), the one place where a Fibonacci spiral has undefined spread. | McClintock §3 | Same | yes (mathematical, not empirical) | yes (only `idx=0`) | **note + monitor** |
| F4 | **node_id collision is unguarded** — `_slots` is keyed by node_id alone; a second `add_node` with the same id silently overwrites. The protocol docstring says "stable, unique"; nothing enforces it. | McClintock §8 | Counterfactual exploration of gate 4 | yes (verified by reading `_place_node`) | yes (any kind, any caller) | **investigate** (real gap) |
| F5 | **`entity` declared but unimplemented** — `NODE_KINDS` lists `entity`, but `compute_slot` has no branch; falls through to anchor fallback, silently colliding with the domain node at `(x,y) == anchor`. | Mendeleev §"Outliers" | Building the periodic table | yes (verifiable by counting nodes at anchor in any current slot stream) | yes (only `kind=='entity'`) | **investigate** (real bug) |
| F6 | **Whole inward hemisphere is empty** — only `mcp` lives on the cross-domain inward face; the column predicts ≥5 more inhabitants. ~90% of the inward space is unused, which is *why cross-domain edges look like a tangle*. | Mendeleev §"Missing-family" | Looking for empty cells | yes (visual; measurable as edge-length distribution) | yes (cross-domain edges only) | **investigate** |
| F7 | **L0 row has no member** — every domain is treated as a top anchor with no parent; multi-project deployments have no `super_domain`. | Mendeleev §"Missing-family" | Same | yes (structural; verifiable when >1 repo loads) | yes (multi-project case only) | **note** (predicted-but-not-yet-pressing per Mendeleev §3) |
| F8 | **Symbol slotting drift — JS force-driven vs Py deterministic petal** — Python `slot_for_symbol` produces a closed-form petal; JS uses random seed + force simulation. Visibly different layouts guaranteed for any graph with symbols. The Python docstring claim of "match JS conventions" is *false* for symbols. | Champollion Drift 1 | Constant-by-constant translation | yes (byte-level diff; both code paths readable) | yes (only `kind=='symbol'`) | **investigate** (the Python module is lying to its caller) |
| F9 | **Two dead constants in Python** — `SYM_R_OUTER=290`, `SYM_R_SPREAD=32` declared, never referenced. | Champollion Drift 2 | Same translation | yes (grep confirms zero callers) | yes (two named symbols) | **discard with note** (low impact; trivial cleanup) |
| F10 | **`outward` is polysemous** — used as both *radial direction from center* and *axis from which local tool angles are measured*. Not byte-level drift, but a Wittgenstein-flagged collision. | Champollion Drift 4 | Same | yes (two call sites use two meanings) | yes (just the word `outward`) | **note** |
| F11 | **Activity-dependent pruning is absent** — files with zero symbols still consume a sector angle in the FILE_R shell, biasing nearby placements outward. ~30–50% of files in a fresh scan have zero exported symbols. | Kekulé §4 | Mapping the cortex analogy | partially (count of zero-symbol files measurable; visual impact requires before/after) | yes (only zero-symbol files) | **investigate** |
| F12 | **Bridge persists by genealogy, not necessity** — `destroy + remount` was a 14-hour political truce on 2026-04-22 with the legacy force-graph renderer. The renderer is gone; the truce remains. The 400/500/5000ms debounce constants are uncited. | Foucault | Tracing the genealogy of one file | yes (three commits; SHAs given) | yes (single file: `workflow_graph_bridge.js`) | **investigate** (active source of session freezes) |
| F13 | **Wire frame redundancy for domain nodes** — every domain frame pays ~20 B because `node_id` and `domain_id` are the same string by gate-4 contract. | McClintock §5 | Single-specimen trace | yes (every domain frame) | yes (only `kind=='domain'`) | **discard with note** (cheap at scale; cosmetic) |

13 anomalies. 8 routed for investigation, 2 routed as note-and-monitor, 2 discarded with note, 1 deferred (F7).

---

## 2. Ranking by potential impact

Criteria: (a) does it cause user-visible misbehavior today? (b) does it block scaling? (c) does it falsify a stated invariant or docstring claim? (d) is the fix small relative to the impact?

| Rank | Anomaly | Severity reasoning | Cost-to-fix |
|---|---|---|---|
| **1** | **F12 — Bridge destroy/remount** | Causes every freeze in current session. Active production-class symptom. Architectural alternative already implemented in sibling file (`workflow_graph_tilemap.js`). | medium (delete + delegate to tilemap, or rewrite as long-lived service). The cost of *not* fixing is higher: every phase event = full re-simulate. |
| **2** | **F5 — `entity` unimplemented** | Declared kind silently colliding at the domain anchor is a correctness bug. Knowledge-graph work depends on this. | small (one branch in `compute_slot` per Mendeleev §1, ~20 LOC). |
| **3** | **F8 — Symbol slot JS↔Py drift** | The Python module's docstring is false. Drift between server and client placement of any symbol-bearing graph. Champollion's recommendation is *delete* `slot_for_symbol` (route a). | small (delete a function + 2 constants; F9 falls out for free). |
| **4** | **F4 — node_id collision unguarded** | Protocol docstring promises uniqueness; no enforcement. Silent overwrite in `_slots`. High-stakes (data-integrity per coding-standards §10). | small (one assert, or document overwrite as intentional). |
| **5** | **F1 — Phantom-domain via lazy anchor read** | Typo'd domain_id permanently consumes a spiral index. Hidden state-corruption path. | small (require explicit `register_domain` call, or guard the lazy read). |
| **6** | **F6 — Empty inward hemisphere** | The visual tangle of cross-domain edges that motivates user complaints. Mendeleev predicts 5 missing kinds; populating any one of them improves visible structure. | medium per missing kind; structural pattern is the larger payoff. |
| **7** | **F11 — Activity-dependent pruning absent** | Visual density loss at scale (~30–50% of files are silent). O(1) fix per Kekulé §4; preserves Pattern 1. | small (one extra counter; lazy debounce). |
| **8** | **F2 — Reservation/population metric drift** | Two epochs of domains live in different metric systems. Manifests as visible jumps when a domain crosses the n=16 boundary. | medium (recompute existing anchors on growth, or pin reservation = expected-final). |
| 9 | F3 — Index-0 axis degeneracy | One pinned point on +x axis. Cosmetic unless build-worker enumeration order is unstable. | small (jitter idx=0 by half a golden-angle step, or document). |
| 10 | F10 — `outward` polysemy | Readability cost only; no current bug. | small (rename one use site). |
| 11 | F7 — L0 row missing | Predicted but not pressing until multi-project. | medium (defer per Mendeleev §3). |
| 12 | F9 — Two dead constants | Trivial; falls out of F8 fix. | trivial. |
| 13 | F13 — Wire-frame redundancy | Cosmetic. ~20 B/frame at our scale. | trivial. |

---

## 3. Fleming-discipline recommendation: which deserve follow-up

**Investigate now (the contaminated plates worth subculturing):**

- **F12** — the bridge. The freeze is the lysis zone. Foucault's hand-off to engineer + Galileo is the right next step. The genealogy *itself* should be filed as an ADR so the next session does not re-petrify the truce.
- **F5** — `entity`. A declared-but-unimplemented kind is exactly Fleming's "noticed contamination": the protocol speaks of it; the geometry is silent. Hand-off: engineer (Mendeleev §"Hand-offs").
- **F8 + F9** — symbol slotting. The Python module is making a false docstring claim. Resolution forces a decision (which language is authoritative); the decision retires F9 for free. Hand-off: engineer + a SPEC.md tablet (Champollion).
- **F4** — node_id collision guard. One assert, high-stakes per coding-standards §10. Hand-off: engineer.
- **F1** — phantom domains. Hand-off: Feynman integrity check (intentional or oversight?), then engineer.

**Publish now without development (Fleming's 1929 paper move):**

- **F6** — empty inward hemisphere. The pattern is real even if the population is not yet built. *Publish the periodic-table column*; let a future session populate it. Mendeleev already routed the falsifiability tests to Curie.
- **F11** — activity-dependent pruning. *Publish the analogy* (Kekulé already did) and the predicted O(1) fix; defer implementation until a measurement (Curie) confirms the visual density loss is significant.
- **F2** — reservation metric drift. *Publish the finding*; defer the fix until a domain-count growth event makes it user-visible.

**Note and monitor (the discards inspected before binning):**

- **F3** (index-0 axis), **F10** (`outward` polysemy), **F13** (wire redundancy) — log in `tasks/layout-authority/anomaly_log.md`, do not act unless they recur with new evidence.

**Defer:**

- **F7** — L0 row. Predicted but not yet pressing; revisit when multi-project lands.

---

## 4. Readiness audit (was the environment serendipity-ready?)

| Condition | State on 2026-04-28 | Serendipity-ready? |
|---|---|---|
| Anomaly visibility | Each genius audit had license to surface things outside its hypothesis | **yes** — without that license, none of F1–F13 would have surfaced |
| Discard inspection | McClintock's counterfactuals (§7, §8) deliberately probed paths the protocol does not document | **yes** |
| Log retention | Per-audit files under `tasks/layout-authority/audits/` preserve raw observations | **yes** |
| Interruptibility for investigation | Each anomaly was followed up *within* the same audit, not deferred | **yes** |
| Publication discipline | All five audits published findings without requiring a fix | **yes — Fleming-pattern** |

The environment was structured for serendipity. The 13 anomalies above are the proof.

---

## 5. Hand-offs

- **F12, F5, F8/F9, F4, F1** → engineer (concrete fixes; small to medium).
- **F1** → Feynman (intentional or oversight?) before engineer.
- **F6, F11** → Curie (instrumented measurement before development).
- **F2** → Darwin (long-horizon; observe across many builds).
- **F3, F10, F13** → `anomaly_log.md` (note-and-monitor).
- **F7** → Mendeleev (revisit when multi-project lands).
- **The genealogy of F12** → ADR author so the next session inherits the finding.

---

*Plates surveyed: 5. Contaminations cataloged: 13. Sub-cultured for follow-up: 5. Published without development: 3. Discarded with note: 3. Deferred: 1. Cleaned up and lost: 0.*
