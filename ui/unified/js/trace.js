// Cortex — Execution-Trace view (domain-split, collapsible, live).
//
// Navigation: domain -expand> session -expand> chain-of-work -expand> file.
// Each level is fetched live on expand (no snapshot):
//   /api/trace/domains              -> collapsed domain hubs
//   /api/trace/sessions?domain=<id> -> sessions + has_session edges
//   /api/trace/chain?session=<sid>  -> ordered prompt/action/file chain
//   /api/trace/file?path=<p>        -> file drill (rendered into detail panel)
//
// Emits workflow_graph.v1-shaped nodes/edges so the existing D3 force
// renderer (workflow_graph.js) + detail panels apply unchanged.
(function () {
  'use strict';

  // Per-tool action colors (override the generic 'action' KIND_COLOR).
  var TOOL_COLOR = {
    Read: '#38BDF8', NotebookRead: '#38BDF8', Grep: '#7DD3FC', Glob: '#7DD3FC',
    Edit: '#FBBF24', MultiEdit: '#FBBF24', NotebookEdit: '#FBBF24',
    Write: '#34D399', Bash: '#F87171',
    Task: '#EC4899', Agent: '#EC4899', WebFetch: '#A78BFA', WebSearch: '#A78BFA',
  };

  var _expanded = Object.create(null);
  var _mounted = false;
  var _booted = false;

  // ── Live tail ──────────────────────────────────────────────────────────
  // The trace is built from JSONL session transcripts, which grow as Claude
  // works. "Real-time" here = polling each EXPANDED session for new chain
  // steps (and each expanded domain for new sessions) and appending only
  // the delta. appendGraphDelta dedups by id, and build_chain's ``since``
  // cursor means each poll ships only the new tail — O(new events), not the
  // whole chain. No pg_notify: memories aren't the trace; tool calls are.
  var _liveSince = Object.create(null);   // session node id -> next_since cursor
  var _liveDomains = Object.create(null); // domain id -> known session count
  var _liveTimer = null;
  var _liveOn = true;
  var LIVE_MS = 4000;

  function _container() { return document.getElementById('graph-container'); }

  function _clearGraph() {
    // Reset dedup sets BEFORE seeding the renderer so the first
    // appendGraphDelta is treated as fresh. setGraphData normalizes to
    // {nodes, links}; pass exactly that shape (force-graph's onChange
    // calls .filter on links, so it must be an array).
    JUG._existingIdSet = new Set();
    JUG._existingEdgeSet = new Set();
    _expanded = Object.create(null);
    // Seed lastData with the TRACE schema so the workflow-graph bridge
    // hands trace data back to the force-graph renderer (tree-branching)
    // instead of overlaying its radial-galaxy canvas. appendGraphDelta
    // only seeds meta when lastData is null, so set it here first.
    JUG.state.lastData = {
      nodes: [], edges: [], links: [],
      meta: { schema: 'trace.v1', source: 'trace' },
    };
    if (typeof JUG.setGraphData === 'function') {
      // renderer.setGraphData(nodes, links) — two ARRAY args, not an object.
      JUG.setGraphData([], []);
    }
  }

  function _colorize(nodes) {
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if ((n.kind === 'action' || n.type === 'action') && n.tool && TOOL_COLOR[n.tool]) {
        n.color = TOOL_COLOR[n.tool];
      }
    }
    return nodes;
  }

  function _fetchJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function _apply(payload) {
    if (!payload) return;
    var nodes = _colorize(payload.nodes || []);
    JUG.appendGraphDelta(nodes, payload.edges || []);
  }

  function _setStatus(text) {
    var el = document.getElementById('status-text');
    if (el) el.textContent = text;
  }

  function _boot() {
    if (_booted) return;
    _booted = true;
    _clearGraph();
    _setStatus('Loading domains...');
    _fetchJSON('/api/trace/domains')
      .then(function (d) {
        _apply(d);
        _setStatus((d.nodes || []).length + ' domains - click to expand');
      })
      .catch(function (err) {
        _setStatus('Trace load failed: ' + err.message);
        _booted = false;
      });
  }

  function _expand(node) {
    if (!node || !node.id) return;
    var kind = node.kind || node.type;
    if (_expanded[node.id] && kind !== 'file') return;

    if (kind === 'domain') {
      _expanded[node.id] = true;
      _setStatus('Loading sessions...');
      _fetchJSON('/api/trace/sessions?domain=' + encodeURIComponent(node.id))
        .then(function (d) {
          _apply(d);
          // Live: remember how many sessions this domain has, so the
          // poller can surface NEW sessions started after expand.
          _liveDomains[node.id] = (d.nodes || []).length;
          _ensureLiveTimer();
          _setStatus((d.nodes || []).length + ' sessions');
        })
        .catch(function (e) { _expanded[node.id] = false; _setStatus('Sessions failed: ' + e.message); });
    } else if (kind === 'session') {
      _expanded[node.id] = true;
      var sid = node.session_id || String(node.id).replace(/^session:/, '');
      _setStatus('Loading chain...');
      _fetchJSON('/api/trace/chain?session=' + encodeURIComponent(sid))
        .then(function (d) {
          _apply(d);
          var m = d.meta || {};
          // Register this session for live tailing.
          _liveSince[node.id] = (typeof d.next_since === 'number')
            ? d.next_since : (m.event_count || 0);
          _ensureLiveTimer();
          _setStatus('chain - ' + (m.event_count || 0) + ' steps (live)');
        })
        .catch(function (e) { _expanded[node.id] = false; _setStatus('Chain failed: ' + e.message); });
    } else if (kind === 'file') {
      _drillFile(node);
    }
  }

  // ── Live tail: poll expanded sessions + domains for new work ──────────
  function _ensureLiveTimer() {
    if (_liveTimer || !_liveOn) return;
    _liveTimer = setInterval(_liveTick, LIVE_MS);
  }

  function _stopLiveTimer() {
    if (_liveTimer) { clearInterval(_liveTimer); _liveTimer = null; }
  }

  function _liveTick() {
    if (!_mounted || !_liveOn) return;
    // 1. Tail every expanded session for new chain steps.
    Object.keys(_liveSince).forEach(function (sessNodeId) {
      var sid = sessNodeId.replace(/^session:/, '');
      var since = _liveSince[sessNodeId] || 0;
      _fetchJSON('/api/trace/chain?session=' + encodeURIComponent(sid) + '&since=' + since)
        .then(function (d) {
          if (d && d.nodes && d.nodes.length) {
            _apply(d);
            _flash((d.nodes || []).filter(function (n) {
              return (n.kind || n.type) === 'action' || (n.kind || n.type) === 'prompt';
            }).length + ' new in ' + sid.slice(0, 8));
          }
          if (typeof d.next_since === 'number') _liveSince[sessNodeId] = d.next_since;
        })
        .catch(function () { /* transient; retry next tick */ });
    });
    // 2. Surface NEW sessions in expanded domains.
    Object.keys(_liveDomains).forEach(function (domId) {
      _fetchJSON('/api/trace/sessions?domain=' + encodeURIComponent(domId))
        .then(function (d) {
          var n = (d.nodes || []).length;
          if (n > (_liveDomains[domId] || 0)) {
            _apply(d);   // dedup drops the ones already shown
            _liveDomains[domId] = n;
            _flash('+new session in ' + domId.replace(/^domain:/, ''));
          }
        })
        .catch(function () {});
    });
  }

  function _flash(msg) {
    _setStatus('● live · ' + msg);
  }

  function _setLive(on) {
    _liveOn = !!on;
    if (_liveOn) { _ensureLiveTimer(); _setStatus('● live on'); }
    else { _stopLiveTimer(); _setStatus('○ live paused'); }
  }

  // ── L3 file drill: AST symbols + git history + impact ─────────────────
  function _drillFile(node) {
    var path = node.path || String(node.id).replace(/^file:/, '');
    _fetchJSON('/api/trace/file?path=' + encodeURIComponent(path))
      .then(function (d) { _renderFileDrill(node, d); })
      .catch(function (e) { _setStatus('File drill failed: ' + e.message); });
  }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _renderFileDrill(node, d) {
    var content = document.getElementById('detail-content');
    if (!content) return;
    var git = (d && d.git) || {};
    var ast = (d && d.ast) || {};
    var h = '<div class="section-title">File - ' + _esc(node.label || '') + '</div>';

    h += '<div class="section-title">Git</div>';
    if (git.available) {
      h += '<div class="conn-item">' + _esc(git.diff_type || 'unknown')
        + ' - ' + ((git.lines || []).length) + ' lines'
        + (git.truncated ? ' (truncated)' : '') + '</div>';
    } else {
      h += '<div class="conn-item" style="color:var(--fg-3)">no git data</div>';
    }

    h += '<div class="section-title">AST symbols</div>';
    var syms = ast && ast.available ? ast.symbols : null;
    var rows = Array.isArray(syms) ? syms
      : (syms && Array.isArray(syms.rows) ? syms.rows
      : (syms && Array.isArray(syms.nodes) ? syms.nodes : []));
    if (ast && ast.available && rows.length) {
      rows.slice(0, 40).forEach(function (s) {
        var nm = s.qualified_name || s.name || s.id || (s.properties && s.properties.name) || '?';
        h += '<div class="conn-item"><span class="conn-label">' + _esc(nm) + '</span></div>';
      });
      if (rows.length > 40) h += '<div class="conn-item">... ' + (rows.length - 40) + ' more</div>';
    } else {
      var reason = (ast && (ast.reason || ast.error)) || 'not indexed';
      h += '<div class="conn-item" style="color:var(--fg-3)">no AST - ' + _esc(reason) + '</div>';
    }

    var prev = content.querySelector('.trace-file-drill');
    if (prev) prev.remove();
    var section = document.createElement('div');
    section.className = 'trace-file-drill';
    section.innerHTML = h;
    content.appendChild(section);
  }

  function _show() {
    var c = _container();
    if (c) c.style.display = '';
    _mounted = true;
    _boot();
    if (_liveOn && (Object.keys(_liveSince).length || Object.keys(_liveDomains).length)) {
      _ensureLiveTimer();
    }
  }
  function _hide() {
    _mounted = false;
    _stopLiveTimer();   // don't poll while another view is active
  }

  function _attach() {
    if (!window.JUG || !JUG.on) { setTimeout(_attach, 60); return; }
    JUG.on('state:activeView', function (ev) {
      if (ev && ev.value === 'trace') _show(); else _hide();
    });
    JUG.on('graph:selectNode', function (node) {
      if (_mounted) _expand(node);
    });
    if (JUG.state && JUG.state.activeView === 'trace') _show();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _attach);
  } else {
    _attach();
  }

  window.TraceView = {
    boot: _boot,
    reload: function () { _booted = false; _boot(); },
    setLive: _setLive,
    isLive: function () { return _liveOn; },
  };
})();
