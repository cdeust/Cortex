# Margulis — Merger-Not-Competition Audit of the Layout Authority

> Premise: the 6 modules (`geometry`, `protocol`, `scheduler`, `log`, `wire`,
> `lod`) plus the integrator (`layout_authority.py`) are framed as
> independent organs. Margulis's lens: *some seams are merger-residue
> from former independent ancestors; others are genuine boundaries
> between formerly-cooperating endosymbionts*. The diagnostic is
> **independent-origin signatures** — own lifecycle, own structure,
> own boundary, self-contained function. Modules with FEW signatures
> across that seam are merger candidates.

## 1 — Heterogeneity survey

| Module | Own lifecycle | Own structure | Own boundary | Self-contained | Sigs |
|---|---|---|---|---|---|
| `geometry` | no (pure fn) | math constants | imports stdlib only | yes (pure) | 2 |
| `protocol` | no (dataclass) | typed contracts | stdlib only; runtime `Protocol` | yes (no logic) | 2 |
| `scheduler` | yes (queues, time) | priority deques + `Stats` | stdlib only | yes | 4 |
| `log` | yes (seq, ring, fanout) | deque + subscriber list | stdlib only; threading | yes | 4 |
| `wire` | no (encoder fn) | byte format | stdlib; TYPE_CHECKING → protocol | yes | 2 |
| `lod` | no (pure fn) | hash + stride table | stdlib only | yes | 2 |
| `layout_authority` | yes (the host cell) | composition root | imports all 6 | NO (consortium) | — |

The host (`layout_authority.py`) is the eukaryote. The 6 modules are
the candidate endosymbionts. **Two have 4 independent-origin signatures
(scheduler, log) — fully independent organisms. Four have 2 signatures
(geometry, protocol, wire, lod) — pure-function fossils, not living
organelles.** Their separation is filing, not mitosis.

## 2 — Convergent-evidence check on the proposed mergers

### Candidate A — **scheduler ⊕ log** (the queue-and-fanout symbiosis)

Lavoisier already named the ledger seam between them: events that
`pop()` from the scheduler must reach `emit()` in the log; the
unwritten worker between them is where conservation breaks
(format failures, subscriber reaping, coalesced duplicates, all
counted on different sides of the boundary).

| Evidence line | Observation |
|---|---|
| Lifecycle (independent?) | Both have own thread-affinity rules; scheduler has multi-producer / multi-consumer; log has **single-producer** (Hamilton invariant). The seam IS that rule. |
| Structure (foreign?) | Both expose a `Stats` snapshot; the schemas don't compose — caller stitches `{**sched.stats, **log.stats}` manually in handlers. |
| Boundary (own?) | None. Scheduler's `pop()` returns a tuple the worker is supposed to hand to `log.emit()`. The worker doesn't exist; the boundary is empty space. |
| Convention drift | Scheduler counts `dropped[p]`; log counts `_event_log_drops`. Same concept, two names, two namespaces. (Lavoisier §rename queue) |

**Verdict — MERGE.** Three independent evidence lines converge:
the missing worker, the duplicated `Stats`, the conflicting
producer-count rules. The seam IS the conservation hole. A merged
`layout_authority_pipeline.py` exposing `submit_node / submit_edge →
SlotAssignment | EdgeOut | Drop(reason, counter)` collapses the
unwritten worker into a single function. **Single producer for both
queues and log**, single `Stats`, format failures counted at the
point of pop. Lavoisier's residuals (parent_pending, edge_pending,
format_failures, coalesced) become fields on one struct.

### Candidate B — **protocol ⊕ geometry** (contract = implementation)

Initially attractive: I3 (symbol-after-file), I4 (file-before-tool_hub),
I7 (domain-late) are *placement* invariants stated in `protocol` and
*executed* by `geometry`. The contract reads like the implementation's
header comment.

But the convergent-evidence check fails:

| Evidence line | Observation |
|---|---|
| Independent reuse? | `geometry` is reused by the integrator without `protocol`'s dataclasses. Pure-math constants (`SETUP_R`, `TOOL_R`, …) are copied from `workflow_graph.js` — there is a non-Python consumer of this contract. |
| Different change-cadence? | `protocol` changes when verbs are added (rare). `geometry` changes when visual constants change (also rare, but for different reasons — UI taste vs API stability). SRP test: two different stakeholders. |
| Foreign internal logic? | `protocol` has zero logic. `geometry` has 218 lines of math. Merger would inflate the contract surface with implementation. |

**Verdict — KEEP SEPARATE.** This is *convergent evolution under
similar constraints* (both shaped by the visualization invariants),
not merger-residue. The cross-host reuse (JS workflow_graph.js shares
the same constants) is the smoking gun: `geometry` has a second
client, and a merged module would force that client to depend on
Python dataclasses it doesn't use. ISP failure waiting to happen.

### Candidate C — **wire ⊕ protocol** (already partially merged)

Not in the brief, but flagged because `wire.py` line 38 has
`if TYPE_CHECKING: from ...protocol import ...`. This is a
weak-merger residue: the encoder NEEDS the dataclass shapes to
encode them, so it imports their *types* but pretends not to.

| Evidence line | Observation |
|---|---|
| The encoder cannot do its job without `SlotAssignment`/`EdgeDelta`. | yes |
| The TYPE_CHECKING fence is a paradigm preserve, not a reuse boundary. | yes |
| Is `protocol` reused without `wire`? | yes — handlers receive `NodeDelta` and never touch wire. |
| Is `wire` reused without `protocol`? | no — it always serializes those exact dataclasses. |

**Verdict — PARTIAL MERGE: fold `wire` into `protocol` OR keep
`wire` and drop the TYPE_CHECKING fence.** `wire` is a downstream
endosymbiont of `protocol` (depends on it but not vice-versa).
Cleanest move: rename `protocol.py` to `protocol.py` + co-locate
`wire.py`'s formatters as `protocol.encode_*` methods on the
dataclasses. Saves one file; removes the import-fence ceremony.
Lower priority than Candidate A — the seam doesn't leak events.

## 3 — Keep separate (false-merger candidates)

| Pair | Why NOT merge |
|---|---|
| `geometry` ↔ rest | Cross-language client (workflow_graph.js); SRP — math vs orchestration. |
| `lod` ↔ rest | Pure decimation. Independent stake-holder (renderer zoom). Useful in isolation; testable as math. |
| `protocol` ↔ `geometry` | Convergent evolution, not merger. Separate change-cadences. |
| `log` ↔ `wire` | Wire is byte-encoding; log is event-ordering. Different conserved quantities (Lavoisier). |

## 4 — Serial-merger order (if Candidate A proceeds)

1. **First merger — scheduler ⊕ log → `pipeline`.** Highest payoff
   (seals Lavoisier's leaks). Producer count drops from "two
   conventions" to "one". `Stats` schema unifies.
2. **Second merger — wire into protocol (optional).** Cosmetic;
   removes one import fence. Defer until first merger ships.
3. **No third merger.** `geometry` and `lod` stay independent
   organelles with their own genomes.

## 5 — Integration-depth and extraction risk

| Module | Integration in `layout_authority.py` | Extraction risk if merged elsewhere |
|---|---|---|
| `scheduler` | imported, owned by the integrator | LOW — no external caller |
| `log` | imported, owned by the integrator | LOW — same |
| `geometry` | imported by integrator + `workflow_graph.js` | HIGH — JS coupling |
| `protocol` | imported by handlers + integrator + wire | MEDIUM — many readers |
| `wire` | imported by SSE handler | LOW — single caller |
| `lod` | imported by SSE handler tier filter | LOW — single caller |

Candidate A merges two LOW-risk modules. Safe.

## 6 — Competition alternative (steel-man for keeping all 6)

Could *gradual modification* fix the scheduler/log seam without
merging? Yes: write the missing worker as `_pump.py` with its own
`Stats` and have it call both modules. But that creates a *third*
module owning the conservation invariant — Lavoisier's hole moves,
it doesn't close. The merger removes the seam; the gradual fix
relocates it.

## 7 — Confidence

- Evidence lines for Candidate A: 3 (independent: missing-worker /
  duplicated-stats / producer-rule-conflict). Convergent. **Strong.**
- Evidence lines for Candidate B (REJECT merge): 3 (cross-language
  client / change-cadence / contract-vs-implementation purity).
  Convergent on KEEP SEPARATE. **Strong.**
- Evidence lines for Candidate C: 2. Insufficient for action;
  **moderate / defer**.

## 8 — Recommendations

1. **MERGE scheduler + log → `layout_authority_pipeline.py`.**
   Single `Stats`, single producer, missing-worker eliminated.
   Closes Lavoisier's residuals (`parent_pending`, `edge_pending`,
   `format_failures`, `coalesced`) at the merge point.
2. **KEEP geometry separate** — cross-language reuse is load-bearing.
3. **KEEP lod separate** — independent stakeholder (renderer zoom).
4. **DEFER wire-into-protocol** — cosmetic, low payoff; revisit
   after merger #1.
5. **PROTOCOL stays the contract module** — the place invariants
   are *stated* must remain distinct from where they are *executed*.

## Hand-offs

- Selection-pressure on the merged pipeline → **Darwin** (does the
  merged organism survive 1e9-event load that broke the
  separated pair?).
- Conservation accounting at the new merge point → **Lavoisier**
  (re-audit once the pipeline exists; the four leaks should close).
- Layer compliance of the merged module → **Liskov** (the
  scheduler's contract and the log's contract must both remain
  substitutable through the merged surface).

## Files touched

None. Audit-only.
