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

  // L0 domain nodes are cached in localStorage so they appear INSTANTLY
  // on every page load after the first. The build takes 20–30 s on cold
  // start; without the cache the user stares at an empty canvas every time.
  var L0_CACHE_KEY = 'cortex.lod.l0.v1';

  var PHASES = ['L0','L1','L2','L3','L4','L5','L6'];
  // L5 phase is ~838 MB of JSON — exceeds V8's string limit.
  // Load in chunks via offset/limit to avoid the parse crash.
  var L5_CHUNK_SIZE = 4000;

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

  // ── Filter helpers ─────────────────────────────────────────────────────────

  function _filterNodes(nodes, edges, domainSlug, phaseKey) {
    // Always remove global sentinel — it is an internal anchor, not a project.
    nodes = nodes.filter(function(n) { return !n.isGlobal && n.id !== 'domain:__global__'; });

    // For L1+, scope strictly to the selected domain.
    if (domainSlug && domainSlug !== 'all' && domainSlug !== '' && phaseKey !== 'L0') {
      nodes = nodes.filter(function(n) { return _belongsToDomain(n, domainSlug); });
    }

    var nodeIds = Object.create(null);
    nodes.forEach(function(n) { nodeIds[n.id] = true; });
    edges = edges.filter(function(e) { return nodeIds[e.source] && nodeIds[e.target]; });
    return { nodes: nodes, edges: edges };
  }

  function _inject(nodes, edges, phaseKey, domainSlug) {
    if (nodes.length && typeof JUG.appendGraphDelta === 'function') {
      JUG.appendGraphDelta(nodes, edges);
      console.log('[lod]', phaseKey, (domainSlug || '*'),
                  '+' + nodes.length + 'N +' + edges.length + 'E');
      _updateLegend();
    }
  }

  // ── Legend: show actual rendered node counts ───────────────────────────────

  function _updateLegend() {
    var d = JUG.state && JUG.state.lastData;
    if (!d || !d.nodes) return;
    var counts = { domain:0, memory:0, entity:0, discussion:0 };
    d.nodes.forEach(function(n) {
      var k = n.kind || n.type || '';
      if (counts[k] !== undefined) counts[k]++;
    });
    var setText = function(id, v) { var el=document.getElementById(id); if(el) el.textContent=v; };
    setText('s-dom',  counts.domain);
    setText('s-mem',  counts.memory);
    setText('s-ent',  counts.entity);
    setText('s-disc', counts.discussion);
    setText('s-nodes', d.nodes.length);
  }

  // ── Load one phase ─────────────────────────────────────────────────────────

  function _loadPhase(phaseKey, domainSlug, onDone) {
    var cacheKey = phaseKey + ':' + (domainSlug || '*');
    if (_loaded[cacheKey] || _pending[cacheKey]) {
      if (typeof onDone === 'function') onDone(); return;
    }
    _pending[cacheKey] = true;
    _status('Loading ' + (DEPTH_LABEL[phaseKey] || phaseKey) +
            (domainSlug ? ' for ' + domainSlug : '') + '…');

    // L5 (memories, ~838 MB) must be paginated — V8 can't parse it in one shot.
    if (phaseKey === 'L5') {
      _loadPhasePaged('L5', domainSlug, 0, cacheKey, onDone);
      return;
    }

    fetch(_base() + '/api/graph/phase?name=' + encodeURIComponent(phaseKey))
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data) { delete _pending[cacheKey]; if(typeof onDone==='function') onDone(); return; }
        if (!data.ready && !data.node_total) {
          setTimeout(function() { delete _pending[cacheKey]; _loadPhase(phaseKey, domainSlug, onDone); }, 2000);
          return;
        }
        var f = _filterNodes(data.nodes || [], data.edges || [], domainSlug, phaseKey);
        _inject(f.nodes, f.edges, phaseKey, domainSlug);

        // Cache L0 for instant display on next page load.
        if (phaseKey === 'L0' && f.nodes.length > 1) {
          try { localStorage.setItem(L0_CACHE_KEY, JSON.stringify({ nodes: f.nodes, edges: f.edges, ts: Date.now() })); } catch(_e) {}
        }

        _loaded[cacheKey] = true; delete _pending[cacheKey];
        _status('Online');
        if (typeof onDone === 'function') onDone();
      })
      .catch(function(err) {
        console.warn('[lod]', phaseKey, 'failed:', err.message);
        _loaded[cacheKey] = true; delete _pending[cacheKey];
        if (typeof onDone === 'function') onDone();
      });
  }

  // ── L5 paginated loader ────────────────────────────────────────────────────

  function _loadPhasePaged(key, domainSlug, offset, cacheKey, onDone) {
    var url = _base() + '/api/graph/phase?name=' + encodeURIComponent(key) +
              '&offset=' + offset + '&limit=' + L5_CHUNK_SIZE;
    fetch(url)
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data || (!data.nodes && !data.edges)) {
          _loaded[cacheKey] = true; delete _pending[cacheKey];
          if (typeof onDone === 'function') onDone(); return;
        }
        var f = _filterNodes(data.nodes || [], data.edges || [], domainSlug, key);
        _inject(f.nodes, f.edges, key + '[' + offset + ']', domainSlug);
        if (!data.done) {
          setTimeout(function() { _loadPhasePaged(key, domainSlug, offset + L5_CHUNK_SIZE, cacheKey, onDone); }, 50);
        } else {
          _loaded[cacheKey] = true; delete _pending[cacheKey];
          _status('Online'); if (typeof onDone === 'function') onDone();
        }
      })
      .catch(function(err) {
        console.warn('[lod] L5 chunk failed:', err.message);
        _loaded[cacheKey] = true; delete _pending[cacheKey];
        if (typeof onDone === 'function') onDone();
      });
  }

  // ── Load up to a given depth level (cumulative) ────────────────────────────
  // L6 is special: server uses L6:cortex, L6:agentic-ai etc — discover from progress.

  var _l6Keys = null;  // discovered L6 phase keys

  function _discoverL6Keys(onReady) {
    if (_l6Keys !== null) { onReady(_l6Keys); return; }
    fetch(_base() + '/api/graph/progress')
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(p) {
        _l6Keys = p && p.phases ? Object.keys(p.phases).filter(function(k) { return /^L6[_:]/.test(k) && p.phases[k]; }) : [];
        onReady(_l6Keys);
      })
      .catch(function() { _l6Keys = []; onReady([]); });
  }

  function loadUpTo(maxDepth, domainSlug) {
    var idx = PHASES.indexOf(maxDepth);
    if (idx < 0) idx = 0;
    // Build a flat chain of phase keys to load in order.
    var chain = PHASES.slice(0, idx + 1);

    function loadNext(i) {
      if (i >= chain.length) return;
      var key = chain[i];
      if (key === 'L6') {
        // Discover and load all L6:proj sub-phases in order.
        _discoverL6Keys(function(keys) {
          if (!keys.length) { _status('No symbol phases available'); return; }
          var ki = 0;
          function nextL6() { if (ki < keys.length) _loadPhase(keys[ki++], domainSlug, nextL6); }
          nextL6();
        });
      } else {
        _loadPhase(key, domainSlug, function() { loadNext(i + 1); });
      }
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

  // ── Boot: L0 domains must appear INSTANTLY ────────────────────────────────
  //
  // Strategy:
  //   1. If localStorage has cached L0 nodes from a previous session, inject
  //      them immediately (< 10 ms) so the graph appears without any wait.
  //   2. In parallel, kick the server build and poll for a fresher L0.
  //      When fresher data arrives, re-inject (dedup is a no-op for nodes
  //      already present; new nodes from updated sessions get added).
  //   3. Cache TTL: 24 h — domains don't change often.

  var L0_CACHE_TTL = 24 * 60 * 60 * 1000;  // 24 hours

  function _bootFromCache() {
    try {
      var raw = localStorage.getItem(L0_CACHE_KEY);
      if (!raw) return false;
      var cached = JSON.parse(raw);
      if (!cached || !cached.nodes || !cached.nodes.length) return false;
      if (Date.now() - (cached.ts || 0) > L0_CACHE_TTL) return false;
      // Inject cached L0 immediately — no network round-trip.
      _inject(cached.nodes, cached.edges || [], 'L0[cache]', '');
      _loaded['L0:*'] = true;   // mark loaded so boot poll refreshes, not re-loads
      _status('Online — use the filter to load deeper layers');
      return true;
    } catch(_e) { return false; }
  }

  function _boot() {
    // Step 1: show domains instantly from cache if available.
    var fromCache = _bootFromCache();

    // Step 2: kick the full build and refresh L0 from server.
    fetch(_base() + '/api/graph?batch_size=1').catch(function(){});

    var tries = 0;
    var refreshed = false;
    function poll() {
      tries++;
      if (tries > 30 || refreshed) return;
      fetch(_base() + '/api/graph/progress')
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(p){
          var l0Ready = p && p.phases && p.phases['L0'] === true;
          if (l0Ready) {
            fetch(_base() + '/api/graph/phase?name=L0')
              .then(function(r){ return r.ok ? r.json() : null; })
              .then(function(phase){
                var nodeCount = phase ? (phase.node_total || (phase.nodes||[]).length) : 0;
                if (nodeCount > 1) {
                  refreshed = true;
                  // Clear stale cache entry so _loadPhase re-injects fresh data.
                  if (fromCache) delete _loaded['L0:*'];
                  _loadPhase('L0', '', function(){
                    if (!fromCache) _status('Online — use the filter to load deeper layers');
                  });
                } else {
                  if (!fromCache) _status('Building domain graph…');
                  setTimeout(poll, 3000);
                }
              })
              .catch(function(){ setTimeout(poll, 3000); });
          } else {
            if (!fromCache) _status('Building graph…');
            setTimeout(poll, 2500);
          }
        })
        .catch(function(){ setTimeout(poll, 3000); });
    }
    // If we had cache, delay the refresh poll so the cached view can settle.
    setTimeout(poll, fromCache ? 2000 : 1200);
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
