// Cortex — Workflow Graph filter bar wiring.
// Listens to clicks on `.filter-btn[data-wfg-filter]` + the domain select
// + the search box, builds a node-level predicate, and asks the active
// renderer to apply it. Nothing matches any filter returns to "All".
(function () {
  var state = {
    wfgFilter: 'all',           // layer / kind: / file: / cross-domain / all
    domain: '',                 // domain label (matches n.domain_id via label)
    query: '',                  // free-text search (path, label, content)
  };

  var SETUP_KINDS = { skill: 1, hook: 1, command: 1, agent: 1 };
  var LAYER_KINDS = {
    L1: { skill: 1, hook: 1, command: 1, agent: 1, mcp: 1, domain: 1 },
    L2: { tool_hub: 1, domain: 1 },
    L3: { file: 1, domain: 1 },
    L4: { discussion: 1, domain: 1 },
    L5: { memory: 1, domain: 1 },
    L6: { symbol: 1, entity: 1, domain: 1 },
  };
  // Edge-kind filter → include every node that is a source or target
  // of an edge of this kind (and domain anchors for scaffolding).
  var AST_EDGE_KINDS = { defined_in: 1, calls: 1, imports: 1, member_of: 1 };

  // Precomputed on each filter change: for edge-based filters, the
  // set of node ids that touch the chosen edge kind. Rebuilt lazily.
  var _edgeHits = null;
  var _edgeHitsKey = '';

  function rebuildEdgeHits(edgeKind, ctx) {
    var key = edgeKind + '@' + (ctx.edges ? ctx.edges.length : 0);
    if (_edgeHits && _edgeHitsKey === key) return _edgeHits;
    var hits = {};
    var edges = ctx.edges || [];
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      if (e.kind !== edgeKind) continue;
      var sId = (typeof e.source === 'object') ? e.source.id : e.source;
      var tId = (typeof e.target === 'object') ? e.target.id : e.target;
      hits[sId] = 1; hits[tId] = 1;
    }
    _edgeHits = hits; _edgeHitsKey = key;
    return hits;
  }

  function predicate(n, ctx) {
    // Domain filter: include the node if it belongs to the selected
    // domain (or IS the selected domain node). Domain label comparison
    // ignores the `domain:` prefix.
    if (state.domain) {
      var sel = state.domain;
      var dom = n.kind === 'domain'
        ? (n.label || n.id.replace('domain:', ''))
        : (ctx.byId[n.domain_id] ? (ctx.byId[n.domain_id].label || '') : '');
      var extras = (n.extra_domain_ids || []).map(function (d) {
        return ctx.byId[d] ? (ctx.byId[d].label || '') : '';
      });
      if (dom !== sel && extras.indexOf(sel) === -1) return false;
    }

    // Main selector.
    var f = state.wfgFilter || 'all';
    if (f !== 'all') {
      if (f.charAt(0) === 'L') {
        if (!(LAYER_KINDS[f] && LAYER_KINDS[f][n.kind])) return false;
      } else if (f.indexOf('kind:') === 0) {
        if (n.kind !== f.slice(5)) return false;
      } else if (f.indexOf('file:') === 0) {
        if (n.kind === 'domain') {
          // keep domain anchors so the cloud still has its hub.
        } else if (n.kind !== 'file' || n.primary_cluster !== f.slice(5)) {
          return false;
        }
      } else if (f.indexOf('edge:') === 0) {
        var ek = f.slice(5);
        if (n.kind === 'domain') {
          // keep domain hubs so context remains readable.
        } else if (AST_EDGE_KINDS[ek]) {
          var hits = rebuildEdgeHits(ek, ctx);
          if (!hits[n.id]) return false;
        }
      } else if (f === 'cross-domain') {
        if (n.kind === 'domain') {
          // keep.
        } else if (!(n.extra_domain_ids && n.extra_domain_ids.length)) {
          return false;
        }
      }
    }

    // Text search — matches on label, path, body, id (case-insensitive).
    if (state.query) {
      var q = state.query.toLowerCase();
      var hay = (n.label || '') + ' ' + (n.path || '') + ' ' + (n.body || '') + ' ' + (n.id || '');
      if (hay.toLowerCase().indexOf(q) === -1) return false;
    }
    return true;
  }

  function apply() {
    if (!window.JUG || typeof JUG.wfgApplyFilter !== 'function') return;
    JUG.wfgApplyFilter(predicate);
  }

  function bindButtons() {
    // Grouped select — one control replaces 14 buttons.
    var sel = document.getElementById('wfg-filter-select');
    if (sel) {
      sel.addEventListener('change', function () {
        state.wfgFilter = sel.value || 'all';
        apply();
      });
    }
    // Reset button: back to "all".
    var reset = document.getElementById('wfg-filter-reset');
    if (reset) {
      reset.addEventListener('click', function () {
        state.wfgFilter = 'all';
        if (sel) sel.value = 'all';
        apply();
      });
    }
    // Backward-compat: old ``data-wfg-filter`` buttons (if any remain).
    document.body.addEventListener('click', function (ev) {
      var btn = ev.target && ev.target.closest
        ? ev.target.closest('.filter-btn[data-wfg-filter]')
        : null;
      if (!btn) return;
      state.wfgFilter = btn.dataset.wfgFilter;
      var all = document.querySelectorAll('.filter-btn[data-wfg-filter]');
      for (var i = 0; i < all.length; i++) all[i].classList.remove('active');
      btn.classList.add('active');
      if (sel) sel.value = state.wfgFilter;
      apply();
    });
  }

  function bindDomainSelect() {
    var sel = document.getElementById('domain-select');
    if (!sel) return;
    // Populate options from the graph data once it's ready.
    function populate() {
      var data = window.JUG && JUG.state && JUG.state.lastData;
      if (!data || !Array.isArray(data.nodes)) return;
      var domains = [];
      for (var i = 0; i < data.nodes.length; i++) {
        var n = data.nodes[i];
        if (n.kind === 'domain' || n.type === 'domain') {
          domains.push(n.label || n.id.replace('domain:', ''));
        }
      }
      domains.sort();
      var current = sel.value;
      sel.innerHTML = '<option value="">All Domains</option>';
      for (var j = 0; j < domains.length; j++) {
        var opt = document.createElement('option');
        opt.value = domains[j];
        opt.textContent = domains[j];
        sel.appendChild(opt);
      }
      if (domains.indexOf(current) !== -1) sel.value = current;
    }
    sel.addEventListener('change', function () {
      state.domain = sel.value || '';
      apply();
    });
    if (window.JUG && JUG.on) JUG.on('state:lastData', populate);
    populate();
  }

  function bindSearch() {
    var box = document.getElementById('search-box');
    if (!box) return;
    var t = null;
    box.addEventListener('input', function () {
      clearTimeout(t);
      t = setTimeout(function () {
        state.query = (box.value || '').trim();
        apply();
      }, 120);
    });
  }

  function boot() {
    if (!window.JUG || !JUG.on) { setTimeout(boot, 50); return; }
    bindButtons();
    bindDomainSelect();
    bindSearch();
    // Initial apply after data arrives.
    JUG.on('state:lastData', function () { setTimeout(apply, 50); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
