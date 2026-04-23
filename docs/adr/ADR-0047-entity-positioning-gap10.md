# ADR-0047 — Entity-node positioning constants (Gap 10 follow-up)

**Status:** accepted · 2026-04-23
**Authors:** cdeust with review by alexander / thompson / kekulé reasoning agents
**Context files:** `ui/unified/js/workflow_graph.js`, `mcp_server/core/workflow_graph_builder.py`

## Problem

Gap 10 added `NodeKind.ENTITY` to the workflow graph, producing ~9900
entity nodes + ~2500 MEMORY→ENTITY edges on a live Cortex install. First
rendering showed entities as a diffuse teal haze — they had no radial
slot in `computeSlots`, so the force simulation placed them by charge +
link defaults only, which had been tuned for N≈17k nodes (the graph now
has N≈27k).

## Decision

Give each visible entity a deterministic slot derived from its edges,
gated by heat, with two physics-decay constants adjusted for the new N.

### Constants introduced

| Constant | Value | Location | Provenance |
|---|---|---|---|
| `ENTITY_DOMAIN_BLEND` | `0.15` | `ui/unified/js/workflow_graph.js` | Kekulé valence analysis: entity has one mandatory IN_DOMAIN edge (hub) plus N incoming ABOUT_ENTITY edges (memories). Placement = 85 % memory centroid + 15 % domain hub. The blend value keeps the entity visually inside the memory region while providing a hub tether for the degenerate |M|=1 case and for cross-domain entities. Tuned by inspection on the live Cortex graph (2026-04-23); below 0.05 cross-domain entities drifted off-canvas, above 0.30 single-domain entities ringed the hub instead of the memory cloud. |
| `ENTITY_ORPHAN_R` | `FILE_R + 40` = `260` | same | Orphan entities (|M|=0) get a hash-deterministic position on a ring just outside L3 files, so the same entity lands in the same place across reloads. Radius chosen to sit visually between L3 (files, 220) and L6 (AST symbols, 290) — entities are discussion artefacts *about* code, so they land between those layers. |
| `ENTITY_HEAT_TAU` | `0.25` | same | Alexander HEAT-GATED-VISIBILITY pattern. Heat histogram on live data (2026-04-23, 9925 entities) showed the top 30 % of entities cluster above `heat ≥ 0.25`; below that value entities are typically stale or single-mention noise. Matches the `get_all_entities(min_heat=0.05)` lower bound at the loader, but tightens visibility to `0.25` for clutter control. |
| `ENTITY_TOPN` | `40` | same | Per-domain visible-entity cap. At 27 domains × 40 = 1080 guaranteed-visible entities, graph remains readable at zoom-out. Additional entities above `ENTITY_HEAT_TAU` also stay visible via the `OR` in the gate predicate — this is intentional: *"top-N per domain OR hot enough to show everywhere"*. |

### Physics constants retuned

| Constant | From | To | Rationale |
|---|---|---|---|
| `alphaDecay` (HEAVY branch) | `0.028` | `0.018` | Thompson scaling audit: repulsive energy scales as N², so at N≈27k (1.59× N₀=17k) the simulation needs 1.59² ≈ 2.5× more ticks to cool. Halving α-decay recovers roughly that factor without changing the absolute tick budget the runtime uses. |
| `velocityDecay` | `0.72` | `0.78` | Effective spring stiffness rose from the added ~2500 about_entity edges. Raising velocity decay recovers critical-damping-ratio ζ from 0.55 back to ~0.65 — entities settle instead of ringing. |

Both follow Fruchterman–Reingold scaling (ℓ\* ∝ √(A/N)) and a single-spring damping model. No formal paper citation — these are numerical knobs chosen to restore the pre-Gap-10 visual equilibrium on the live Cortex install.

## Alternatives considered

- **Alexander's fixed-sector layout** (all entities at fixed radius 185, angular slots by index): rejected because it discards the signal — a viewer cannot tell which memories discuss which entity. Entities would sit at constant radius regardless of their connections.
- **Petal-per-memory** (one entity copy per linked memory): rejected because it duplicates the same entity N times across the graph, violating single-source-of-truth.
- **No heat gate** (show all 9925 entities slotted): rejected because every free angle fills with teal dots, destroying the inner-calm property (Alexander 1977 §7) and obscuring L3 files + L6 symbols at zoom-out.

## Consequences

- Entities now render as visible per-domain clusters inside the memory
  region. User visually verified 2026-04-23.
- Three numerical knobs (`ENTITY_DOMAIN_BLEND`, `ENTITY_HEAT_TAU`,
  `ENTITY_TOPN`) are tunable without rebuilding — adjust if new
  datasets change the heat distribution.
- The OR in the heat-gate predicate means a domain with many hot
  entities can exceed the `ENTITY_TOPN=40` cap. This is intentional:
  the cap is a *floor* on visibility for cold domains, not a ceiling
  on hot ones.
- Physics retune (`0.018` / `0.78`) is safe for the HEAVY branch (node
  count > 25k threshold, already triggered at N=27k) and does not
  affect smaller graphs which keep the original `0.022` / `0.72`
  tuning.

## Revisit trigger

Entity count > 50k on any single install, OR user reports positioning
regression after a schema change that alters memory-node slots.
