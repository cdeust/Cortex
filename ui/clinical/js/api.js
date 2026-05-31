/**
 * api.js — Fetch wrappers for every server endpoint.
 *
 * Every function returns a Promise.
 * Every error is surfaced via state.reportError(); no silent failures.
 * Callers may also attach .catch() but the status-bar message is guaranteed.
 */

import { reportError } from "./state.js";

const BASE = "";  // same-origin; no trailing slash

/**
 * Shared JSON fetch helper. All errors are reported to state.
 * @param {string} url
 * @param {string} [label] — human-readable label for error messages
 * @returns {Promise<*>}
 */
async function _jsonFetch(url, label) {
  const res = await fetch(BASE + url).catch(err => {
    const msg = `${label || url}: network error — ${err.message}`;
    reportError(msg);
    throw new Error(msg);
  });
  if (!res.ok) {
    const msg = `${label || url}: HTTP ${res.status}`;
    reportError(msg);
    throw new Error(msg);
  }
  return res.json().catch(err => {
    const msg = `${label || url}: JSON parse error — ${err.message}`;
    reportError(msg);
    throw new Error(msg);
  });
}

/**
 * GET /api/graph/progress
 * @returns {Promise<{phase:string, pct:number, phases:Object, full_ready:boolean, message:string, elapsed:number}>}
 */
export function fetchProgress() {
  return _jsonFetch("/api/graph/progress", "graph/progress");
}

/**
 * GET /api/graph/phase?name=<key>
 * @param {string} key
 * @returns {Promise<{nodes:Array, edges:Array, ready:boolean, node_total:number, edge_total:number, phase:string, deps:Array}>}
 */
export function fetchPhase(key) {
  return _jsonFetch(
    `/api/graph/phase?name=${encodeURIComponent(key)}`,
    `graph/phase:${key}`
  );
}

/**
 * GET /api/quadtree
 * Returns the Apache Arrow IPC response as an ArrayBuffer, or null on 503.
 * Caller is responsible for parsing Arrow IPC.
 * @returns {Promise<ArrayBuffer|null>}
 */
export async function fetchQuadtree() {
  const res = await fetch(BASE + "/api/quadtree").catch(err => {
    reportError(`quadtree: network error — ${err.message}`);
    throw err;
  });
  if (res.status === 503) {
    // Not-ready is expected on cold start — not an error.
    return null;
  }
  if (!res.ok) {
    const msg = `quadtree: HTTP ${res.status}`;
    reportError(msg);
    throw new Error(msg);
  }
  return res.arrayBuffer().catch(err => {
    const msg = `quadtree: buffer read error — ${err.message}`;
    reportError(msg);
    throw new Error(msg);
  });
}

/**
 * GET /api/recompute_layout  (fire-and-forget; best-effort)
 * Initiates DrL layout computation.  Errors are warnings only.
 * @returns {Promise<void>}
 */
export async function triggerLayoutRecompute() {
  fetch(BASE + "/api/recompute_layout").catch(err => {
    console.warn("[api] recompute_layout error (non-fatal):", err.message);
  });
}

/**
 * GET /api/graph/chain?id=<label>&depth=<n>&type=<causal|impact|call>
 * @param {string} nodeLabel
 * @param {number} depth
 * @param {"causal"|"impact"|"call"} type
 * @returns {Promise<{mermaid:string, node_count:number, edge_count:number, depth_reached:number, truncated:boolean, seed:string}>}
 */
export function fetchChain(nodeLabel, depth, type) {
  const params = new URLSearchParams({ id: nodeLabel, depth: String(depth), type });
  return _jsonFetch(`/api/graph/chain?${params}`, `graph/chain:${nodeLabel}`);
}

/**
 * Open an SSE connection to /api/graph/events.
 * Returns an EventSource. Caller must add event listeners and call .close().
 * @returns {EventSource}
 */
export function openGraphEvents() {
  return new EventSource(BASE + "/api/graph/events");
}
