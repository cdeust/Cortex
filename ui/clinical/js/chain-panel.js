/**
 * chain-panel.js — Side-panel chain-of-call / chain-of-action view.
 *
 * Spec: docs/02-sub-graph-drill-down.md
 *
 * Responsibilities
 * ────────────────
 *  • Open / replace / close the #side-panel.
 *  • Maintain a back-navigation history stack (max 5 entries).
 *  • Show local graphology neighbours instantly (zero-latency).
 *  • Fetch GET /api/graph/chain and render via Mermaid.
 *  • Apply per-kind default tab mapping.
 *  • Handle all error cases with user-visible feedback.
 *
 * This module never touches the main Sigma instance or the graphology graph
 * directly — it receives a `getGraph` factory so it stays decoupled.
 *
 * External dependencies (via globals)
 * ────────────────────────────────────
 *  window.mermaid  — loaded from vendor/mermaid.min.js
 */

import { fetchChain } from "./api.js";

// ── DOM refs (resolved once on first open) ────────────────────────────────

/** @type {HTMLElement|null} */
let _panel      = null;
/** @type {HTMLElement|null} */
let _labelEl    = null;
/** @type {HTMLElement|null} */
let _kindEl     = null;
/** @type {HTMLElement|null} */
let _backBtn    = null;
/** @type {HTMLElement|null} */
let _closeBtn   = null;
/** @type {HTMLElement|null} */
let _bodyEl     = null;
/** @type {HTMLElement|null} */
let _tabsEl     = null;
/** @type {HTMLElement|null} */
let _neighbourList = null;
/** @type {HTMLElement|null} */
let _mermaidSection = null;
/** @type {HTMLElement|null} */
let _mermaidDiv     = null;
/** @type {HTMLElement|null} */
let _truncatedBadge = null;
/** @type {HTMLElement|null} */
let _chainError     = null;

// ── State ─────────────────────────────────────────────────────────────────

/** @type {string|null} */
let _currentNodeId = null;
/** @type {"causal"|"impact"|"call"} */
let _currentTab = "call";

/**
 * History stack for back-navigation.
 * @type {Array<{nodeId:string, tab:"causal"|"impact"|"call"}>}
 */
const _history = [];
const HISTORY_MAX = 5;

// ── Mermaid lazy init ─────────────────────────────────────────────────────

let _mermaidReady = false;
let _mermaidInitPending = false;

function _initMermaid() {
  if (_mermaidReady || _mermaidInitPending) return;
  if (!window.mermaid) {
    console.warn("[chain-panel] mermaid global not loaded; chain diagram unavailable");
    return;
  }
  _mermaidInitPending = true;
  try {
    window.mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });
    _mermaidReady = true;
  } catch (e) {
    console.warn("[chain-panel] mermaid.initialize error:", e);
  }
  _mermaidInitPending = false;
}

// ── getGraph factory ──────────────────────────────────────────────────────

/** @type {()=>any|null} */
let _getGraph = () => null;

// ── Per-kind default tab ──────────────────────────────────────────────────

/**
 * Map node kind → default panel tab per spec §4.
 * @param {string} kind
 * @returns {"causal"|"impact"|"call"}
 */
function _defaultTab(kind) {
  switch (kind) {
    case "memory":     return "causal";
    case "symbol":     return "call";
    case "file":       return "impact";
    case "discussion": return "causal";
    case "domain":     return "impact";
    case "entity":     return "causal";
    default:           return "call";
  }
}

// ── DOM bootstrap ─────────────────────────────────────────────────────────

function _ensureDom() {
  if (_panel) return;
  _panel           = document.getElementById("side-panel");
  _labelEl         = document.getElementById("panel-node-label");
  _kindEl          = document.getElementById("panel-node-kind");
  _backBtn         = document.getElementById("panel-back-btn");
  _closeBtn        = document.getElementById("panel-close-btn");
  _bodyEl          = document.getElementById("panel-body");
  _tabsEl          = document.getElementById("panel-tabs");
  _neighbourList   = document.getElementById("panel-neighbour-list");
  _mermaidSection  = document.getElementById("panel-mermaid-section");
  _mermaidDiv      = document.getElementById("panel-mermaid-div");
  _truncatedBadge  = document.getElementById("panel-truncated-badge");
  _chainError      = document.getElementById("panel-chain-error");
}

// ── Tab handling ──────────────────────────────────────────────────────────

/**
 * Activate the given tab button and update _currentTab.
 * @param {"causal"|"impact"|"call"} tab
 */
function _activateTab(tab) {
  _currentTab = tab;
  if (!_tabsEl) return;
  _tabsEl.querySelectorAll(".panel-tab").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
}

// ── Neighbour list ────────────────────────────────────────────────────────

const _KIND_COLOURS = {
  domain: "#d9a63c", skill: "#42c5b5", hook: "#b06fcf",
  agent: "#5882e8", command: "#5abf7c", tool: "#e07040",
  file: "#c8943c", discussion: "#6870cf", memory: "#66b87a",
  symbol: "#c4963c", entity: "#c75840",
};

/** @param {string} kind @returns {string} */
function _kindColour(kind) {
  return _KIND_COLOURS[kind] || "#7a7a7a";
}

/**
 * Render local graphology neighbours (depth = 1).
 * @param {string} nodeId
 */
function _renderNeighbours(nodeId) {
  if (!_neighbourList) return;
  _neighbourList.innerHTML = "";

  const graph = _getGraph();
  if (!graph || !graph.hasNode(nodeId)) {
    _appendEmptyNeighbour("No neighbours in loaded graph");
    return;
  }

  const edges = [
    ...graph.inEdges(nodeId).map(e => ({
      neighbour:  graph.source(e),
      edgeAttrs:  graph.getEdgeAttributes(e),
      direction:  "in",
    })),
    ...graph.outEdges(nodeId).map(e => ({
      neighbour:  graph.target(e),
      edgeAttrs:  graph.getEdgeAttributes(e),
      direction:  "out",
    })),
  ].slice(0, 50);

  if (edges.length === 0) {
    _appendEmptyNeighbour("No neighbours loaded");
    return;
  }

  for (const { neighbour, edgeAttrs, direction } of edges) {
    const nAttrs = graph.getNodeAttributes(neighbour);
    const li = document.createElement("li");
    li.className = "neighbour-item";
    li.setAttribute("role", "button");
    li.setAttribute("tabindex", "0");
    li.setAttribute("aria-label", `Navigate to ${nAttrs.label || neighbour}`);

    const dot = document.createElement("span");
    dot.className = "neighbour-kind-dot";
    dot.style.background = _kindColour(nAttrs.kind);

    const labelSpan = document.createElement("span");
    labelSpan.className = "neighbour-label";
    labelSpan.textContent = nAttrs.label || neighbour;

    const edgeSpan = document.createElement("span");
    edgeSpan.className = "neighbour-edge-type";
    edgeSpan.textContent = `${direction === "in" ? "←" : "→"} ${edgeAttrs.type || edgeAttrs.label || ""}`;

    li.appendChild(dot);
    li.appendChild(labelSpan);
    li.appendChild(edgeSpan);

    // Clicking or activating a neighbour navigates the panel to that node.
    li.addEventListener("click", () => { openNode(neighbour); });
    li.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNode(neighbour); }
    });
    _neighbourList.appendChild(li);
  }
}

/**
 * @param {string} text
 */
function _appendEmptyNeighbour(text) {
  if (!_neighbourList) return;
  const li = document.createElement("li");
  li.className = "neighbour-item";
  li.style.color = "var(--fg-3)";
  li.textContent = text;
  _neighbourList.appendChild(li);
}

// ── Mermaid rendering ─────────────────────────────────────────────────────

/**
 * Show a loading placeholder inside the mermaid container.
 */
function _showChainLoading() {
  if (!_mermaidDiv) return;
  _mermaidDiv.removeAttribute("data-processed");
  _mermaidDiv.innerHTML = "";
  if (_chainError)     { _chainError.classList.remove("visible");     _chainError.textContent = ""; }
  if (_truncatedBadge) { _truncatedBadge.classList.remove("visible"); }

  const loadingEl = document.createElement("div");
  loadingEl.className = "panel-loading";
  loadingEl.innerHTML = `<span class="spinner"></span><span>Loading chain…</span>`;
  _mermaidDiv.appendChild(loadingEl);
}

/**
 * Render a Mermaid diagram string inside the panel.
 * Handles render errors gracefully by showing raw source in <pre>.
 * @param {string} mermaidSource
 * @param {boolean} truncated
 */
async function _renderMermaid(mermaidSource, truncated) {
  if (!_mermaidDiv) return;

  if (!mermaidSource || !mermaidSource.trim()) {
    _showChainUnavailable("No chain data available for this node");
    return;
  }

  _initMermaid();

  if (truncated && _truncatedBadge) {
    _truncatedBadge.classList.add("visible");
  } else if (_truncatedBadge) {
    _truncatedBadge.classList.remove("visible");
  }

  // Clear loading placeholder.
  _mermaidDiv.innerHTML = "";
  _mermaidDiv.removeAttribute("data-processed");
  _mermaidDiv.textContent = mermaidSource;

  if (!_mermaidReady || !window.mermaid) {
    // Mermaid not available: show raw source.
    const pre = document.createElement("pre");
    pre.style.cssText = "font-size:10px;white-space:pre-wrap;color:var(--fg-2);";
    pre.textContent = mermaidSource;
    _mermaidDiv.innerHTML = "";
    _mermaidDiv.appendChild(pre);
    return;
  }

  try {
    await window.mermaid.run({ nodes: [_mermaidDiv] });
  } catch (err) {
    console.warn("[chain-panel] mermaid render error:", err);
    // Fallback: raw source in <pre>.
    const pre = document.createElement("pre");
    pre.style.cssText = "font-size:10px;white-space:pre-wrap;color:var(--fg-2);margin:0;";
    pre.textContent = mermaidSource;
    _mermaidDiv.innerHTML = "";
    _mermaidDiv.appendChild(pre);
  }
}

/**
 * Show a chain-unavailable message (non-fatal: neighbour list stays visible).
 * @param {string} message
 */
function _showChainUnavailable(message) {
  if (!_mermaidDiv)  return;
  _mermaidDiv.innerHTML = "";
  if (_chainError) {
    _chainError.textContent = message;
    _chainError.classList.add("visible");
  }
  if (_truncatedBadge) _truncatedBadge.classList.remove("visible");
}

// ── Chain fetch + render ──────────────────────────────────────────────────

/**
 * Fetch and render the chain for the given node label and tab.
 * @param {string} nodeId
 * @param {"causal"|"impact"|"call"} tab
 * @param {string} nodeLabel
 */
function _fetchAndRenderChain(nodeId, tab, nodeLabel) {
  // Show loading state immediately.
  _showChainLoading();

  // Use nodeLabel for the chain lookup (server resolves by entity name).
  const label = nodeLabel || nodeId;

  fetchChain(label, 4, tab)
    .then(data => {
      if (!data) {
        _showChainUnavailable("Chain unavailable");
        return;
      }
      if (!data.mermaid || !data.mermaid.trim()) {
        _showChainUnavailable("No chain available for this node");
        return;
      }
      _renderMermaid(data.mermaid, data.truncated === true).catch(err => {
        console.warn("[chain-panel] renderMermaid threw:", err);
        _showChainUnavailable("Diagram render error");
      });
    })
    .catch(err => {
      console.warn("[chain-panel] fetchChain failed:", err.message);
      _showChainUnavailable("Chain unavailable — " + err.message);
    });
}

// ── Back-navigation ───────────────────────────────────────────────────────

/**
 * Update the back button visibility.
 */
function _syncBackBtn() {
  if (!_backBtn) return;
  if (_history.length > 0) {
    _backBtn.classList.add("visible");
  } else {
    _backBtn.classList.remove("visible");
  }
}

// ── Core render ───────────────────────────────────────────────────────────

/**
 * Render the panel content for a node.
 * @param {string} nodeId
 * @param {"causal"|"impact"|"call"} tab
 * @param {boolean} [pushHistory=true]
 */
function _render(nodeId, tab, pushHistory = true) {
  _ensureDom();
  if (!_panel) return;

  if (pushHistory && _currentNodeId !== null) {
    if (_history.length >= HISTORY_MAX) _history.shift();
    _history.push({ nodeId: _currentNodeId, tab: _currentTab });
  }

  _currentNodeId = nodeId;
  _activateTab(tab);
  _syncBackBtn();

  // Update panel header.
  const graph = _getGraph();
  const attrs = graph && graph.hasNode(nodeId) ? graph.getNodeAttributes(nodeId) : {};
  const label = attrs.label || nodeId;
  const kind  = attrs.kind  || "";

  if (_labelEl) _labelEl.textContent = label;
  if (_kindEl)  _kindEl.textContent  = kind;

  // Show panel if not already open.
  _panel.classList.add("open");

  // Render local neighbours immediately (zero latency).
  _renderNeighbours(nodeId);

  // Fetch and render chain diagram.
  _fetchAndRenderChain(nodeId, tab, label);
}

// ── Public API ────────────────────────────────────────────────────────────

/**
 * Initialise the panel module.
 * Must be called once before openNode().
 * @param {{
 *   getGraph: () => any|null,
 * }} options
 */
export function init({ getGraph }) {
  _getGraph = getGraph || (() => null);
  _ensureDom();

  // Wire tab clicks.
  if (_tabsEl) {
    _tabsEl.querySelectorAll(".panel-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        if (!_currentNodeId) return;
        _render(_currentNodeId, btn.dataset.tab, /* pushHistory= */ false);
      });
    });
  }

  // Wire back button.
  if (_backBtn) {
    _backBtn.addEventListener("click", panelBack);
  }

  // Wire close button.
  if (_closeBtn) {
    _closeBtn.addEventListener("click", closePanel);
  }
}

/**
 * Open (or replace) the panel for a node.
 * Uses the per-kind default tab unless overridden.
 * Pushes the previous node onto the history stack.
 * @param {string} nodeId
 * @param {"causal"|"impact"|"call"} [tab]
 */
export function openNode(nodeId, tab) {
  _ensureDom();
  const graph = _getGraph();
  const attrs = graph && graph.hasNode(nodeId) ? graph.getNodeAttributes(nodeId) : {};
  const resolvedTab = tab || _defaultTab(attrs.kind || "");
  _render(nodeId, resolvedTab);
}

/**
 * Switch tab on the CURRENT node without pushing to history.
 * No-op when no node is focused.
 * @param {"causal"|"impact"|"call"} tab
 */
export function switchTab(tab) {
  if (!_currentNodeId) return;
  _render(_currentNodeId, tab, /* pushHistory= */ false);
}

/**
 * Navigate back one step in history.
 * If history is empty, closes the panel.
 */
export function panelBack() {
  if (_history.length === 0) {
    closePanel();
    return;
  }
  const prev = _history.pop();
  _render(prev.nodeId, prev.tab, /* pushHistory= */ false);
  _syncBackBtn();
}

/**
 * Close the panel and reset state.
 */
export function closePanel() {
  _ensureDom();
  if (_panel) _panel.classList.remove("open");
  _currentNodeId = null;
  _history.length = 0;
  _syncBackBtn();
}

/**
 * Return the currently focused node ID, or null.
 * @returns {string|null}
 */
export function currentNodeId() {
  return _currentNodeId;
}
