# Smoke Test — Clinical Graph UI

Manual end-to-end test plan for `ui/clinical/`. Run after every non-trivial
change to JS, CSS, or the server endpoints listed in the project spec.

No Playwright or Puppeteer required. All steps use a browser DevTools console
and normal mouse/keyboard interaction.

---

## Prerequisites

```
# 1. Start the Cortex HTTP server (port 7000 by default).
python -m mcp_server.server.http_viz_server

# 2. Verify the server is up.
curl -s http://localhost:7000/api/graph/progress | python -m json.tool

# 3. Open DevTools (F12 / Cmd+Option+I) and go to the Console tab.
#    Filter level: Verbose (so warn + error + info all appear).
#    Leave this tab open for every step below.

# 4. Check for JS syntax errors before loading the page.
node --check ui/clinical/js/boot.js
node --check ui/clinical/js/streaming.js
node --check ui/clinical/js/navigation.js
node --check ui/clinical/js/renderer.js
node --check ui/clinical/js/chain-panel.js
node --check ui/clinical/js/subgraph.js
node --check ui/clinical/js/api.js
node --check ui/clinical/js/state.js
node --check ui/clinical/js/arrow-ipc.js
# Expected: no output from any command (syntax OK).
```

**Pass criteria that apply to EVERY step:**
- Console shows zero `console.error` calls and zero uncaught exceptions.
- The browser status bar (bottom-left) does not freeze on a network request.

---

## ST-01 — Cold Start: Big-Picture in < 3 s

**Scenario:** Open a fresh tab. The graph must reach a usable state (L0 + L1
rendered) within 3 seconds of the page finishing load.

**Steps:**

1. Open a new Private / Incognito window (clears `localStorage`).
2. Navigate to `http://localhost:7000/clinical/`.
3. Start a stopwatch the moment the tab title reads "Cortex — Clinical Graph".
4. Watch the canvas area (`#graph`).

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Progress bar (`#progress-bar`) appears immediately. | Visible within 0.5 s of page load. |
| 2 | Phase label (`#phase-label`) cycles through phase names. | Text changes at least once within 2 s. |
| 3 | Nodes appear on the canvas. | At least one node rendered within 3 s. |
| 4 | Depth indicator (`#depth-indicator`) shows dot 1 as active. | Dot for depth=1 has class `active`. |
| 5 | No `console.error` in DevTools during load. | Console is clean. |
| 6 | `#status-bar` is hidden or absent. | No error messages shown. |
| 7 | `#incomplete-banner` is hidden. | Banner does not appear. |

**Console command to verify node count (run after 3 s):**

```js
// Should return > 0
document.getElementById('graph').__sigma?.getGraph()?.order
// OR (if __sigma is not exposed):
// Look for a globalThis.cortexGraph reference or check the depth label text.
```

**What to look for in Network tab:**
- `GET /api/graph/progress` → 200
- `GET /api/graph/phase?name=L0` → 200
- `GET /api/graph/phase?name=L1` → 200
- `GET /api/quadtree` → 200 or 503 (both are handled; see ST-06 for 503 path)
- `GET /api/graph/events` → 200, type `text/event-stream`

---

## ST-02 — Zoom In: Next Phase Loads on Scroll

**Scenario:** At depth 1 (Wings view), scroll down to zoom in. The UI must
transition to depth 2 (Departments) and load the L2 phase without errors.

**Steps:**

1. Starting from a loaded ST-01 state (depth 1 visible).
2. Place the mouse cursor over the canvas (`#graph`).
3. Scroll the mouse wheel downward (zoom in) steadily for ~2 seconds.
4. Watch the depth indicator and the canvas.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Depth indicator advances from dot 1 to dot 2. | Dot 2 gains class `active`. |
| 2 | Depth spinner appears briefly. | `#depth-spinner` `display` changes from `none` to `inline-block`, then back. |
| 3 | New nodes fade in on the canvas. | Node count visibly increases; no layout pop. |
| 4 | Depth label text updates. | `#depth-label` text contains "L2" or "Departments". |
| 5 | No duplicate-node error thrown. | Console shows no `addNode` Sigma exceptions. |
| 6 | Console has zero `console.error` entries. | Console is clean. |

**Console command to confirm L2 is loaded:**

```js
// Run in DevTools — should include "L2"
[...window.__cortexLoadedPhases ?? []]
// If the Set isn't exposed globally, check the Network tab for
// GET /api/graph/phase?name=L2 → 200.
```

**Continue scrolling to depth 3 and repeat the checks above for L3.**

---

## ST-03 — Click a Domain Node: Domain Detail Sub-Graph

**Scenario:** Single-click a domain-level node (kind = "domain", depth = 0 or 1).
The chain-of-call side panel must open without modifying the main canvas.

**Steps:**

1. At depth 1 or 2, identify a large hub node (domain nodes are rendered
   larger, 18–30 px, and labelled at all zoom levels).
2. Single-click the node.
3. Observe the right edge of the viewport.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Side panel slides in from the right. | `#side-panel` gains class `open` or equivalent; panel width ≈ 360 px. |
| 2 | Panel header shows the node's label. | `#panel-node-label` text matches the node's label. |
| 3 | Panel header shows kind badge "domain". | `#panel-node-kind` text is "domain". |
| 4 | "Impact" tab is selected by default. | Tab button with `data-tab="impact"` has class `active`. |
| 5 | Neighbour list (`#panel-neighbour-list`) populates. | At least one `<li>` item visible. |
| 6 | Mermaid diagram renders (or shows "chain unavailable"). | `#panel-mermaid-div` is non-empty OR `#panel-chain-error` shows an error message. |
| 7 | Main canvas is unchanged. | No new nodes added; camera position unchanged. |
| 8 | Console has zero `console.error` entries. | Console is clean. |

**Network tab:** expect `GET /api/graph/chain?id=<label>&depth=<n>&type=impact` → 200.

---

## ST-04 — Click a Memory Node: Chain-of-Action Sub-Graph

**Scenario:** Single-click a memory-level node (kind = "memory", depth = 5).
The panel must open showing the Causal tab by default and populate a chain diagram.

**Steps:**

1. Scroll into depth 5 (Beds). Memory nodes are small; hover to find one
   labelled in the tooltip.
2. Single-click a memory node.
3. Observe the panel.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Panel opens; header shows node label. | `#panel-node-label` non-empty. |
| 2 | Panel header shows kind badge "memory". | `#panel-node-kind` text is "memory". |
| 3 | "Causal" tab is selected by default. | Tab button with `data-tab="causal"` has class `active`. |
| 4 | Network request fires for causal chain. | `GET /api/graph/chain?…&type=causal` appears in Network tab → 200. |
| 5 | Mermaid diagram renders OR chain-error message shown. | `#panel-mermaid-div` non-empty OR `#panel-chain-error` non-empty; never both empty. |
| 6 | Main canvas is unchanged. | Camera and node count unaffected. |
| 7 | Console has zero `console.error` entries. | Console is clean. |

**Tab switch test (within the same panel):**

1. Click the "Impact" tab button.
2. Expected: Network tab shows `GET /api/graph/chain?…&type=impact`.
3. Mermaid section updates; neighbour list unchanged.

---

## ST-05 — Esc Closes Sub-Graph; Main View Restored

**Scenario:** With the side panel open (from ST-03 or ST-04), press Escape.
The panel must close and the main graph must be fully interactive again.

**Steps:**

1. Open the panel by clicking any node (ST-03 or ST-04 precondition).
2. Confirm the panel is open: `#side-panel` is visible.
3. Press the `Escape` key.
4. Confirm the panel is closed.
5. Click on a canvas node again.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Panel slides out after Escape. | `#side-panel` loses its open class or transitions off-screen within 300 ms. |
| 2 | Main canvas is fully interactive. | Clicking a node opens the panel again (no stale event listener). |
| 3 | Panel history stack is cleared. | Back button (`#panel-back-btn`) is absent or disabled when panel re-opens fresh. |
| 4 | `#status-bar` is still hidden. | No error was triggered by closing the panel. |
| 5 | Console has zero `console.error` entries. | Console is clean. |

**Additional close paths to verify:**

- Click the `×` button (`#panel-close-btn`) → panel closes.
- Click on the empty canvas (stage) while panel is open → panel closes.
- Open panel → click a neighbour item inside the panel → panel replaces
  content (does NOT close); then Escape closes it.

---

## ST-06 — SSE Streaming: Nodes Stream In on a Fresh Build

**Scenario:** On a server where `full_ready` is `false` (graph still being
built), open the page and observe the SSE stream populating the graph
incrementally.

**Setup — force cold server state:**

```bash
# Stop the server, restart it without a cached layout.
# Or on a machine where Cortex memory DB is populated but the server
# has just started and DrL layout has not been run yet:
curl -s http://localhost:7000/api/quadtree
# Expect: 503 {"reason":"no_layout"}
```

**Steps:**

1. Navigate to `http://localhost:7000/clinical/` with DevTools Network tab open.
2. In the Network tab, filter by `events` to find the SSE stream.
3. Click on the SSE request; select the "EventStream" sub-tab (Chrome) or
   "Response" (Firefox).
4. Observe the stream.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | SSE request appears with status 200, type `text/event-stream`. | Listed in Network tab within 1 s. |
| 2 | Batches arrive with `event: batch`. | EventStream tab shows at least one `batch` event within 5 s. |
| 3 | Canvas node count grows as batches arrive. | Visible nodes increase over time without a page reload. |
| 4 | Quadtree 503 is handled gracefully. | Status bar shows a brief "circular layout" or similar message (or stays silent); no `console.error`. |
| 5 | `GET /api/recompute_layout` fires once. | Network tab contains exactly one request to `/api/recompute_layout`. |
| 6 | After SSE `done` event, no further SSE requests appear. | Network tab does not show a second EventStream request (source.close() worked). |
| 7 | `#incomplete-banner` stays hidden. | Banner does not appear (stream completed). |
| 8 | Console has zero `console.error` entries. | Console is clean. |

**Quadtree retry path (when 503 at boot):**

After the SSE `done` event fires, the client retries `GET /api/quadtree`.
If the layout is now ready (200), node positions should update from circular
to DrL coordinates. Observe: nodes visually re-position without disappearing.

---

## ST-07 — Window Resize: Canvas Reflows, No Errors

**Scenario:** While the graph is visible and loaded, resize the browser window.
Sigma must reflow the canvas to fill the new dimensions without crashing.

**Steps:**

1. Start from a loaded graph (any depth with nodes visible).
2. Drag the browser window to make it noticeably narrower (e.g., 800 px wide).
3. Wait 500 ms.
4. Drag it back to original size.
5. Repeat once with a very tall, narrow window (portrait-like).

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Canvas fills the `#graph` container at all sizes. | No white strips or overflowing canvas. |
| 2 | Nodes remain interactive after resize. | Clicking a node after resize opens the panel normally. |
| 3 | Depth indicator is visible and correctly positioned. | `#depth-indicator` not hidden behind the canvas or clipped. |
| 4 | Side panel (if open) reflows correctly. | Panel remains 360 px wide and does not overflow. |
| 5 | Console has zero `console.error` entries during resize. | Console is clean. |
| 6 | No JS exceptions thrown. | DevTools shows no uncaught errors. |

**DevTools check:**

```js
// After resize, confirm Sigma's canvas dimensions updated:
document.querySelector('#graph canvas').width  // should match container width
document.querySelector('#graph canvas').height // should match container height
```

---

## ST-08 — Phase Badge Completeness

**Scenario:** After SSE completes, all phase badges in `#header-phases` must
be marked done.

**Steps:**

1. Wait for the SSE stream to reach the `done` event (progress bar at 100%
   or `full_ready: true` from `/api/graph/progress`).
2. Inspect the header.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | All `<span class="phase-badge">` elements have class `done`. | Zero badges without `.done` class. |
| 2 | L6 dynamic keys (if any) each have a badge. | Every key from `Object.keys(progress.phases).filter(k => k.startsWith('L6:'))` has a matching badge element. |
| 3 | Progress bar is at 100% width. | `#progress-fill` `width` style is `100%`. |

---

## ST-09 — Error Resilience: Simulated Phase Failure

**Scenario:** Simulate a network error on an L2 fetch and confirm the UI
surfaces the error without crashing.

**Steps (DevTools Network throttling / blocking):**

1. Open DevTools → Network tab → Block request URL containing
   `/api/graph/phase?name=L2`.
2. Start at depth 1 and scroll in to trigger L2 load.
3. Observe status bar and console.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Status bar shows a phase-failure message. | `#status-bar` text contains "L2" or "failed" within 5 s. |
| 2 | Status bar auto-clears after ~4 s. | `#status-bar` gains class `hidden` within 8 s. |
| 3 | Main graph remains interactive. | Nodes already loaded are still visible and clickable. |
| 4 | Console shows `console.warn` but zero `console.error`. | Only warn-level logging for the failure; no uncaught error. |
| 5 | `#incomplete-banner` stays hidden. | Banner only appears on SSE failure, not phase failure. |

**Unblock the URL after verifying the above.**

---

## ST-10 — Panel History: Back Navigation Within Panel

**Scenario:** Open a node's panel, click a neighbour to replace the panel,
then click the back button to return to the first node.

**Steps:**

1. Click any node — panel opens (node A).
2. In the neighbour list, click any item — panel replaces with node B.
3. Click `#panel-back-btn` (← button).
4. Observe panel content.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | Panel shows node A's content after back. | `#panel-node-label` text matches node A's label. |
| 2 | Back button disappears (or is disabled) when history is empty. | `#panel-back-btn` is hidden or disabled. |
| 3 | Pressing back with empty history closes the panel. | Panel slides out. |
| 4 | Main canvas is unchanged throughout. | Camera and loaded phases unaffected. |
| 5 | Console has zero `console.error` entries. | Console is clean. |

---

## ST-11 — Depth Persistence via localStorage

**Scenario:** Navigate to depth 3, then close and reopen the tab. The app
must restore depth 3 (not always default to depth 1) from `localStorage`.

**Steps:**

1. Scroll in to depth 3.
2. Verify `localStorage.getItem('cortex.clinical.depth')` returns `"3"`.
3. Close the tab. Open a NEW tab (same Private window — keeps localStorage).
4. Navigate to `http://localhost:7000/clinical/`.
5. Observe the initial depth.

**Expected results:**

| # | Observation | Pass criterion |
|---|-------------|----------------|
| 1 | `localStorage` key set on depth change. | `localStorage.getItem('cortex.clinical.depth')` is `"3"` after step 2. |
| 2 | App restores to depth 3 on reload. | Depth indicator shows dot 3 active. L0–L3 phases are fetched. |
| 3 | Depth 6 is NOT auto-restored. | If `localStorage` has `"6"`, app loads at depth 5 maximum on cold start. |
| 4 | Console has zero `console.error` entries. | Console is clean. |

---

## Common Failure Signatures

| Symptom | Likely cause | Where to look |
|---------|-------------|---------------|
| `Sigma: addNode — node already exists` | Duplicate-node guard missing or broken | `streaming.js` — `loadedPhases` / `pendingPhases` Sets |
| `EventSource` reconnects in a loop | SSE `done` handler not calling `source.close()` | `streaming.js` done handler |
| White canvas, no nodes | `#graph` container missing or zero height | `layout.css`, `renderer.mount()` |
| Panel opens but Mermaid blank | `mermaid.run()` not called, or `mermaid` global missing | `chain-panel.js`, `vendor/mermaid.min.js` load order |
| Status bar never clears | `setTimeout` race with persistent flag | `boot.js` `_showStatus()` |
| Depth indicator frozen | `navigation.onDepthChange` callback not wired | `boot.js` `navigation.init()` call |
| 503 on quadtree crashes app | Missing `.catch()` on quadtree fetch | `streaming.js` `coldStart()` |
| No SSE data | Server not ready; `full_ready` already `true` before SSE connected | Check `/api/graph/progress` before starting — restart server if needed |

---

## Checklist Summary

| Test | Description | Pass |
|------|-------------|------|
| ST-01 | Cold start — big-picture < 3 s | ☐ |
| ST-02 | Zoom in — next phase loads | ☐ |
| ST-03 | Domain node click — panel opens | ☐ |
| ST-04 | Memory node click — causal chain | ☐ |
| ST-05 | Esc closes panel; main view restored | ☐ |
| ST-06 | SSE streaming — nodes stream in | ☐ |
| ST-07 | Window resize — no console errors | ☐ |
| ST-08 | Phase badge completeness after SSE done | ☐ |
| ST-09 | Phase failure shows status, no crash | ☐ |
| ST-10 | Panel history back navigation | ☐ |
| ST-11 | Depth restored from localStorage | ☐ |

All eleven tests must pass before merging to `main`.
