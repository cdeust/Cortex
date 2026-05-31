/**
 * boot.js — Clinical graph UI entry point.
 *
 * Wires all modules together:
 *   state → api → renderer → navigation → streaming → subgraph panel
 *
 * Cold-start sequence (spec 03 §1):
 *   1. Mount Sigma on #graph
 *   2. Restore session depth
 *   3. Run coldStart() — fetches L0+L1, tries quadtree, opens SSE
 *   4. Hook scroll event → navigation.onWheel (semantic depth)
 *   5. Hook camera "updated" → navigation.onCameraUpdate (visual zoom thresholds)
 *   6. Hook node click → chain panel (subgraph.js)
 */

import * as state      from "./state.js";
import * as renderer   from "./renderer.js";
import * as navigation from "./navigation.js";
import * as streaming  from "./streaming.js";
import * as subgraph   from "./subgraph.js";

// ── 1. Mount Sigma ─────────────────────────────────────────────────────────
const graphContainer = document.getElementById("graph");
if (!graphContainer) {
  _showStatus("#graph element not found — cannot mount", true);
  throw new Error("[boot] #graph element not found — cannot mount Sigma");
}

renderer.mount(graphContainer, {
  onNodeClick:    _handleNodeClick,
  onNodeHover:    _handleNodeHover,
  onNodeHoverOut: _handleNodeHoverOut,
});

// ── 2. Restore session depth ───────────────────────────────────────────────
const initialDepth = navigation.restoreDepth(1);
state.update({ currentDepth: initialDepth, targetDepth: initialDepth });
_updateDepthIndicator(initialDepth);

// ── 3. Init navigation ─────────────────────────────────────────────────────
navigation.init({
  onDepthChange:  _handleDepthChange,
  onDepthLoading: _handleDepthLoading,
  onDepthLoaded:  _handleDepthLoaded,
});

// ── 3b. Init sub-graph chain panel ─────────────────────────────────────────
subgraph.init({ getGraph: renderer.getGraph });

// ── 4. Wire Sigma camera events ────────────────────────────────────────────
const sigma = renderer.getSigma();
if (sigma) {
  // Visual zoom threshold — may also trigger semantic depth advances.
  sigma.getCamera().on("updated", ({ ratio }) => {
    navigation.onCameraUpdate(ratio);
  });

  // Double-click on a node → jump one depth deeper centred on that node.
  sigma.on("doubleClickNode", ({ node, event }) => {
    event.preventDefault();
    const attrs = renderer.getGraph()?.getNodeAttributes(node);
    if (!attrs) return;
    const nodeDepth  = attrs.depth || 0;
    const current    = state.get("currentDepth");
    if (nodeDepth >= current) {
      navigation.jumpToDepth(current + 1);
    }
  });

  // Click on background canvas → close the chain panel.
  sigma.on("clickStage", () => {
    _closePanel();
  });
}

// ── 5. Wire scroll → semantic depth (plain wheel, no modifier) ───────────
graphContainer.addEventListener("wheel", (ev) => {
  navigation.onWheel(ev);
}, { passive: false });

// ── 6. Wire keyboard shortcuts ─────────────────────────────────────────────
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") _closePanel();
});

// ── 7. Wire panel close/back buttons ──────────────────────────────────────
// chain-panel.js owns the panel DOM; we keep Escape/stage-click here only.
// close-btn and back-btn are wired by chain-panel.init() to avoid duplicate listeners.

// ── 8. Wire panel tabs ─────────────────────────────────────────────────────
// chain-panel.js wires tab clicks in its init(); no duplicate wiring here.

// ── 9. Subscribe to state errors → status bar ─────────────────────────────
state.subscribe("lastError", () => {
  const msg = state.get("lastError");
  if (msg) _showStatus(msg);
});

// ── 10. Wire depth-indicator clicks for quick jumps ───────────────────────
document.querySelectorAll(".depth-dot").forEach(dot => {
  dot.addEventListener("click", () => {
    const d = parseInt(dot.dataset.depth, 10);
    if (!isNaN(d)) navigation.jumpToDepth(d);
  });
  dot.style.cursor = "pointer";
});

// ── 11. Cold start ─────────────────────────────────────────────────────────
streaming.coldStart().catch(err => {
  console.warn("[boot] coldStart failed", err);
  _showStatus("Graph load failed — " + err.message, true);
});

// ─────────────────────────────────────────────────────────────────────────
//  Depth change handler
// ─────────────────────────────────────────────────────────────────────────

/** @param {number} depth */
function _handleDepthChange(depth) {
  _updateDepthIndicator(depth);
  renderer.setVisibleDepth(depth);

  // Trigger async load for this depth if not yet loaded.
  const allKeys = state.get("allPhaseKeys") || [];
  if (depth === 6) {
    streaming.requestL6Phases(allKeys);
  } else {
    const phaseKey = `L${depth}`;
    streaming.requestPhase(phaseKey);
  }

  // Update indicator text after load (node count may change).
  _scheduleIndicatorUpdate(depth);
}

/**
 * Show a spinner near the depth indicator while a phase is loading.
 * @param {number} depth
 */
function _handleDepthLoading(depth) {
  const spinner = document.getElementById("depth-spinner");
  if (spinner) {
    spinner.style.display = "inline-block";
    spinner.title = `Loading L${depth}…`;
  }
}

/**
 * Hide the spinner and refresh the indicator text once load is done.
 * @param {number} depth
 */
function _handleDepthLoaded(depth) {
  const spinner = document.getElementById("depth-spinner");
  if (spinner) spinner.style.display = "none";
  const current = state.get("currentDepth");
  if (depth === current) _updateDepthIndicator(current);
}

// ─────────────────────────────────────────────────────────────────────────
//  Depth indicator UI
// ─────────────────────────────────────────────────────────────────────────

/** @param {number} depth */
function _updateDepthIndicator(depth) {
  // Update dot states.
  document.querySelectorAll(".depth-dot").forEach(dot => {
    const d = parseInt(dot.dataset.depth, 10);
    dot.classList.toggle("active", d === depth);
    dot.classList.toggle("loaded", d < depth);
  });

  // Update indicator text label.
  const nodeCount = renderer.getNodeCountAtDepth(depth);
  const text = navigation.getDepthIndicatorText(depth, nodeCount);
  const label = document.getElementById("depth-label");
  if (label) label.textContent = text;
}

/**
 * Schedule a depth indicator update on the next frame (after nodes are added).
 * @param {number} depth
 */
function _scheduleIndicatorUpdate(depth) {
  requestAnimationFrame(() => _updateDepthIndicator(depth));
}

// ─────────────────────────────────────────────────────────────────────────
//  Node event handlers
// ─────────────────────────────────────────────────────────────────────────

/** @param {string} nodeId @param {Object} attrs */
function _handleNodeClick(nodeId, attrs) {
  state.update({ focusedNode: nodeId });
  // chain-panel.js opens the panel and renders content.
  subgraph.openSubgraph(nodeId);
}

/** @param {string} nodeId @param {Object} attrs */
function _handleNodeHover(nodeId, attrs) {
  const tooltip = document.getElementById("node-tooltip");
  if (!tooltip) return;
  document.getElementById("tooltip-label").textContent = attrs.label || nodeId;
  document.getElementById("tooltip-kind").textContent  = attrs.kind  || "";
  tooltip.style.display = "block";
}

/** @param {string} _nodeId */
function _handleNodeHoverOut(_nodeId) {
  const tooltip = document.getElementById("node-tooltip");
  if (tooltip) tooltip.style.display = "none";
}

// ─────────────────────────────────────────────────────────────────────────
//  Side panel helpers (panel content owned by chain-panel.js via subgraph.js)
// ─────────────────────────────────────────────────────────────────────────

function _closePanel() {
  subgraph.closeSubgraph();
  state.update({ focusedNode: null });
}

// ─────────────────────────────────────────────────────────────────────────
//  Tooltip mouse tracking
// ─────────────────────────────────────────────────────────────────────────

document.addEventListener("mousemove", (ev) => {
  const tooltip = document.getElementById("node-tooltip");
  if (!tooltip || tooltip.style.display === "none") return;
  tooltip.style.left = `${ev.clientX + 14}px`;
  tooltip.style.top  = `${ev.clientY + 8}px`;
});

// ─────────────────────────────────────────────────────────────────────────
//  Status bar
// ─────────────────────────────────────────────────────────────────────────

let _statusClearTimer = null;

/**
 * @param {string}  message
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

