/**
 * renderer.js — Sigma + graphology instance creator.
 *
 * Manages a single Sigma WebGL renderer over a graphology directed graph.
 * All visual state is encoded in node/edge attributes; Sigma reads them
 * through node/edge reducers.
 *
 * Depth visibility is controlled by per-node `hidden` attribute:
 *   hidden = (node.depth > currentVisibleDepth)
 *
 * Fade-in is implemented by transitioning `fadePct` (0 → 1) on newly-
 * revealed nodes over FADE_FRAMES animation frames.
 *
 * Public surface
 * ──────────────
 * mount(container, callbacks)
 * addNodes(nodes)
 * addEdges(edges)
 * clear()
 * refresh()
 * applyPositions(positionMap)
 * applyCircularLayout()
 * setVisibleDepth(maxDepth)
 * getNodeCountAtDepth(depth)
 * getGraph()
 * getSigma()
 * onNodeClick(fn)
 */

/** @type {any|null} — graphology Graph instance */
let _graph = null;
/** @type {any|null} — Sigma instance */
let _sigma = null;

/** @type {Function|null} */
let _nodeClickCb    = null;
/** @type {Function|null} */
let _nodeHoverCb    = null;
/** @type {Function|null} */
let _nodeHoverOutCb = null;

// ── Fade animation ─────────────────────────────────────────────────────────
// Nodes being faded in are tracked here.  Each tick advances fadePct toward 1.
/** @type {Set<string>} */
const _fadingIn = new Set();
const FADE_FRAMES = 18;   // ~300 ms at 60 fps
let _fadeRafId = null;

// ── Node-kind → colour ─────────────────────────────────────────────────────
const KIND_COLOURS = {
  domain:     "#d9a63c",
  skill:      "#42c5b5",
  hook:       "#b06fcf",
  agent:      "#5882e8",
  command:    "#5abf7c",
  tool:       "#e07040",
  file:       "#c8943c",
  discussion: "#6870cf",
  memory:     "#66b87a",
  symbol:     "#c4963c",
  entity:     "#c75840",
};
const DEFAULT_COLOUR = "#7a7a7a";

// ── Depth → default node size ──────────────────────────────────────────────
const DEPTH_SIZE = [22, 16, 12, 8, 5, 4, 3];

// ─────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────

/**
 * @param {string} kind
 * @returns {string}
 */
function kindColour(kind) {
  return KIND_COLOURS[kind] || DEFAULT_COLOUR;
}

/**
 * @param {number} depth
 * @returns {number}
 */
function depthSize(depth) {
  return DEPTH_SIZE[Math.min(depth, DEPTH_SIZE.length - 1)] || 3;
}

/**
 * Blend a hex colour toward transparent by multiplying alpha.
 * Returns an rgba() string.
 * @param {string} hex  — "#rrggbb"
 * @param {number} alpha — 0..1
 * @returns {string}
 */
function _hexAlpha(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
}

// ─────────────────────────────────────────────────────────────────────────
//  Reducers
// ─────────────────────────────────────────────────────────────────────────

/**
 * Node reducer: map stored attributes to Sigma visual attributes.
 * Applies fade (fadePct) and hidden flag.
 * @param {any} _g
 * @param {string} _node
 * @param {Object} data
 * @returns {Object}
 */
function _nodeReducer(_g, _node, data) {
  const depth  = data.depth || 0;
  const hidden = data.hidden === true;
  const base   = data.color || kindColour(data.kind || "");
  const size   = data.size  || depthSize(depth);

  if (hidden) {
    return { ...data, hidden: true, label: "", color: base, size };
  }

  // Fade-in: if fadePct < 1 apply alpha to colour and shrink size.
  const pct   = typeof data.fadePct === "number" ? data.fadePct : 1;
  const color = pct < 0.999 ? _hexAlpha(base.startsWith("#") ? base : "#7a7a7a", pct) : base;

  return {
    ...data,
    color,
    size:   size * (0.3 + 0.7 * pct),
    hidden: false,
    label:  data.label || _node,
  };
}

/**
 * Edge reducer: hide edges if either endpoint is hidden.
 * @param {any} graph
 * @param {string} edge
 * @param {Object} data
 * @returns {Object}
 */
function _edgeReducer(graph, edge, data) {
  const srcHidden = graph.getNodeAttribute(graph.source(edge), "hidden");
  const tgtHidden = graph.getNodeAttribute(graph.target(edge), "hidden");
  if (srcHidden || tgtHidden) return { ...data, hidden: true };
  return { ...data, hidden: false, color: "#333333", size: 0.5 };
}

// ─────────────────────────────────────────────────────────────────────────
//  Fade animation loop
// ─────────────────────────────────────────────────────────────────────────

function _tickFade() {
  if (!_graph || _fadingIn.size === 0) {
    _fadeRafId = null;
    return;
  }
  const step = 1 / FADE_FRAMES;
  const done = [];
  for (const id of _fadingIn) {
    if (!_graph.hasNode(id)) { done.push(id); continue; }
    const cur = _graph.getNodeAttribute(id, "fadePct") || 0;
    const next = Math.min(1, cur + step);
    _graph.setNodeAttribute(id, "fadePct", next);
    if (next >= 1) done.push(id);
  }
  for (const id of done) _fadingIn.delete(id);
  if (_sigma) _sigma.refresh();
  _fadeRafId = requestAnimationFrame(_tickFade);
}

/** Start the fade loop if not already running. */
function _startFade() {
  if (_fadeRafId !== null) return;
  _fadeRafId = requestAnimationFrame(_tickFade);
}

// ─────────────────────────────────────────────────────────────────────────
//  Public API
// ─────────────────────────────────────────────────────────────────────────

/**
 * Mount Sigma on the given container element.
 * Kills any previous instance first.
 * @param {HTMLElement} container
 * @param {{
 *   onNodeClick?:    (id: string, attrs: Object) => void,
 *   onNodeHover?:    (id: string, attrs: Object) => void,
 *   onNodeHoverOut?: (id: string) => void,
 * }} callbacks
 */
export function mount(container, callbacks = {}) {
  if (_sigma) { _sigma.kill(); _sigma = null; _graph = null; }

  const GraphClass = (window.graphology && window.graphology.Graph)
    ? window.graphology.Graph
    : window.graphology;

  _graph = new GraphClass({ multi: false, type: "directed", allowSelfLoops: false });

  const SigmaClass = window.Sigma;
  _sigma = new SigmaClass(_graph, container, {
    renderEdgeLabels:              false,
    defaultEdgeType:               "arrow",
    labelDensity:                  0.07,
    labelGridCellSize:             60,
    labelRenderedSizeThreshold:    6,
    nodeReducer:                   _nodeReducer,
    edgeReducer:                   _edgeReducer,
  });

  _nodeClickCb    = callbacks.onNodeClick    || null;
  _nodeHoverCb    = callbacks.onNodeHover    || null;
  _nodeHoverOutCb = callbacks.onNodeHoverOut || null;

  _sigma.on("clickNode", ({ node }) => {
    if (_nodeClickCb) _nodeClickCb(node, _graph.getNodeAttributes(node));
  });
  _sigma.on("enterNode", ({ node }) => {
    if (_nodeHoverCb) _nodeHoverCb(node, _graph.getNodeAttributes(node));
  });
  _sigma.on("leaveNode", ({ node }) => {
    if (_nodeHoverOutCb) _nodeHoverOutCb(node);
  });
}

/**
 * Add nodes to the graphology graph.
 * Skips existing nodes silently.
 * Newly-added nodes that are NOT hidden start with fadePct=0 for fade-in.
 * @param {Array<{id:string, label?:string, kind?:string, depth?:number, x?:number, y?:number, [k:string]:*}>} nodes
 * @param {number} [currentVisibleDepth=Infinity]  — pass to skip hidden nodes' fade-in
 */
export function addNodes(nodes, currentVisibleDepth = Infinity) {
  if (!_graph) return;
  for (const n of nodes) {
    if (_graph.hasNode(n.id)) continue;
    const { id, ...attrs } = n;
    const nodeDepth = attrs.depth || 0;
    const isVisible = nodeDepth <= currentVisibleDepth;
    // Start fade-in for visible nodes; hidden nodes have fadePct=1 (irrelevant).
    const fadePct = isVisible ? 0 : 1;
    _graph.addNode(id, {
      label:   attrs.label || id,
      kind:    attrs.kind  || "default",
      depth:   nodeDepth,
      x:       typeof attrs.x === "number" ? attrs.x : (Math.random() - 0.5) * 100,
      y:       typeof attrs.y === "number" ? attrs.y : (Math.random() - 0.5) * 100,
      color:   kindColour(attrs.kind || ""),
      size:    depthSize(nodeDepth),
      hidden:  !isVisible,
      fadePct,
      ...attrs,
      // Ensure computed attrs are not overwritten by spread.
    });
    if (isVisible) {
      _fadingIn.add(id);
    }
  }
  _startFade();
}

/**
 * Add edges to the graphology graph.
 * Skips edges where source or target is missing, or already present.
 * @param {Array<{id?:string, source:string, target:string, type?:string}>} edges
 */
export function addEdges(edges) {
  if (!_graph) return;
  for (const e of edges) {
    const { source: src, target: tgt } = e;
    if (!src || !tgt) continue;
    if (!_graph.hasNode(src) || !_graph.hasNode(tgt)) continue;
    const edgeId = e.id || `${src}→${tgt}`;
    if (_graph.hasEdge(edgeId)) continue;
    if (_graph.hasEdge(src, tgt)) continue;
    try {
      _graph.addEdgeWithKey(edgeId, src, tgt, {
        type:   e.type  || "depends",
        label:  e.label || e.type || "",
        hidden: false,
      });
    } catch (_) {
      // Duplicate or self-loop — skip silently.
    }
  }
}

/**
 * Clear all nodes and edges from the graph.
 */
export function clear() {
  if (!_graph) return;
  _fadingIn.clear();
  _graph.clear();
  if (_sigma) _sigma.refresh();
}

/**
 * Register a click callback (replaces any previous).
 * @param {Function} fn  (nodeId: string, attrs: Object) => void
 */
export function onNodeClick(fn) {
  _nodeClickCb = fn;
}

/**
 * Trigger a Sigma refresh.
 */
export function refresh() {
  if (_sigma) _sigma.refresh();
}

/**
 * Update node positions from a {id → {x,y}} map.
 * @param {Map<string,{x:number,y:number}>} positionMap
 */
export function applyPositions(positionMap) {
  if (!_graph) return;
  positionMap.forEach(({ x, y }, id) => {
    if (_graph.hasNode(id)) {
      _graph.setNodeAttribute(id, "x", x);
      _graph.setNodeAttribute(id, "y", y);
    }
  });
  if (_sigma) _sigma.refresh();
}

/**
 * Apply graphology's built-in circular layout as a fallback.
 * Nodes are placed on concentric circles by depth band.
 */
export function applyCircularLayout() {
  if (!_graph) return;
  const nodes = _graph.nodes();
  const count = nodes.length;
  if (count === 0) return;
  nodes.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / count;
    const depth = _graph.getNodeAttribute(id, "depth") || 0;
    const r = 200 + depth * 60;
    _graph.setNodeAttribute(id, "x", r * Math.cos(angle));
    _graph.setNodeAttribute(id, "y", r * Math.sin(angle));
  });
  if (_sigma) _sigma.refresh();
}

/**
 * Show nodes up to maxDepth, hide nodes deeper than maxDepth.
 * Newly-revealed nodes receive fadePct=0 → fade animation.
 * @param {number} maxDepth
 */
export function setVisibleDepth(maxDepth) {
  if (!_graph) return;
  _graph.forEachNode((id, attrs) => {
    const nodeDepth = attrs.depth || 0;
    const shouldBeVisible = nodeDepth <= maxDepth;
    const wasHidden = attrs.hidden === true;

    if (shouldBeVisible && wasHidden) {
      // Reveal with fade-in.
      _graph.setNodeAttribute(id, "hidden",  false);
      _graph.setNodeAttribute(id, "fadePct", 0);
      _fadingIn.add(id);
    } else if (!shouldBeVisible && !wasHidden) {
      // Hide immediately.
      _graph.setNodeAttribute(id, "hidden",  true);
      _graph.setNodeAttribute(id, "fadePct", 1);
      _fadingIn.delete(id);
    }
  });
  _startFade();
  if (_sigma) _sigma.refresh();
}

/**
 * Return the number of nodes currently in the graph at exactly depth d.
 * @param {number} depth
 * @returns {number}
 */
export function getNodeCountAtDepth(depth) {
  if (!_graph) return 0;
  let count = 0;
  _graph.forEachNode((_id, attrs) => {
    if ((attrs.depth || 0) === depth) count++;
  });
  return count;
}

/**
 * Return the number of nodes currently in the graph at depth <= maxDepth.
 * @param {number} maxDepth
 * @returns {number}
 */
export function getNodeCountUpToDepth(maxDepth) {
  if (!_graph) return 0;
  let count = 0;
  _graph.forEachNode((_id, attrs) => {
    if ((attrs.depth || 0) <= maxDepth) count++;
  });
  return count;
}

/**
 * Get the underlying graphology graph (read-only reference).
 * @returns {any|null}
 */
export function getGraph() {
  return _graph;
}

/**
 * Get the Sigma instance.
 * @returns {any|null}
 */
export function getSigma() {
  return _sigma;
}
