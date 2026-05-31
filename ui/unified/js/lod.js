// Cortex — LOD: on-demand, per-node progressive loading.
//
// POLICY:
//   Startup: load L0 (domains, ~20 nodes). That's it.
//   On click: inject ONLY the children of the clicked node.
//             Never load the whole next phase at once.
//
// How it works:
//   Each phase is fetched ONCE and cached in _phaseCache.
//   Clicking a node injects only the slice of cached nodes whose
//   domain_id or parent id matches the clicked node — so clicking
//   "cortex" shows cortex's L1 children, not every domain's L1.
//
// Nodes injected near the clicked node's position for natural placement.
(function () {
  'use strict';

  // ── Phase cache ────────────────────────────────────────────────────────────
  var _phaseCache   = {};   // phaseKey → {nodes, edges}
  var _fetchPromise = {};   // phaseKey → Promise (dedup concurrent fetches)
  var _injectedFor  = {};   // nodeId → true (already expanded this node)

  // Kind → which phase to fetch when this node is clicked.
  var KIND_PHASE = {
    domain:     'L1',
    tool_hub:   'L2',
    mcp:        'L2',
    agent:      'L2',
    skill:      'L3',
    hook:       'L3',
    command:    'L3',
    file:       'L4',
    discussion: 'L5',
    memory:     'L5',
  };

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _base() {
    return (JUG.API_URL || 'http://127.0.0.1:3458/api/graph')
             .replace('/api/graph', '');
  }

  function _status(msg) {
    var el = document.getElementById('status-text');
    if (el) el.textContent = msg;
  }

  // ── Fetch + cache a phase ──────────────────────────────────────────────────

  function _fetchPhase(key) {
    if (_phaseCache[key]) return Promise.resolve(_phaseCache[key]);
    if (_fetchPromise[key]) return _fetchPromise[key];

    _fetchPromise[key] = fetch(_base() + '/api/graph/phase?name=' + encodeURIComponent(key))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.ready) {
          _phaseCache[key] = { nodes: data.nodes || [], edges: data.edges || [] };
          return _phaseCache[key];
        }
        // Not ready — retry in 3 s, do not cache.
        delete _fetchPromise[key];
        return new Promise(function (resolve) {
          setTimeout(function () { resolve(_fetchPhase(key)); }, 3000);
        });
      })
      .catch(function () {
        delete _fetchPromise[key];
        return { nodes: [], edges: [] };
      });

    return _fetchPromise[key];
  }

  // ── Inject children of a clicked node ─────────────────────────────────────

  function _injectChildren(node, phaseKey) {
    if (_injectedFor[node.id]) return;
    _injectedFor[node.id] = true;
    _status('Loading children of ' + (node.label || node.id) + '…');

    _fetchPhase(phaseKey).then(function (phase) {
      var allNodes = phase.nodes;
      var allEdges = phase.edges;

      // Filter to nodes whose domain_id matches the clicked node, OR whose
      // parent edge connects to the clicked node id.
      var domainId = node.id;             // e.g. "domain:cortex"
      var domainSlug = node.domain || (node.id.split(':')[1] || '');

      var childNodes = allNodes.filter(function (n) {
        return n.domain_id === domainId
            || n.domain    === domainSlug
            || n.parent_id === domainId;
      });

      if (!childNodes.length) {
        // No domain match — fall back to injecting the full phase once.
        // This covers tool_hub, file, etc. whose parent isn't a domain.
        childNodes = allNodes;
      }

      // Collect edges that connect child nodes.
      var childIds = Object.create(null);
      childNodes.forEach(function (n) { childIds[n.id] = true; });
      var childEdges = allEdges.filter(function (e) {
        return childIds[e.source] || childIds[e.target];
      });

      // Seed positions near the clicked node so D3 places them locally.
      var graph = JUG.state && JUG.state.lastData;
      var px = 0, py = 0;
      if (graph) {
        var parent = (graph.nodes || []).find(function (n) { return n.id === node.id; });
        if (parent) { px = parent.x || 0; py = parent.y || 0; }
      }
      childNodes.forEach(function (n) {
        if (n.x == null) n.x = px + (Math.random() - 0.5) * 60;
        if (n.y == null) n.y = py + (Math.random() - 0.5) * 60;
      });

      if (childNodes.length) {
        if (typeof JUG.appendGraphDelta === 'function') {
          JUG.appendGraphDelta(childNodes, childEdges);
        }
        console.log('[lod] injected', childNodes.length, 'children of', node.id,
                    '(phase', phaseKey + ')');
      }
      _status('Online — click nodes to expand');
    });
  }

  // ── Click handler ──────────────────────────────────────────────────────────

  if (window.JUG && JUG.on) {
    JUG.on('graph:selectNode', function (node) {
      if (!node) return;
      var kind = node.kind || node.type || '';
      var phase = KIND_PHASE[kind];
      if (!phase) return;
      _injectChildren(node, phase);
    });
  }

  // ── Boot: load L0 once the server has it ready ─────────────────────────────

  var _bootTries = 0;
  function _bootPoll() {
    _bootTries++;
    if (_bootTries > 30) return; // give up after ~60 s
    fetch(_base() + '/api/graph/progress')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (p) {
        if (!p || !p.phases) return;
        if (p.phases['L0']) {
          _fetchPhase('L0').then(function (phase) {
            if (phase.nodes.length && typeof JUG.appendGraphDelta === 'function') {
              JUG.appendGraphDelta(phase.nodes, phase.edges);
              console.log('[lod] boot: L0 loaded,', phase.nodes.length, 'domain nodes');
              _status('Online — click a domain to expand it');
            }
          });
          return; // stop polling
        }
        _status('Building graph…');
        setTimeout(_bootPoll, 2000);
      })
      .catch(function () { setTimeout(_bootPoll, 3000); });
  }

  // Kick build then poll.
  fetch(_base() + '/api/graph/progress').catch(function () {});
  setTimeout(_bootPoll, 1200);

  // ── Debug ──────────────────────────────────────────────────────────────────
  window.JUG = window.JUG || {};
  JUG._lod = {
    cache: _phaseCache,
    injected: _injectedFor,
    loadPhase: _fetchPhase,
    inject: _injectChildren,
  };

}());
