# Schelling Audit — Focal Points in the Layout-Authority Protocol

**Frame.** Producers (build worker) and consumers (SSE clients, geometry,
log, wire) cannot negotiate every convention at runtime. Where the
protocol does not spell out a rule, both sides converge on the
**salient** answer — the focal point. Once a focal point is broken, an
explicit signal MUST replace it, or the system fractures silently.

This audit enumerates the focal points that `layout_authority_protocol.py`,
`layout_authority.py`, `layout_authority_geometry.py`, `_wire.py`, and
`_log.py` implicitly rely on. For each: salience source, written status,
and the cost of breakage.

## Verdict at a glance

- **18 focal points** identified across 5 categories.
- **6** are written down normatively (protocol docstrings, INVARIANTS).
- **9** are assumed — present in code, absent from any spec.
- **3** are partially documented (mentioned but not as contracts).
- The dominant risk is the **id-namespace focal point** — every layer
  depends on `domain:<slug>`, `file:<path>`, etc., but the prefix grammar
  is nowhere written and nowhere validated.

## Category A — Identifier grammar (the most load-bearing focal points)

| # | Focal point | Salience source | Written? | Breakage cost |
|---|---|---|---|---|
| A1 | `domain_id` starts with `domain:` | The smoke test (`layout_authority.py:428`) and every test fixture; nowhere in `protocol.py` | **NO** | Silent: `_DomainRegistry` keys by string; nothing detects a non-prefixed id until cross-layer lookups miss |
| A2 | `file:<path>`, `symbol:<…>`, `tool_hub:<tool>:<domain>` prefixes | Smoke test + JS renderer parses the prefix to choose an icon | **NO** | Renderer mis-classifies; geometry still computes a slot |
| A3 | `node_id` is unique across the whole graph (not just per-kind) | `_slots: dict[str, SlotAssignment]` — single keyspace | **Partial** — protocol says "stable, unique" without scope | A `file:foo` colliding with `domain:foo` overwrites the slot |
| A4 | For `kind == 'domain'`, `domain_id == node_id` (self-reference) | `_validate_node` enforces this | **YES** — NodeDelta docstring + ValueError | — |
| A5 | `tool_name` is one of the 7 keys in `TOOL_LOCAL_ANGLE` (Edit/Write/Read/Grep/Glob/Bash/Task) | `tool_hub_angle` defaults unknown tools to `outward` | **NO** — protocol says non-empty, not "from this set" | Silent fallback; a typo `EDIT` → angle 0 (outward), not the Edit angle |

## Category B — Ordering and arrival (race-window focal points)

| # | Focal point | Salience source | Written? | Breakage cost |
|---|---|---|---|---|
| B1 | Build worker emits `domain` node before its members "most of the time" | I7 hedges: domain MAY arrive late, slot is FINAL | **YES** — INVARIANTS I7 | Member placed against placeholder anchor; permanent |
| B2 | Build worker emits `file` before its `symbol` children | I3 + `_pending_symbols` buffer | **YES** — INVARIANTS I3 | Symbol buffered; flushes on file arrival |
| B3 | Build worker emits `tool_hub` before `file` parented to it | I4: file falls back to domain anchor, FINAL | **YES** — INVARIANTS I4 | File slotted against domain hub angle, never reseats |
| B4 | Build worker emits both endpoints before the edge | I5 + `_pending_edges` ring buffer (cap 100k) | **YES** — INVARIANTS I5 | Beyond 100k pending: oldest edge silently dropped |
| B5 | `seq` is the only ordering clients should trust | I2; SlotAssignment.seq docstring | **YES** | — |

## Category C — Coordinate and numeric conventions

| # | Focal point | Salience source | Written? | Breakage cost |
|---|---|---|---|---|
| C1 | Default canvas is 1000×1000; client rescales to viewport | `width=1000.0, height=1000.0` defaults in `build_authority` and SlotAssignment docstring | **Partial** — mentioned in SlotAssignment.x docstring, not in INVARIANTS | Client that assumes pixel-perfect coords gets rubber-banding |
| C2 | Origin is top-left, +y goes down (matches HTML canvas, not math) | Implicit in geometry math (`cy = height/2`) | **NO** | A renderer using +y up will see the layout vertically mirrored |
| C3 | All slots are finite floats (no NaN, no inf) | I1 — wire layer rejects | **YES** | ValueError at wire boundary |
| C4 | `total_in_kind` is computed per `(domain_id, kind)` bucket, not per `(domain_id, kind, parent)` | `_counts` keying in `_compute_assignment` | **NO** | A kind expecting per-parent buckets (e.g. files-per-hub) gets a domain-wide idx instead |
| C5 | Symbol idx uses a SEPARATE counter, keyed by `("__sym__", parent_file_id)` | `_geometry_ctx` for kind == "symbol" | **NO** — magic key `"__sym__"` is invisible to anyone not reading `layout_authority.py:324` | Drift if any other code path writes `_counts[("__sym__", x)]` |

## Category D — Lifecycle and idempotence

| # | Focal point | Salience source | Written? | Breakage cost |
|---|---|---|---|---|
| D1 | `request_subtree` is idempotent and safe on unknown domains | Protocol docstring: "returns silently" | **YES** | — |
| D2 | A SlotAssignment for a given `node_id` is FINAL except after `request_subtree` | I2 + I4 + I7 (multiple invariants imply this jointly) | **Partial** — never stated as one rule | Client caches that assume "first wins" diverge from one assuming "last wins" |
| D3 | `done` event terminates the stream; clients close on receipt | `_wire.format_done` + the `done` event kind in module docstring | **NO** as a client contract | Client that keeps polling after `done` sees no new data forever |

## Category E — Encoding (the wire-level focal points)

| # | Focal point | Salience source | Written? | Breakage cost |
|---|---|---|---|---|
| E1 | Pipe `\|` is the field separator; ids/kinds may not contain it | `_validate_id`, `_validate_kind`, the wire docstring | **YES** — wire module preface + ValueError | — |
| E2 | UTF-8 throughout; ids are ASCII identifier-ish in practice | `_MAX_KIND = 32`, comment "ASCII identifier ceiling" | **Partial** — only `kind` width is enforced; `node_id` width is unbounded | A multi-KB id explodes wire bandwidth and SSE buffer reasoning |

## The five focal points that should be promoted to written contracts

Ranked by breakage cost × silence of the failure mode:

1. **A1/A2 — id-prefix grammar.** Add to `protocol.py` an enum or regex
   table: `domain:<slug>`, `file:<path>`, `symbol:<qual>`, `tool_hub:<Tool>:<domain_slug>`,
   `discussion:<…>`, `memory:<…>`, `mcp:<…>`, `entity:<…>`, `skill:<…>`,
   `hook:<…>`, `command:<…>`, `agent:<…>`. Validate at `add_node`. The
   JS renderer ALREADY depends on this grammar to choose icons.
2. **A5 — tool_name allowed set.** Either reject unknown tool names or
   document the silent-fallback behavior in NodeDelta. Today, `tool_name="EDIT"`
   produces an `outward` angle that looks correct in isolation but
   collides with an actual `outward` placement.
3. **C2 — y-axis orientation.** A one-line note in `compute_slot`'s
   docstring: "Coordinates are HTML-canvas convention: +y is down."
4. **C4 — bucketing of `total_in_kind`.** State explicitly that the idx
   passed to `compute_slot` is the **domain-wide** rank for that kind,
   not the per-hub rank. The Carnot/Ginzburg audits already noticed
   this; Schelling formalizes it as a focal-point disclosure.
5. **D2 — finality rule.** One paragraph in INVARIANTS: "After
   SlotAssignment is emitted for `node_id`, all subsequent emissions
   for the same `node_id` MUST come from `request_subtree`. Clients
   MUST update by `seq` (I2). Caches keyed by node_id MUST be
   last-write-wins."

## Tipping-point note (Schelling Move 2)

The id-prefix focal point (A1/A2) is at a tipping point right now: 12
node kinds, all currently using the `<kind>:<rest>` convention, none
validated. Add one off-pattern producer (e.g. a tool that emits
`mem-<id>` instead of `memory:<id>`), and the renderer's prefix-based
icon dispatch silently mis-classifies an entire kind. Cost of preventing
the cascade today: ~10 lines in `_validate_node`. Cost after the
cascade: every client that ever shipped now has divergent fallback
logic.

## Hand-offs

- **Implementation** → engineer: add a `KIND_ID_PREFIX: dict[str, str]`
  table in `protocol.py`, validate in `_validate_node`, write a unit
  test for each kind.
- **Comparative evidence** → Mill: compare prefix strictness in two
  reference SSE-graph protocols (D3-force, Cytoscape).
- **Formal proof** → Lamport: prove that finality (D2) plus monotonic
  seq (I2) implies a total order on node placements that all subscribers
  agree on, even with `request_subtree` interleavings.
