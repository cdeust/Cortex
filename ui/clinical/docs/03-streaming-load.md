# Streaming & Initial-Load Design

## 1. Cold-Start Sequence

```
1. GET /api/graph/progress
   → parse .phases dict; L6 keys = Object.keys(phases).filter(k => k.startsWith('L6:'))
   → record full_ready flag

2. Fetch L0 + L1 via /api/graph/phase?name=L0 and ?name=L1 (parallel)
   → add nodes/edges to graphology; mark both keys in loadedPhases Set

3. GET /api/quadtree
   → 200: parse Arrow IPC; store {id → {x,y}} in positionMap
   → 503 {reason:"no_layout"}: positionMap = null; use graphology circular layout
     for initial render; retry once after SSE 'done' fires

4. Render initial graph (L0 + L1, positioned or circular fallback)

5. Open SSE: GET /api/graph/events
   → stream remaining phases (L2 … L6:*)
   → do NOT call /api/graph (legacy snapshot) or decode .bin (no CXGB decoder)
```

If SSE connect fails, fall back to polling `/api/graph/phase` per unloaded key
at 2 s intervals with the same loadedPhases / pendingPhases guard.

---

## 2. SSE Batch → Per-Depth Additions

### Event schema (from server)

```
event: batch
data: {"label":"L2","nodes":[…],"edges":[…],"off":0,"n_total":4200,"e_total":9800}

event: done
data: {"total_nodes":18400,"total_edges":52000}
```

### Queue + drain pattern

Incoming batches push onto `pendingItems`. A `requestAnimationFrame` loop
drains at a fixed budget per frame.

```
MAX_ADDITIONS_PER_FRAME = 300   // nodes + edges combined
```

At 60 fps this yields ~18 000 additions/s — enough to ingest all L0–L5
in < 2 s while keeping frame time under 5 ms.

```js
function drainQueue() {
  let budget = MAX_ADDITIONS_PER_FRAME;
  while (budget > 0 && pendingItems.length > 0) {
    applyItem(pendingItems.shift());   // addNode or addEdge on graphology
    budget--;
  }
  if (pendingItems.length > 0 || !sseComplete) requestAnimationFrame(drainQueue);
  else renderer.refresh();
}
```

`applyItem` resolves position before `graph.addNode` (see §4).
Edges whose source or target is absent go into `edgeHoldQueue`; flush
each entry after the corresponding node addition.

### Duplicate guard

```js
const loadedPhases = new Set();   // completed /api/graph/phase fetches
const pendingPhases = new Set();  // in-flight fetches

function maybeLoadPhase(key) {
  if (loadedPhases.has(key) || pendingPhases.has(key)) return;
  pendingPhases.add(key);
  fetch(`/api/graph/phase?name=${encodeURIComponent(key)}`)
    .then(r => r.json())
    .then(d => { enqueue(d); loadedPhases.add(key); pendingPhases.delete(key); })
    .catch(e => { pendingPhases.delete(key); showStatus(`Phase ${key} failed: ${e.message}`); });
}
```

SSE batch `label` is cross-checked against `loadedPhases`.
Before every `graph.addNode(id, …)`: `if (graph.hasNode(id)) continue;`

---

## 3. Error / Reconnect Strategy

**SSE drops:** exponential backoff `[500, 1000, 2000, 4000, 8000] ms`, max 5 attempts.
On each retry track the highest `off` per phase already ingested and skip covered batches.
After 5 failures, fall back to per-phase polling (§1 fallback) and show a persistent banner.

**SSE done event:**
```js
source.addEventListener('done', () => {
  source.close();    // prevent auto-reconnect loop
  sseComplete = true;
  retryQuadtree();   // update positions if quadtree was 503 at boot
});
```

**Fetch errors:** every `fetch()` has `.catch(err => showStatus(err.message))`.
`showStatus` writes to `#status-bar` at `console.warn` level. No silent failures.

---

## 4. Position-Less Node Handling

A node has no position when it arrives before the quadtree is populated
or when it belongs to a phase not yet covered by the DrL layout run.

Resolution order inside `applyItem`, before `graph.addNode`. NaN is never written.

1. **positionMap lookup** — DrL coordinates if available.
2. **Neighbour centroid** — average x/y of already-placed neighbours (from `edgeHoldQueue` + existing edges); jitter ±10 to avoid overlap.
3. **Domain anchor** — centroid of already-placed nodes sharing the same `domain` attribute, plus jitter.
4. **Origin jitter** — `(rand(−50,50), rand(−50,50))` as last resort.

After `retryQuadtree()` succeeds, update all nodes from steps 2–4 to DrL
coordinates via `graph.setNodeAttribute` then `renderer.refresh()`.

---

## 5. Loading UI

### Progress bar

Poll `/api/graph/progress` every 500 ms until `full_ready === true`.
Map `pct` (0–100) to CSS width of `#progress-fill`; write `.message` to `#phase-label`.

```js
function updateProgress() {
  fetch('/api/graph/progress')
    .then(r => r.json())
    .then(p => {
      document.getElementById('progress-fill').style.width = `${p.pct}%`;
      document.getElementById('phase-label').textContent = p.message ?? p.phase ?? '';
      if (!p.full_ready) setTimeout(updateProgress, 500);
    })
    .catch(err => console.warn('progress poll error', err));
}
```

### Status bar + phase badges

`#status-bar` shows transient errors (SSE reconnect, quadtree retry, phase failures).
Messages auto-clear after 4 s unless the failure is persistent.

On first progress response enumerate `Object.keys(phases)` and render one
`<span class="phase-badge">` per key. Toggle `.done` when `phases[key] === true`.
