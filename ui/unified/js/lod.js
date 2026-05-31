// Cortex — LOD (Level of Detail) progressive graph loader.
//
// Prevents rendering 600K+ nodes at once by loading phases on demand:
//   - Zoom out → show only domain skeleton (L0, ~20 nodes)
//   - Zoom in  → auto-load the next phase for the visible area
//   - Click node → expand that node's immediate children
//
// Works on top of the existing D3 force graph via JUG.appendGraphDelta.
// The force simulation absorbs new nodes at their parent's position,
// letting D3 handle placement naturally.
//
// Phase map (matches server PHASES):
//   L0  domains        ← always loaded
//   L1  setup (skills/hooks/agents/commands)
//   L2  tools (tool_hub)
//   L3  files
//   L4  discussions
//   L5  memories
//   L6:<proj>  AST symbols (per project, skipped if >50K nodes)
//
// Usage: loaded by unified-viz.html after workflow_graph_bridge.js.
//        No explicit init needed — attaches to JUG events automatically.
(function () {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var loadedPhases    = {};   // phaseKey → true
  var pendingPhases   = {};   // phaseKey → true (in-flight)
  var L6_NODE_CAP     = 50000; // skip L6 phases larger than this

  // Zoom thresholds: D3's k (scale) value at which to auto-load deeper phases.
  // k = 1 is the initial zoom; k > 1 = zoomed in.
  var ZOOM_THRESHOLDS = [
    { phase: 'L1', minK: 0.6  },   // zoom in slightly → load setup ring
    { phase: 'L2', minK: 1.1  },   // more zoom → tools
    { phase: 'L3', minK: 1.8  },   // file ring
    { phase: 'L4', minK: 2.8  },   // discussions
    { phase: 'L5', minK: 4.0  },   // memories
  ];

  // ── Phase loading ─────────────────────────────────────────────────────────

  function _apiURL(path) {
    var base = (window.JUG && JUG.API_URL) || 'http://127.0.0.1:3458/api/graph';
    return base.replace('/api/graph', '') + path;
  }

  function _loadPhase(key) {
    if (loadedPhases[key] || pendingPhases[key]) return;
    pendingPhases[key] = true;
    fetch(_apiURL('/api/graph/phase?name=' + encodeURIComponent(key)))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.ready) return;
        var nodes = data.nodes || [];
        var edges = data.edges || [];
        if (!nodes.length && !edges.length) return;
        // Skip oversized L6 phases — symbols cloud would overwhelm the sim.
        if (key.indexOf('L6:') === 0 && (data.node_total || 0) > L6_NODE_CAP) {
          console.log('[lod] skipped (too large)', key, data.node_total, 'nodes');
          loadedPhases[key] = true;
          return;
        }
        if (typeof JUG.appendGraphDelta === 'function') {
          JUG.appendGraphDelta(nodes, edges);
        }
        loadedPhases[key] = true;
        console.log('[lod] loaded', key, '+' + nodes.length + 'N', '+' + edges.length + 'E');
      })
      .catch(function (err) {
        console.warn('[lod] phase', key, 'failed:', err.message);
        loadedPhases[key] = true; // don't retry
      })
      .then(function () { delete pendingPhases[key]; });
  }

  function _loadL6FromProgress() {
    fetch(_apiURL('/api/graph/progress'))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (p) {
        if (!p || !p.phases) return;
        Object.keys(p.phases).forEach(function (k) {
          if (k.indexOf('L6:') === 0 && p.phases[k]) _loadPhase(k);
        });
      })
      .catch(function () {});
  }

  // ── Zoom-driven auto-expand ───────────────────────────────────────────────

  var _lastK = 1;
  var _zoomCheckRaf = null;

  function _onZoom(k) {
    if (Math.abs(k - _lastK) < 0.05) return;   // ignore micro-changes
    _lastK = k;

    ZOOM_THRESHOLDS.forEach(function (t) {
      if (k >= t.minK && !loadedPhases[t.phase]) {
        _loadPhase(t.phase);
        if (t.phase === 'L3') {
          // L3 ready → also trigger L6 discovery
          setTimeout(_loadL6FromProgress, 2000);
        }
      }
    });
  }

  // Hook into D3's zoom event via JUG events emitted by workflow_graph_bridge.
  // The bridge emits 'graph:zoom' with {k} on every D3 zoom transform.
  if (window.JUG && JUG.on) {
    JUG.on('graph:zoom', function (ev) {
      if (ev && ev.k != null) _onZoom(ev.k);
    });
  }

  // ── Click-to-expand: reveal children of clicked node ─────────────────────

  // When a node is clicked, load the phase that contains its children.
  // Domain → load L1; tool_hub → load L2; file → load L3; etc.
  var KIND_NEXT_PHASE = {
    domain:     'L1',
    tool_hub:   'L2',
    file:       'L3',
    discussion: 'L4',
    memory:     'L5',
  };

  if (window.JUG && JUG.on) {
    JUG.on('graph:selectNode', function (node) {
      if (!node) return;
      var next = KIND_NEXT_PHASE[node.kind || node.type || ''];
      if (next && !loadedPhases[next]) {
        console.log('[lod] click-expand', node.id, '→ loading', next);
        _loadPhase(next);
      }
    });
  }

  // ── Polling: watch progress and load ready phases ─────────────────────────
  // On initial page load, poll until L0 is ready, then hand off to zoom/click.

  var _progressPoller = null;
  var _pollCount = 0;

  function _pollProgress() {
    fetch(_apiURL('/api/graph/progress'))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (p) {
        if (!p) return;
        // L0 is the skeleton — load it once ready.
        if (p.phases && p.phases['L0'] && !loadedPhases['L0']) {
          _loadPhase('L0');
        }
        // Kick progress polling off after we have L0.
        if (loadedPhases['L0'] || _pollCount > 30) {
          clearInterval(_progressPoller);
          return;
        }
      })
      .catch(function () {});
    _pollCount++;
  }

  // Start polling after a short delay to let the build kick off.
  setTimeout(function () {
    _progressPoller = setInterval(_pollProgress, 1500);
    _pollProgress();
  }, 800);

  // ── Expose for debugging ──────────────────────────────────────────────────
  window.JUG = window.JUG || {};
  JUG._lod = {
    loaded: loadedPhases,
    pending: pendingPhases,
    loadPhase: _loadPhase,
  };

})();
