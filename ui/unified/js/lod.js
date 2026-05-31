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
        if (!data) return;
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
        if (domainSlug && domainSlug !== 'all' && domainSlug !== '') {
          nodes = nodes.filter(function (n) {
            return n.domain === domainSlug
                || (n.domain_id || '').indexOf(domainSlug) !== -1
                || n.kind === 'domain';  // always keep domain hubs visible
          });
          var nodeIds = Object.create(null);
          nodes.forEach(function (n) { nodeIds[n.id] = true; });
          edges = edges.filter(function (e) {
            return nodeIds[e.source] || nodeIds[e.target];
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

  function _onFilterChange() {
    var depth  = _currentDepth();
    var domain = _currentDomain();
    // Reset graph to domain skeleton before loading new depth.
    if (typeof JUG.buildGraph === 'function' && JUG.state && JUG.state.lastData) {
      // Keep only domain nodes in lastData, then reload.
      JUG.state.lastData = { nodes: [], edges: [], meta: {} };
      _loaded = {};
    }
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
          // Reload current depth for the new domain.
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
    function poll() {
      tries++;
      if (tries > 20) return;
      fetch(_base() + '/api/graph/progress')
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(p){
          if (p && (p.node_count > 0 || (p.phases && p.phases['L0']))) {
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
