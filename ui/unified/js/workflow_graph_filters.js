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
    L1: { skill: 1, hook: 1, command: 1, agent: 1, domain: 1 },
    L2: { tool_hub: 1, domain: 1 },
    L3: { file: 1, domain: 1 },
    L4: { discussion: 1, domain: 1 },
    L5: { memory: 1, domain: 1 },
  };

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
    document.body.addEventListener('click', function (ev) {
      var btn = ev.target && ev.target.closest
        ? ev.target.closest('.filter-btn[data-wfg-filter]')
        : null;
      if (!btn) return;
      state.wfgFilter = btn.dataset.wfgFilter;
      // Visual active-state toggle scoped to wfg filter buttons.
      var all = document.querySelectorAll('.filter-btn[data-wfg-filter]');
      for (var i = 0; i < all.length; i++) all[i].classList.remove('active');
      btn.classList.add('active');
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
