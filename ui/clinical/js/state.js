/**
 * state.js — Reactive state store for the clinical graph UI.
 *
 * Single source of truth. Mutation only through update().
 * Subscribers receive the diff key set.
 */

/** @type {Map<string, Set<Function>>} */
const _listeners = new Map();

/** @type {Object} */
const _state = {
  /** 0..6  — what depth is currently rendered */
  currentDepth: 1,
  /** 0..6  — destination of an in-flight depth transition */
  targetDepth: 1,
  /** "idle" | "zooming_in" | "zooming_out" */
  transition: "idle",
  /** Set<string> — phases whose nodes are in the graph */
  loadedPhases: new Set(),
  /** Set<string> — phases currently being fetched */
  pendingPhases: new Set(),
  /** Sigma camera ratio (1.0 = default) */
  cameraZ: 1.0,
  /** string|null — node id with open chain-of-call panel */
  focusedNode: null,
  /** string|null — last error message */
  lastError: null,
  /** "loading" | "partial" | "ready" */
  loadState: "loading",
  /** Object|null — last /api/graph/progress response */
  progressData: null,
  /** All phase keys known from /api/graph/progress */
  allPhaseKeys: [],
  /** Whether the SSE stream has completed */
  sseComplete: false,
  /** Whether the quadtree layout is available */
  quadtreeReady: false,
};

/**
 * Read a state value.
 * @param {string} key
 * @returns {*}
 */
export function get(key) {
  return _state[key];
}

/**
 * Read the entire state (shallow copy).
 * @returns {Object}
 */
export function snapshot() {
  return { ..._state };
}

/**
 * Update state keys and notify subscribers.
 * @param {Object} patch
 */
export function update(patch) {
  const changedKeys = [];
  for (const [k, v] of Object.entries(patch)) {
    if (_state[k] !== v) {
      _state[k] = v;
      changedKeys.push(k);
    }
  }
  if (changedKeys.length === 0) return;
  for (const key of changedKeys) {
    const subs = _listeners.get(key);
    if (subs) {
      for (const fn of subs) {
        try { fn(v => _state[key], key); } catch (e) { console.warn("[state] subscriber error", key, e); }
      }
    }
  }
  const wildcardSubs = _listeners.get("*");
  if (wildcardSubs) {
    for (const fn of wildcardSubs) {
      try { fn(changedKeys); } catch (e) { console.warn("[state] wildcard subscriber error", e); }
    }
  }
}

/**
 * Subscribe to state changes on a specific key or "*" for any change.
 * @param {string} key
 * @param {Function} fn
 * @returns {Function} unsubscribe
 */
export function subscribe(key, fn) {
  if (!_listeners.has(key)) _listeners.set(key, new Set());
  _listeners.get(key).add(fn);
  return () => _listeners.get(key).delete(fn);
}

/**
 * Report a non-fatal error into state. Surfaces in #status-bar.
 * @param {string} message
 */
export function reportError(message) {
  update({ lastError: message });
}
