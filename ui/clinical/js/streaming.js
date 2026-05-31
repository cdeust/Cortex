/**
 * streaming.js — SSE subscriber and phase-load logic.
 *
 * Spec: 03-streaming-load.md
 *
 * Manages:
 *  - loadedPhases / pendingPhases duplicate guard
 *  - SSE subscription with exponential-backoff reconnect
 *  - RAF-based drain queue (MAX_ADDITIONS_PER_FRAME = 300)
 *  - Edge hold queue for edges whose source/target is not yet loaded
 *  - Position resolution (positionMap → neighbour centroid → domain anchor → jitter)
 *  - Quadtree retry after SSE done
 *  - Progress bar polling
 */

import * as api        from "./api.js";
import * as state      from "./state.js";
import * as renderer   from "./renderer.js";
import * as navigation from "./navigation.js";
import { parseQuadtreeIpc } from "./arrow-ipc.js";

// ── Duplicate guard ────────────────────────────────────────────────────────
export const loadedPhases = new Set();
export const pendingPhases = new Set();

// ── Pending delta queues — separate node and edge queues (spec §2) ───────
/** @type {Array<Object>} — node attribute objects waiting to be added */
const _pendingDeltaNodes = [];
/** @type {Array<Object>} — edge attribute objects waiting to be added */
const _pendingDeltaEdges = [];

// ── Edge hold queue (edges waiting for their endpoints) ───────────────────
/** @type {Array<{source:string, target:string, [key:string]:*}>} */
const _edgeHoldQueue = [];

// ── Position map from quadtree ─────────────────────────────────────────────
/** @type {Map<string,{x:number,y:number}>|null} */
let _positionMap = null;

// ── RAF drain loop state ──────────────────────────────────────────────────
let _rafRunning = false;
let _sseComplete = false;
/** Max nodes to drain per animation frame (spec §2: 200 nodes + 400 edges). */
const MAX_NODES_PER_FRAME = 200;
/** Max edges to drain per animation frame (spec §2: 200 nodes + 400 edges). */
const MAX_EDGES_PER_FRAME = 400;

// ── SSE reconnect state ───────────────────────────────────────────────────
const SSE_BACKOFFS = [500, 1000, 2000, 4000, 8000];
let _sseRetryCount = 0;
/** @type {EventSource|null} */
let _sseSource = null;

// ── Progress polling ──────────────────────────────────────────────────────
let _progressTimer = null;

// ── Domain centroid cache ─────────────────────────────────────────────────
/** @type {Map<string,{x:number,y:number,count:number}>} */
const _domainCentroids = new Map();

// ── Hierarchical fallback layout ──────────────────────────────────────────
// Used when /api/quadtree returns 503 (no DrL positions yet).
// L0 domain nodes: golden-angle ring at DOMAIN_R.
// L1+ nodes: golden-angle orbit around their domain hub at depth-scaled radius.
// Coordinate space matches DrL's normalised [-1, 1] output so that
// positions snap correctly when quadtree becomes available.
const DOMAIN_R      = 0.85;   // domain ring — fits in the [-1,1] world
const CHILD_R_BASE  = 0.18;   // L1 orbit radius around domain hub
const CHILD_R_STEP  = 0.12;   // extra radius per additional depth level
const GOLDEN_ANGLE  = 2.39996322972865332; // radians (2π / φ²)

/** @type {Map<string,{x:number,y:number}>} domain node id → position */
const _domainNodePos  = new Map();
let   _domainNodeIdx  = 0;
/** @type {Map<string,number>} domain id → child counter */
const _domainChildIdx = new Map();

/**
 * Deterministic position for a node when the quadtree is unavailable.
 * Domain nodes are placed on a golden-angle ring; others orbit their hub.
 * @param {Object} n — node with kind, domain_id, depth fields
 * @returns {{x:number, y:number}}
 */
function _fallbackLayout(n) {
  const domainId = n.domain_id || ("domain:" + (n.domain || ""));

  // L0 domain nodes — evenly distribute on a large ring.
  if (n.kind === "domain" || n.kind === "tool_hub" && !n.domain_id) {
    if (!_domainNodePos.has(n.id)) {
      const angle = _domainNodeIdx * GOLDEN_ANGLE;
      _domainNodePos.set(n.id, {
        x: DOMAIN_R * Math.cos(angle),
        y: DOMAIN_R * Math.sin(angle),
      });
      _domainNodeIdx++;
    }
    return _domainNodePos.get(n.id);
  }

  // All other nodes — orbit around their domain hub.
  const hub = _domainNodePos.get(domainId) || { x: 0, y: 0 };
  const childIdx = _domainChildIdx.get(domainId) || 0;
  _domainChildIdx.set(domainId, childIdx + 1);
  const depth = n.depth || 1;
  const r = CHILD_R_BASE + (depth - 1) * CHILD_R_STEP;
  const angle = childIdx * GOLDEN_ANGLE;
  return {
    x: hub.x + r * Math.cos(angle),
    y: hub.y + r * Math.sin(angle),
  };
}

// ─────────────────────────────────────────────────────────────────────────
//  Public API
// ─────────────────────────────────────────────────────────────────────────

/**
 * Full cold-start sequence from spec §1.
 * Called once by boot.js after renderer is mounted.
 */
export async function coldStart() {
  // 1. Fetch progress to enumerate all phase keys.
  const progress = await api.fetchProgress().catch(() => null);
  if (progress) {
    state.update({ progressData: progress, allPhaseKeys: Object.keys(progress.phases || {}) });
    _renderPhaseBadges(progress.phases || {});
  }

  // 2. Fire-and-forget layout recompute (non-blocking).
  api.triggerLayoutRecompute();

  // 3. Fetch L0 + L1 in parallel and seed graph.
  await Promise.all([_maybeLoadPhase("L0"), _maybeLoadPhase("L1")]);

  // 4. Try quadtree for DrL positions.
  await _tryQuadtree();

  // 5. Apply initial layout (DrL or circular fallback).
  if (!_positionMap) {
    renderer.applyCircularLayout();
  } else {
    renderer.applyPositions(_positionMap);
  }
  renderer.refresh();
  renderer.fitCamera();  // zoom out to show the full domain ring

  // 6. Start progress bar polling.
  _startProgressPolling();

  // 7. Open SSE for remaining phases.
  _connectSSE();
}

/**
 * Load a specific phase by key (called from navigation.js when depth changes).
 * @param {string} key
 */
export function requestPhase(key) {
  _maybeLoadPhase(key);
}

/**
 * Load all L6:* phases (called when depth 6 is reached).
 * @param {string[]} allKeys — from state.allPhaseKeys
 */
export function requestL6Phases(allKeys) {
  const l6 = allKeys.filter(k => k.startsWith("L6:"));
  // Load up to 3 in parallel.
  const chunks = [];
  for (let i = 0; i < l6.length; i += 3) chunks.push(l6.slice(i, i + 3));
  const loadChunk = (idx) => {
    if (idx >= chunks.length) return;
    Promise.all(chunks[idx].map(_maybeLoadPhase)).then(() => loadChunk(idx + 1)).catch(err => console.warn("[streaming] chunk load failed", err));
  };
  loadChunk(0);
}

// ─────────────────────────────────────────────────────────────────────────
//  Phase loading
// ─────────────────────────────────────────────────────────────────────────

/**
 * @param {string} key
 * @returns {Promise<void>}
 */
async function _maybeLoadPhase(key) {
  if (loadedPhases.has(key) || pendingPhases.has(key)) return;
  pendingPhases.add(key);
  const depth = _depthForKey(key);
  navigation.markLoading(depth);
  try {
    const data = await api.fetchPhase(key);
    _enqueuePhaseData(data, key);
    loadedPhases.add(key);
  } catch (err) {
    // One retry after 2 s — then give up so we don't loop forever.
    setTimeout(async () => {
      try {
        const data = await api.fetchPhase(key);
        _enqueuePhaseData(data, key);
      } catch (_) {
        console.warn(`[streaming] Phase ${key} permanently failed — SSE will fill in`);
      } finally {
        loadedPhases.add(key);   // mark done (success or permanent failure)
        navigation.markLoaded(depth);
        pendingPhases.delete(key);
      }
    }, 2000);
    return;
  } finally {
    pendingPhases.delete(key);
  }
  navigation.markLoaded(depth);
}

/** @param {Object} data @param {string} key */
function _enqueuePhaseData(data, key) {
  if (!data) return;
  const depthForPhase = _depthForKey(key);
  for (const n of (data.nodes || [])) {
    // Use phase depth, then kind-based depth, then node's own depth field.
    const depth = n.depth ?? (depthForPhase || _depthForKind(n.kind || ""));
    _pendingDeltaNodes.push({ ...n, depth });
  }
  for (const e of (data.edges || [])) {
    _pendingDeltaEdges.push(e);
  }
  if (!_rafRunning) _scheduleDrain();
}

/** Map phase key OR SSE batch label → depth number.
 *  SSE labels come from PHASES[key]["label"] e.g. "L0 domains",
 *  "L1 Claude setup", "L5 memories", "L6 cortex symbols".
 *  Falls through to kind-based mapping when label is unknown.
 */
function _depthForKey(key) {
  if (!key) return 0;
  if (key === "L0" || key.startsWith("L0 ") || key === "skeleton" || key === "domains") return 0;
  if (key === "L1" || key.startsWith("L1 ") || key === "setup") return 1;
  if (key === "L2" || key.startsWith("L2 ") || key === "tools") return 2;
  if (key === "L3" || key.startsWith("L3 ") || key === "files") return 3;
  if (key === "L4" || key.startsWith("L4 ") || key === "discussions") return 4;
  if (key === "L5" || key.startsWith("L5 ") || key === "memories") return 5;
  if (key.startsWith("L6") || key.includes("symbol") || key.includes("cross")) return 6;
  return 0;
}

/** Depth derived from node kind when the phase key is unknown. */
function _depthForKind(kind) {
  const D = { domain: 0, skill: 1, hook: 1, command: 1, agent: 1, mcp: 1,
               tool_hub: 2, file: 3, discussion: 4, memory: 5, symbol: 6, entity: 1 };
  return D[kind] ?? 1;
}

// ─────────────────────────────────────────────────────────────────────────
//  RAF drain queue
// ─────────────────────────────────────────────────────────────────────────

function _scheduleDrain() {
  _rafRunning = true;
  requestAnimationFrame(_drainQueue);
}

function _drainQueue() {
  // Drain nodes first (up to MAX_NODES_PER_FRAME).
  let nodeBudget = MAX_NODES_PER_FRAME;
  while (nodeBudget > 0 && _pendingDeltaNodes.length > 0) {
    _applyNode(_pendingDeltaNodes.shift());
    nodeBudget--;
  }

  // Then drain edges (up to MAX_EDGES_PER_FRAME).
  let edgeBudget = MAX_EDGES_PER_FRAME;
  while (edgeBudget > 0 && _pendingDeltaEdges.length > 0) {
    _applyEdge(_pendingDeltaEdges.shift());
    edgeBudget--;
  }

  // Flush edge hold queue after new nodes may have been added.
  _flushEdgeHold();

  const hasPending = _pendingDeltaNodes.length > 0 || _pendingDeltaEdges.length > 0;
  if (hasPending || !_sseComplete) {
    requestAnimationFrame(_drainQueue);
  } else {
    renderer.refresh();
    _rafRunning = false;
  }
}

/**
 * Apply a single node from the pending delta.
 * Nodes whose depth exceeds currentDepth are added to the graph with hidden=true
 * so that zoom-in can reveal them without re-fetching (buffered but not rendered).
 * @param {Object} n — node attribute object
 */
function _applyNode(n) {
  const graph = renderer.getGraph();
  if (!graph) return;
  if (graph.hasNode(n.id)) return;
  const pos = _resolvePosition(n);
  const currentDepth = state.get("currentDepth") ?? 1;
  renderer.addNodes([{ ...n, x: pos.x, y: pos.y }], currentDepth);
  // Track domain centroid for position fallback (§4).
  if (n.domain) {
    const c = _domainCentroids.get(n.domain) || { x: 0, y: 0, count: 0 };
    c.x += pos.x; c.y += pos.y; c.count++;
    _domainCentroids.set(n.domain, c);
  }
}

/**
 * Apply a single edge from the pending delta.
 * Moves to edgeHoldQueue if either endpoint is not yet in the graph.
 * @param {Object} e — edge attribute object
 */
function _applyEdge(e) {
  const graph = renderer.getGraph();
  if (!graph) return;
  if (!graph.hasNode(e.source) || !graph.hasNode(e.target)) {
    _edgeHoldQueue.push(e);
    return;
  }
  renderer.addEdges([e]);
}

function _flushEdgeHold() {
  const graph = renderer.getGraph();
  if (!graph) return;
  let i = 0;
  while (i < _edgeHoldQueue.length) {
    const e = _edgeHoldQueue[i];
    if (graph.hasNode(e.source) && graph.hasNode(e.target)) {
      renderer.addEdges([e]);
      _edgeHoldQueue.splice(i, 1);
    } else {
      i++;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────
//  Position resolution
// ─────────────────────────────────────────────────────────────────────────

/**
 * Resolve position for a node before addNode.
 * Priority: positionMap → neighbour centroid → domain anchor → jitter.
 * @param {Object} n
 * @returns {{x:number, y:number}}
 */
function _resolvePosition(n) {
  // 1. DrL quadtree
  if (_positionMap && _positionMap.has(n.id)) return _positionMap.get(n.id);

  const graph = renderer.getGraph();

  // 2. Neighbour centroid
  if (graph && n.id) {
    // Use edges in hold queue to find potential neighbours.
    const neighbourIds = _edgeHoldQueue
      .filter(e => e.source === n.id || e.target === n.id)
      .map(e => e.source === n.id ? e.target : e.source)
      .filter(id => graph.hasNode(id));
    if (neighbourIds.length > 0) {
      let sx = 0, sy = 0;
      for (const id of neighbourIds) {
        sx += graph.getNodeAttribute(id, "x") || 0;
        sy += graph.getNodeAttribute(id, "y") || 0;
      }
      const jx = (Math.random() - 0.5) * 20;
      const jy = (Math.random() - 0.5) * 20;
      return { x: sx / neighbourIds.length + jx, y: sy / neighbourIds.length + jy };
    }
  }

  // 3. Domain anchor (centroid of already-positioned siblings)
  if (n.domain && _domainCentroids.has(n.domain)) {
    const c = _domainCentroids.get(n.domain);
    const jx = (Math.random() - 0.5) * 20;
    const jy = (Math.random() - 0.5) * 20;
    return { x: c.x / c.count + jx, y: c.y / c.count + jy };
  }

  // 4. Hierarchical fallback — deterministic golden-angle ring / orbit.
  //    Avoids the all-nodes-at-origin pile-up when quadtree is 503.
  return _fallbackLayout(n);
}

// ─────────────────────────────────────────────────────────────────────────
//  Quadtree
// ─────────────────────────────────────────────────────────────────────────

async function _tryQuadtree() {
  const buf = await api.fetchQuadtree().catch(() => null);
  if (!buf) return;  // 503 or error — circular layout will be used
  _positionMap = _parseArrowIpc(buf);
  if (_positionMap) state.update({ quadtreeReady: true });
}

/**
 * Attempt to parse Apache Arrow IPC stream into a position Map.
 * Delegates to arrow-ipc.js. Returns null on any parse failure.
 * @param {ArrayBuffer} buf
 * @returns {Map<string,{x:number,y:number}>|null}
 */
function _parseArrowIpc(buf) {
  return parseQuadtreeIpc(buf);
}

async function _retryQuadtree() {
  if (state.get("quadtreeReady")) return;
  await _tryQuadtree();
  if (_positionMap) renderer.applyPositions(_positionMap);
}

// ─────────────────────────────────────────────────────────────────────────
//  SSE
// ─────────────────────────────────────────────────────────────────────────

function _connectSSE() {
  if (_sseSource) { _sseSource.close(); _sseSource = null; }
  _sseSource = api.openGraphEvents();

  _sseSource.addEventListener("batch", (ev) => {
    try {
      const d = JSON.parse(ev.data);
      const key = d.label;
      // Cross-check: skip if already loaded via /api/graph/phase.
      if (loadedPhases.has(key)) return;
      _enqueuePhaseData({ nodes: d.nodes || [], edges: d.edges || [] }, key);
    } catch (e) {
      console.warn("[streaming] SSE batch parse error", e);
    }
  });

  _sseSource.addEventListener("done", (ev) => {
    _sseSource.close();
    _sseSource = null;
    _sseComplete = true;
    state.update({ sseComplete: true, loadState: "ready" });
    // Retry quadtree now that all data is loaded.
    _retryQuadtree().catch(err => console.warn("[streaming] quadtree retry failed", err));
  });

  _sseSource.onerror = () => {
    _sseSource.close();
    _sseSource = null;
    if (_sseRetryCount < SSE_BACKOFFS.length) {
      const delay = SSE_BACKOFFS[_sseRetryCount++];
      _showStatus(`SSE disconnected — reconnecting in ${delay}ms…`);
      setTimeout(_connectSSE, delay);
    } else {
      document.getElementById("incomplete-banner")?.classList.add("visible");
      _fallbackPolling();
    }
  };
}

// ─────────────────────────────────────────────────────────────────────────
//  Fallback polling
// ─────────────────────────────────────────────────────────────────────────

function _fallbackPolling() {
  const allKeys = state.get("allPhaseKeys") || [];
  const missing = allKeys.filter(k => !loadedPhases.has(k) && !pendingPhases.has(k));
  const loadNext = (idx) => {
    if (idx >= missing.length) return;
    _maybeLoadPhase(missing[idx]).then(() => setTimeout(() => loadNext(idx + 1), 2000)).catch(err => console.warn("[streaming] fallback phase load failed", err));
  };
  loadNext(0);
}

// ─────────────────────────────────────────────────────────────────────────
//  Progress bar
// ─────────────────────────────────────────────────────────────────────────

function _startProgressPolling() {
  _pollProgress();
}

function _pollProgress() {
  api.fetchProgress()
    .then(p => {
      const fill = document.getElementById("progress-fill");
      const label = document.getElementById("phase-label");
      if (fill) fill.style.width = `${p.pct || 0}%`;
      if (label) label.textContent = p.message || p.phase || "";
      _updatePhaseBadges(p.phases || {});
      if (!p.full_ready) {
        _progressTimer = setTimeout(_pollProgress, 500);
      } else {
        if (fill) fill.style.width = "100%";
      }
    })
    .catch(err => console.warn("[streaming] progress poll error", err));
}

// ─────────────────────────────────────────────────────────────────────────
//  Phase badge UI
// ─────────────────────────────────────────────────────────────────────────

function _renderPhaseBadges(phases) {
  const container = document.getElementById("header-phases");
  if (!container) return;
  container.innerHTML = "";
  for (const key of Object.keys(phases)) {
    const span = document.createElement("span");
    span.className = "phase-badge" + (phases[key] ? " done" : "");
    span.dataset.phase = key;
    span.textContent = key;
    container.appendChild(span);
  }
}

function _updatePhaseBadges(phases) {
  for (const [key, done] of Object.entries(phases)) {
    const el = document.querySelector(`.phase-badge[data-phase="${CSS.escape(key)}"]`);
    if (el) el.classList.toggle("done", Boolean(done));
  }
}

// ─────────────────────────────────────────────────────────────────────────
//  Status bar
// ─────────────────────────────────────────────────────────────────────────

let _statusClearTimer = null;

/**
 * @param {string} message
 * @param {boolean} [persistent=false]
 */
function _showStatus(message, persistent = false) {
  const bar = document.getElementById("status-bar");
  if (!bar) return;
  bar.textContent = message;
  bar.classList.remove("hidden", "error");
  clearTimeout(_statusClearTimer);
  if (!persistent) {
    _statusClearTimer = setTimeout(() => bar.classList.add("hidden"), 4000);
  }
}
