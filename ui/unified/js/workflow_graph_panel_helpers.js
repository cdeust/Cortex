// Cortex Workflow Graph — neighbor + framework helpers for the side panel.
//
// Extracted from workflow_graph_panel.js (Dijkstra compliance pass —
// the panel module exceeded the project 300-line rule; neighbor
// traversal + rendering primitives factor out cleanly since they are
// pure DOM/data transforms with no dependency on panel state).
//
// Exports JUG._wfgPanelNeighbors = {
//   NEIGHBOR_MAX,
//   domainLabel(ctx, domain_id) -> string,
//   countNeighborsByKind(n, ctx) -> { kind: count },
//   collectNeighbors(n, ctx, filter) -> [neighborNode],
//   renderNeighborList(body, title, neighbors, ctx, onClickFactory?),
// };
//
// The panel module publishes framework primitives (el, row, section)
// on JUG._wfgPanelHelpers BEFORE this module runs; we read them here
// so the extraction is a one-way dependency: helpers → panel.

(function () {
  function P() {
    return (window.JUG && window.JUG._wfgPanelHelpers) || {};
  }
  function H() {
    return (window.JUG && window.JUG._wfgHumanize) || {};
  }

  function domainLabel(ctx, domain_id) {
    var d = ctx.byId[domain_id];
    return d ? (d.label || d.id.replace('domain:', '')) : (domain_id || '—');
  }

  function countNeighborsByKind(n, ctx) {
    var out = {};
    var adj = ctx.adj[n.id] || {};
    for (var id in adj) {
      var kind = (ctx.byId[id] && ctx.byId[id].kind) || '?';
      out[kind] = (out[kind] || 0) + 1;
    }
    return out;
  }

  // Gather neighbors split by (edge-kind, direction, neighbor-kind) so
  // we can show contextual lists like "Called from", "Uses", etc.
  // ``filter(edge, isOutgoing, neighborNode) -> boolean``
  function collectNeighbors(n, ctx, filter) {
    var out = [];
    var seen = {};
    for (var i = 0; i < ctx.edges.length; i++) {
      var e = ctx.edges[i];
      var sId = e.source.id || e.source;
      var tId = e.target.id || e.target;
      var isOut = sId === n.id;
      var isIn = tId === n.id;
      if (!isOut && !isIn) continue;
      var other = isOut ? ctx.byId[tId] : ctx.byId[sId];
      if (!other) continue;
      if (!filter(e, isOut, other)) continue;
      if (seen[other.id]) continue;
      seen[other.id] = 1;
      out.push(other);
    }
    return out;
  }

  var NEIGHBOR_MAX = 24;

  function _onNeighborClick(nb) {
    return function (ev) {
      ev.preventDefault();
      if (window.JUG && JUG.wfgApplyFilter) {
        if (typeof JUG.emit === 'function') JUG.emit('graph:selectNode', nb);
      }
    };
  }

  function _buildNeighborRow(nb) {
    var p = P();
    var h = H();
    var r = p.el('div', 'wfg-panel__row wfg-panel__row--clickable');
    var k = p.el('div', 'wfg-panel__key');
    // Vygotsky audit: go through kindLabel so neighbor rows show
    // "Memory" not "memory", "Code item" not "symbol".
    k.textContent = h.kindLabel ? h.kindLabel(nb.kind) : (nb.kind || '?');
    var v = p.el('div', 'wfg-panel__val');
    var a = p.el('a', 'wfg-panel__link');
    a.textContent = nb.label || nb.path || nb.id;
    a.href = '#';
    a.title = nb.path || nb.id;
    a.addEventListener('click', _onNeighborClick(nb));
    v.appendChild(a);
    r.appendChild(k); r.appendChild(v);
    return r;
  }

  // Render a list of named neighbor nodes under a section title.
  // Truncates to NEIGHBOR_MAX; shows "+N more" footer if exceeded.
  function renderNeighborList(body, sectionTitle, neighbors, ctx, onClickFactory) {
    if (!neighbors || !neighbors.length) return;
    var p = P();
    var s = p.section(sectionTitle + ' (' + neighbors.length + ')');
    var shown = neighbors.slice(0, NEIGHBOR_MAX);
    shown.forEach(function (nb) {
      var r = _buildNeighborRow(nb);
      if (onClickFactory) {
        // Replace default click with caller-supplied handler.
        var a = r.querySelector ? r.querySelector('a') : null;
        if (a) {
          a.removeEventListener && a.removeEventListener('click', _onNeighborClick);
          a.addEventListener('click', onClickFactory(nb));
        }
      }
      s.appendChild(r);
    });
    if (neighbors.length > NEIGHBOR_MAX) {
      var more = p.el('div', 'wfg-panel__more');
      more.textContent = '+' + (neighbors.length - NEIGHBOR_MAX) + ' more…';
      s.appendChild(more);
    }
    body.appendChild(s);
  }

  // ── actionBtn + renderTechnicalDetails ──────────────────────────────
  // Moved here from workflow_graph_panel.js in the Dijkstra YELLOW pass
  // so the panel module stays under the project 300-line rule.

  function actionBtn(label, onClick) {
    var p = P();
    var b = p.el('button', 'wfg-panel__action');
    b.type = 'button';
    b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
  }

  // Fields already shown humanized OR structural — skipped.
  var _TECHNICAL_SKIP = {
    id: 1, kind: 1, label: 1, color: 1, size: 1,
    body: 1, tags: 1, is_protected: 1, is_stale: 1,
  };

  function _technicalKeys(n) {
    return Object.keys(n).filter(function (k) {
      if (_TECHNICAL_SKIP[k]) return false;
      var v = n[k];
      if (v == null) return false;
      if (Array.isArray(v) && v.length === 0) return false;
      if (typeof v === 'object' && Object.keys(v).length === 0) return false;
      return true;
    });
  }

  // Vygotsky ZPD bridge: plain label + raw key.
  function _buildAdvancedRow(k, v, pretty) {
    var p = P();
    if (typeof v === 'object') v = JSON.stringify(v);
    if (typeof v === 'number' && !Number.isInteger(v)) v = v.toFixed(4);
    var r = p.el('div', 'wfg-panel__row');
    var keyCell = p.el('div', 'wfg-panel__key');
    keyCell.textContent = pretty(k);
    if (pretty(k) !== k && pretty(k).toLowerCase() !== k.replace(/_/g, ' ')) {
      var raw = p.el('span', 'wfg-panel__raw-key');
      raw.textContent = ' · ' + k;
      keyCell.appendChild(raw);
    }
    var valCell = p.el('div', 'wfg-panel__val');
    valCell.textContent = v == null ? '—' : String(v);
    r.appendChild(keyCell); r.appendChild(valCell);
    return r;
  }

  function renderTechnicalDetails(body, n, humanizer) {
    var p = P();
    var pretty = (humanizer && humanizer.prettyFieldKey)
      || function (k) { return k; };
    var keys = _technicalKeys(n);
    if (!keys.length) return;
    var d = document.createElement('details');
    d.className = 'wfg-panel__advanced';
    var sum = document.createElement('summary');
    sum.textContent = 'Technical details';
    d.appendChild(sum);
    var wrap = p.el('div', 'wfg-panel__advanced-body');
    keys.sort().forEach(function (k) {
      wrap.appendChild(_buildAdvancedRow(k, n[k], pretty));
    });
    d.appendChild(wrap);
    body.appendChild(d);
  }

  window.JUG = window.JUG || {};
  window.JUG._wfgPanelNeighbors = {
    NEIGHBOR_MAX:          NEIGHBOR_MAX,
    domainLabel:           domainLabel,
    countNeighborsByKind:  countNeighborsByKind,
    collectNeighbors:      collectNeighbors,
    renderNeighborList:    renderNeighborList,
    actionBtn:             actionBtn,
    renderTechnicalDetails: renderTechnicalDetails,
  };
})();
