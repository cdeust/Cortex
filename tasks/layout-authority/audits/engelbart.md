# Engelbart augment-vs-automate audit — Layout Authority

**Procedure:** every design decision is classified as either AUGMENT (extends
the user's reach: more nodes visible, more metadata accessible, faster
navigation, finer control) or AUTOMATE (the system decides for the user, often
silently, and removes the decision from their hand). The user's stated stance
is unambiguous and on the record: *"track everything"*, *"no loss of
metadata"*, *"real time streaming"*. That is an augmentation brief. Every
silent automation in the path between memory and pixel is a regression against
that brief unless the automation is explicitly justified and reversible.

Files audited: 8× `layout_authority_*.py`, `cost-model.md`, `polling.js`,
`workflow_graph_tilemap.js`, `workflow_graph_filters.js`,
`workflow_graph_bridge.js`.

---

## 1. Per-module classification

| Module | Decision it makes | A/A | Aligned with user brief? |
|---|---|---|---|
| `layout_authority_geometry.py` | (x,y) from (kind, idx, total_in_kind, parent) — closed-form, deterministic, lossless | **AUGMENT** | Yes. Pure positional rendering; metadata untouched. |
| `layout_authority.py` (counters, anchors) | Bumps counter and emits slot per `add_node` | **AUGMENT** | Yes. One slot per node; no aggregation. |
| `layout_authority_protocol.py` | Three input verbs, one output event | **AUGMENT** | Yes. Verbs are additive; nothing collapses. |
| `layout_authority_log.py` (500 K event cap, 100 K subscriber queue) | Drops oldest events when cap reached | **AUTOMATE** ⚠ | Partial. Cap is silent and unsurfaced — the user is not told that history before event N was discarded. *"Track everything"* is violated under sustained burst. |
| `layout_authority_scheduler.py` (Hamilton priority) | P4 symbols dropped before P2 files; P5 edges dropped before any node | **AUTOMATE** ⚠⚠ | **Conflict.** The user said *no loss of metadata*. The scheduler drops symbols and edges silently when saturated. *Edges* are the relational metadata; dropping them means the user sees a node but not what it connects to. |
| `layout_authority_lod.py` (power-law stride decimation of `symbol`, `memory`, `entity`) | At zoom < 1.0 only every k-th symbol is emitted | **AUTOMATE** ⚠⚠⚠ | **Direct conflict.** This is the textbook commercial-software pattern Engelbart warned against: optimize the floor (smooth zoom-out for novice eyes) by lowering the ceiling (expert can no longer trust that what they see is what exists). The decimation is deterministic-by-hash, not user-chosen. |
| `layout_authority_wire.py` (SSE serialization) | What fields cross the wire | depends — see §2 | Risk: any field omitted here is metadata loss the user cannot recover. |
| `polling.js` (client polling cadence) | When to ask the server | **AUGMENT** | Yes. User can read-faster but cannot be starved. |
| `workflow_graph_tilemap.js` (auto-fit, viewport culling) | Default zoom on load; which tiles to fetch | **AUTOMATE** ⚠ | Mixed. Viewport culling is legitimate (off-screen pixels carry no info). Auto-fit-on-load is a one-shot decision that takes the framing out of the user's hand without an explicit "back to my view" affordance. |
| `workflow_graph_filters.js` | What kinds are checked by default | **AUTOMATE** ⚠ | Default-hide-anything is a metadata-suppression decision. The user said *track everything* — so the *default state* should be "show everything," and the filter is the user's tool to subtract, never the system's tool to subtract on their behalf. |
| `workflow_graph_bridge.js` (kind→layer mapping) | Which renderer pipeline a kind is sent to | **AUGMENT** | Yes — routing, not filtering. |

Legend: ⚠ = automation that should be surfaced to the user; ⚠⚠ = automation
in conflict with stated brief; ⚠⚠⚠ = automation that *defines the conflict*.

---

## 2. The three places augmentation is silently downgraded to automation

### 2.1 LOD decimation (`layout_authority_lod.py`)
The stride formula `2^(3 − 4·zoom)` is a server-side decision that *some*
symbols will not reach the client at zooms < 1.0. The user has no UI affordance
that says *"you are seeing 1/4 of symbols at this zoom — click here to override"*.
For a *user trying to understand their own cognitive memory*, this is the
worst possible failure: the system is deciding what is forgettable. The
Mandelbrot fractal-self-similarity argument is mathematically correct for
*rendering bandwidth* but does not justify hiding the existence of the omitted
nodes from the user's awareness. **Fix:** emit a per-zoom badge ("showing
124 K / 487 K symbols, stride 4 — [show all]"). The override must be one click.

### 2.2 Scheduler drops on saturation (`layout_authority_scheduler.py`)
P5 edges and P4 symbols are dropped under burst. Edges are relational
metadata: a memory linked to a symbol that is linked to a file is the entire
shape of the cognitive graph. Silently dropping edges turns *augmentation of
the user's structural understanding* into *automation of "what looks
important to the system."* **Fix:** every drop must increment a per-kind
counter that is streamed to the client and surfaced as a visible "N edges
deferred — replay" affordance. Backpressure must be *visible*, not silent.

### 2.3 Default-hidden filter state (`workflow_graph_filters.js`)
If any kind ships with `checked: false` by default the system has automated
the "this kind is noise" decision on the user's behalf. The user's brief is
the opposite: show everything; subtraction is a user verb. **Fix:** every
kind defaults to visible. A "Reset to all visible" button is mandatory.

---

## 3. Where the design correctly augments

- **Closed-form geometry** (`_geometry.py`): O(1) per node, no force
  simulation, no clustering. Node #10⁹ is placed identically to node #1.
  This is augmentation: the user can drop a billion nodes and the
  *positional answer is the same shape* they'd get for ten. No emergent
  layout drift, no "the system decided to cluster these for you."
- **Counter-only state** (`_authority.py`): O(kinds) memory, not O(nodes).
  The authority never *summarizes*; it *places*. Summarization would be
  automation; placement is augmentation.
- **SSE real-time streaming**: every `add_node` produces a `SlotAssignment`
  the user sees within tens of ms. The user is *in* the loop of seeing
  their memory grow, not handed a finished picture.

---

## 4. The bootstrap test

Engelbart's load-bearing question: *does the team building the tool use the
tool for their own work?* For the layout authority specifically — does the
maintainer **watch their own session** in the unified visualization while
they code? If yes, the LOD decimation will be felt the first time they zoom
out and lose the symbol they were just editing. If no, the decimation will
ship and only burn external users. **Recommendation:** make the visualization
the maintainer's primary debugging surface for the next two weeks. The pain
points found there are the design specification.

---

## 5. The ceiling test

What can an expert user do with this visualization after a month of daily
use? Under the *current* design with default LOD + default filters + silent
drops:

- Novice (first hour): can zoom and pan a smooth-looking graph. **Floor: high.**
- Expert (after a month): cannot trust that absence-of-node means
  absence-of-memory. They have to double-check via `recall` for every
  empty region. **Ceiling: collapsed back to the floor.**

This is the exact ARC → Xerox PARC regression Engelbart spent his late
career protesting. The augmentation tool is being commercially smoothed
into an automation tool by default settings. The fix is small: surface
every silent decision, make every override one click, default to
"show everything." The geometry layer is already correct; only the
visibility/scheduling/filter defaults need to flip.

---

## 6. Hand-offs

- **Hopper:** the badge "showing 124K/487K — [show all]" is a level-of-
  abstraction primitive; design it as a reusable component for any
  decimating surface.
- **UX-designer:** every ⚠ row above needs an affordance spec.
- **Curie:** measure how often the scheduler actually drops under realistic
  burst rates. If drops are rare, the fix is cheap; if frequent, it is
  load-bearing.
- **Feynman:** integrity check on the LOD claim — does the power-law stride
  actually preserve "structural understanding" or does it just preserve
  *visual smoothness*? Those are different properties.

---

## 7. One-line verdict

The geometry is augmentation. The scheduler, LOD, and filter defaults are
automation that the user did not ask for and that conflict with the
stated *"track everything / no loss of metadata"* brief. Flip the defaults,
surface the deferrals, and the tool returns to the augmentation contract.
