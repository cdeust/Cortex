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

  // ── Authoritative state — NEVER read from DOM, always from these vars ──────
  var _selectedDepth  = 'L0';
  var _selectedDomain = '';
  // Guard: set true while lod.js is programmatically rebuilding dropdowns.
  // Prevents innerHTML-rebuild from firing spurious change events into the
  // domain/depth listeners — those only react to genuine user interactions.
  var _suppressChange = false;

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

    // Scope strictly to the selected domain — ALL phases including L0.
    // When the user picks "agentic-ai" they want ONLY agentic-ai nodes.
    if (domainSlug && domainSlug !== 'all' && domainSlug !== '') {
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

    // L5 memories: read directly from Postgres via /api/memories (fast, local).
    // The graph-build-cache path is slow (build must finish L5 first).
    // /api/memories is keyset-paginated from Postgres — 5000 records in ~60ms.
    if (phaseKey === 'L5') {
      _loadMemoriesFast(domainSlug, null, cacheKey, onDone);
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

  // ── Fast memory loader via /api/memories (Postgres keyset pagination) ────────
  // ~5000 memories per request at ~60ms each → 130K memories in ~1.5s locally.

  var MEM_PAGE = 5000;
  var MEM_COLORS = {
    labile: '#EF4444', early_ltp: '#F59E0B', late_ltp: '#10B981',
    consolidated: '#06B6D4', reconsolidating: '#A855F7',
  };

  function _memToNode(m) {
    var stage = m.consolidation_stage || m.stage || 'labile';
    return {
      id:      'mem:' + m.id,
      kind:    'memory',
      type:    'memory',
      label:   (m.label || m.content || '').slice(0, 50) || ('mem ' + m.id),
      domain:  m.domain || '',
      domain_id: m.domain_id || ('domain:' + (m.domain || '')),
      color:   MEM_COLORS[stage] || '#10B981',
      consolidation_stage: stage,
      heat:    m.heat || 0,
      isGlobal: !!m.isGlobal,
      selectableDomain: false,
    };
  }

  function _loadMemoriesFast(domainSlug, cursor, cacheKey, onDone) {
    var url = _base() + '/api/memories?limit=' + MEM_PAGE;
    if (domainSlug && domainSlug !== 'all' && domainSlug !== '') {
      url += '&domain=' + encodeURIComponent(domainSlug);
    }
    if (cursor) url += '&cursor=' + encodeURIComponent(cursor);

    fetch(url)
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data || !data.items || !data.items.length) {
          _loaded[cacheKey] = true; delete _pending[cacheKey];
          _status('Online'); if (typeof onDone === 'function') onDone(); return;
        }
        var nodes = data.items.map(_memToNode);
        if (typeof JUG.appendGraphDelta === 'function') {
          JUG.appendGraphDelta(nodes, []);
          console.log('[lod] L5[memories]', (domainSlug || '*'), '+' + nodes.length + 'N');
          _updateLegend();
        }
        if (data.next_cursor) {
          // More pages — continue immediately (local Postgres is fast).
          _loadMemoriesFast(domainSlug, data.next_cursor, cacheKey, onDone);
        } else {
          _loaded[cacheKey] = true; delete _pending[cacheKey];
          _status('Online'); if (typeof onDone === 'function') onDone();
        }
      })
      .catch(function(err) {
        console.warn('[lod] L5 memories failed:', err.message);
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

  // Read from JS state — never from DOM (DOM can be reset; state cannot).
  function _currentDepth()  { return _selectedDepth; }
  function _currentDomain() { return _selectedDomain; }

  // Sync DOM to state (called after any dropdown rebuild).
  function _syncDomToState() {
    var depthSel  = document.getElementById('wfg-filter-select');
    var domainSel = document.getElementById('domain-select');
    if (depthSel  && depthSel.value  !== _selectedDepth)  depthSel.value  = _selectedDepth;
    if (domainSel && domainSel.value !== _selectedDomain) domainSel.value = _selectedDomain;
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
    var depthSel  = document.getElementById('wfg-filter-select');
    var domainSel = document.getElementById('domain-select');

    // Sync JS state FROM current DOM values (browser may have restored
    // previous selections via autocomplete/bfcache).
    if (depthSel  && /^L[0-6]$/.test(depthSel.value))  _selectedDepth  = depthSel.value;
    if (domainSel && domainSel.value)                   _selectedDomain = domainSel.value;

    if (depthSel) {
      depthSel.addEventListener('change', function () {
        if (_suppressChange) return;
        var val = depthSel.value;
        if (!/^L[0-6]$/.test(val)) return;
        _selectedDepth = val;
        _onFilterChange();
      });
    }
    if (domainSel) {
      domainSel.addEventListener('change', function () {
        if (_suppressChange) return;
        _selectedDomain = domainSel.value || '';
        if (!/^L[0-6]$/.test(_selectedDepth)) return;
        _clearPhasesFor(_selectedDepth, _selectedDomain);
        if (typeof JUG.resetGraph === 'function') JUG.resetGraph();
        _syncDomToState();
        loadUpTo(_selectedDepth, _selectedDomain);
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

  // ── Domain dropdown: populate directly from L0 nodes ─────────────────────
  // Populate immediately when we have L0 data — don't wait for state:lastData.
  // workflow_graph_filters.js and controls.js also populate on state:lastData,
  // but this ensures the dropdown is ready before any user interaction.

  function _populateDomainDropdown(nodes) {
    var sel = document.getElementById('domain-select');
    if (!sel) return;
    var domains = [];
    nodes.forEach(function(n) {
      if (n.selectableDomain && n.label) domains.push(n.label);
    });
    if (!domains.length) return;
    domains.sort();
    // Suppress change events while rebuilding — innerHTML resets value to ''
    // which fires a spurious change event that calls resetGraph().
    _suppressChange = true;
    sel.innerHTML = '<option value="">All Domains</option>';
    domains.forEach(function(d) {
      var opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    });
    sel.value = _selectedDomain;
    setTimeout(function() { _suppressChange = false; }, 0);
  }

  // ── Boot: L0 domains INSTANTLY ────────────────────────────────────────────
  // 1. Try localStorage cache first → sub-10ms display.
  // 2. Immediately fetch /api/graph/phase?name=L0 — if server has data, use it.
  // 3. If server returns empty (cold start), kick build and retry.
  // No complex progress-polling — just try L0 directly and retry on miss.

  var L0_CACHE_TTL = 24 * 60 * 60 * 1000;

  function _applyL0(nodes, edges, fromCache) {
    var f = _filterNodes(nodes, edges, '', 'L0');
    if (!f.nodes.length) return false;
    _inject(f.nodes, f.edges, fromCache ? 'L0[cache]' : 'L0', '');
    _populateDomainDropdown(f.nodes);
    _loaded['L0:*'] = true;
    _status('Online — select a depth or domain to explore');
    // Update localStorage with fresh data.
    if (!fromCache) {
      try { localStorage.setItem(L0_CACHE_KEY, JSON.stringify({ nodes: f.nodes, edges: f.edges, ts: Date.now() })); } catch(_e) {}
    }
    return true;
  }

  function _boot() {
    // 1. Try cache for instant display.
    var showedCache = false;
    try {
      var raw = localStorage.getItem(L0_CACHE_KEY);
      if (raw) {
        var cached = JSON.parse(raw);
        if (cached && cached.nodes && cached.nodes.length &&
            (Date.now() - (cached.ts || 0)) < L0_CACHE_TTL) {
          showedCache = _applyL0(cached.nodes, cached.edges || [], true);
        }
      }
    } catch(_e) {}

    // 2. Kick the build so the server starts building fresh data.
    fetch(_base() + '/api/graph?batch_size=1').catch(function(){});

    // 3. Immediately try fetching L0 from server (works if server is warm).
    var tries = 0;
    function tryL0() {
      tries++;
      if (tries > 25) return;
      fetch(_base() + '/api/graph/phase?name=L0')
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(phase) {
          var nodes = phase ? (phase.nodes || []) : [];
          // Filter out global; count real project domains.
          var realDomains = nodes.filter(function(n) { return n.selectableDomain; });
          if (realDomains.length > 0) {
            if (showedCache) delete _loaded['L0:*'];
            _applyL0(nodes, phase.edges || [], false);
          } else {
            // Server still building — show progress and retry quickly.
            if (!showedCache) {
              _status('Building graph (' + tries + '/' + 25 + ')… ' +
                      'Nodes: ' + (phase ? (phase.node_total || 0) : 0));
            }
            setTimeout(tryL0, 1000);  // retry every 1s, not 2.5s
          }
        })
        .catch(function() { setTimeout(tryL0, 2000); });
    }
    setTimeout(tryL0, showedCache ? 1500 : 200);  // try at 200ms on cold start
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
