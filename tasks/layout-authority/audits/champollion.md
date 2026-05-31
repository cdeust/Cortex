# Champollion Audit — Bilingual Decoding of the Layout Law

**Rosetta Stone:** the layout law exists in two languages.
- **Greek text (known, original):** `ui/unified/js/workflow_graph.js` (734 lines, JavaScript)
- **Hieroglyphs (translated):** `mcp_server/server/layout_authority_geometry.py` (218 lines, Python)

**Anchors used:** the radius constants and `TOOL_LOCAL_ANGLE` proper names — they cannot be "translated," only spelled identically. Verified pass-through.

**Counting argument.** JS: 8 radii + 3 sector angles + 7 tool angles + 4 entity + 14 edge dist + 14 edge str + 12 kind radii + 12 kind colors + 2 cross-domain + 1 canvas = **77**. Python: 9 radii + 3 sector + 7 tool + 0 else = **19**. The 58-constant gap is a deliberate scope boundary (Py = slot geometry; JS = rendering+physics+styling) — correct unless Py becomes the single source of truth.

---

## Constants Table — every numeric, both sides

### Slot geometry — IN PYTHON, must agree byte-for-byte

| Constant | JS value | JS line | Python value | Py line | Drift |
|---|---|---|---|---|---|
| SETUP_R | 70 | 43 | 70.0 | 28 | none |
| TOOL_R | 140 | 44 | 140.0 | 29 | none |
| FILE_R | 220 | 45 | 220.0 | 30 | none |
| DISC_R | 150 | 46 | 150.0 | 31 | none |
| MEM_R | 150 | 47 | 150.0 | 32 | none |
| MCP_R | 50 | 48 | 50.0 | 33 | none |
| SYM_R_OUTER | 290 | 52 | 290.0 | 34 | **declared, never used in Py** |
| SYM_R_SPREAD | 32 | 53 | 32.0 | 35 | **declared, never used in Py** |
| SYM_CLUMP_R | 18 | 54 | 18.0 | 36 | none (Py uses) |
| SECTOR_SETUP_HALF | π/2.6 | 63 | math.pi/2.6 | 39 | none |
| SECTOR_SIDE_HALF | π/6.5 | 64 | math.pi/6.5 | 40 | none |
| SECTOR_SIDE_ANGLE | π·0.72 | 65 | math.pi*0.72 | 41 | none |
| TOOL_LOCAL_ANGLE.Edit | 0 | 77 | 0.0 | 45 | none |
| TOOL_LOCAL_ANGLE.Write | -π/12 | 78 | -math.pi/12 | 46 | none |
| TOOL_LOCAL_ANGLE.Read | π/12 | 79 | math.pi/12 | 47 | none |
| TOOL_LOCAL_ANGLE.Grep | -π/6 | 80 | -math.pi/6 | 48 | none |
| TOOL_LOCAL_ANGLE.Glob | π/6 | 81 | math.pi/6 | 49 | none |
| TOOL_LOCAL_ANGLE.Bash | -π/3.6 | 82 | -math.pi/3.6 | 50 | none |
| TOOL_LOCAL_ANGLE.Task | π/3.6 | 83 | math.pi/3.6 | 51 | none |
| golden angle (φ) | π·(3-√5) | 323 | math.pi*(3-√5) | 55 | none |
| baseR floor coeff | 0.42 | 320 | 0.42 | 68 | none |
| baseR shell pad | 60 | 318 | 60.0 | 66 | none |
| baseR scale | 0.65 | 321 | 0.65 | 68 | none |
| outward upward-bias threshold | 5 px | 464 | 5.0 px | 88 | none |
| Setup jitter step | 8 (idx%2) | 504 | 8.0 (idx%2) | 101 | none |
| File jitter step | 4 ((idx%3)-1) | 492 | 4.0 ((idx%3)-1) | 128 | none |
| File arc base / scale / cap | 0.08 / 0.015 / 0.35 | 489 | 0.08 / 0.015 / 0.35 | 126 | none |
| Disc jitter step | 6 (idx%3) | 516 | 6.0 (idx%3) | 141 | none |
| Disc arc widen / cap | 0.04 / π/3 | 513 | 0.04 / math.pi/3 | 139 | none |
| Mem jitter step | 8 (idx%4) | 528 | 8.0 (idx%4) | 154 | none |
| Mem arc widen / cap | 0.03 / π/2.5 | 525 | 0.03 / math.pi/2.5 | 152 | none |
| MCP jitter step | 0.25 | 538 | 0.25 | 164 | none |
| Symbol clump idx coeff | n/a (no slot) | — | 3.0 (idx%4) | 177 | **JS-NULL vs Py-DETERMINISTIC** |
| Symbol seed past-file | 30..150 random | 236 | n/a | — | **JS only** |
| Symbol angular jitter | ±0.075 random | 237 | n/a | — | **JS only** |

### Entity layer (L5+E, ADR-0047) — JS ONLY

| Constant | JS value | Py | Status |
|---|---|---|---|
| ENTITY_DOMAIN_BLEND | 0.15 | absent | Py cannot slot entities |
| ENTITY_ORPHAN_R | FILE_R+40 = 260 | absent | Py cannot slot orphans |
| ENTITY_HEAT_TAU | 0.25 | absent | no heat gate server-side |
| ENTITY_TOPN | 40 | absent | no per-domain floor server-side |

### Rendering / physics / styling — JS ONLY (out of Py scope)

KIND_RADIUS (12), KIND_COLOR (12), SHELL_LEVELS (4), EDGE_DISTANCE (14),
EDGE_STRENGTH (14), CROSS_DOMAIN_{DISTANCE=260, STRENGTH=0.02},
CANVAS_THRESHOLD=2000, charge (-620/-140/-80/-22/-28), alphaDecay (0.018/0.022),
velocityDecay 0.78, slotK (1.2/0.85), distanceMax 180, collide 0.92,
symMultiCenter 0.06, interDomain k=0.08·8000. **JS only — by design.**

---

## Drift Findings

### Drift 1 — Symbol slotting semantics diverge (BYTE-LEVEL DRIFT)

JS (lines 595–601): symbols intentionally have **no slot**. They are seeded once
in `mount()` (lines 216–243) along the outward ray with `Math.random()` past-file
distance ∈ [30, 150] and angular jitter ±0.075 rad, then `defined_in / calls /
imports / member_of` forces position them.

Python `slot_for_symbol` (lines 170–179) places each symbol on a **deterministic
petal**: `angle = 2π·(idx+0.5)/total_in_file`, `r = SYM_CLUMP_R + (idx%4)·3 ∈
{18, 21, 24, 27}`. No randomness, no force interaction.

This is a **dual-nature collision**. JS is force-driven; Python is closed-form
geometric. They will produce visibly different layouts for any graph with
symbols. The Python module's docstring claims "Match the visual conventions of
ui/unified/js/workflow_graph.js" — for symbols this is false.

**Resolution required:** decide which language is authoritative. Either
(a) Python drops `slot_for_symbol` and emits no slot for `kind == "symbol"`
(matching JS), or (b) JS adopts the deterministic petal (replacing the random
seed in mount()). The audit recommends (a) — preserves the force-driven
"flow into interlock space" semantic that Alexander's multi-centroid force
relies on.

### Drift 2 — SYM_R_OUTER (290) and SYM_R_SPREAD (32) imported but dead in Python

Python declares both constants at module load but never references them. They
are parameters of the JS-side symbol shell that Python's petal does not honor.
Per project rule "no dead code" — either remove them, or use them. If Drift 1
is fixed by route (a), they should be deleted from the Python file.

### Drift 3 — Entity layer absent server-side

JS slots entities as Kekulé centroids of linked memories blended 15% to the
domain hub, with heat-gate OR top-N visibility. Python has no `slot_for_entity`.
Today this is silent because the server pipeline does not yet emit entity
positions; if entity slotting moves server-side, Python will need:
  - `slot_for_entity(domain_hub, mem_slots, heats, blend=0.15)`
  - `slot_for_orphan_entity(domain_hub, entity_id_hash, r=FILE_R+40)`
  - `entity_visible(idx, heat, top_n=40, tau=0.25)` predicate

### Drift 4 — Polysemy hand-off (Wittgenstein-flagged)

`outward` is used as both *radial direction from center* (line 462) and *axis
from which local tool angles are measured* (line 472, `t = outward + local`).
Both files share the collision; not byte-level drift but recorded for the SoT.

---

## Stone Tablet — Single Source of Truth

The values below are canonical. Both `workflow_graph.js` and
`layout_authority_geometry.py` MUST agree byte-for-byte. Any future change
edits this table first, both files second, and ships only when both match.

```
SETUP_R                = 70
TOOL_R                 = 140
FILE_R                 = 220
DISC_R                 = 150
MEM_R                  = 150
MCP_R                  = 50
SYM_R_OUTER            = 290    # JS-side symbol shell
SYM_R_SPREAD           = 32     # JS-side symbol shell
SYM_CLUMP_R            = 18     # symbol seed clump

SECTOR_SETUP_HALF      = π / 2.6
SECTOR_SIDE_HALF       = π / 6.5
SECTOR_SIDE_ANGLE      = π · 0.72

TOOL_LOCAL_ANGLE = {
    Edit:  0,
    Write: -π / 12,
    Read:   π / 12,
    Grep:  -π /  6,
    Glob:   π /  6,
    Bash:  -π / 3.6,
    Task:   π / 3.6,
}

GOLDEN_ANGLE           = π · (3 − √5)
BASE_R_FLOOR_COEFF     = 0.42
BASE_R_SHELL_PAD       = 60
BASE_R_SCALE           = 0.65
OUTWARD_BIAS_THRESHOLD = 5.0

# Per-kind slot jitter
SETUP_JITTER           = (idx % 2) · 8
FILE_JITTER            = ((idx % 3) − 1) · 4
DISC_JITTER            = (idx % 3) · 6
MEM_JITTER             = (idx % 4) · 8
MCP_JITTER_STEP        = 0.25

# Per-kind arc widening
FILE_ARC               = min(0.35, 0.08 + n · 0.015)
DISC_ARC               = SECTOR_SIDE_HALF·2 + min(π/3,   n · 0.04)
MEM_ARC                = SECTOR_SIDE_HALF·2 + min(π/2.5, n · 0.03)
SETUP_ARC              = SECTOR_SETUP_HALF · 2

# Symbols: NO slot. Force-driven from `defined_in / calls / imports / member_of`.
# Initial seed (JS only): outward ray past parent file, distance random ∈ [30,150]
# px, angular jitter ±0.075 rad. Python should match by emitting no slot.

# Entity layer (JS only today; promote to tablet if entity slotting moves server-side):
ENTITY_DOMAIN_BLEND    = 0.15        # ADR-0047
ENTITY_ORPHAN_R        = FILE_R + 40 # ADR-0047
ENTITY_HEAT_TAU        = 0.25        # ADR-0047
ENTITY_TOPN            = 40          # ADR-0047
```

---

## Verdict

- **35 slot-geometry constants** match byte-for-byte; translation faithful.
- **1 byte-level semantic drift**: `slot_for_symbol` is deterministic in Py vs. force-driven in JS — visible divergence guaranteed for any graph with symbols.
- **2 dead constants** in Py (`SYM_R_OUTER`, `SYM_R_SPREAD`) — no callers.
- **4 entity constants** missing in Py (acceptable today; tracked for promotion).
- **58 rendering/physics constants** legitimately JS-only (out of Py scope).

**Recommendation:** apply Drift-1 route (a) — drop `slot_for_symbol`, drop
`SYM_R_OUTER`/`SYM_R_SPREAD`. Promote the tablet block to
`tasks/layout-authority/SPEC.md` that both files cite by line in their headers.
