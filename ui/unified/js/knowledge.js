// Cortex — Knowledge View
// Readable memory cards organized by domain with search, sort, and filtering
(function() {
  var container = null;
  var visible = false;
  var currentSort = 'heat';
  var currentDomain = 'all';
  var searchQuery = '';
  var expandedCardId = null;

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
    JUG.on('state:lastData', function() {
      if (visible) rebuild();
    });
  }

  function show() {
    if (!container) return;
    container.style.display = 'flex';
    visible = true;
    rebuild();
  }

  function hide() {
    visible = false;
    if (container) container.style.display = 'none';
    closeExpanded();
  }

  // ── Extract memories from graph data ──
  function getMemories() {
    var data = JUG.state.lastData;
    if (!data || !data.nodes) return [];
    return data.nodes.filter(function(n) { return n.type === 'memory'; });
  }

  function getDomains(mems) {
    var set = {};
    mems.forEach(function(m) {
      var d = m.domain || 'unknown';
      set[d] = (set[d] || 0) + 1;
    });
    return Object.keys(set).sort();
  }

  // ── Filter + sort ──
  function filterAndSort(mems) {
    var result = mems;

    // Domain filter
    if (currentDomain === 'global') {
      result = result.filter(function(m) { return m.isGlobal; });
    } else if (currentDomain !== 'all') {
      result = result.filter(function(m) { return m.domain === currentDomain; });
    }

    // Search
    if (searchQuery) {
      var q = searchQuery.toLowerCase();
      result = result.filter(function(m) {
        return (m.content || '').toLowerCase().indexOf(q) >= 0 ||
               (m.label || '').toLowerCase().indexOf(q) >= 0 ||
               (m.domain || '').toLowerCase().indexOf(q) >= 0 ||
               ((m.tags || []).join(' ')).toLowerCase().indexOf(q) >= 0;
      });
    }

    // Sort
    result.sort(function(a, b) {
      if (currentSort === 'heat') return (b.heat || 0) - (a.heat || 0);
      if (currentSort === 'recency') {
        var ta = a.createdAt || a.lastAccessed || '';
        var tb = b.createdAt || b.lastAccessed || '';
        return tb.localeCompare(ta);
      }
      if (currentSort === 'importance') return (b.importance || 0) - (a.importance || 0);
      return 0;
    });

    return result;
  }

  // ── Build the view ──
  function rebuild() {
    if (!container) return;
    container.innerHTML = '';
    var allMems = getMemories();
    var domains = getDomains(allMems);

    // Domain pills
    var domainBar = el('div', 'kv-domain-bar');
    domainBar.appendChild(domainPill('All', 'all'));
    domainBar.appendChild(domainPill('Global', 'global', true));
    domains.forEach(function(d) {
      domainBar.appendChild(domainPill(shortDomain(d), d));
    });
    container.appendChild(domainBar);

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
        rebuildGrid();
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
        rebuild();
      });
      sortGroup.appendChild(btn);
    });
    searchRow.appendChild(sortGroup);
    container.appendChild(searchRow);

    // Stats bar
    var filtered = filterAndSort(allMems);
    var statsBar = el('div', 'kv-stats-bar');
    statsBar.appendChild(statEl(filtered.length, 'memories'));
    statsBar.appendChild(statEl(domains.length, 'domains'));
    var globalCount = allMems.filter(function(m) { return m.isGlobal; }).length;
    if (globalCount > 0) statsBar.appendChild(statEl(globalCount, 'global rules'));
    var hotCount = allMems.filter(function(m) { return (m.heat || 0) >= 0.5; }).length;
    if (hotCount > 0) statsBar.appendChild(statEl(hotCount, 'hot'));
    container.appendChild(statsBar);

    // Grid container (separate so we can rebuild just this)
    var grid = el('div', 'kv-grid');
    grid.id = 'kv-grid';
    container.appendChild(grid);

    populateGrid(grid, filtered, allMems);
  }

  function rebuildGrid() {
    var grid = document.getElementById('kv-grid');
    if (!grid) return;
    var allMems = getMemories();
    var filtered = filterAndSort(allMems);
    populateGrid(grid, filtered, allMems);
  }

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
      rebuild();
    });
    return pill;
  }

  // ── Initialize ──
  document.addEventListener('DOMContentLoaded', init);
})();
