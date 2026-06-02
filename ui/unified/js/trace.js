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
      // Chain renders ON the canvas as the session's grouped sub-cluster
      // (computeSlots gives each session an exclusive sector). Detail goes
      // in the single detail panel (detail_panel.js). No node-list panel.
      _expanded[node.id] = true;
      var sid = node.session_id || String(node.id).replace(/^session:/, '');
      _setStatus('Loading chain...');
      _fetchJSON('/api/trace/chain?session=' + encodeURIComponent(sid))
        .then(function (d) {
          var m = d.meta || {};
          _apply(d);            // chain nodes/edges → canvas, grouped
          _setStatus('chain - ' + (m.event_count || 0) + ' steps');
        })
        .catch(function (e) { _expanded[node.id] = false; _setStatus('Chain failed: ' + e.message); });
    }
    // file click: the impact diagram + detail are handled by the
    // detail-panel "Impact" section (detail_panel.js), not here.
  }

  // Tool→color used by both the canvas (via workflow_graph KIND_COLOR) and
  // the impact diagram / flow panel.
  var TOOL_DOT = {
    Read: '#38BDF8', NotebookRead: '#38BDF8', Grep: '#7DD3FC', Glob: '#7DD3FC',
    Edit: '#FBBF24', MultiEdit: '#FBBF24', NotebookEdit: '#FBBF24',
    Write: '#34D399', Bash: '#F87171', Task: '#EC4899', Agent: '#EC4899',
    WebFetch: '#A78BFA', WebSearch: '#A78BFA',
  };

  // ── Impact / dependency DIAGRAM (flow panel) ─────────────────────────
  // A developer's blast-radius view for a file: what it imports/calls
  // (downstream) and what calls/imports it (upstream), grouped, with the
  // file in the center. Built from /api/trace/impact (Cortex code-graph).
  // Exposed as window.TraceView.showImpact(path) so the detail-panel
  // "Impact" section can open it.
  var EDGE_KIND_LABEL = {
    imports: 'imports', calls: 'calls', member_of: 'member', uses: 'uses',
  };

  function _renderImpact(path) {
    var panel = document.getElementById('flow-panel');
    var content = document.getElementById('flow-content');
    var title = document.getElementById('flow-title');
    if (!panel || !content) return;
    if (title) title.textContent = 'Impact · ' + _short(path.split('/').pop(), 32);
    content.innerHTML = '<div class="impact-loading">analyzing dependencies…</div>';
    panel.classList.add('open');
    var detail = document.getElementById('detail-panel');
    panel.classList.toggle('with-detail', !!(detail && detail.classList.contains('open')));

    _fetchJSON('/api/trace/impact?path=' + encodeURIComponent(path))
      .then(function (d) {
        if (!d || !d.available) {
          content.innerHTML = '<div class="impact-loading">No dependency data · '
            + _esc((d && (d.reason || d.error)) || 'not indexed') + '</div>';
          return;
        }
        content.innerHTML = _impactHtml(d);
        // click a box → select that file/symbol on the canvas if present
        content.querySelectorAll('.impact-box[data-file]').forEach(function (el) {
          el.addEventListener('click', function () {
            var fp = el.getAttribute('data-file');
            var nid = 'file:' + fp;
            var nd = (JUG.state.lastData.nodes || []).filter(function (x) { return x.id === nid; })[0];
            if (nd && JUG.emit) JUG.emit('graph:selectNode', nd);
          });
        });
      })
      .catch(function (e) {
        content.innerHTML = '<div class="impact-loading">Impact failed: ' + _esc(e.message) + '</div>';
      });
  }

  function _impactGroup(title, items, dir) {
    if (!items || !items.length) return '';
    var h = '<div class="impact-group"><div class="impact-group-title">'
      + (dir === 'up' ? '▲ ' : dir === 'down' ? '▼ ' : '') + _esc(title)
      + ' <span class="impact-count">' + items.length + '</span></div>';
    items.slice(0, 60).forEach(function (it) {
      var kindLabel = EDGE_KIND_LABEL[it.kind] || it.kind || '';
      var conf = (it.confidence != null && it.confidence < 1)
        ? ' <span class="impact-conf">' + Math.round(it.confidence * 100) + '%</span>' : '';
      h += '<div class="impact-box" data-file="' + _esc(it.file || '') + '">'
        + '<span class="impact-arrow">' + (dir === 'up' ? '←' : dir === 'down' ? '→' : '·') + '</span>'
        + '<span class="impact-name">' + _esc(it.label || it.name || it.file || '?') + '</span>'
        + '<span class="impact-edge">' + _esc(kindLabel) + conf + '</span>'
        + '</div>';
    });
    if (items.length > 60) h += '<div class="impact-loading">… ' + (items.length - 60) + ' more</div>';
    return h + '</div>';
  }

  function _impactHtml(d) {
    var center = d.center || {};
    var h = '<div class="impact-center">' + _esc(center.label || center.file || 'this file') + '</div>';
    h += _impactGroup('Calls / imports (downstream)', d.downstream, 'down');
    h += _impactGroup('Called / imported by (upstream)', d.upstream, 'up');
    h += _impactGroup('Defines', d.members, 'flat');
    if (!(d.downstream || []).length && !(d.upstream || []).length && !(d.members || []).length) {
      h += '<div class="impact-loading">No dependencies found in the code-graph.</div>';
    }
    return h;
  }

  function _closeFlow() {
    var panel = document.getElementById('flow-panel');
    if (panel) panel.classList.remove('open');
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

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Trace detail panel: kind-dispatched rich info ────────────────────
  // Owns #detail-content for trace nodes. domain → counts; session →
  // linked conversation + chain summary; action → causal context + files;
  // prompt → full text; file → git diff + AST/impact.
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

  function _short(text, n) {
    n = n || 60;
    var s = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  function _attach() {
    if (!window.JUG || !JUG.on) { setTimeout(_attach, 60); return; }
    JUG.on('state:activeView', function (ev) {
      if (ev && ev.value === 'trace') _show(); else _hide();
    });
    // Detail is rendered by detail_panel.js (the single panel). Trace only
    // drives canvas EXPANSION on select.
    JUG.on('graph:selectNode', function (node) {
      if (_mounted) _expand(node);
    });
    var flowClose = document.getElementById('flow-close');
    if (flowClose) flowClose.addEventListener('click', _closeFlow);
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
    showImpact: _renderImpact,   // detail-panel "Impact" section opens this
  };
})();
