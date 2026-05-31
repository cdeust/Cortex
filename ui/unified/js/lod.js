// Cortex — LOD loader.
// The depth filter select (#wfg-filter-select) drives loading:
//   L0 (default): domains only
//   L1: + setup (skills/hooks/agents/commands)
//   L2: + tools
//   L3: + files   etc.
//
// The domain select (#domain-select) scopes which domain's children load.
// "All Domains" + L1 = all domains' setup layer.
// "cortex" + L2 = only cortex's tools.
//
// Data comes from /api/graph/phase (pull on demand).
// Nothing loads until the user changes the filter or clicks a node.
(function () {
  'use strict';

  var _loaded   = {};   // "phaseKey:domainSlug" → true
  var _pending  = {};   // same key → true (in-flight)

  var PHASES = ['L0','L1','L2','L3','L4','L5','L6'];

  var DEPTH_LABEL = {
    L0: 'domains', L1: 'setup', L2: 'tools',
    L3: 'files',   L4: 'discussions', L5: 'memories', L6: 'symbols',
  };

  // ── API base ───────────────────────────────────────────────────────────────

  function _base() {
    return (JUG.API_URL || 'http://127.0.0.1:3458/api/graph')
             .replace('/api/graph', '');
  }

  function _status(msg) {
    var el = document.getElementById('status-text');
    if (el) el.textContent = msg;
  }

  // ── Domain scoping ─────────────────────────────────────────────────────────
  //
  // A node belongs to the selected domain when its own `domain`/`domain_id`
  // names that domain. The domain hub node for `slug` is the node with
  // `kind === 'domain'` and `label === slug` (or `id` ending in `:slug`); it
  // also satisfies `domain === slug` for hubs that self-tag, so it is included
  // by the same predicate.
  //
  // Symptom: "I ask for L1 of Cortex I get all domains." Root cause: the old
  // filter had `|| n.kind === 'domain'`, which kept ALL 20 domain hubs for any
  // selected domain, regardless of slug — so selecting "cortex" still rendered
  // every domain. Fix: scope strictly to the selected domain's own nodes; the
  // one matching domain hub comes along naturally.
  function _belongsToDomain(n, slug) {
    if (n.domain === slug) return true;
    if ((n.domain_id || '').indexOf(slug) !== -1) return true;
    // The domain hub for this slug (its own kind === 'domain' node).
    if ((n.kind || n.type) === 'domain') {
      if (n.label === slug) return true;
      if ((n.id || '').indexOf(':' + slug) !== -1) return true;
    }
    return false;
  }

  // ── Load one phase, filtered by domain slug if provided ────────────────────

  function _loadPhase(phaseKey, domainSlug, onDone) {
    var cacheKey = phaseKey + ':' + (domainSlug || '*');
    if (_loaded[cacheKey] || _pending[cacheKey]) {
      if (typeof onDone === 'function') onDone();
      return;
    }
    _pending[cacheKey] = true;
    _status('Loading ' + (DEPTH_LABEL[phaseKey] || phaseKey) +
            (domainSlug ? ' for ' + domainSlug : '') + '…');

    fetch(_base() + '/api/graph/phase?name=' + encodeURIComponent(phaseKey))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) {
          delete _pending[cacheKey];
          if (typeof onDone === 'function') onDone();
          return;
        }
        if (!data.ready && !data.node_total) {
          // Not ready yet — retry once in 2 s
          setTimeout(function () {
            delete _pending[cacheKey];
            _loadPhase(phaseKey, domainSlug, onDone);
          }, 2000);
          return;
        }
        var nodes = data.nodes || [];
        var edges = data.edges || [];

        // Domain filter: keep only nodes matching the selected domain.
        //
        // L0 is the structural domain layer — keep ALL domain hubs so the
        // overall map layout stays intact even when a single domain is
        // selected. For L1+ (setup, tools, files, …) scope STRICTLY to the
        // selected domain: the user picked "cortex" + "L1" to see cortex's
        // hub and cortex's children, NOT all 20 domains' children.
        if (domainSlug && domainSlug !== 'all' && domainSlug !== '' &&
            phaseKey !== 'L0') {
          nodes = nodes.filter(function (n) {
            return _belongsToDomain(n, domainSlug);
          });
          var nodeIds = Object.create(null);
          nodes.forEach(function (n) { nodeIds[n.id] = true; });
          // Keep only edges internal to the kept node set — matches the
          // server-side AND scoping so no dangling edge endpoints leak in.
          edges = edges.filter(function (e) {
            return nodeIds[e.source] && nodeIds[e.target];
          });
        }

        if (nodes.length && typeof JUG.appendGraphDelta === 'function') {
          JUG.appendGraphDelta(nodes, edges);
          console.log('[lod]', phaseKey, (domainSlug || '*'),
                      '+' + nodes.length + 'N +' + edges.length + 'E');
        }
        _loaded[cacheKey] = true;
        delete _pending[cacheKey];
        _status('Online');
        if (typeof onDone === 'function') onDone();
      })
      .catch(function (err) {
        console.warn('[lod]', phaseKey, 'failed:', err.message);
        _loaded[cacheKey] = true;
        delete _pending[cacheKey];
        if (typeof onDone === 'function') onDone();
      });
  }

  // ── Load up to a given depth level (cumulative) ────────────────────────────

  function loadUpTo(maxDepth, domainSlug) {
    var idx  = PHASES.indexOf(maxDepth);
    if (idx < 0) idx = 0;
    var chain = PHASES.slice(0, idx + 1);  // e.g. ['L0','L1','L2'] for L2

    // Load sequentially so L0 domain hubs appear first.
    function loadNext(i) {
      if (i >= chain.length) return;
      _loadPhase(chain[i], domainSlug, function () { loadNext(i + 1); });
    }
    loadNext(0);
  }

  // ── Wire the depth filter select ───────────────────────────────────────────

  function _currentDepth() {
    var sel = document.getElementById('wfg-filter-select');
    if (!sel) return 'L0';
    var val = sel.value;
    // Only respond to our LOD options (L0-L6).
    return /^L[0-6]$/.test(val) ? val : 'L0';
  }

  function _currentDomain() {
    var sel = document.getElementById('domain-select');
    return sel ? (sel.value || '') : '';
  }

  // Clear only the cache keys for the phases we are about to (re)load, for the
  // requested domain scope. Clearing the WHOLE `_loaded` map (the old bug)
  // also wiped the boot poller's record that L0 had loaded, letting the poller
  // re-fire and reload from scratch — part of the reset loop.
  function _clearPhasesFor(depth, domain) {
    var idx = PHASES.indexOf(depth);
    if (idx < 0) idx = 0;
    var scope = ':' + (domain || '*');
    for (var i = 0; i <= idx; i++) {
      delete _loaded[PHASES[i] + scope];
    }
  }

  function _onFilterChange() {
    var depth  = _currentDepth();
    var domain = _currentDomain();
    // No full reset. resetGraph() rebuilds the scene with an EMPTY dataset,
    // which emits `state:lastData` with 0 nodes → the console "Graph: 0 nodes,
    // 0 edges" flash AND wipes the domain dropdown (controls.js /
    // workflow_graph_filters.js repopulate it from lastData on that event).
    // Instead we clear only the affected phase cache keys and re-append; the
    // dedup sets in graph.js make already-present nodes a no-op, so re-loading
    // the same depth is harmless and there is no visible empty flash.
    _clearPhasesFor(depth, domain);
    loadUpTo(depth, domain);
  }

  // Attach to the depth filter.
  function _attachControls() {
    var depthSel = document.getElementById('wfg-filter-select');
    if (depthSel) {
      depthSel.addEventListener('change', function () {
        var val = depthSel.value;
        if (/^L[0-6]$/.test(val)) _onFilterChange();
        // Non-LOD values fall through to the existing graph filter logic.
      });
    }
    var domainSel = document.getElementById('domain-select');
    if (domainSel) {
      domainSel.addEventListener('change', function () {
        var depth = _currentDepth();
        if (/^L[0-6]$/.test(depth)) {
          // Reload current depth for the new domain. Clear only this depth's
          // phase keys for the new scope so the strict domain filter re-runs.
          _clearPhasesFor(depth, domainSel.value || '');
          loadUpTo(depth, domainSel.value || '');
        }
      });
    }
  }

  // ── Click-to-expand: one depth deeper for the clicked node's domain ────────

  var _clickExpanded = {};

  if (window.JUG && JUG.on) {
    JUG.on('graph:selectNode', function (node) {
      if (!node || _clickExpanded[node.id]) return;
      _clickExpanded[node.id] = true;

      var kind  = node.kind || node.type || '';
      var KIND_NEXT = { domain:'L1', tool_hub:'L2', mcp:'L2',
                        file:'L3', discussion:'L4' };
      var next = KIND_NEXT[kind];
      if (!next) return;

      var slug = node.domain || (node.id.split(':')[1] || '');
      var cacheKey = next + ':' + slug;
      if (_loaded[cacheKey]) return;

      console.log('[lod] click-expand', node.id, '→', next, '(' + slug + ')');
      _loadPhase(next, slug);
    });
  }

  // ── Boot: load L0 (domains only) ──────────────────────────────────────────

  function _boot() {
    // Kick the build, wait for it to have L0, then load.
    fetch(_base() + '/api/graph/progress').catch(function(){});
    var tries = 0;
    var booted = false;  // guard: load L0 exactly once, regardless of polls
    function poll() {
      tries++;
      if (tries > 20 || booted) return;
      fetch(_base() + '/api/graph/progress')
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(p){
          if (p && (p.node_count > 0 || (p.phases && p.phases['L0']))) {
            booted = true;
            _loadPhase('L0', '', function(){
              _status('Online — use the filter to load deeper layers');
            });
          } else {
            _status('Building graph…');
            setTimeout(poll, 2500);
          }
        })
        .catch(function(){ setTimeout(poll, 3000); });
    }
    setTimeout(poll, 1200);
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      _attachControls();
      _boot();
    });
  } else {
    _attachControls();
    _boot();
  }

  // Suppress the memory/symbol build progress banners.
  function _hideBuildBanner() {
    var b = document.getElementById('build-progress');
    if (b) b.style.display = 'none';
  }
  setTimeout(_hideBuildBanner, 6000);
  if (window.JUG && JUG.on) {
    JUG.on('state:activeView', function(ev){
      if (ev && ev.value === 'graph') _hideBuildBanner();
    });
  }

  // ── Debug ─────────────────────────────────────────────────────────────────
  window.JUG = window.JUG || {};
  JUG._lod = { loaded: _loaded, loadUpTo: loadUpTo, loadPhase: _loadPhase };

}());
