// Cortex — LOD via SSE with depth gate.
//
// Subscribes to /api/graph/events (the live SSE stream).
// Each batch has a `label` that maps to a depth level.
// Default gate: accept depth 0 (domains) + depth 1 (setup).
// On node click: open the gate one level deeper for that node's domain.
//
// No polling loops. No phase endpoint. The SSE stream IS the data.
(function () {
  'use strict';

  // ── Depth mapping: SSE batch label → depth level ───────────────────────────
  // Labels come from the graph builder (graph_event_stream.py push calls).
  function _depthOf(label, kind) {
    if (!label) return _kindDepth(kind);
    var l = label.toLowerCase();
    if (l === 'skeleton' || l.startsWith('l0') || l === 'domains') return 0;
    if (l === 'skills' || l === 'hooks' || l === 'agents' || l === 'commands'
        || l.startsWith('l1') || l === 'setup') return 1;
    if (l === 'tools' || l.startsWith('l2') || l === 'tool_hubs') return 2;
    if (l === 'files' || l.startsWith('l3')) return 3;
    if (l === 'discussions' || l.startsWith('l4')) return 4;
    if (l === 'memories' || l.startsWith('l5')) return 5;
    if (l.startsWith('l6') || l.includes('symbol')) return 6;
    return _kindDepth(kind);
  }

  function _kindDepth(kind) {
    var map = { domain:0, skill:1, hook:1, command:1, agent:1, mcp:1,
                tool_hub:2, file:3, discussion:4, memory:5, symbol:6 };
    return map[kind] != null ? map[kind] : 1;
  }

  // ── Gate: which depths are currently allowed ───────────────────────────────
  // Default: domains (0) + setup (1). Never memories/symbols unless asked.
  var _maxDepth = 1;          // global ceiling
  var _domainDepth = {};      // domainSlug → ceiling (overrides global)
  var _seenBatches = {};      // label → true (prevent re-injecting on reconnect)

  function _allowed(depth, domainSlug) {
    var ceiling = (_domainDepth[domainSlug] != null)
                    ? _domainDepth[domainSlug]
                    : _maxDepth;
    return depth <= ceiling;
  }

  // ── SSE subscriber ─────────────────────────────────────────────────────────
  var _source = null;
  var _retries = 0;
  var _MAX_RETRIES = 5;

  function _connect() {
    if (_source) { _source.close(); _source = null; }
    var url = (JUG.API_URL || 'http://127.0.0.1:3458/api/graph')
                .replace('/api/graph', '/api/graph/events');
    _source = new EventSource(url);

    _source.addEventListener('batch', function (ev) {
      try {
        var d = JSON.parse(ev.data);
        var nodes = d.nodes || [];
        var edges = d.edges || [];
        if (!nodes.length && !edges.length) return;

        // Classify batch by first node's kind if label is ambiguous.
        var firstKind = nodes[0] ? (nodes[0].kind || nodes[0].type || '') : '';
        var depth = _depthOf(d.label, firstKind);

        // Filter nodes to allowed depth.
        var allowed = nodes.filter(function (n) {
          var nDepth = _depthOf(d.label, n.kind || n.type || '');
          var slug = n.domain || (n.domain_id || '').split(':')[1] || '';
          return _allowed(nDepth, slug);
        });
        if (!allowed.length) return;

        // Seed positions from parent if available.
        var graph = JUG.state && JUG.state.lastData;
        allowed.forEach(function (n) {
          if (n.x != null && n.y != null) return;
          var domId = n.domain_id || ('domain:' + (n.domain || ''));
          if (graph) {
            var parent = (graph.nodes || []).find(function(gn){ return gn.id === domId; });
            if (parent) {
              n.x = (parent.x || 0) + (Math.random() - 0.5) * 80;
              n.y = (parent.y || 0) + (Math.random() - 0.5) * 80;
            }
          }
        });

        var allowedIds = Object.create(null);
        allowed.forEach(function(n){ allowedIds[n.id] = true; });
        var filtEdges = edges.filter(function(e){
          return allowedIds[e.source] || allowedIds[e.target];
        });

        if (typeof JUG.appendGraphDelta === 'function') {
          JUG.appendGraphDelta(allowed, filtEdges);
        }
        _retries = 0;
      } catch (e) {
        console.warn('[lod] batch parse error', e);
      }
    });

    _source.addEventListener('done', function () {
      _source.close(); _source = null;
      _status('Online — click a node to expand');
    });

    _source.onerror = function () {
      _source.close(); _source = null;
      if (_retries < _MAX_RETRIES) {
        _retries++;
        setTimeout(_connect, 2000 * _retries);
      }
    };
  }

  // ── Click-to-expand: unlock one more depth for the clicked node's domain ───
  var _expandedNodes = {};

  if (window.JUG && JUG.on) {
    JUG.on('graph:selectNode', function (node) {
      if (!node || _expandedNodes[node.id]) return;
      _expandedNodes[node.id] = true;

      var kind  = node.kind || node.type || '';
      var slug  = node.domain || (node.id.split(':')[1] || '');
      var depth = _kindDepth(kind);
      var want  = depth + 1;

      if (want > 4) return; // stop before memories (5) unless explicit

      // Raise the ceiling for this domain and reconnect SSE so missed
      // batches replay (EventSource Last-Event-ID handles resume).
      var current = _domainDepth[slug] != null ? _domainDepth[slug] : _maxDepth;
      if (want <= current) return; // already unlocked

      _domainDepth[slug] = want;
      console.log('[lod] unlocked', slug, '→ depth', want);
      _status('Loading depth ' + want + ' for ' + (node.label || slug) + '…');

      // Reconnect to replay missed batches at new depth.
      setTimeout(function () { _connect(); }, 50);
    });
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function _status(msg) {
    var el = document.getElementById('status-text');
    if (el) el.textContent = msg;
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  // Kick the build via progress poll, then open the SSE stream.
  fetch((JUG.API_URL||'http://127.0.0.1:3458/api/graph').replace('/api/graph','/api/graph/progress'))
    .catch(function(){});
  setTimeout(_connect, 1000);

  // Suppress the "loading memories" progress banner — user only cares about
  // structural graph. Hide it after L1 is done.
  if (window.JUG && JUG.on) {
    JUG.on('state:activeView', function(ev) {
      if (ev && ev.value === 'graph') {
        var b = document.getElementById('build-progress');
        if (b) b.style.display = 'none';
      }
    });
  }
  // Also hide it on boot after a short grace period.
  setTimeout(function() {
    var b = document.getElementById('build-progress');
    if (b) b.style.display = 'none';
  }, 8000);

  // ── Debug ──────────────────────────────────────────────────────────────────
  window.JUG = window.JUG || {};
  JUG._lod = {
    maxDepth: function(d){ _maxDepth = d; _connect(); },
    unlockDomain: function(slug, d){ _domainDepth[slug] = d; _connect(); },
    domainDepth: _domainDepth,
  };

}());
