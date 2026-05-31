/**
 * navigation.js — Semantic zoom-state machine.
 *
 * Two orthogonal concepts:
 *   1. VISUAL zoom — Sigma camera ratio. Controlled by pinch / Ctrl+wheel.
 *      Sigma handles this natively. We watch it only for threshold crossings
 *      that also advance the semantic depth (see _evaluateThreshold).
 *   2. SEMANTIC depth — which phase band [0..6] is currently rendered.
 *      Advanced by plain scroll (wheel without modifier) and by the camera-
 *      threshold crossings above.
 *
 * Depth transitions are debounced (DEBOUNCE_MS) so rapid scroll bursts
 * do not fire multiple fetches.
 *
 * Public surface
 * ──────────────
 * init(opts)           Wire callbacks.
 * onCameraUpdate(r)    Called by boot.js on Sigma camera "updated" event.
 * onWheel(ev)          Called by boot.js on wheel events on #graph.
 * zoomIn()             Programmatic depth increment.
 * zoomOut()            Programmatic depth decrement.
 * jumpToDepth(n)       Programmatic jump (e.g. double-click on node).
 * restoreDepth(fb)     Read persisted depth from localStorage.
 * getDepthLabel(d)     Human-readable label for a depth level.
 * getDepthNodeCount(d) Node count currently in graph at depth d.
 */

import * as state from "./state.js";

// ── Depth label metadata ───────────────────────────────────────────────────
const DEPTH_META = [
  { label: "Overview",     kind: "domains" },
  { label: "Wings",        kind: "setup" },
  { label: "Departments",  kind: "tools" },
  { label: "Corridors",    kind: "files" },
  { label: "Rooms",        kind: "discussions" },
  { label: "Beds",         kind: "memories" },
  { label: "Atoms",        kind: "symbols" },
];

/**
 * Camera ratio thresholds for depth transitions driven by pinch/Ctrl+scroll.
 * Ratio > 1 = zoomed out; ratio < 1 = zoomed in (Sigma convention).
 */
const DEPTH_THRESHOLDS = [
  { depth: 0, zoomOut: Infinity, zoomIn: 0.9 },
  { depth: 1, zoomOut: 1.1,      zoomIn: 0.6 },
  { depth: 2, zoomOut: 0.7,      zoomIn: 0.35 },
  { depth: 3, zoomOut: 0.4,      zoomIn: 0.18 },
  { depth: 4, zoomOut: 0.22,     zoomIn: 0.08 },
  { depth: 5, zoomOut: 0.10,     zoomIn: 0.035 },
  { depth: 6, zoomOut: 0.045,    zoomIn: 0.0 },
];

// ── Scroll accumulator ────────────────────────────────────────────────────
// Accumulate delta until a threshold is crossed to avoid hyper-sensitive
// single-tick jumps on trackpads that send many small events.
const SCROLL_THRESHOLD = 80;   // pixels (or wheel-delta units)
let _scrollAccum = 0;

// ── Debounce ──────────────────────────────────────────────────────────────
let _debounceTimer = null;
const DEBOUNCE_MS = 120;

// ── Registered callbacks ──────────────────────────────────────────────────
/** @type {Function|null} (depth: number) => void */
let _onDepthChange = null;
/** @type {Function|null} (depth: number) => void — fired when async load starts */
let _onDepthLoading = null;
/** @type {Function|null} (depth: number) => void — fired when load completes */
let _onDepthLoaded = null;

// ── In-flight load tracking ───────────────────────────────────────────────
/** @type {Set<number>} */
const _loadingDepths = new Set();

// ─────────────────────────────────────────────────────────────────────────
//  Public API
// ─────────────────────────────────────────────────────────────────────────

/**
 * Initialise navigation. Call once from boot.js after renderer is mounted.
 * @param {{
 *   onDepthChange?:  (depth: number) => void,
 *   onDepthLoading?: (depth: number) => void,
 *   onDepthLoaded?:  (depth: number) => void,
 * }} opts
 */
export function init(opts = {}) {
  _onDepthChange  = opts.onDepthChange  || null;
  _onDepthLoading = opts.onDepthLoading || null;
  _onDepthLoaded  = opts.onDepthLoaded  || null;
}

/**
 * Handle a wheel event on the graph canvas.
 * Plain scroll → semantic depth change.
 * Ctrl/Meta+scroll → visual camera zoom (let Sigma handle it, do NOT intercept).
 * @param {WheelEvent} ev
 */
export function onWheel(ev) {
  // Let Ctrl/Meta+scroll be handled by Sigma for visual zoom.
  if (ev.ctrlKey || ev.metaKey) return;

  // Prevent the browser's native page scroll.
  ev.preventDefault();

  // Accumulate delta; positive deltaY = scroll down = zoom out = shallower.
  _scrollAccum += ev.deltaY;

  if (Math.abs(_scrollAccum) < SCROLL_THRESHOLD) return;

  if (_scrollAccum > 0) {
    _scrollAccum = 0;
    _scheduleDepthChange(-1);    // scroll down → shallower
  } else {
    _scrollAccum = 0;
    _scheduleDepthChange(+1);    // scroll up   → deeper
  }
}

/**
 * Evaluate camera ratio against thresholds and fire a depth transition when
 * a crossing is detected. Called on every Sigma camera "updated" event.
 * Debounced internally.
 * @param {number} cameraRatio
 */
export function onCameraUpdate(cameraRatio) {
  state.update({ cameraZ: cameraRatio });
  clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => {
    _evaluateThreshold(cameraRatio);
  }, DEBOUNCE_MS);
}

/**
 * Trigger depth increment (zoom in = deeper).
 */
export function zoomIn() {
  const current = state.get("currentDepth");
  if (current < 6) _requestDepth(current + 1);
}

/**
 * Trigger depth decrement (zoom out = shallower).
 */
export function zoomOut() {
  const current = state.get("currentDepth");
  if (current > 0) _requestDepth(current - 1);
}

/**
 * Jump to a specific depth (e.g. from a double-click on a node).
 * @param {number} depth
 */
export function jumpToDepth(depth) {
  const clamped = Math.max(0, Math.min(6, depth));
  if (clamped !== state.get("currentDepth")) {
    _requestDepth(clamped);
  }
}

/**
 * Mark a depth as currently loading (called by boot.js / streaming.js).
 * @param {number} depth
 */
export function markLoading(depth) {
  _loadingDepths.add(depth);
  if (_onDepthLoading) _onDepthLoading(depth);
}

/**
 * Mark a depth as finished loading.
 * @param {number} depth
 */
export function markLoaded(depth) {
  _loadingDepths.delete(depth);
  if (_onDepthLoaded) _onDepthLoaded(depth);
}

/**
 * Whether a depth band is currently being loaded.
 * @param {number} depth
 * @returns {boolean}
 */
export function isLoading(depth) {
  return _loadingDepths.has(depth);
}

/**
 * Read persisted depth from localStorage.
 * Returns a value in [0, 5] or the supplied fallback (default 1).
 * @param {number} [fallback=1]
 * @returns {number}
 */
export function restoreDepth(fallback = 1) {
  try {
    const raw = localStorage.getItem("cortex.clinical.depth");
    if (raw !== null) {
      const n = parseInt(raw, 10);
      if (!isNaN(n) && n >= 0 && n <= 5) return n;
    }
  } catch (_) {}
  return fallback;
}

/**
 * Human-readable label for a depth level, e.g. "L3 Corridors".
 * @param {number} depth
 * @returns {string}
 */
export function getDepthLabel(depth) {
  const meta = DEPTH_META[depth];
  if (!meta) return `L${depth}`;
  return `L${depth} ${meta.label}`;
}

/**
 * Full indicator text including node count, e.g. "L3 files · 14 022 nodes".
 * nodeCount may be 0 if the phase is not yet loaded.
 * @param {number} depth
 * @param {number} nodeCount
 * @returns {string}
 */
export function getDepthIndicatorText(depth, nodeCount) {
  const meta = DEPTH_META[depth] || { label: "", kind: "nodes" };
  const countStr = nodeCount.toLocaleString("en-US");
  return `L${depth} ${meta.kind} · ${countStr} nodes`;
}

// ─────────────────────────────────────────────────────────────────────────
//  Internal helpers
// ─────────────────────────────────────────────────────────────────────────

/**
 * Schedule a relative depth change after clearing any pending debounce.
 * @param {number} delta  +1 or -1
 */
function _scheduleDepthChange(delta) {
  clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => {
    const current = state.get("currentDepth");
    const next = Math.max(0, Math.min(6, current + delta));
    if (next !== current) _requestDepth(next);
  }, DEBOUNCE_MS);
}

/**
 * Check camera ratio against thresholds and fire a depth transition if
 * a crossing is detected.
 * @param {number} ratio
 */
function _evaluateThreshold(ratio) {
  const current = state.get("currentDepth");

  // Check zoom-in: should we go deeper?
  if (current < 6) {
    const next = DEPTH_THRESHOLDS[current + 1];
    if (next && ratio <= next.zoomIn) {
      _requestDepth(current + 1);
      return;
    }
  }

  // Check zoom-out: should we go shallower?
  if (current > 0) {
    const curr = DEPTH_THRESHOLDS[current];
    if (curr && ratio >= curr.zoomOut) {
      _requestDepth(current - 1);
    }
  }
}

/**
 * Commit a depth change: update state, fire callback, persist to localStorage.
 * @param {number} depth
 */
function _requestDepth(depth) {
  const current = state.get("currentDepth");
  if (depth === current) return;
  const dir = depth > current ? "zooming_in" : "zooming_out";
  state.update({ targetDepth: depth, transition: dir, currentDepth: depth });
  if (_onDepthChange) _onDepthChange(depth);
  try {
    localStorage.setItem("cortex.clinical.depth", String(depth));
  } catch (_) {}
}
