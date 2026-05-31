# Bruner Audit — Layout-Authority Narrative Arc

**Mode determination.** The question "is the user's experience of opening the
visualization a coherent story?" is *narrative*, not paradigmatic. Latency
budgets and event-emission correctness are paradigmatic concerns owned by
Lamport / Dijkstra. Here we treat the user's lived experience as a story with
a Begin–Middle–End structure and ask: where does the story break, where does
meaning leak out, and where is the canonical expectation breached without
narrative repair?

Sources grounded in code: `ui/unified/js/polling.js`, `ui/unified/js/workflow_graph_tilemap.js`,
`mcp_server/handlers/open_visualization.py`, `mcp_server/handlers/recompute_layout.py`,
`mcp_server/handlers/quadtree_handler.py`.

---

## 1. The user's three-act story (as currently told)

| Act | User cognitive action | System feedback observed | Source |
|---|---|---|---|
| BEGIN | "I want to see my brain" — invokes `cortex:open_visualization` or opens URL | Browser navigates; loader DOM shows "Loading tilemap dependencies…" | `tilemap.js:123` |
| MIDDLE-1 | Waits, watches loader | "Fetching quadtree…" → on 503 → silent self-heal `recompute_layout` → "Layout ready (N nodes); fetching quadtree…" | `tilemap.js:134-156` |
| MIDDLE-2 | Sees first tiles fade in | deck.gl tiles arrive z=0 → z=1 → z=2 (no explicit textual signal) | `tilemap.js:269-284` |
| END | Pans, zooms, clicks node | Hover layer resolves via flatbush; side panel opens | `tilemap.js:87,261-262` |

Parallel (legacy 3D `polling.js` path): "Building graph..." retry loop, then
`updateStatus('Online (N nodes)')` and loader fades. Two paths, two narratives.

---

## 2. Pentad analysis

| Element | Tilemap path | In balance? |
|---|---|---|
| Agent | The user, *plus* an invisible second agent: the layout worker that triggers `recompute_layout` | **No** — second agent is hidden |
| Act | "Open visualization" → expand into "render my graph" | OK |
| Scene | Browser + cold/warm cache + igraph/datashader extras maybe-installed | **No** — scene state opaque |
| Agency | deck.gl Tile layer + Arrow-IPC quadtree + server tile PNGs | OK once running |
| Purpose | Explore graph structure, find specific nodes | OK |
| **Breach** | 503 on `/api/quadtree` ("no_layout") OR "viz_tile_extra_missing" | Recovery exists for first; second exposes raw install commands |

The pentad is unbalanced at **Agent** and **Scene**. The user does not know a
second agent exists (the layout recompute) and cannot read the scene's state
(is the cache cold? is igraph installed? are tiles streaming or stalled?).

---

## 3. Canonical breach detection

**Canonical expectation** the user brings: "I click, it loads, I see my graph
the way maps load — coarse-then-detailed, monotonically."

**Actual breaches:**

1. **Silent recompute breach.** `tilemap.js:134-156` does a self-healing
   `recompute_layout` POST when `/api/quadtree` 503s. The status line flickers
   from "Fetching quadtree…" → "Layout ready (N nodes); fetching quadtree…"
   in one beat. The user sees one word change. They never learn that a
   non-trivial computation just ran on their behalf. **Meaning lost:** the
   system did invisible heroic work; the story does not credit it.

2. **Tile-arrival breach.** Once tiles begin arriving the status text says
   nothing. Tiles fade in at zoom=0 (one big blurry blob), then sharpen as
   the user zooms. Without a phase indicator, the user cannot distinguish
   "still loading" from "this IS the rendered graph" — especially at z=0
   where Datashader output looks like a smear.

3. **Extras-missing breach.** `viz_tile_extra_missing` shows raw `pip install`
   commands inline (`tilemap.js:167-171`). This is a paradigmatic message
   ("here is the fix") inserted into a narrative moment ("I am exploring my
   memory"). The mode-mismatch breaks immersion.

4. **Two-narrative breach.** `polling.js` (3D path) and `tilemap.js` tell
   *different stories* with different vocabulary: "Building graph..." vs
   "Fetching quadtree…", "Online (N nodes)" vs no explicit ready state. A
   user who reloads or switches `?viz=` modes lives in two universes.

---

## 4. Identity narrative being constructed

The current story constructs Cortex as **"a fast tool that mostly works and
occasionally has install issues."** That identity is *thinner* than the
underlying system warrants — the system is actually doing layered layout
computation, quadtree indexing, server-side Datashader rendering, progressive
tile streaming. The narrative excludes all of this competence.

Compare the implicit story to a richer one: **"a microscope into your
cognitive history that builds a map at the resolution you ask for."** That
identity requires phase signals to be visible — the user must witness the
map being built, not just receive the result.

Excluded from the current narrative: the layout worker, the cache state,
the consolidation pipeline metrics already streamed in `meta.system_vitals`
(`polling.js:60-72`) but never surfaced during the load arc.

---

## 5. Cross-narrative comparison

| Event | `polling.js` says | `tilemap.js` says | Divergence |
|---|---|---|---|
| First fetch | "Loading…" (implicit) | "Loading tilemap dependencies…" | Different vocabulary |
| Server building | "Building graph..." retry every 1s | (no equivalent — assumes layout exists or 503s) | Tilemap has no patient-wait phase |
| No layout cached | (n/a) | 503 → silent self-heal recompute | Hidden work |
| Ready | "Online (N nodes)" | (silent) | Tilemap never declares "ready" |
| Idle exploration | No status updates | No status updates | Both go quiet |

**Significance:** the legacy 3D path tells a *more complete* narrative for
the cold-cache case. The tilemap path is faster but mute. Speed without
narration leaves the user wondering whether what they see is final.

---

## 6. Implications for action — gap-closing recommendations

Ordered by narrative impact, not implementation cost.

### G1. Make the layout-recompute phase visible (HIGH)
*Breach addressed:* silent recompute breach.
The self-heal in `tilemap.js:140-156` should narrate: "No layout cached —
computing graph layout…" → progress while `recompute_layout` runs → "Layout
computed (N nodes, M ms) — fetching quadtree…". This converts hidden agency
into visible heroism.

### G2. Add a five-phase indicator to the loader (HIGH)
*Breach addressed:* tile-arrival breach + canonical expectation.
Replace the binary "loader / no loader" with a labeled phase strip:

  `[1 deps] → [2 layout] → [3 quadtree] → [4 first tiles] → [5 ready]`

Each phase lights up as the corresponding promise resolves. Phase 5 fires
when the first non-zero-zoom tile has rendered (deck.gl `onTileLoad`), not
when fetches complete. This is the END signal the tilemap currently lacks.

### G3. Unify vocabulary across `polling.js` and `tilemap.js` (MEDIUM)
*Breach addressed:* two-narrative breach.
Pick one story per phase: "preparing", "building layout", "streaming tiles",
"ready". Use the same words in both files. Identity coherence requires
narrative coherence.

### G4. Translate the install-extras error into narrative form (MEDIUM)
*Breach addressed:* extras-missing breach.
`tilemap.js:167-171` should say: "Your viz environment is missing the tile
renderer. To finish the setup, run …". Then the install command. The order
matters — narrative frame first, paradigmatic instruction second.

### G5. Surface system_vitals during load, not only after (LOW)
*Breach addressed:* identity-thinness.
`meta.system_vitals` is already populated by `polling.js:60-72`. During the
"building layout" phase show "10,432 memories · 2,108 entities · pipeline
healthy". This lets the loading time itself communicate scale and capability,
turning dead time into identity-building time.

### G6. Emit SSE phase events from `open_visualization` and the layout worker (LOW, structural)
*Breach addressed:* both clients reinventing phase tracking via polling.
Currently neither `open_visualization.py` nor `recompute_layout.py` emits
SSE; clients infer phase from HTTP status codes. A single
`/api/graph/events` SSE stream with `event: phase` / `data: {name, pct}`
would let G2 be implemented without ad-hoc client polling. This is the
structural change the other gaps quietly assume.

---

## 7. Hand-offs and zetetic note

- Latency budgets per phase, idempotency of silent recompute under concurrent
  opens → **Lamport / Dijkstra**.
- "Are users actually confused by the silent recompute?" — comparative test
  of G2 with/without phase indicator → **Mill**.
- "Why did tilemap ship without the narrative the 3D path had?" → **Foucault**.

Claims in §1 and §3 are line-cited. Recommendations in §6 are ordered by
narrative reasoning, not measured user impact — G1, G2, G3 should be
validated by observation before locking in. No user-study data was
consulted; if it exists, it overrides these priorities.
