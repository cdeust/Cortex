// Cortex Memory Board — Kanban by consolidation stage with flow header
// Shows consolidated vs dropped memories in a tree-like view.
//
// Data source: /api/memories (paged endpoint). Lazy-loads pages on
// scroll; never holds the full memory set in memory. Sort = recent so
// the freshest activity lands first.
(function() {
  var container = null;
  var visible = false;
  var currentData = null;
  var selectedId = null;
  var _emitting = false;

  // Paged-fetch state. ONE page on open, all subsequent pages gated
  // on actual user scroll.
  var BOARD_PAGE_LIMIT = 100;
  var boardAccum = [];
  var boardSeenIds = Object.create(null);
  var boardCursor = null;
  var boardLoading = false;
  var boardDone = false;
  var boardPagesFetched = 0;
  var boardFetchToken = 0;
  var boardScrolledSinceFetch = false;

  // Server-known facets + active filters (mirror Knowledge tab).
  var boardFacets = null;
  var boardFilterDomain = 'all';     // 'all' | 'global' | <domain name>
  var boardFilterStage = null;       // null = all stages
  var boardFilterEmotion = null;
  var boardFilterMinHeat = null;
  var boardFilterProtected = false;
  var boardSearchQuery = '';
  var boardSort = 'recent';           // 'recent' | 'heat'

  var STAGES = ['labile', 'early_ltp', 'late_ltp', 'consolidated', 'reconsolidating'];
  var STAGE_COLORS = JUG.CONSOLIDATION_COLORS;
  var STAGE_LABELS = JUG.CONSOLIDATION_LABELS || {};
  var EMO_COLORS = {
    urgency: '#ff3366', frustration: '#ef4444',
    satisfaction: '#22c55e', discovery: '#f59e0b',
    confusion: '#8b5cf6'
  };

  var STAGE_BIO = {
    labile: { decay: '2.0x', vuln: '90%', plast: '100%', advance: 'DA\u22651 or imp>0.3' },
    early_ltp: { decay: '1.2x', vuln: '50%', plast: '70%', advance: 'replay\u22651 or imp>0.4' },
    late_ltp: { decay: '0.8x', vuln: '20%', plast: '30%', advance: 'replay\u22653' },
    consolidated: { decay: '0.5x', vuln: '5%', plast: '10%', advance: 'Stable' },
    reconsolidating: { decay: '1.5x', vuln: '80%', plast: '90%', advance: 'Re-stabilizes' },
  };

  function init() {
    container = document.getElementById('timeline-container');
    if (!container) return;

    JUG.on('state:activeView', function(ev) {
      if (ev.value === 'timeline') show(); else hide();
    });
    JUG.on('state:lastData', function(ev) {
      if (visible && ev.value) { currentData = ev.value; rebuild(); }
    });
    JUG.on('state:activeFilter', rebuildIfVisible);
    JUG.on('state:domainFilter', rebuildIfVisible);
    JUG.on('state:emotionFilter', rebuildIfVisible);
    JUG.on('state:stageFilter', rebuildIfVisible);
    JUG.on('graph:selectNode', function(node) {
      if (_emitting || !visible || !node || node.type !== 'memory') return;
      if (selectedId === node.id) return;
      highlightMemory(node.id);
    });
    JUG.on('graph:deselectNode', function() {
      if (_emitting || !visible) return;
      clearHighlight();
    });
  }

  function show() {
    if (!container) return;
    container.style.display = 'flex';
    visible = true;
    if (!boardFacets) {
      _boardFetchFacets().then(function() { _boardResetAndFetch(); });
    } else {
      _boardResetAndFetch();
    }
    if (JUG.state.selectedId) highlightMemory(JUG.state.selectedId);

    // 60s poll for live updates: refetch the first page (heat may have
    // shifted, new memories landed). Cheap because the page is paged.
    if (!window._boardPollInterval) {
      window._boardPollInterval = setInterval(function() {
        if (visible && document.querySelector('.kb-board')) _boardResetAndFetch();
      }, 60000);
    }
  }

  function _boardFetchFacets() {
    return fetch('/api/memories/facets')
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(d) { if (d) boardFacets = d; })
      .catch(function(err) { console.warn('[board] facets fetch failed:', err); });
  }
  function hide() {
    visible = false;
    if (container) container.style.display = 'none';
  }
  function rebuildIfVisible() { if (visible) rebuild(); }

  // ── Lazy-load paged memories from /api/memories ──
  function _boardResetAndFetch() {
    boardAccum = [];
    boardSeenIds = Object.create(null);
    boardCursor = null;
    boardDone = false;
    boardLoading = false;
    boardPagesFetched = 0;
    boardFetchToken++;
    boardScrolledSinceFetch = true;  // allow the very first page
    currentData = { nodes: [], edges: [], links: [] };
    rebuild();
    _boardFetchPage();
  }

  function _boardFetchPage() {
    if (boardDone || boardLoading) return;
    // Gate: every page after the first must be triggered by a genuine
    // user scroll. Without this the sentinel inside the initial
    // viewport keeps firing the IntersectionObserver in a loop.
    if (!boardScrolledSinceFetch) return;
    boardScrolledSinceFetch = false;
    boardLoading = true;
    var token = boardFetchToken;
    var qs = '?limit=' + BOARD_PAGE_LIMIT + '&sort=' + encodeURIComponent(boardSort);
    if (boardCursor) qs += '&cursor=' + encodeURIComponent(boardCursor);
    if (boardFilterDomain === 'global') qs += '&global=1';
    else if (boardFilterDomain !== 'all') qs += '&domain=' + encodeURIComponent(boardFilterDomain);
    if (boardFilterStage) qs += '&stage=' + encodeURIComponent(boardFilterStage);
    if (boardFilterEmotion) qs += '&emotion=' + encodeURIComponent(boardFilterEmotion);
    if (boardFilterMinHeat != null) qs += '&min_heat=' + encodeURIComponent(boardFilterMinHeat);
    if (boardFilterProtected) qs += '&protected=1';
    if (boardSearchQuery) qs += '&search=' + encodeURIComponent(boardSearchQuery);
    fetch('/api/memories' + qs)
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(data) {
        if (token !== boardFetchToken) return;
        var items = data.items || [];
        for (var i = 0; i < items.length; i++) {
          var m = items[i];
          if (boardSeenIds[m.id]) continue;
          boardSeenIds[m.id] = true;
          m._ts = parseTs(m.createdAt) || 0;
          boardAccum.push(m);
        }
        boardCursor = data.next_cursor || null;
        boardDone = !boardCursor;
        boardPagesFetched++;
        boardLoading = false;
        currentData = { nodes: boardAccum, edges: [], links: [] };
        rebuild();
        // No auto-prefetch — every subsequent page is gated on user
        // scroll via boardScrolledSinceFetch. The first page is enough
        // to populate the columns; user scrolls to load more.
      })
      .catch(function(err) {
        console.warn('[board] /api/memories fetch failed:', err);
        boardLoading = false;
      });
  }

  function extractMemories(data) {
    var nodes = (data && data.nodes) ? data.nodes : [];
    if (JUG._applyExtraFilters) nodes = JUG._applyExtraFilters(nodes);
    return nodes;
  }

  function _boardChip(label, active, onClick, accent) {
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

  function _boardFilterBar() {
    var wrap = el('div', 'kb-filter-wrap');
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:6px;padding:10px 14px;border-bottom:1px solid rgba(120,180,200,0.08);background:rgba(8,12,20,0.3)';

    // Row 1: search + sort + clear-all.
    var row1 = el('div');
    row1.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap';
    var searchInput = el('input');
    searchInput.type = 'text'; searchInput.placeholder = 'Search…';
    searchInput.value = boardSearchQuery;
    searchInput.style.cssText = 'flex:1;min-width:180px;background:rgba(10,16,28,0.6);border:1px solid rgba(120,200,220,0.25);color:#c4d4dc;padding:5px 10px;border-radius:3px;font:inherit;font-size:12px';
    var sDeb = null;
    searchInput.addEventListener('input', function() {
      clearTimeout(sDeb);
      sDeb = setTimeout(function() {
        boardSearchQuery = searchInput.value;
        _boardResetAndFetch();
      }, 250);
    });
    row1.appendChild(searchInput);

    [['recent', 'Recent'], ['heat', 'Heat']].forEach(function(s) {
      row1.appendChild(_boardChip(s[1], boardSort === s[0],
        function() { boardSort = s[0]; _boardResetAndFetch(); }));
    });

    var anyActive = boardFilterDomain !== 'all' || boardFilterStage || boardFilterEmotion
      || boardFilterMinHeat != null || boardFilterProtected || boardSearchQuery;
    if (anyActive) {
      var clr = el('button'); clr.textContent = 'Clear all';
      clr.style.cssText = 'background:transparent;border:1px solid rgba(224,176,64,0.4);color:#E0B040;padding:3px 10px;border-radius:3px;cursor:pointer;font:inherit;letter-spacing:0.6px;text-transform:uppercase;font-size:9px';
      clr.addEventListener('click', function() {
        boardFilterDomain = 'all'; boardFilterStage = null; boardFilterEmotion = null;
        boardFilterMinHeat = null; boardFilterProtected = false; boardSearchQuery = '';
        _boardResetAndFetch();
      });
      row1.appendChild(clr);
    }
    wrap.appendChild(row1);

    // Row 2: domain chips (server-known facets).
    var row2 = el('div');
    row2.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;align-items:center';
    var domLabel = el('span'); domLabel.textContent = 'Domain';
    domLabel.style.cssText = 'color:#7a8e9c;letter-spacing:1px;text-transform:uppercase;font-size:9px;margin-right:4px';
    row2.appendChild(domLabel);
    row2.appendChild(_boardChip('All' + (boardFacets ? ' (' + boardFacets.total + ')' : ''),
      boardFilterDomain === 'all',
      function() { boardFilterDomain = 'all'; _boardResetAndFetch(); }));
    if (boardFacets && boardFacets.global > 0) {
      row2.appendChild(_boardChip('Global (' + boardFacets.global + ')',
        boardFilterDomain === 'global',
        function() { boardFilterDomain = 'global'; _boardResetAndFetch(); }, '#FF4081'));
    }
    var domains = boardFacets && boardFacets.domains ? boardFacets.domains : [];
    domains.slice(0, 30).forEach(function(d) {
      row2.appendChild(_boardChip(_boardShortDomain(d.name) + ' (' + d.count + ')',
        boardFilterDomain === d.name,
        function() { boardFilterDomain = d.name; _boardResetAndFetch(); }));
    });
    wrap.appendChild(row2);

    // Row 3: stage + emotion + heat + protected.
    var row3 = el('div');
    row3.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;align-items:center';
    var fLabel = el('span'); fLabel.textContent = 'Filter';
    fLabel.style.cssText = 'color:#7a8e9c;letter-spacing:1px;text-transform:uppercase;font-size:9px;margin-right:4px';
    row3.appendChild(fLabel);
    var stageOpts = [
      { v: null,              t: 'Any stage' },
      { v: 'labile',          t: 'New' },
      { v: 'early_ltp',       t: 'Growing' },
      { v: 'late_ltp',        t: 'Strong' },
      { v: 'consolidated',    t: 'Stable' },
      { v: 'reconsolidating', t: 'Updating' },
    ];
    stageOpts.forEach(function(opt) {
      var c = boardFacets && opt.v ? boardFacets.stages[opt.v]
            : (opt.v == null && boardFacets ? boardFacets.total : '');
      row3.appendChild(_boardChip(opt.t + (c !== '' ? ' (' + c + ')' : ''),
        boardFilterStage === opt.v,
        function() { boardFilterStage = opt.v; _boardResetAndFetch(); },
        STAGE_COLORS && opt.v ? STAGE_COLORS[opt.v] : null));
    });
    var sep = el('span'); sep.textContent = '·';
    sep.style.cssText = 'color:#5a6e7c;margin:0 6px';
    row3.appendChild(sep);
    var emoOpts = [
      { v: null,       t: 'Any feel' },
      { v: 'urgent',   t: 'Urgent',   color: '#ff3366' },
      { v: 'positive', t: 'Positive', color: '#22c55e' },
      { v: 'negative', t: 'Negative', color: '#ef4444' },
      { v: 'neutral',  t: 'Neutral' },
    ];
    emoOpts.forEach(function(opt) {
      var c = boardFacets && opt.v ? boardFacets.emotions[opt.v] : '';
      row3.appendChild(_boardChip(opt.t + (c !== '' ? ' (' + c + ')' : ''),
        boardFilterEmotion === opt.v,
        function() { boardFilterEmotion = opt.v; _boardResetAndFetch(); }, opt.color));
    });
    var sep2 = el('span'); sep2.textContent = '·';
    sep2.style.cssText = 'color:#5a6e7c;margin:0 6px';
    row3.appendChild(sep2);
    row3.appendChild(_boardChip('Hot' + (boardFacets ? ' (' + boardFacets.hot + ')' : ''),
      boardFilterMinHeat != null,
      function() { boardFilterMinHeat = boardFilterMinHeat != null ? null : 0.5; _boardResetAndFetch(); },
      '#E07070'));
    row3.appendChild(_boardChip('Protected' + (boardFacets ? ' (' + boardFacets.protected + ')' : ''),
      boardFilterProtected,
      function() { boardFilterProtected = !boardFilterProtected; _boardResetAndFetch(); },
      '#E0B040'));
    wrap.appendChild(row3);

    return wrap;
  }

  function _boardShortDomain(d) {
    if (!d) return 'unknown';
    var parts = d.replace(/\\/g, '/').split('/').filter(Boolean);
    return parts.length > 0 ? parts[parts.length - 1] : d;
  }

  function parseTs(val) {
    if (!val) return null;
    var d = new Date(val);
    return isNaN(d.getTime()) ? null : d.getTime();
  }

  function rebuild() {
    var memories = extractMemories(currentData);
    container.innerHTML = '';

    // Group by stage
    var groups = {};
    STAGES.forEach(function(s) { groups[s] = []; });
    memories.forEach(function(m) {
      // Accept all shapes the backend has emitted over time:
      //   m.stage                (current workflow_graph.v1 field)
      //   m.consolidationStage   (legacy camelCase)
      //   m.consolidation_stage  (snake_case from memory record)
      var s = m.stage || m.consolidationStage || m.consolidation_stage || 'labile';
      if (!groups[s]) s = 'labile';
      groups[s].push(m);
    });
    STAGES.forEach(function(s) {
      groups[s].sort(function(a, b) {
        return (b.heat || 0) - (a.heat || 0) || (b._ts || 0) - (a._ts || 0);
      });
    });

    var total = memories.length;

    // ── Flow header ──
    var flowStrip = el('div', 'kb-flow-strip');
    STAGES.forEach(function(stage, i) {
      var sc = STAGE_COLORS[stage] || '#50C8E0';
      var count = groups[stage].length;
      var pct = total > 0 ? (count / total * 100) : 0;
      var bio = STAGE_BIO[stage];

      if (i > 0) {
        var arrow = el('div', 'kb-flow-arrow');
        arrow.style.setProperty('--sc', STAGE_COLORS[STAGES[i-1]] || '#50C8E0');
        arrow.innerHTML = '<div class="kb-flow-arrow-line"></div>';
        flowStrip.appendChild(arrow);
      }

      // Compute live metrics
      var stageMems = groups[stage];
      var avgHeat = 0, avgImp = 0, avgEnc = 0, avgInterf = 0, avgReplay = 0, avgHippo = 0;
      if (stageMems.length > 0) {
        stageMems.forEach(function(m) {
          avgHeat += (m.heat || 0);
          avgImp += (m.importance || 0);
          avgEnc += (m.encodingStrength || 0);
          avgInterf += (m.interferenceScore || 0);
          avgReplay += (m.accessCount || 0);
          avgHippo += (m.hippocampalDependency || 0);
        });
        var n = stageMems.length;
        avgHeat /= n; avgImp /= n; avgEnc /= n; avgInterf /= n; avgReplay /= n; avgHippo /= n;
      }

      var card = el('div', 'kb-flow-node');
      card.style.setProperty('--sc', sc);

      // Count + name
      card.innerHTML =
        '<div class="kb-flow-count" style="color:' + sc + '">' + count + '</div>' +
        '<div class="kb-flow-label">' + (STAGE_LABELS[stage] || stage).toUpperCase() + '</div>';

      // Percentage bar
      var pctRow = el('div', 'kb-flow-pct-row');
      pctRow.innerHTML =
        '<div class="kb-flow-pct-bar"><div class="kb-flow-pct-fill" style="width:' + pct + '%;background:' + sc + '"></div></div>' +
        '<span class="kb-flow-pct">' + pct.toFixed(1) + '%</span>';
      card.appendChild(pctRow);

      // Biological properties
      var bioEl = el('div', 'kb-flow-bio-section');
      bioEl.innerHTML =
        '<div class="kb-flow-bio-row"><span>Decay</span><span>' + bio.decay + '</span></div>' +
        '<div class="kb-flow-bio-row"><span>Vulnerability</span><span>' + bio.vuln + '</span></div>' +
        '<div class="kb-flow-bio-row"><span>Plasticity</span><span>' + bio.plast + '</span></div>';
      card.appendChild(bioEl);

      // Live metrics bars
      if (count > 0) {
        var liveEl = el('div', 'kb-flow-live');
        liveEl.innerHTML =
          '<div class="kb-flow-live-title">LIVE</div>' +
          miniBar('Heat', avgHeat, sc) +
          miniBar('Import', avgImp, sc) +
          miniBar('Enc', avgEnc, sc) +
          miniBar('Interf', avgInterf, '#E07070') +
          miniBar('Hippo', avgHippo, '#C070D0') +
          '<div class="kb-flow-bio-row"><span>Replay</span><span>' + avgReplay.toFixed(1) + '</span></div>';
        card.appendChild(liveEl);
      }

      // Advance condition
      var advEl = el('div', 'kb-flow-advance');
      advEl.innerHTML = '<span style="color:' + sc + '">Advance:</span> ' + bio.advance;
      card.appendChild(advEl);

      // At-risk count badge
      var atRisk = stageMems.filter(function(m) {
        return (m.interferenceScore || 0) > 0.3 && (m.heat || 0) < 0.2;
      }).length;
      if (atRisk > 0) {
        var riskBadge = el('div', 'kb-flow-risk-badge');
        riskBadge.textContent = '\u26A0 ' + atRisk + ' at risk';
        card.appendChild(riskBadge);
      }

      flowStrip.appendChild(card);
    });
    container.appendChild(flowStrip);

    // Filter chips — same shape as Knowledge tab.
    container.appendChild(_boardFilterBar());

    // ── Board columns ──
    var board = el('div', 'kb-board');

    STAGES.forEach(function(stage) {
      var sc = STAGE_COLORS[stage] || '#50C8E0';
      var mems = groups[stage];

      var col = el('div', 'kb-col');
      col.style.setProperty('--sc', sc);

      // Header
      var header = el('div', 'kb-col-header');
      var title = el('span', 'kb-col-title');
      title.textContent = (STAGE_LABELS[stage] || stage).toUpperCase();
      header.appendChild(title);
      var count = el('span', 'kb-col-count');
      count.textContent = mems.length;
      header.appendChild(count);
      col.appendChild(header);

      // Cards
      var cards = el('div', 'kb-col-cards');

      mems.forEach(function(mem) {
        var card = buildCard(mem, sc);
        cards.appendChild(card);
      });

      if (mems.length === 0) {
        var empty = el('div', 'kb-empty');
        empty.textContent = 'No memories';
        cards.appendChild(empty);
      }

      col.appendChild(cards);
      board.appendChild(col);
    });

    container.appendChild(board);

    // Sentinel + manual "Load more" button — same triple-trigger
    // pattern as Knowledge: IntersectionObserver, scroll/wheel
    // backstop, and an explicit click button. Without this the user
    // sees the first ~500 memories and the Board feels capped.
    var sentinel = el('div', 'kb-load-sentinel');
    sentinel.id = 'kb-load-sentinel';
    sentinel.style.cssText = 'min-height:60px;display:flex;align-items:center;justify-content:center;gap:12px;color:#7a8e9c;font-size:11px;letter-spacing:1px;text-transform:uppercase;padding:24px';
    var sText = el('span'); sText.id = 'kb-load-text';
    sText.textContent = boardDone
      ? '— end of board — ' + boardAccum.length + ' memories loaded'
      : (boardLoading
          ? 'Loading more memories… (' + boardAccum.length + ' so far)'
          : 'Scroll for more · ' + boardAccum.length + ' loaded');
    sentinel.appendChild(sText);
    if (!boardDone) {
      var sBtn = el('button', 'kb-load-more');
      sBtn.id = 'kb-load-more';
      sBtn.style.cssText = 'background:rgba(80,210,235,0.15);border:1px solid rgba(120,200,220,0.4);color:#80d2e0;padding:6px 14px;border-radius:3px;cursor:pointer;font:inherit;letter-spacing:1.2px';
      sBtn.textContent = 'Load more';
      sBtn.addEventListener('click', function(){
        boardScrolledSinceFetch = true;  // explicit user intent
        _boardFetchPage();
      });
      sentinel.appendChild(sBtn);
    }
    container.appendChild(sentinel);
    _boardAttachIntersectionObserver(sentinel);
    _boardAttachScrollBackstop(sentinel);
  }

  function _boardAttachIntersectionObserver(sentinel) {
    if (!('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function(entries) {
      entries.forEach(function(e) { if (e.isIntersecting) _boardFetchPage(); });
    }, { root: null, rootMargin: '400px' });
    io.observe(sentinel);
  }

  function _boardAttachScrollBackstop(sentinel) {
    if (window._boardScrollBackstopAttached) return;
    window._boardScrollBackstopAttached = true;
    var maybeFetch = function() {
      if (!visible || boardLoading || boardDone) return;
      // Mark that the user has actually scrolled — only NOW does the
      // gate in _boardFetchPage allow another fetch.
      boardScrolledSinceFetch = true;
      var s = document.getElementById('kb-load-sentinel');
      if (!s) return;
      var rect = s.getBoundingClientRect();
      var vh = window.innerHeight || document.documentElement.clientHeight;
      if (rect.top < vh + 400) _boardFetchPage();
    };
    container.addEventListener('scroll', maybeFetch, { passive: true });
    window.addEventListener('scroll', maybeFetch, { passive: true });
    container.addEventListener('wheel', maybeFetch, { passive: true });
  }

  function buildCard(mem, stageColor) {
    var card = el('div', 'kb-card');
    card.dataset.memId = mem.id;

    var heat = Math.max(0, Math.min(1, mem.heat || 0));
    var stability = mem.stability;
    var interference = mem.interferenceScore || 0;
    var plasticity = Math.max(0, Math.min(1, mem.plasticity || 0));
    var replayCount = mem.accessCount || 0;

    // Heat tint via CSS custom property (used by ::before pseudo-element)
    card.style.setProperty('--card-heat', heat);
    card.style.setProperty('--card-stage-color', stageColor);

    // Card opacity — floor at 0.55
    card.style.opacity = Math.max(0.55, 0.4 + heat * 0.5);

    // Integrity border class (null-safe stability check)
    var borderClass;
    if (stability == null || stability === undefined) {
      borderClass = 'kb-card--neutral';
    } else if (stability > 0.7 && interference < 0.3) {
      borderClass = 'kb-card--healthy';
    } else if (stability > 0.3) {
      borderClass = 'kb-card--consolidating';
    } else if (interference > 0.5) {
      borderClass = 'kb-card--at-risk';
    } else {
      borderClass = 'kb-card--fading';
    }
    card.classList.add(borderClass);

    // Fading indicator for very low heat
    if (heat < 0.1) {
      card.classList.add('kb-card-fading');
    }

    var body = el('div', 'kb-card-body');

    // Content — 2 lines max, 100 chars
    var label = el('div', 'kb-card-label');
    label.textContent = (mem.label || mem.content || '').slice(0, 100);
    body.appendChild(label);

    // Emotion chip — high-signal affective indicator under the label.
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildEmotionChip === 'function') {
      var emoChip = JUG._memSci.buildEmotionChip(mem);
      if (emoChip) {
        emoChip.classList.add('ms-emotion--compact');
        body.appendChild(emoChip);
      }
    }

    // Meta row: domain pill + store type badge + relative age
    var meta = el('div', 'kb-card-meta');

    var domain = el('span', 'kb-card-domain');
    domain.textContent = (mem.domain || '').slice(0, 18);
    meta.appendChild(domain);

    var storeType = mem.storeType || (mem.consolidationStage === 'consolidated' ? 'semantic' : 'episodic');
    var storeBadge = el('span', 'kb-card__store-badge');
    if (storeType === 'semantic') {
      storeBadge.classList.add('kb-card__store-badge--semantic');
      storeBadge.textContent = 'SEM';
    } else {
      storeBadge.classList.add('kb-card__store-badge--episodic');
      storeBadge.textContent = 'EP';
    }
    meta.appendChild(storeBadge);

    if (mem._ts) {
      var time = el('span', 'kb-card-time');
      time.textContent = formatTime(mem._ts);
      meta.appendChild(time);
    }
    body.appendChild(meta);

    // Meaning — schema alignment, semantic tags, gist.
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildMeaningSection === 'function') {
      var meaning = JUG._memSci.buildMeaningSection(mem);
      if (meaning) {
        meaning.classList.add('ms-meaning--compact');
        body.appendChild(meaning);
      }
    }

    // Scientific measurements — compact variant keeps Kanban column
    // cards dense (6 top rows max; bars + counters only, no text/age).
    if (window.JUG && JUG._memSci && typeof JUG._memSci.buildSciencePanel === 'function') {
      var sci = JUG._memSci.buildSciencePanel(mem, 'compact');
      if (sci) body.appendChild(sci);
    }

    // Tags — up to 2
    if (mem.tags && mem.tags.length > 0) {
      var tagsRow = el('div', 'kb-card-tags');
      mem.tags.slice(0, 2).forEach(function(t) {
        var tag = el('span', 'kb-card-tag');
        tag.textContent = t;
        tagsRow.appendChild(tag);
      });
      body.appendChild(tagsRow);
    }

    // Code impact — AST symbols that touch this memory (by file-ref
    // or verbatim label mention). Cap at 3 chips here to keep Kanban
    // cards compact; the Knowledge-view expanded modal shows more.
    var _kvSyms = (window.JUG && JUG._kvResolve) ? JUG._kvResolve(mem, 3) : null;
    if (_kvSyms && _kvSyms.length) {
      var symRow = el('div', 'kb-card-tags');
      symRow.title = 'Code symbols connected to this memory';
      _kvSyms.forEach(function (ref) {
        var chip = el('span', 'kb-card-tag');
        chip.textContent = '⟨/⟩ ' + (ref.node.label || ref.node.id);
        chip.style.cursor = 'pointer';
        chip.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (window.JUG && JUG.emit) JUG.emit('graph:selectNode', ref.node);
          if (JUG.state) JUG.state.activeView = 'graph';
        });
        symRow.appendChild(chip);
      });
      body.appendChild(symRow);
    }

    // Protected badge
    if (mem.isProtected) {
      var shield = el('span', 'kb-badge kb-badge-protected');
      shield.textContent = '\u26A1';
      body.appendChild(shield);
    }

    // Hover-expand scan tier (hidden by default, shown on hover via CSS)
    var scan = el('div', 'kb-card__scan');
    var safeStability = (stability != null) ? Math.max(0, Math.min(1, stability)) : 0;

    // Plasticity bar
    scan.innerHTML =
      '<div class="kb-card__bar">' +
        '<span class="kb-card__bar-label">Plasticity</span>' +
        '<div class="kb-card__bar-track"><div class="kb-card__bar-fill" style="width:' + (plasticity * 100) + '%"></div></div>' +
      '</div>' +
      '<div class="kb-card__bar">' +
        '<span class="kb-card__bar-label">Stability</span>' +
        '<div class="kb-card__bar-track"><div class="kb-card__bar-fill" style="width:' + (safeStability * 100) + '%"></div></div>' +
      '</div>' +
      (interference > 0.3 ? '<span class="kb-card__risk-badge">\u26A0 Interference</span>' : '') +
      (replayCount > 0 ? '<span class="kb-card__meta-badge">\u21BB ' + replayCount + '</span>' : '');

    body.appendChild(scan);
    card.appendChild(body);

    // Tooltip on hover
    card.addEventListener('mouseenter', function() { JUG._tooltip.show(mem); });
    card.addEventListener('mouseleave', function() { JUG._tooltip.hide(); });

    // Click to select/deselect
    card.addEventListener('click', function(e) {
      e.stopPropagation();
      _emitting = true;
      if (selectedId === mem.id) {
        clearHighlight();
        JUG.emit('graph:deselectNode');
      } else {
        highlightMemory(mem.id);
        JUG.emit('graph:selectNode', mem);
      }
      _emitting = false;
    });

    return card;
  }

  function highlightMemory(id) {
    selectedId = id;
    if (!container) return;
    var cards = container.querySelectorAll('.kb-card');
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].dataset.memId === id) {
        cards[i].classList.add('kb-card-selected');
        cards[i].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        cards[i].classList.add('kb-card-dimmed');
      }
    }
  }

  function clearHighlight() {
    selectedId = null;
    if (!container) return;
    var cards = container.querySelectorAll('.kb-card');
    for (var i = 0; i < cards.length; i++) {
      cards[i].classList.remove('kb-card-selected', 'kb-card-dimmed');
    }
  }

  function formatTime(ts) {
    var d = new Date(ts);
    var now = new Date();
    var diff = now - d;
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    if (diff < 604800000) return Math.floor(diff / 86400000) + 'd ago';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function miniBar(label, value, color) {
    var pct = Math.max(0, Math.min(100, (value || 0) * 100));
    return '<div class="kb-flow-metric">' +
      '<span class="kb-flow-metric-label">' + label + '</span>' +
      '<div class="kb-flow-metric-bar"><div class="kb-flow-metric-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
      '<span class="kb-flow-metric-val">' + pct.toFixed(0) + '%</span></div>';
  }

  function el(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    requestAnimationFrame(init);
  }

  JUG.timelineView = { show: show, hide: hide };
})();
