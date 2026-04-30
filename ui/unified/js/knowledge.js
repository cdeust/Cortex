// Cortex — Knowledge View
// Readable memory cards organized by domain with search, sort, and filtering.
//
// Data source: /api/memories (keyset-paged endpoint backed by Postgres).
// Lazy-loads pages on scroll; never holds the full memory set in memory,
// so it works at any N. Filter / sort / search are server-side params.
(function() {
  var container = null;
  var visible = false;
  var currentSort = 'heat';
  var currentDomain = 'all';
  var searchQuery = '';
  var expandedCardId = null;

  // Paged-fetch state. Reset on every show()/filter change. Each page
  // after the first is gated on a genuine user scroll.
  var PAGE_LIMIT = 50;
  var memoriesAccum = [];          // accumulated rows across pages
  var seenIds = Object.create(null);
  var nextCursor = null;
  var pageLoading = false;
  var pageDone = false;
  var lastFetchToken = 0;
  var scrolledSinceFetch = false;

  // Server-known filter facets. Loaded once on first show() so chips
  // can show ALL options up-front (not only what's been paged).
  var facets = null;

  // Active filters (server-side params).
  var filterStage = null;         // 'labile' | 'early_ltp' | 'late_ltp' | 'consolidated' | 'reconsolidating'
  var filterEmotion = null;       // 'urgent' | 'positive' | 'negative' | 'neutral'
  var filterMinHeat = null;       // 0.5 when "Hot" toggle on
  var filterProtected = false;    // true when "Protected" toggle on

  var STAGE_MAP = {
    labile:          { label: 'New',      cls: 'kv-badge-new' },
    early_ltp:       { label: 'Growing',  cls: 'kv-badge-growing' },
    late_ltp:        { label: 'Strong',   cls: 'kv-badge-strong' },
    consolidated:    { label: 'Stable',   cls: 'kv-badge-stable' },
    reconsolidating: { label: 'Updating', cls: 'kv-badge-updating' },
  };

  var EMO_COLORS = {
    urgency: '#ff3366', frustration: '#ef4444',
    satisfaction: '#22c55e', discovery: '#f59e0b',
    confusion: '#8b5cf6',
  };

  // ── Title extraction ──
  // Pulls a meaningful title from raw memory content
  function extractTitle(content) {
    if (!content) return 'Untitled Memory';
    var text = content.trim();

    // If content starts with a markdown heading, use it
    var headingMatch = text.match(/^#{1,3}\s+(.+)/);
    if (headingMatch) return headingMatch[1].trim();

    // Use the first sentence (up to first period, question mark, or newline)
    var firstLine = text.split('\n')[0].trim();
    var sentenceMatch = firstLine.match(/^(.+?[.?!])\s/);
    if (sentenceMatch && sentenceMatch[1].length >= 12) {
      return sentenceMatch[1];
    }

    // Fall back to first line, capped at reasonable length
    if (firstLine.length <= 120) return firstLine;
    // Truncate at last word boundary before 120 chars
    var truncated = firstLine.substring(0, 120);
    var lastSpace = truncated.lastIndexOf(' ');
    if (lastSpace > 60) truncated = truncated.substring(0, lastSpace);
    return truncated;
  }

  // Extract body preview (content after the title)
  function extractPreview(content, title) {
    if (!content) return '';
    var text = content.trim();

    // Remove the heading line if title came from a heading
    if (text.match(/^#{1,3}\s+/)) {
      text = text.replace(/^#{1,3}\s+.+\n?/, '').trim();
    } else {
      // Remove the title portion from the beginning
      var idx = text.indexOf(title);
      if (idx === 0) {
        text = text.substring(title.length).trim();
      }
    }

    // Strip markdown artifacts for cleaner preview
    text = text.replace(/^[-*]\s+/gm, '').replace(/\*\*/g, '').replace(/`/g, '');

    // Return first ~200 chars at a word boundary
    if (text.length <= 200) return text;
    var cut = text.substring(0, 200);
    var sp = cut.lastIndexOf(' ');
    if (sp > 100) cut = cut.substring(0, sp);
    return cut;
  }

  function init() {
    container = document.getElementById('knowledge-container');
    if (!container) return;

    JUG.on('state:activeView', function(ev) {
      if (ev.value === 'knowledge') show(); else hide();
    });
    // Re-render counters if the legacy lastData arrives, but we no
    // longer depend on it for the actual memory list — that comes
    // from the paged /api/memories endpoint.
    JUG.on('state:lastData', function() { /* no-op */ });
  }

  function show() {
    if (!container) return;
    container.style.display = 'flex';
    visible = true;
    if (!facets) {
      _fetchFacets().then(function() { _resetAndFetch(); });
    } else {
      _resetAndFetch();
    }
  }

  function _fetchFacets() {
    return fetch('/api/memories/facets')
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(d) { if (d) facets = d; })
      .catch(function(err) { console.warn('[knowledge] facets fetch failed:', err); });
  }

  function hide() {
    visible = false;
    if (container) container.style.display = 'none';
    closeExpanded();
  }

  // ── Lazy-load paged memories from /api/memories ──
  function _serverSort() {
    if (currentSort === 'recency') return 'recent';
    if (currentSort === 'importance') return 'heat'; // server has no importance index; fall back to heat (client-side reorder is per-page)
    return 'heat';
  }

  function _resetAndFetch() {
    memoriesAccum = [];
    seenIds = Object.create(null);
    nextCursor = null;
    pageDone = false;
    pageLoading = false;
    domainsSeen = Object.create(null);
    globalCount = 0;
    hotCount = 0;
    lastFetchToken++;
    scrolledSinceFetch = true;  // allow the very first page on open/filter
    rebuild();
    _fetchPage();
  }

  function _fetchPage() {
    if (pageDone || pageLoading) return;
    // Gate: subsequent pages require a real user scroll since the
    // last fetch. Without it, the IntersectionObserver on a sentinel
    // that's already in-view loops forever.
    if (!scrolledSinceFetch) return;
    scrolledSinceFetch = false;
    pageLoading = true;
    var token = lastFetchToken;
    var qs = '?limit=' + PAGE_LIMIT + '&sort=' + encodeURIComponent(_serverSort());
    if (nextCursor) qs += '&cursor=' + encodeURIComponent(nextCursor);
    if (currentDomain === 'global') {
      qs += '&global=1';
    } else if (currentDomain !== 'all') {
      qs += '&domain=' + encodeURIComponent(currentDomain);
    }
    if (searchQuery) qs += '&search=' + encodeURIComponent(searchQuery);
    if (filterStage) qs += '&stage=' + encodeURIComponent(filterStage);
    if (filterEmotion) qs += '&emotion=' + encodeURIComponent(filterEmotion);
    if (filterMinHeat != null) qs += '&min_heat=' + encodeURIComponent(filterMinHeat);
    if (filterProtected) qs += '&protected=1';
    fetch('/api/memories' + qs)
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(data) {
        if (token !== lastFetchToken) return; // superseded by newer fetch
        var items = data.items || [];
        for (var i = 0; i < items.length; i++) {
          var m = items[i];
          if (seenIds[m.id]) continue;
          seenIds[m.id] = true;
          if (currentDomain === 'global' && !m.isGlobal) continue;
          memoriesAccum.push(m);
          if (m.domain) domainsSeen[m.domain] = (domainsSeen[m.domain] || 0) + 1;
          if (m.isGlobal) globalCount++;
          if ((m.heat || 0) >= 0.5) hotCount++;
        }
        nextCursor = data.next_cursor || null;
        pageDone = !nextCursor;
        pageLoading = false;
        _renderPagedGrid();
      })
      .catch(function(err) {
        console.warn('[knowledge] /api/memories fetch failed:', err);
        pageLoading = false;
        if (memoriesAccum.length === 0) {
          var grid = document.getElementById('kv-grid');
          if (grid) {
            grid.innerHTML = '';
            var empty = el('div', 'kv-empty');
            var t = el('div', 'kv-empty-title'); t.textContent = 'Failed to load memories';
            empty.appendChild(t);
            var s = el('div', 'kv-empty-sub'); s.textContent = String(err.message || err);
            empty.appendChild(s);
            grid.appendChild(empty);
          }
        }
      });
  }

  // Compatibility shim: old call sites expected an in-memory list.
  // After lazy-load, "all memories" is what we've fetched so far.
  function getMemories() { return memoriesAccum; }

  function getDomains() { return Object.keys(domainsSeen).sort(); }

  // ── Build the view (chrome only — grid populated by _renderPagedGrid) ──
  function rebuild() {
    if (!container) return;
    container.innerHTML = '';

    // Domain pills (rebuilt on demand from domainsSeen as pages arrive).
    var domainBar = el('div', 'kv-domain-bar');
    domainBar.id = 'kv-domain-bar';
    container.appendChild(domainBar);
    _refreshDomainBar();

    // Search + sort row
    var searchRow = el('div', 'kv-search-row');
    var searchInput = el('input', 'kv-search');
    searchInput.type = 'text';
    searchInput.placeholder = 'Search memories...';
    searchInput.value = searchQuery;
    var debounce = null;
    searchInput.addEventListener('input', function() {
      clearTimeout(debounce);
      debounce = setTimeout(function() {
        searchQuery = searchInput.value;
        _resetAndFetch();
      }, 250);
    });
    searchRow.appendChild(searchInput);

    var sortGroup = el('div', 'kv-sort-group');
    var sortLabel = el('span', 'kv-sort-label');
    sortLabel.textContent = 'Sort:';
    sortGroup.appendChild(sortLabel);
    var sortLabels = { heat: 'Activity', recency: 'Recency', importance: 'Importance' };
    ['heat', 'recency', 'importance'].forEach(function(s) {
      var btn = el('button', 'kv-sort-btn');
      btn.textContent = sortLabels[s];
      if (s === currentSort) btn.classList.add('active');
      btn.addEventListener('click', function() {
        currentSort = s;
        _resetAndFetch();
      });
      sortGroup.appendChild(btn);
    });
    searchRow.appendChild(sortGroup);
    container.appendChild(searchRow);

    // Filter chip row (server-side facets). Rebuilt once facets load.
    var filterRow = el('div', 'kv-filter-row');
    filterRow.id = 'kv-filter-row';
    filterRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:0 14px 10px;font-size:11px';
    container.appendChild(filterRow);
    _refreshFilterRow();

    // Stats bar (live: counters update as pages stream in)
    var statsBar = el('div', 'kv-stats-bar');
    statsBar.id = 'kv-stats-bar';
    container.appendChild(statsBar);
    _refreshStatsBar();

    // Grid container — items appended page-by-page, sentinel at bottom
    // triggers next-page fetch via IntersectionObserver.
    var grid = el('div', 'kv-grid');
    grid.id = 'kv-grid';
    container.appendChild(grid);

    var sentinel = el('div', 'kv-load-sentinel');
    sentinel.id = 'kv-load-sentinel';
    sentinel.style.cssText = 'min-height:60px;display:flex;align-items:center;justify-content:center;gap:12px;color:#7a8e9c;font-size:11px;letter-spacing:1px;text-transform:uppercase';
    var sentinelText = el('span'); sentinelText.id = 'kv-load-text'; sentinelText.textContent = 'Loading more memories…';
    sentinel.appendChild(sentinelText);
    var loadMoreBtn = el('button', 'kv-load-more');
    loadMoreBtn.id = 'kv-load-more';
    loadMoreBtn.style.cssText = 'background:rgba(80,210,235,0.15);border:1px solid rgba(120,200,220,0.4);color:#80d2e0;padding:6px 14px;border-radius:3px;cursor:pointer;font:inherit;letter-spacing:1.2px';
    loadMoreBtn.textContent = 'Load more';
    loadMoreBtn.addEventListener('click', function(){
      scrolledSinceFetch = true;   // explicit user intent
      _fetchPage();
    });
    sentinel.appendChild(loadMoreBtn);
    container.appendChild(sentinel);
    _attachIntersectionObserver(sentinel);
    _attachScrollBackstop(sentinel);
  }

  function _attachScrollBackstop(sentinel) {
    var maybeFetch = function() {
      if (!visible || pageLoading || pageDone) return;
      // Arm the gate — the user has now genuinely scrolled.
      scrolledSinceFetch = true;
      var rect = sentinel.getBoundingClientRect();
      var vh = window.innerHeight || document.documentElement.clientHeight;
      if (rect.top < vh + 400) _fetchPage();
    };
    container.addEventListener('scroll', maybeFetch, { passive: true });
    window.addEventListener('scroll', maybeFetch, { passive: true });
    container.addEventListener('wheel', maybeFetch, { passive: true });
  }

  function _refreshDomainBar() {
    var bar = document.getElementById('kv-domain-bar');
    if (!bar) return;
    bar.innerHTML = '';
    bar.appendChild(domainPill('All' + (facets ? ' (' + facets.total + ')' : ''), 'all'));
    if (!facets || facets.global > 0) {
      bar.appendChild(domainPill('Global' + (facets ? ' (' + facets.global + ')' : ''), 'global', true));
    }
    // Server-known domains beat the accumulated set — even if you've
    // only paged through 50 of 179k memories, every domain pill is
    // available with its full count.
    var serverDomains = facets && facets.domains
      ? facets.domains.map(function(d) { return d; })
      : Object.keys(domainsSeen).sort().map(function(name) {
          return { name: name, count: domainsSeen[name] };
        });
    serverDomains.forEach(function(d) {
      bar.appendChild(domainPill(shortDomain(d.name) + ' (' + d.count + ')', d.name));
    });
  }

  // Build the filter chip row: stage, emotion, hot, protected.
  function _refreshFilterRow() {
    var row = document.getElementById('kv-filter-row');
    if (!row) return;
    row.innerHTML = '';

    var label = el('span'); label.textContent = 'Filter:';
    label.style.cssText = 'color:#7a8e9c;letter-spacing:1px;text-transform:uppercase;font-size:9px;margin-right:4px';
    row.appendChild(label);

    // Stage chips (consolidation pipeline).
    var stageOpts = [
      { v: null,              t: 'Any stage' },
      { v: 'labile',          t: 'New' },
      { v: 'early_ltp',       t: 'Growing' },
      { v: 'late_ltp',        t: 'Strong' },
      { v: 'consolidated',    t: 'Stable' },
      { v: 'reconsolidating', t: 'Updating' },
    ];
    stageOpts.forEach(function(opt) {
      var c = facets && opt.v ? facets.stages[opt.v] : (opt.v == null ? (facets ? facets.total : '') : '');
      row.appendChild(_chip(opt.t + (c !== '' ? ' (' + c + ')' : ''),
        filterStage === opt.v,
        function() { filterStage = opt.v; _resetAndFetch(); }));
    });

    var sep1 = el('span'); sep1.textContent = '·';
    sep1.style.cssText = 'color:#5a6e7c;margin:0 6px';
    row.appendChild(sep1);

    // Emotion chips.
    var emoOpts = [
      { v: null,       t: 'Any feel' },
      { v: 'urgent',   t: 'Urgent', color: '#ff3366' },
      { v: 'positive', t: 'Positive', color: '#22c55e' },
      { v: 'negative', t: 'Negative', color: '#ef4444' },
      { v: 'neutral',  t: 'Neutral' },
    ];
    emoOpts.forEach(function(opt) {
      var c = facets && opt.v ? facets.emotions[opt.v] : '';
      row.appendChild(_chip(opt.t + (c !== '' ? ' (' + c + ')' : ''),
        filterEmotion === opt.v,
        function() { filterEmotion = opt.v; _resetAndFetch(); }, opt.color));
    });

    var sep2 = el('span'); sep2.textContent = '·';
    sep2.style.cssText = 'color:#5a6e7c;margin:0 6px';
    row.appendChild(sep2);

    // Boolean toggles.
    row.appendChild(_chip(
      'Hot' + (facets ? ' (' + facets.hot + ')' : ''),
      filterMinHeat != null,
      function() { filterMinHeat = filterMinHeat != null ? null : 0.5; _resetAndFetch(); },
      '#E07070'));
    row.appendChild(_chip(
      'Protected' + (facets ? ' (' + facets.protected + ')' : ''),
      filterProtected,
      function() { filterProtected = !filterProtected; _resetAndFetch(); },
      '#E0B040'));

    // Reset button if anything is active.
    if (filterStage || filterEmotion || filterMinHeat != null || filterProtected
        || currentDomain !== 'all' || searchQuery) {
      var clr = el('button'); clr.textContent = 'Clear all';
      clr.style.cssText = 'margin-left:auto;background:transparent;border:1px solid rgba(224,176,64,0.4);color:#E0B040;padding:3px 10px;border-radius:3px;cursor:pointer;font:inherit;letter-spacing:0.6px;text-transform:uppercase;font-size:9px';
      clr.addEventListener('click', function() {
        filterStage = null; filterEmotion = null; filterMinHeat = null;
        filterProtected = false; currentDomain = 'all'; searchQuery = '';
        _resetAndFetch();
      });
      row.appendChild(clr);
    }
  }

  function _chip(label, active, onClick, accent) {
    var b = el('button');
    b.textContent = label;
    var fg = active ? '#04080F' : (accent || '#c4d4dc');
    var bg = active ? (accent || '#80d2e0') : 'rgba(120,200,220,0.06)';
    var bd = active ? (accent || '#80d2e0') : 'rgba(120,200,220,0.25)';
    b.style.cssText =
      'background:' + bg + ';color:' + fg + ';border:1px solid ' + bd + ';' +
      'padding:3px 10px;border-radius:11px;cursor:pointer;font:inherit;font-size:11px;letter-spacing:0.4px;' +
      (active ? 'font-weight:600;' : '');
    b.addEventListener('click', onClick);
    return b;
  }

  function _refreshStatsBar() {
    var bar = document.getElementById('kv-stats-bar');
    if (!bar) return;
    bar.innerHTML = '';
    bar.appendChild(statEl(memoriesAccum.length + (pageDone ? '' : '+'), 'loaded'));
    bar.appendChild(statEl(getDomains().length, 'domains'));
    if (globalCount > 0) bar.appendChild(statEl(globalCount, 'global rules'));
    if (hotCount > 0) bar.appendChild(statEl(hotCount, 'hot'));
  }

  function _attachIntersectionObserver(sentinel) {
    if (!('IntersectionObserver' in window)) return;  // scroll-backstop covers it
    // Use the viewport (root: null) — the kv-grid scrolls inside the
    // body in the unified-viz layout, NOT inside container. Anchoring
    // root to container made the sentinel always count as "inside the
    // root" so isIntersecting was permanently true (or permanently
    // false depending on overflow), and pagination stalled.
    var io = new IntersectionObserver(function(entries) {
      entries.forEach(function(e) { if (e.isIntersecting) _fetchPage(); });
    }, { root: null, rootMargin: '400px' });
    io.observe(sentinel);
  }

  function _renderPagedGrid() {
    var grid = document.getElementById('kv-grid');
    var sentinel = document.getElementById('kv-load-sentinel');
    if (!grid) return;

    // Group into globals + by-domain on the cumulative accumulated set.
    var globals = [];
    var byDomain = {};
    for (var i = 0; i < memoriesAccum.length; i++) {
      var m = memoriesAccum[i];
      if (m.isGlobal) { globals.push(m); continue; }
      if (currentDomain !== 'all' && currentDomain !== 'global'
          && m.domain !== currentDomain) continue;
      var d = m.domain || 'unknown';
      if (!byDomain[d]) byDomain[d] = [];
      byDomain[d].push(m);
    }

    grid.innerHTML = '';
    if (globals.length > 0 && (currentDomain === 'all' || currentDomain === 'global')) {
      var banner = el('div', 'kv-global-banner');
      var bannerTitle = el('div', 'kv-global-title');
      bannerTitle.textContent = 'Rules That Apply Everywhere';
      banner.appendChild(bannerTitle);
      grid.appendChild(banner);
      globals.forEach(function(m) { grid.appendChild(buildCard(m, memoriesAccum)); });
    }
    if (currentDomain === 'all' || currentDomain === 'global') {
      var keys = Object.keys(byDomain).sort();
      keys.forEach(function(d) {
        var header = el('div', 'kv-domain-header');
        header.textContent = shortDomain(d) + ' (' + byDomain[d].length + ')';
        grid.appendChild(header);
        byDomain[d].forEach(function(m) { grid.appendChild(buildCard(m, memoriesAccum)); });
      });
    } else {
      var arr = byDomain[currentDomain] || [];
      arr.forEach(function(m) { grid.appendChild(buildCard(m, memoriesAccum)); });
    }

    if (memoriesAccum.length === 0 && pageDone) {
      var empty = el('div', 'kv-empty');
      var t = el('div', 'kv-empty-title'); t.textContent = 'No memories found';
      empty.appendChild(t);
      var s = el('div', 'kv-empty-sub');
      s.textContent = searchQuery ? 'No memories match "' + searchQuery + '"' : 'No memories yet';
      empty.appendChild(s);
      grid.appendChild(empty);
    }

    var sText = document.getElementById('kv-load-text');
    var sBtn = document.getElementById('kv-load-more');
    if (sText) {
      sText.textContent = pageDone
        ? '— end of memories — ' + memoriesAccum.length + ' loaded'
        : (pageLoading
            ? 'Loading more memories… (' + memoriesAccum.length + ' so far)'
            : 'Scroll for more · ' + memoriesAccum.length + ' loaded');
    }
    if (sBtn) sBtn.style.display = pageDone ? 'none' : 'inline-block';

    _refreshDomainBar();
    _refreshStatsBar();
  }

  // Legacy alias kept for anything still calling it.
  function rebuildGrid() { _renderPagedGrid(); }

  function populateGrid(grid, filtered, allMems) {
    grid.innerHTML = '';

    if (filtered.length === 0) {
      var empty = el('div', 'kv-empty');
      var emptyTitle = el('div', 'kv-empty-title');
      emptyTitle.textContent = 'No memories found';
      empty.appendChild(emptyTitle);
      var emptyText = document.createElement('div');
      emptyText.className = 'kv-empty-sub';
      emptyText.textContent = searchQuery
        ? 'No memories match "' + searchQuery + '"'
        : 'No memories in this domain yet';
      empty.appendChild(emptyText);
      grid.appendChild(empty);
      return;
    }

    // Global memories pinned at top
    var globals = filtered.filter(function(m) { return m.isGlobal; });
    var nonGlobals = filtered.filter(function(m) { return !m.isGlobal; });

    if (globals.length > 0 && currentDomain === 'all') {
      var banner = el('div', 'kv-global-banner');
      var bannerTitle = el('div', 'kv-global-title');
      bannerTitle.textContent = 'Rules That Apply Everywhere';
      banner.appendChild(bannerTitle);
      grid.appendChild(banner);

      globals.forEach(function(m) {
        grid.appendChild(buildCard(m, allMems));
      });
    }

    // Group by domain if showing all
    if (currentDomain === 'all' || currentDomain === 'global') {
      var byDomain = {};
      nonGlobals.forEach(function(m) {
        var d = m.domain || 'unknown';
        if (!byDomain[d]) byDomain[d] = [];
        byDomain[d].push(m);
      });
      var domainKeys = Object.keys(byDomain).sort();
      domainKeys.forEach(function(d) {
        var header = el('div', 'kv-domain-header');
        header.textContent = shortDomain(d);
        grid.appendChild(header);
        byDomain[d].forEach(function(m) {
          grid.appendChild(buildCard(m, allMems));
        });
      });
    } else {
      nonGlobals.forEach(function(m) {
        grid.appendChild(buildCard(m, allMems));
      });
    }
  }

  // ── Symbol ↔ memory impact resolution ──
  // A memory is "impacted by" a code symbol when (a) a file touched by
  // the memory (path / file_refs / file_path) is the symbol's parent
  // file, or (b) the symbol's label appears verbatim in the memory's
  // body or tags. We resolve this purely from the already-loaded graph
  // data so no extra server round-trip is needed.
  var _symIndexCache = null;
  var _symIndexKey = 0;
  function _buildSymbolIndex() {
    var data = window.JUG && JUG.state && JUG.state.lastData;
    if (!data || !Array.isArray(data.nodes)) return null;
    // Cache by data-identity so repeated card renders reuse the index.
    var key = data.nodes.length + ':' + (data.edges ? data.edges.length : 0);
    if (_symIndexCache && _symIndexKey === key) return _symIndexCache;
    // Object.create(null) — no prototype, so a key like "constructor"
    // or "toString" doesn't short-circuit to the builtin function.
    var byPath = Object.create(null);
    var byLabel = Object.create(null);
    data.nodes.forEach(function (n) {
      if (n.kind !== 'symbol' && n.type !== 'symbol') return;
      var p = n.path || '';
      if (p) {
        if (!byPath[p]) byPath[p] = [];
        byPath[p].push(n);
        var base = p.split('/').pop();
        if (base && base !== p) {
          if (!byPath[base]) byPath[base] = [];
          byPath[base].push(n);
        }
      }
      // Case-sensitive key — function names in memories are usually
      // written with their original casing (`appendGraphDelta`), and
      // case-sensitive matching avoids "do" matching every "Do" verb.
      var lbl = (n.label || '').trim();
      if (lbl && lbl.length >= 4) {
        if (!byLabel[lbl]) byLabel[lbl] = [];
        byLabel[lbl].push(n);
      }
    });
    _symIndexCache = { byPath: byPath, byLabel: byLabel };
    _symIndexKey = key;
    return _symIndexCache;
  }
  function _isWordChar(ch) {
    return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
           (ch >= '0' && ch <= '9') || ch === '_';
  }
  function _hasWordMatch(hay, needle) {
    // Case-sensitive indexOf + manual word-boundary check — avoids
    // the 4000-per-card RegExp churn that was freezing the tab.
    if (!needle) return false;
    var idx = 0;
    while (true) {
      var pos = hay.indexOf(needle, idx);
      if (pos === -1) return false;
      var before = pos === 0 ? '' : hay.charAt(pos - 1);
      var after = pos + needle.length >= hay.length ? '' : hay.charAt(pos + needle.length);
      if (!_isWordChar(before) && !_isWordChar(after)) return true;
      idx = pos + 1;
    }
  }

  function resolveMemorySymbols(mem, maxN) {
    var idx = _buildSymbolIndex();
    if (!idx) return [];
    var refs = [];
    var seen = Object.create(null);
    // File-based matches (cheap, exact).
    var fileRefs = [];
    if (mem.path) fileRefs.push(mem.path);
    if (Array.isArray(mem.file_refs)) fileRefs = fileRefs.concat(mem.file_refs);
    if (Array.isArray(mem.fileRefs)) fileRefs = fileRefs.concat(mem.fileRefs);
    for (var f = 0; f < fileRefs.length && refs.length < (maxN || 12); f++) {
      var fp = fileRefs[f];
      if (!fp) continue;
      var hits = idx.byPath[fp] || [];
      var base = fp.split('/').pop();
      if (base && base !== fp && idx.byPath[base]) hits = hits.concat(idx.byPath[base]);
      for (var h = 0; h < hits.length && refs.length < (maxN || 12); h++) {
        var s = hits[h];
        if (seen[s.id]) continue;
        seen[s.id] = 1;
        refs.push({ node: s, via: 'file' });
      }
    }
    if (refs.length >= (maxN || 12)) return refs.slice(0, maxN || 12);

    // Label-based matches — iterate labels, not characters. Cap at
    // 1500 labels and stop as soon as we've filled maxN to keep the
    // per-card cost bounded on 10k-symbol graphs.
    var hay = (mem.content || mem.body || '') + ' ' +
              ((mem.tags || []).join(' '));
    if (hay.length > 4) {
      var labelKeys = Object.keys(idx.byLabel);
      var cap = Math.min(labelKeys.length, 1500);
      for (var i = 0; i < cap && refs.length < (maxN || 12); i++) {
        var k = labelKeys[i];
        if (hay.indexOf(k) === -1) continue;   // cheap pre-filter
        if (!_hasWordMatch(hay, k)) continue;  // word-boundary check
        var syms = idx.byLabel[k];
        for (var j = 0; j < syms.length && refs.length < (maxN || 12); j++) {
          var sym = syms[j];
          if (seen[sym.id]) continue;
          seen[sym.id] = 1;
          refs.push({ node: sym, via: 'label' });
        }
      }
    }
    return refs.slice(0, maxN || 12);
  }

  // Shared export so timeline.js (Board) reuses the same resolver.
  window.JUG = window.JUG || {};
  window.JUG._kvResolve = resolveMemorySymbols;

  // ── Build a memory card ──
  function buildCard(mem, allMems) {
    var heat = mem.heat || 0;
    var card = el('div', 'kv-card');
    if (mem.isGlobal) card.classList.add('kv-card-global');
    if (heat >= 0.5) card.classList.add('kv-card-hot');

    // Use the pre-computed color from the graph node (heat gradient + emotion)
    var nodeColor = mem.color || heatColor(heat);
    card.style.borderLeftColor = nodeColor;

    // Title
    var title = extractTitle(mem.content || mem.label || '');
    var titleEl = el('div', 'kv-card-title');
    titleEl.textContent = title;
    card.appendChild(titleEl);

    // Emotion chip — prominent, at top. Carries the affective signal.
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildEmotionChip === 'function') {
      var emoChip = JUG._memSci.buildEmotionChip(mem);
      if (emoChip) card.appendChild(emoChip);
    }

    // Body preview
    var preview = extractPreview(mem.content || mem.label || '', title);
    if (preview) {
      var bodyEl = el('div', 'kv-card-body');
      bodyEl.textContent = preview;
      card.appendChild(bodyEl);
    }

    // Meaning section — store type, schema alignment, semantic tags, gist.
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildMeaningSection === 'function') {
      var meaning = JUG._memSci.buildMeaningSection(mem);
      if (meaning) card.appendChild(meaning);
    }

    // Metadata row: stage badge + domain + store type + heat + date
    var metaRow = el('div', 'kv-card-meta');

    var stage = mem.consolidationStage || 'labile';
    var sm = STAGE_MAP[stage] || STAGE_MAP.labile;
    var badge = el('span', 'kv-badge ' + sm.cls);
    badge.textContent = sm.label;
    metaRow.appendChild(badge);

    if (mem.domain) {
      var domChip = el('span', 'kv-card-domain');
      domChip.textContent = shortDomain(mem.domain);
      metaRow.appendChild(domChip);
    }

    var storeLabel = el('span', 'kv-card-store');
    storeLabel.textContent = (mem.storeType === 'semantic') ? 'Knowledge' : 'Experience';
    metaRow.appendChild(storeLabel);

    if (mem.emotion && mem.emotion !== 'neutral') {
      var emo = el('span', 'kv-card-emotion');
      emo.textContent = mem.emotion;
      emo.style.color = EMO_COLORS[mem.emotion] || '#A0B8C8';
      metaRow.appendChild(emo);
    }

    if (mem.isProtected) {
      var prot = el('span', 'kv-card-protected');
      prot.textContent = 'Protected';
      metaRow.appendChild(prot);
    }

    // Heat indicator — use the node's actual color
    var heatEl = el('span', 'kv-card-heat');
    heatEl.textContent = heat >= 0.7 ? 'Hot' : heat >= 0.4 ? 'Warm' : heat >= 0.15 ? 'Cool' : 'Cold';
    heatEl.style.color = nodeColor;
    metaRow.appendChild(heatEl);

    // Date
    var dateStr = formatDate(mem.createdAt || mem.lastAccessed);
    if (dateStr !== '--') {
      var dateEl = el('span', 'kv-card-date');
      dateEl.textContent = dateStr;
      metaRow.appendChild(dateEl);
    }

    card.appendChild(metaRow);

    // Scientific measurements — every instrumented field Cortex tracks
    // per memory (heat, importance, surprise, valence, plasticity,
    // hippo-dep, access/useful/replay counts, schema, flags, …).
    if (JUG._memSci && typeof JUG._memSci.buildSciencePanel === 'function') {
      var sci = JUG._memSci.buildSciencePanel(mem, 'full');
      if (sci) card.appendChild(sci);
    }

    // Tags
    var tags = mem.tags || [];
    if (tags.length > 0) {
      var tagsRow = el('div', 'kv-card-tags');
      tags.slice(0, 6).forEach(function(t) {
        var tag = el('span', 'kv-card-tag');
        tag.textContent = t;
        tagsRow.appendChild(tag);
      });
      if (tags.length > 6) {
        var more = el('span', 'kv-card-tag kv-tag-more');
        more.textContent = '+' + (tags.length - 6);
        tagsRow.appendChild(more);
      }
      card.appendChild(tagsRow);
    }

    // Code impact — symbols whose file or name connects to this memory.
    // Clicking a chip focuses the symbol in the Graph view.
    var syms = resolveMemorySymbols(mem, 8);
    if (syms.length) {
      var symRow = el('div', 'kv-card-tags');
      symRow.title = 'Code symbols that impact this memory';
      syms.forEach(function (ref) {
        var chip = el('span', 'kv-card-tag kv-card-symchip');
        chip.textContent = (ref.via === 'file' ? 'in ' : '') + (ref.node.label || ref.node.id);
        chip.style.cursor = 'pointer';
        chip.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (window.JUG && JUG.emit) JUG.emit('graph:selectNode', ref.node);
          if (JUG.state) JUG.state.activeView = 'graph';
        });
        symRow.appendChild(chip);
      });
      card.appendChild(symRow);
    }

    // Click to expand
    card.addEventListener('click', function() {
      openExpanded(mem, allMems);
    });

    return card;
  }

  // ── Expanded card modal ──
  function openExpanded(mem, allMems) {
    closeExpanded();
    expandedCardId = mem.id;

    var backdrop = el('div', 'kv-backdrop');
    backdrop.id = 'kv-backdrop';
    backdrop.addEventListener('click', closeExpanded);
    document.body.appendChild(backdrop);

    var heat = mem.heat || 0;
    var nodeColor = mem.color || heatColor(heat);
    var stage = mem.consolidationStage || 'labile';
    var sm = STAGE_MAP[stage] || STAGE_MAP.labile;
    var stageColor = JUG.CONSOLIDATION_COLORS ? (JUG.CONSOLIDATION_COLORS[stage] || '#50D0E8') : '#50D0E8';

    var panel = el('div', 'kv-expanded');
    panel.id = 'kv-expanded';
    // Use the node color as top accent border
    panel.style.borderTop = '4px solid ' + nodeColor;

    // Close button
    var closeBtn = el('button', 'kv-expanded-close');
    closeBtn.innerHTML = '&#x2715;';
    closeBtn.addEventListener('click', closeExpanded);
    panel.appendChild(closeBtn);

    // Title — colored by node color
    var title = extractTitle(mem.content || mem.label || '');
    var titleEl = el('h2', 'kv-expanded-title');
    titleEl.textContent = title;
    titleEl.style.color = nodeColor;
    panel.appendChild(titleEl);

    // Metadata row — use all the color systems
    var metaRow = el('div', 'kv-expanded-meta-row');

    // Consolidation badge with its color
    var badge = el('span', 'kv-badge ' + sm.cls);
    badge.textContent = sm.label;
    badge.style.color = stageColor;
    badge.style.borderColor = stageColor + '40';
    metaRow.appendChild(badge);

    if (mem.domain) {
      var domChip = el('span', 'kv-card-domain');
      domChip.textContent = shortDomain(mem.domain);
      metaRow.appendChild(domChip);
    }

    // Store type
    var st = el('span', 'kv-card-store');
    st.textContent = (mem.storeType === 'semantic') ? 'Knowledge' : 'Experience';
    metaRow.appendChild(st);

    // Emotion with its specific color
    if (mem.emotion && mem.emotion !== 'neutral') {
      var emoChip = el('span', 'kv-card-emotion');
      emoChip.textContent = mem.emotion.charAt(0).toUpperCase() + mem.emotion.slice(1);
      emoChip.style.color = EMO_COLORS[mem.emotion] || '#c0c8d8';
      emoChip.style.borderColor = (EMO_COLORS[mem.emotion] || '#c0c8d8') + '40';
      metaRow.appendChild(emoChip);
    }

    // Heat with gradient color
    var heatChip = el('span', 'kv-card-heat');
    heatChip.textContent = heat >= 0.7 ? 'Hot' : heat >= 0.4 ? 'Warm' : heat >= 0.15 ? 'Cool' : 'Cold';
    heatChip.style.color = nodeColor;
    metaRow.appendChild(heatChip);

    panel.appendChild(metaRow);

    // Prominent emotion + meaning (same as card, no duplication).
    if (window.JUG && JUG._memSci) {
      if (typeof JUG._memSci.buildEmotionChip === 'function') {
        var detailEmo = JUG._memSci.buildEmotionChip(mem);
        if (detailEmo) {
          detailEmo.classList.add('ms-emotion--detail');
          panel.appendChild(detailEmo);
        }
      }
      if (typeof JUG._memSci.buildMeaningSection === 'function') {
        var detailMeaning = JUG._memSci.buildMeaningSection(mem);
        if (detailMeaning) panel.appendChild(detailMeaning);
      }
    }

    // Full content — rendered with basic markdown formatting
    var contentBlock = el('div', 'kv-expanded-content');
    contentBlock.innerHTML = renderMemoryContent(mem.content || mem.label || '');
    panel.appendChild(contentBlock);

    // Explained scientific panel — every instrumented field with a
    // non-technical explanation. Superset of the summary card's grid.
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildExplainedPanel === 'function') {
      var explained = JUG._memSci.buildExplainedPanel(mem);
      if (explained) panel.appendChild(explained);
    }

    // Tags
    var allTags = mem.tags || [];
    if (allTags.length > 0) {
      var tagSec = el('div', 'kv-expanded-section');
      tagSec.textContent = 'Tags';
      panel.appendChild(tagSec);
      var tagsRow = el('div', 'kv-card-tags');
      allTags.forEach(function(t) {
        var tag = el('span', 'kv-card-tag');
        tag.textContent = t;
        tagsRow.appendChild(tag);
      });
      panel.appendChild(tagsRow);
    }

    // Related entities (from graph edges)
    var entities = findRelatedEntities(mem, allMems);
    if (entities.length > 0) {
      var entSec = el('div', 'kv-expanded-section');
      entSec.textContent = 'Entities';
      panel.appendChild(entSec);
      var entRow = el('div', 'kv-expanded-entities');
      entities.forEach(function(e) {
        var chip = el('span', 'kv-entity-chip');
        chip.textContent = e.label || e.id;
        chip.style.borderColor = JUG.getNodeColor(e) + '40';
        entRow.appendChild(chip);
      });
      panel.appendChild(entRow);
    }

    // Code impact — AST symbols that connect to this memory.
    var symRefs = resolveMemorySymbols(mem, 30);
    if (symRefs.length > 0) {
      var symSec = el('div', 'kv-expanded-section');
      symSec.textContent = 'Code impact';
      panel.appendChild(symSec);
      var symRow = el('div', 'kv-expanded-entities');
      symRefs.forEach(function (ref) {
        var chip = el('span', 'kv-entity-chip');
        var pfx = ref.via === 'file' ? 'in ' : '';
        chip.textContent = pfx + (ref.node.label || ref.node.id);
        chip.title = (ref.node.path || '') + (ref.node.symbol_type ? ' · ' + ref.node.symbol_type : '');
        chip.style.cursor = 'pointer';
        chip.addEventListener('click', function () {
          if (window.JUG && JUG.emit) JUG.emit('graph:selectNode', ref.node);
          if (JUG.state) JUG.state.activeView = 'graph';
        });
        symRow.appendChild(chip);
      });
      panel.appendChild(symRow);
    }

    // Related memories (same domain, high similarity by shared tags)
    var related = findRelatedMemories(mem, allMems);
    if (related.length > 0) {
      var relSec = el('div', 'kv-expanded-section');
      relSec.textContent = 'Related Memories';
      panel.appendChild(relSec);
      related.slice(0, 5).forEach(function(r) {
        var item = el('div', 'kv-related-item');
        var rTitle = el('div', 'kv-related-title');
        rTitle.textContent = extractTitle(r.content || r.label || '');
        item.appendChild(rTitle);
        var rPreview = extractPreview(r.content || r.label || '', rTitle.textContent);
        if (rPreview) {
          var rBody = el('div', 'kv-related-preview');
          rBody.textContent = rPreview.substring(0, 100);
          item.appendChild(rBody);
        }
        item.addEventListener('click', function(e) {
          e.stopPropagation();
          openExpanded(r, allMems);
        });
        panel.appendChild(item);
      });
    }

    document.body.appendChild(panel);

    // Esc to close
    panel._escHandler = function(e) {
      if (e.key === 'Escape') closeExpanded();
    };
    window.addEventListener('keydown', panel._escHandler);
  }

  function closeExpanded() {
    var panel = document.getElementById('kv-expanded');
    var backdrop = document.getElementById('kv-backdrop');
    if (panel) {
      if (panel._escHandler) window.removeEventListener('keydown', panel._escHandler);
      panel.remove();
    }
    if (backdrop) backdrop.remove();
    expandedCardId = null;
  }

  // ── Helpers ──
  function findRelatedEntities(mem, allMems) {
    var data = JUG.state.lastData;
    if (!data || !data.edges) return [];
    var entities = [];
    var nodeMap = {};
    (data.nodes || []).forEach(function(n) { nodeMap[n.id] = n; });

    data.edges.forEach(function(e) {
      var sid = typeof e.source === 'object' ? e.source.id : e.source;
      var tid = typeof e.target === 'object' ? e.target.id : e.target;
      if (sid === mem.id && nodeMap[tid] && nodeMap[tid].type === 'entity') {
        entities.push(nodeMap[tid]);
      } else if (tid === mem.id && nodeMap[sid] && nodeMap[sid].type === 'entity') {
        entities.push(nodeMap[sid]);
      }
    });
    return entities;
  }

  function isToolCapture(m) {
    var c = (m.content || m.label || '').trim();
    if (!c) return false;
    // Tool captures start with "# Tool:" or "Tool:" markers
    if (/^#?\s*Tool:\s*/i.test(c)) return true;
    // Command/Output skeleton with no narrative
    if (/\*\*Command:\*\*/.test(c) && /\*\*Output:\*\*/.test(c)) return true;
    return false;
  }

  function findRelatedMemories(mem, allMems) {
    var memTags = new Set(mem.tags || []);
    if (memTags.size === 0) return [];
    return allMems.filter(function(m) {
      if (m.id === mem.id) return false;
      if (m.domain !== mem.domain) return false;
      if (isToolCapture(m)) return false;
      var overlap = (m.tags || []).filter(function(t) { return memTags.has(t); });
      return overlap.length >= 1;
    }).sort(function(a, b) {
      var oa = (a.tags || []).filter(function(t) { return memTags.has(t); }).length;
      var ob = (b.tags || []).filter(function(t) { return memTags.has(t); }).length;
      return ob - oa;
    }).slice(0, 5);
  }

  function shortDomain(d) {
    if (!d) return 'unknown';
    var parts = d.replace(/\\/g, '/').split('/').filter(Boolean);
    return parts.length > 0 ? parts[parts.length - 1] : d;
  }

  function heatColor(h) {
    if (h >= 0.7) return '#E07070';
    if (h >= 0.4) return '#E0B840';
    if (h >= 0.1) return '#50D0E8';
    return '#607080';
  }

  function formatDate(iso) {
    if (!iso) return '--';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var now = new Date();
    var diff = now - d;
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    if (diff < 604800000) return Math.floor(diff / 86400000) + 'd ago';
    return d.toISOString().slice(0, 10);
  }

  function el(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  function statEl(val, label) {
    var s = el('div', 'kv-stat');
    var v = el('span', 'kv-stat-val');
    v.textContent = val;
    var l = el('span', 'kv-stat-label');
    l.textContent = label;
    s.appendChild(v);
    s.appendChild(l);
    return s;
  }

  function esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function renderMemoryContent(raw) {
    if (!raw) return '';
    var text = raw;

    // Unescape literal \n to real newlines (from JSON serialization)
    text = text.replace(/\\n/g, '\n');

    var lines = text.split('\n');
    var html = [];
    var inCode = false;
    var codeLines = [];
    var codeLang = '';

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      // Fenced code blocks
      var fence = line.match(/^```(\w*)/);
      if (fence) {
        if (inCode) {
          html.push('<pre class="kv-code"><code>' + codeLines.join('\n') + '</code></pre>');
          codeLines = [];
          inCode = false;
        } else {
          codeLang = fence[1] || '';
          inCode = true;
        }
        continue;
      }
      if (inCode) { codeLines.push(esc(line)); continue; }

      // Detect JSON blocks — accumulate, then parse and pretty-print
      if (/^\s*[\{\[]/.test(line) && !inCode) {
        var jsonLines = [line];
        var depth = 0;
        for (var c = 0; c < line.length; c++) {
          if (line[c] === '{' || line[c] === '[') depth++;
          if (line[c] === '}' || line[c] === ']') depth--;
        }
        while (depth > 0 && i + 1 < lines.length) {
          i++;
          jsonLines.push(lines[i]);
          for (var c2 = 0; c2 < lines[i].length; c2++) {
            if (lines[i][c2] === '{' || lines[i][c2] === '[') depth++;
            if (lines[i][c2] === '}' || lines[i][c2] === ']') depth--;
          }
        }
        var jsonRaw = jsonLines.join('\n');
        var rendered = null;
        try {
          var parsed = JSON.parse(jsonRaw);
          // Tool capture shape: { stdout, stderr, ... } — render plain text, not JSON
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) &&
              ('stdout' in parsed || 'stderr' in parsed)) {
            var parts = [];
            if (parsed.stdout) parts.push(String(parsed.stdout));
            if (parsed.stderr) parts.push('--- stderr ---\n' + String(parsed.stderr));
            rendered = '<pre class="kv-code"><code>' + esc(parts.join('\n')) + '</code></pre>';
          } else {
            rendered = '<pre class="kv-code"><code>' + esc(JSON.stringify(parsed, null, 2)) + '</code></pre>';
          }
        } catch (e) {
          rendered = '<pre class="kv-code"><code>' + esc(jsonRaw) + '</code></pre>';
        }
        html.push(rendered);
        continue;
      }

      // Blank lines
      if (!line.trim()) { continue; }

      // Headings
      var hm = line.match(/^(#{1,4})\s+(.+)/);
      if (hm) {
        var level = hm[1].length;
        html.push('<h' + (level + 1) + '>' + esc(hm[2]) + '</h' + (level + 1) + '>');
        continue;
      }

      // Bold
      var formatted = esc(line);
      formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');

      // List items
      if (/^\s*[-*]\s+/.test(line)) {
        html.push('<li>' + formatted.replace(/^\s*[-*]\s+/, '') + '</li>');
        continue;
      }

      html.push('<p>' + formatted + '</p>');
    }

    // Close unclosed code
    if (inCode && codeLines.length) {
      html.push('<pre class="kv-code"><code>' + codeLines.join('\n') + '</code></pre>');
    }

    return html.join('');
  }

  function addMeta(parent, label, value) {
    var item = el('div', 'kv-expanded-meta-item');
    var l = el('span', 'kv-expanded-meta-label');
    l.textContent = label;
    var v = el('span', 'kv-expanded-meta-val');
    v.textContent = value;
    item.appendChild(l);
    item.appendChild(v);
    parent.appendChild(item);
  }

  function addMetaColored(parent, label, value, color) {
    var item = el('div', 'kv-expanded-meta-item');
    var l = el('span', 'kv-expanded-meta-label');
    l.textContent = label;
    var v = el('span', 'kv-expanded-meta-val');
    v.textContent = value;
    v.style.color = color;
    item.appendChild(l);
    item.appendChild(v);
    parent.appendChild(item);
  }

  function domainPill(label, value, isGlobal) {
    var pill = el('button', 'kv-domain-pill');
    if (isGlobal) pill.classList.add('kv-pill-global');
    if (value === currentDomain) pill.classList.add('active');
    pill.textContent = label;
    pill.addEventListener('click', function() {
      currentDomain = value;
      _resetAndFetch();
    });
    return pill;
  }

  // ── Initialize ──
  document.addEventListener('DOMContentLoaded', init);
})();
