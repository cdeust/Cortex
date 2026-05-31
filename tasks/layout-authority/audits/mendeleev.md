# Mendeleev Audit — Periodic Table of NODE_KINDS

Survey scope: the 12 NODE_KINDS declared in
`mcp_server/server/layout_authority_protocol.py:30-33`, placed by
`layout_authority_geometry.compute_slot`. Goal: choose axes that make
the regularity visible, leave gaps where the pattern demands a kind
that does not exist, and predict the missing kinds' properties.

## Axes considered

| Row axis | Column axis | Pattern density | Gap visibility | Chosen? |
|---|---|---|---|---|
| rendering radius | aggregator/leaf | medium | low | no |
| hierarchy depth (L0..L6) | scope (private / domain / cross-domain) | high | high | YES |
| cardinality (1, few, many) | kind-bucket size | medium | low | no |

Chosen axes:
- **Rows = hierarchy depth** (L0 root → L6 leaf). Aligns with the
  shells already encoded by the radii constants (lines 28-36).
- **Columns = scope** = where the kind's edges reach: *Private* (inside
  one parent), *Domain-local* (inside one domain hub), *Cross-domain*
  (edges span multiple domains).

## The table

```
                      Private           Domain-local              Cross-domain
                  (1 parent only)    (one domain shell)         (spans domains)
─────────────────────────────────────────────────────────────────────────────────
L0 root           ──                 ──                         ⟦super_domain⟧ †
L1 hub            ──                 domain (r=anchor)          ⟦project_hub⟧ †
L2 aggregator     ──                 tool_hub (r=140)           mcp (r=50, inward)
L3 setup-ring     ──                 skill, hook, command,      ⟦shared_skill⟧ †
                                     agent (r=70)
L4 lane           ──                 discussion (r=150),        ⟦discussion_hub⟧ †
                                     memory (r=150)             ⟦memory_hub⟧ †
L5 file orbit     ──                 file (r=220)               ──
L6 leaf           symbol (petal      entity (UNPLACED!) ‡       ⟦cross_entity⟧ †
                  around file)
```

Legend: `⟦name⟧ †` = predicted gap. `‡` = known-item outlier (in
NODE_KINDS but `compute_slot` has no branch — falls through to anchor
fallback, geometry.py:218).

## Outliers in known items

| Item | Expected position | Actual | Diagnosis |
|---|---|---|---|
| `entity` | L6 cross-domain leaf with own radius | declared in NODE_KINDS, **no branch in `compute_slot`** — silently emits at the domain anchor (collides with `domain` node) | **Wrong axis / missing implementation.** Either entity is an L6 leaf and needs its own slot helper, or it is the placeholder for the predicted `cross_entity` family and should be moved to the inward/cross-domain side (mirror of `mcp`). |
| `mcp` | L2 aggregator | placed *inward* (r=50, opposite of outward) | Correct: mcp is the only declared cross-domain aggregator, so it lives on the inward face where edges to other domains fan visibly. The pattern says: cross-domain kinds occupy the inward hemisphere. |
| `tool_hub` | L2 domain-local aggregator | placed outward (r=140) | Correct. Confirms the row/column axes: domain-local aggregators go outward, cross-domain aggregators go inward. |

## Predicted gaps

| Gap | Position (L, col) | Predicted properties | Edges it would carry | Falsifiability test |
|---|---|---|---|---|
| **`super_domain`** | L0, cross-domain | Anchor for clusters of related domains (e.g. all Cortex sub-projects). Placement: graph centroid (cx,cy) — the only reserved coordinate. Radius 0; domains orbit it on the Fibonacci spiral with `base_r` derived from `super_domain` count. Bucket size: 1–5. | `domain → in_super_domain → super_domain`; `super_domain → about_entity → entity` for cross-project topics. | If we ever render >1 project, do all domain anchors collapse to one centroid? If yes, this gap is real. |
| **`project_hub`** | L1, cross-domain | Per-repo aggregator below super_domain; placement: inward arc of the super_domain at r ≈ MCP_R/2. Bucket size: 1 per repo. | `domain → member_of → project_hub`; `project_hub → invoked_mcp → mcp`. | Does any current visualization need to group "all domains from repo X" without flattening to one domain? |
| **`discussion_hub`** | L4, cross-domain | Mirror of `tool_hub`: aggregates discussions that touch multiple domains (cross-project conversations, ADRs, RFCs). Radius ≈ DISC_R + 30. Sector: side-lane, but on the *inward* hemisphere so it parallels `mcp`. | `discussion → member_of → discussion_hub`; `discussion_hub → discussion_touched_file → file` (cross-domain). | Today, a discussion that references files in 3 domains gets pinned to one arbitrary domain. Does that hurt readability? Yes → gap is real. |
| **`memory_hub`** | L4, cross-domain | Mirror of above for memories. The thermodynamic memory model already has anchored / cross-domain memories (see `core/thermodynamics.py`); they currently render in one domain's memory lane only. Radius ≈ MEM_R + 30, inward side-lane. | `memory → member_of → memory_hub`; `memory_hub → about_entity → entity`. | Anchored memories with `domain_id == "*"` exist — where are they placed today? Nowhere correctly. Gap confirmed. |
| **`shared_skill`** | L3, cross-domain | Skills/agents/hooks invoked from >1 domain (e.g. the engineer agent, the refactorer). Placement: inward setup ring at r ≈ SETUP_R, mirror of the outward setup ring. | `domain → invoked_skill → shared_skill`; `shared_skill → spawned_agent → agent`. | Count distinct domains that invoke `engineer.md`. If >1, today it is duplicated as N separate `skill` nodes. |
| **`cross_entity`** (or: fix `entity`) | L6, cross-domain | Knowledge-graph entities that link memories/files across domains. Placement: inward leaf ring at r ≈ SYM_R_OUTER, jittered like symbols but anchored to the inward face. | `memory → about_entity → cross_entity`; `discussion → about_entity → cross_entity`; `cross_entity ↔ cross_entity` (relationship edges, currently no edge_kind for this — see edge gaps). | The `entity` kind is declared but has no slot — this gap is already a bug. |

## Missing-family check

Whole **column missing**: the *cross-domain hemisphere* (inward face)
is sparsely populated — only `mcp` lives there today. The table
predicts at least 5 more inhabitants. Adding the column is structural,
not a patch: the inward hemisphere is currently ~90% empty space,
which is why cross-domain edges look like a tangle rather than a fan.

Whole **row missing**: **L0 (root)** has no member. Every domain is
treated as a top anchor with no parent. For multi-project Cortex
deployments this row needs `super_domain`.

## Edge-kind gaps implied by the node-kind gaps

| Predicted edge | Connects | Why it's missing |
|---|---|---|
| `in_super_domain` | domain → super_domain | no L0 today |
| `member_of` (extended) | discussion → discussion_hub, memory → memory_hub | aggregation in cross-domain lanes |
| `entity_relation` | entity ↔ entity | knowledge graph has relationships in PG, but no edge_kind exposes them |
| `shared_invoked` | domain → shared_skill | distinguishes cross-domain reuse from local skill |

## Predictions summary (falsifiable)

1. Fixing `entity` (give it an L6 inward branch in `compute_slot`)
   will eliminate the silent collision at the domain anchor —
   verifiable by counting nodes with `(x,y) == anchor` in any current
   slot stream.
2. Adding `discussion_hub` will reduce cross-domain edge length for
   any discussion touching ≥2 domains — measurable on the BEAM /
   LongMemEval visualization runs.
3. Adding `super_domain` is a no-op until the layout serves >1 repo.
   Until then, the gap is *predicted but not yet pressing*.
4. The inward-hemisphere column is real: every cross-domain kind that
   exists (`mcp`) lives there, and every kind we predict to be added
   for cross-domain reach also belongs there. Axes are vindicated.

## Hand-offs

- Implementation of the `entity` slot branch → engineer (small fix,
  geometry.py:215-218; add an `r ≈ SYM_R_OUTER` inward leaf helper).
- Empirical measurement of cross-domain discussion / memory frequency
  to justify `discussion_hub` / `memory_hub` → Curie.
- Bracket estimate of node count per predicted bucket at full scale →
  Fermi.
- Formal definition of "scope" axis (Private vs Domain-local vs
  Cross-domain) as a typed property of `NodeDelta` → Shannon.

## Compliance

- Sources: `layout_authority_protocol.py:30-40`, `layout_authority_geometry.py:28-218`,
  `layout_authority.py:300-337`, `workflow_graph.js` lines 43-541
  (referenced as the visual ground truth).
- No invented constants. All radii cited from geometry.py with line numbers.
- `entity` outlier verified by reading compute_slot dispatcher: no
  branch matches `entity`, fallback returns the anchor.
