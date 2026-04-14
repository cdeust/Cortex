// Cortex — Wiki View (Dark Codex)
// Professional knowledge base with tree sidebar and markdown rendering
(function() {
  var container = null;
  var visible = false;
  var pages = [];
  var activePath = '';
  var searchQuery = '';
  var expandedKinds = {};
  var expandedDomains = {};

  var KIND_ORDER = ['adr', 'spec', 'lesson', 'convention', 'note', 'guide', 'domain', 'entity', 'index', 'misc'];
  var KIND_LABELS = {
    adr:        'Architecture Decisions',
    spec:       'Specifications',
    lesson:     'Lessons',
    convention: 'Conventions',
    note:       'Notes',
    guide:      'Guides',
    domain:     'Domains',
    entity:     'Entities',
    index:      'Indexes',
    misc:       'Miscellaneous',
  };
  var KIND_ICONS = {
    adr:        '',
    spec:       '',
    lesson:     '',
    convention: '',
    note:       '',
    guide:      '',
    domain:     '',
    entity:     '',
    index:      '',
    misc:       '',
  };

  var MATURITY = {
    stub:     { label: 'Stub',     cls: 'wiki-mat-stub' },
    draft:    { label: 'Draft',    cls: 'wiki-mat-draft' },
    reviewed: { label: 'Reviewed', cls: 'wiki-mat-reviewed' },
    stable:   { label: 'Stable',   cls: 'wiki-mat-stable' },
  };

  // ── Initialization ──
  function init() {
    container = document.getElementById('wiki-container');
    if (!container) return;
    JUG.on('state:activeView', function(ev) {
      if (ev.value === 'wiki') show(); else hide();
    });
  }

  function show() {
    if (!container) return;
    container.style.display = 'block';
    visible = true;
    if (pages.length === 0) fetchPages();
    else buildLayout();
  }

  function hide() {
    visible = false;
    if (container) container.style.display = 'none';
  }

  // ── Data ──
  function fetchPages() {
    container.innerHTML = '<div class="wiki-loading"><div class="wiki-loading-spinner"></div>Loading wiki index\u2026</div>';
    fetch('/api/wiki/list')
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(data) {
        pages = data.pages || [];
        buildLayout();
      })
      .catch(function(err) {
        console.warn('[cortex] Wiki list fetch error:', err.message);
        container.innerHTML = '';
        container.appendChild(buildErrorState('Wiki unavailable', 'Could not load wiki pages. The wiki might not be initialized yet.'));
      });
  }

  // ── Layout ──
  function buildLayout() {
    container.innerHTML = '';
    var layout = el('div', 'wiki-layout');

    // Sidebar
    var sidebar = el('div', 'wiki-sidebar');

    // Search
    var searchWrap = el('div', 'wiki-search-wrap');
    var searchIcon = el('span', 'wiki-search-icon');
    searchIcon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
    var search = el('input', 'wiki-search');
    search.type = 'text';
    search.placeholder = 'Search pages\u2026';
    search.value = searchQuery;
    var debounce = null;
    search.addEventListener('input', function() {
      clearTimeout(debounce);
      debounce = setTimeout(function() {
        searchQuery = search.value;
        rebuildTree();
      }, 180);
    });
    searchWrap.appendChild(searchIcon);
    searchWrap.appendChild(search);
    sidebar.appendChild(searchWrap);

    var tree = el('div', 'wiki-tree');
    tree.id = 'wiki-tree';
    sidebar.appendChild(tree);

    layout.appendChild(sidebar);

    // Content
    var main = el('div', 'wiki-main');
    main.id = 'wiki-main';
    layout.appendChild(main);

    container.appendChild(layout);
    rebuildTree();

    if (activePath) {
      loadPage(activePath);
    } else {
      showWelcome();
    }
  }

  // ── Sidebar Tree ──
  function rebuildTree() {
    var tree = document.getElementById('wiki-tree');
    if (!tree) return;
    var savedScroll = tree.scrollTop;
    tree.innerHTML = '';

    var filtered = pages;
    if (searchQuery) {
      var q = searchQuery.toLowerCase();
      filtered = pages.filter(function(p) {
        return (p.title || '').toLowerCase().indexOf(q) >= 0 ||
               (p.path || '').toLowerCase().indexOf(q) >= 0 ||
               ((p.tags || []).join(' ')).toLowerCase().indexOf(q) >= 0 ||
               (p.kind || '').toLowerCase().indexOf(q) >= 0 ||
               (p.domain || '').toLowerCase().indexOf(q) >= 0;
      });
    }

    // Group by kind
    var byKind = {};
    filtered.forEach(function(p) {
      var k = p.kind || 'misc';
      if (!byKind[k]) byKind[k] = [];
      byKind[k].push(p);
    });

    var kindKeys = KIND_ORDER.filter(function(k) { return byKind[k]; });
    Object.keys(byKind).forEach(function(k) {
      if (kindKeys.indexOf(k) < 0) kindKeys.push(k);
    });

    if (kindKeys.length === 0) {
      var emptyMsg = el('div', 'wiki-tree-empty');
      emptyMsg.textContent = searchQuery ? 'No pages match "' + searchQuery + '"' : 'No pages found';
      tree.appendChild(emptyMsg);
      return;
    }

    kindKeys.forEach(function(kind) {
      var section = el('div', 'wiki-tree-section');
      var kindPages = byKind[kind];

      // Kind header
      var kindHeader = el('div', 'wiki-tree-kind');
      var isExpanded = expandedKinds[kind] !== false;

      var arrow = el('span', 'wiki-tree-arrow');
      arrow.textContent = '\u25B6';
      if (isExpanded) arrow.classList.add('expanded');

      var label = el('span', 'wiki-tree-kind-label');
      label.textContent = KIND_LABELS[kind] || kind;

      var count = el('span', 'wiki-tree-count');
      count.textContent = kindPages.length;

      kindHeader.appendChild(arrow);
      kindHeader.appendChild(label);
      kindHeader.appendChild(count);

      var items = el('div', 'wiki-tree-items');
      if (!isExpanded) items.classList.add('collapsed');

      kindHeader.addEventListener('click', function() {
        var nowExpanded = items.classList.contains('collapsed');
        if (nowExpanded) {
          items.classList.remove('collapsed');
          arrow.classList.add('expanded');
          expandedKinds[kind] = true;
        } else {
          items.classList.add('collapsed');
          arrow.classList.remove('expanded');
          expandedKinds[kind] = false;
        }
      });

      section.appendChild(kindHeader);

      // Group by domain within kind
      var byDomain = {};
      kindPages.forEach(function(p) {
        var d = extractDomain(p) || '_root';
        if (!byDomain[d]) byDomain[d] = [];
        byDomain[d].push(p);
      });

      var domainKeys = Object.keys(byDomain).sort();
      domainKeys.forEach(function(d) {
        if (d !== '_root' && domainKeys.length > 1) {
          var domKey = kind + '/' + d;
          var domExpanded = expandedDomains[domKey] !== false;

          var domHeader = el('div', 'wiki-tree-domain');
          var domArrow = el('span', 'wiki-tree-arrow wiki-tree-arrow-sm');
          domArrow.textContent = '\u25B6';
          if (domExpanded) domArrow.classList.add('expanded');

          var domLabel = el('span', 'wiki-tree-domain-label');
          domLabel.textContent = d;

          var domCount = el('span', 'wiki-tree-count');
          domCount.textContent = byDomain[d].length;

          domHeader.appendChild(domArrow);
          domHeader.appendChild(domLabel);
          domHeader.appendChild(domCount);

          var domItems = el('div', 'wiki-tree-domain-items');
          if (!domExpanded) domItems.classList.add('collapsed');

          domHeader.addEventListener('click', function(e) {
            e.stopPropagation();
            var nowOpen = domItems.classList.contains('collapsed');
            if (nowOpen) {
              domItems.classList.remove('collapsed');
              domArrow.classList.add('expanded');
              expandedDomains[domKey] = true;
            } else {
              domItems.classList.add('collapsed');
              domArrow.classList.remove('expanded');
              expandedDomains[domKey] = false;
            }
          });

          items.appendChild(domHeader);

          byDomain[d].forEach(function(p) {
            domItems.appendChild(buildTreeItem(p));
          });
          items.appendChild(domItems);
        } else {
          byDomain[d].forEach(function(p) {
            items.appendChild(buildTreeItem(p));
          });
        }
      });

      section.appendChild(items);
      tree.appendChild(section);
    });

    // Restore scroll position after DOM rebuild
    tree.scrollTop = savedScroll;
  }

  function buildTreeItem(p) {
    var item = el('div', 'wiki-tree-item');
    item.dataset.path = p.path;
    if (p.path === activePath) {
      item.classList.add('active');
    }
    var name = el('span', 'wiki-tree-item-label');
    name.textContent = p.title || p.path;
    item.appendChild(name);
    item.addEventListener('click', function(e) {
      e.stopPropagation();
      loadPage(p.path);
    });
    return item;
  }

  // ── Welcome Panel ──
  function showWelcome() {
    var main = document.getElementById('wiki-main');
    if (!main) return;
    main.innerHTML = '';

    var wrap = el('div', 'wiki-welcome');

    var header = el('div', 'wiki-welcome-header');
    var title = el('h1', 'wiki-welcome-title');
    title.textContent = 'Knowledge Base';
    var subtitle = el('p', 'wiki-welcome-subtitle');
    subtitle.textContent = pages.length + ' pages across ' + countKinds() + ' categories';
    header.appendChild(title);
    header.appendChild(subtitle);
    wrap.appendChild(header);

    // Kind breakdown
    var kindGrid = el('div', 'wiki-welcome-kinds');
    var byKind = {};
    pages.forEach(function(p) {
      var k = p.kind || 'misc';
      byKind[k] = (byKind[k] || 0) + 1;
    });
    KIND_ORDER.forEach(function(k) {
      if (!byKind[k]) return;
      var card = el('div', 'wiki-welcome-kind-card');
      var info = el('div', 'wiki-welcome-kind-info');
      var ct = el('span', 'wiki-welcome-kind-count');
      ct.textContent = byKind[k];
      var lb = el('span', 'wiki-welcome-kind-label');
      lb.textContent = KIND_LABELS[k] || k;
      info.appendChild(ct);
      info.appendChild(lb);
      card.appendChild(info);
      kindGrid.appendChild(card);
    });
    // Catch kinds not in KIND_ORDER
    Object.keys(byKind).forEach(function(k) {
      if (KIND_ORDER.indexOf(k) < 0) {
        var card = el('div', 'wiki-welcome-kind-card');
        var info = el('div', 'wiki-welcome-kind-info');
        var ct = el('span', 'wiki-welcome-kind-count');
        ct.textContent = byKind[k];
        var lb = el('span', 'wiki-welcome-kind-label');
        lb.textContent = KIND_LABELS[k] || k;
        info.appendChild(ct);
        info.appendChild(lb);
        card.appendChild(info);
        kindGrid.appendChild(card);
      }
    });
    wrap.appendChild(kindGrid);

    // Recent pages
    var sorted = pages.slice().sort(function(a, b) {
      return (b.updated || b.created || '').localeCompare(a.updated || a.created || '');
    });

    var recentSection = el('div', 'wiki-welcome-section');
    var recentTitle = el('h2', 'wiki-welcome-section-title');
    recentTitle.textContent = 'Recently Updated';
    recentSection.appendChild(recentTitle);

    var recentList = el('div', 'wiki-welcome-list');
    sorted.slice(0, 10).forEach(function(p) {
      var row = el('div', 'wiki-welcome-list-item');
      row.addEventListener('click', function() { loadPage(p.path); });

      var rowTitle = el('span', 'wiki-welcome-list-title');
      rowTitle.textContent = p.title || p.path;

      var rowMeta = el('span', 'wiki-welcome-list-meta');
      var parts = [];
      if (p.kind) parts.push(p.kind);
      if (p.domain) parts.push(p.domain);
      if (p.updated || p.created) parts.push(p.updated || p.created);
      rowMeta.textContent = parts.join(' \u00B7 ');

      row.appendChild(rowTitle);
      row.appendChild(rowMeta);
      recentList.appendChild(row);
    });
    recentSection.appendChild(recentList);
    wrap.appendChild(recentSection);

    // Core Knowledge (stable pages)
    var stablePages = pages.filter(function(p) {
      return p.maturity === 'stable';
    });
    if (stablePages.length > 0) {
      var coreSection = el('div', 'wiki-welcome-section');
      var coreTitle = el('h2', 'wiki-welcome-section-title');
      coreTitle.textContent = 'Core Knowledge';
      var coreSub = el('p', 'wiki-welcome-section-sub');
      coreSub.textContent = 'Pages at stable maturity';
      coreSection.appendChild(coreTitle);
      coreSection.appendChild(coreSub);

      var coreList = el('div', 'wiki-welcome-list');
      stablePages.slice(0, 5).forEach(function(p) {
        var row = el('div', 'wiki-welcome-list-item wiki-welcome-list-item--stable');
        row.addEventListener('click', function() { loadPage(p.path); });
        var badge = el('span', 'wiki-mat-pill wiki-mat-stable');
        badge.textContent = 'Stable';
        var rowTitle = el('span', 'wiki-welcome-list-title');
        rowTitle.textContent = p.title || p.path;
        row.appendChild(badge);
        row.appendChild(rowTitle);
        coreList.appendChild(row);
      });
      coreSection.appendChild(coreList);
      wrap.appendChild(coreSection);
    }

    main.appendChild(wrap);
  }

  // ── Page Loading ──
  function loadPage(path) {
    activePath = path;
    // Update active state without rebuilding the entire tree
    var tree = document.getElementById('wiki-tree');
    if (tree) {
      tree.querySelectorAll('.wiki-tree-item.active').forEach(function(el) { el.classList.remove('active'); });
      tree.querySelectorAll('.wiki-tree-item').forEach(function(el) {
        if (el.dataset.path === path) el.classList.add('active');
      });
    }

    var main = document.getElementById('wiki-main');
    if (!main) return;
    main.innerHTML = '<div class="wiki-loading"><div class="wiki-loading-spinner"></div>Loading page\u2026</div>';
    main.scrollTop = 0;

    Promise.all([
      fetch('/api/wiki/page?path=' + encodeURIComponent(path)).then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }),
      // page_meta is best-effort — missing DB shouldn't block page render
      fetch('/api/wiki/page_meta?path=' + encodeURIComponent(path))
        .then(function(r) { return r.ok ? r.json() : null; })
        .catch(function() { return null; })
    ]).then(function(results) {
      var data = results[0];
      var pmeta = results[1];
      if (data.error) throw new Error(data.error);
      renderPage(main, data, pmeta);
    }).catch(function(err) {
      console.warn('[cortex] Wiki page fetch error:', err.message);
      main.innerHTML = '';
      main.appendChild(buildErrorState('Page not found', 'Could not load ' + path));
    });
  }

  // ── Page Rendering ──
  function renderPage(main, data, pmeta) {
    main.innerHTML = '';
    var meta = data.meta || {};
    var body = data.body || '';
    var dbRow = (pmeta && pmeta.db_row) || null;

    var article = el('article', 'wiki-article');

    // Page header
    var pageHeader = el('header', 'wiki-page-header');

    // Breadcrumb
    var breadcrumb = el('div', 'wiki-breadcrumb');
    var crumbs = [];
    if (meta.kind) crumbs.push(KIND_LABELS[meta.kind] || meta.kind);
    if (meta.domain) crumbs.push(meta.domain);
    breadcrumb.innerHTML = crumbs.map(function(c) { return '<span>' + esc(c) + '</span>'; }).join('<span class="wiki-breadcrumb-sep">/</span>');
    pageHeader.appendChild(breadcrumb);

    // Title
    var titleRow = el('div', 'wiki-title-row');
    var title = el('h1', 'wiki-page-title');
    title.textContent = meta.title || data.path;
    titleRow.appendChild(title);

    // Badges
    var maturity = meta.maturity || meta.status || 'draft';
    var mm = MATURITY[maturity] || MATURITY.draft;
    var mBadge = el('span', 'wiki-mat-pill ' + mm.cls);
    mBadge.textContent = mm.label;
    titleRow.appendChild(mBadge);

    if (meta.kind) {
      var kindBadge = el('span', 'wiki-kind-pill');
      kindBadge.textContent = KIND_LABELS[meta.kind] || meta.kind;
      titleRow.appendChild(kindBadge);
    }

    // Thermodynamic state pills — only when DB has the row
    if (dbRow) {
      var lifecycle = dbRow.lifecycle_state || 'active';
      var lcPill = el('span', 'wiki-lc-pill wiki-lc-' + lifecycle);
      lcPill.textContent = lifecycle;
      titleRow.appendChild(lcPill);

      if (dbRow.is_stale) {
        var stalePill = el('span', 'wiki-stale-pill');
        stalePill.textContent = 'stale';
        titleRow.appendChild(stalePill);
      }
    }

    pageHeader.appendChild(titleRow);

    // Thermodynamic heat bar
    if (dbRow && typeof dbRow.heat === 'number') {
      var heatWrap = el('div', 'wiki-heat-bar');
      var heatFill = el('div', 'wiki-heat-fill');
      heatFill.style.width = Math.max(0, Math.min(1, dbRow.heat)) * 100 + '%';
      heatWrap.appendChild(heatFill);
      var heatLabel = el('span', 'wiki-heat-label');
      heatLabel.textContent = 'heat ' + dbRow.heat.toFixed(2)
        + ' \u00B7 cited ' + (dbRow.citation_count || 0)
        + ' \u00B7 ' + (dbRow.backlink_count || 0) + ' backlinks';
      heatWrap.appendChild(heatLabel);
      pageHeader.appendChild(heatWrap);
    }

    // Metadata
    var metaBar = el('div', 'wiki-meta-bar');
    if (meta.created || meta.date) {
      metaBar.appendChild(buildMetaItem('Created', meta.created || meta.date));
    }
    if (meta.updated) {
      metaBar.appendChild(buildMetaItem('Updated', meta.updated));
    }

    var tags = meta.tags || [];
    if (tags.length > 0) {
      var tagWrap = el('div', 'wiki-tag-wrap');
      tags.forEach(function(t) {
        var tag = el('span', 'wiki-tag');
        tag.textContent = t;
        tagWrap.appendChild(tag);
      });
      metaBar.appendChild(tagWrap);
    }
    pageHeader.appendChild(metaBar);

    // Edit + Export buttons
    var actions = el('div', 'wiki-page-actions');
    var editBtn = el('button', 'wiki-edit-btn');
    editBtn.type = 'button';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', function() {
      openEditor(main, data, pmeta);
    });
    actions.appendChild(editBtn);
    ['pdf', 'tex', 'docx', 'html'].forEach(function(fmt) {
      var b = el('button', 'wiki-export-btn');
      b.type = 'button';
      b.textContent = fmt.toUpperCase();
      b.title = 'Export via Pandoc → ' + fmt;
      b.addEventListener('click', function() {
        _exportDownload(data.path, fmt, b);
      });
      actions.appendChild(b);
    });
    pageHeader.appendChild(actions);

    article.appendChild(pageHeader);

    // Body
    var bodyEl = el('div', 'wiki-body');
    bodyEl.innerHTML = renderMarkdown(body);

    // KaTeX math — renders $…$ and $$…$$ spans to real math.
    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(bodyEl, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: '$', right: '$', display: false },
            { left: '\\(', right: '\\)', display: false },
            { left: '\\[', right: '\\]', display: true }
          ],
          throwOnError: false
        });
      } catch (e) { /* KaTeX optional; swallow failures */ }
    }

    // Phase 9 — academic passes (section numbering, figure/equation
    // numbering, cross-refs, citations + bibliography). Runs async;
    // the body is visible immediately, citations appear when loaded.
    applyAcademicPasses(bodyEl, meta);

    // Wire internal wiki links
    bodyEl.querySelectorAll('.wiki-link').forEach(function(link) {
      link.addEventListener('click', function() {
        var target = link.getAttribute('data-path');
        if (target) loadPage(target);
      });
    });

    article.appendChild(bodyEl);

    // Backlinks section — rendered from page_meta
    if (pmeta && pmeta.backlinks && pmeta.backlinks.length > 0) {
      var blSec = el('section', 'wiki-backlinks');
      var blTitle = el('h2', 'wiki-backlinks-title');
      blTitle.textContent = 'Backlinks (' + pmeta.backlinks.length + ')';
      blSec.appendChild(blTitle);
      var blList = el('ul', 'wiki-backlinks-list');
      pmeta.backlinks.slice(0, 20).forEach(function(b) {
        var li = el('li', 'wiki-backlinks-item');
        var a = el('a', 'wiki-link');
        a.textContent = b.src_title || b.src_rel_path || 'Unknown';
        a.dataset.path = b.src_rel_path || '';
        if (b.src_rel_path) {
          a.addEventListener('click', function() { loadPage(b.src_rel_path); });
          a.style.cursor = 'pointer';
        }
        var kindTag = el('span', 'wiki-link-kind');
        kindTag.textContent = b.link_kind || 'see-also';
        li.appendChild(a);
        li.appendChild(kindTag);
        blList.appendChild(li);
      });
      blSec.appendChild(blList);
      article.appendChild(blSec);
    }

    // Inspector toggle — reveals draft history + memos
    if (pmeta && dbRow) {
      article.appendChild(buildInspector(dbRow, pmeta));
    }

    main.appendChild(article);
  }

  // ── Inspector (Hopper "plumb drawer") ──
  function buildInspector(dbRow, pmeta) {
    var details = el('details', 'wiki-inspector');
    var summary = el('summary', 'wiki-inspector-summary');
    summary.textContent = 'Inspect — thermodynamic state, memos, lineage';
    details.appendChild(summary);

    var grid = el('div', 'wiki-inspector-grid');

    // State column
    var stateCol = el('div', 'wiki-inspector-col');
    stateCol.appendChild(buildInspectLine('page id', dbRow.id));
    stateCol.appendChild(buildInspectLine('heat', (dbRow.heat || 0).toFixed(4)));
    stateCol.appendChild(buildInspectLine('lifecycle', dbRow.lifecycle_state));
    stateCol.appendChild(buildInspectLine('status', dbRow.status));
    stateCol.appendChild(buildInspectLine('is_stale', String(dbRow.is_stale)));
    stateCol.appendChild(buildInspectLine('citations', dbRow.citation_count));
    stateCol.appendChild(buildInspectLine('backlinks', dbRow.backlink_count));
    stateCol.appendChild(buildInspectLine('planted', dbRow.planted));
    stateCol.appendChild(buildInspectLine('tended', dbRow.tended));
    if (dbRow.archived_at) {
      stateCol.appendChild(buildInspectLine('archived_at', dbRow.archived_at));
    }
    if (dbRow.memory_id) stateCol.appendChild(buildInspectLine('memory_id', dbRow.memory_id));
    if (dbRow.concept_id) stateCol.appendChild(buildInspectLine('concept_id', dbRow.concept_id));
    grid.appendChild(stateCol);

    // Memos column — lazy load on expand
    var memosCol = el('div', 'wiki-inspector-col');
    var memoTitle = el('h4', 'wiki-inspector-heading');
    memoTitle.textContent = 'Memos';
    memosCol.appendChild(memoTitle);
    var memoBody = el('div', 'wiki-inspector-memos');
    memoBody.textContent = 'Loading\u2026';
    memosCol.appendChild(memoBody);
    grid.appendChild(memosCol);

    details.appendChild(grid);

    // Fetch memos once details is opened
    var loaded = false;
    details.addEventListener('toggle', function() {
      if (!details.open || loaded) return;
      loaded = true;
      fetch('/api/wiki/memos?subject_type=page&subject_id=' + dbRow.id + '&limit=20')
        .then(function(r) { return r.ok ? r.json() : { memos: [] }; })
        .then(function(data) {
          memoBody.innerHTML = '';
          var memos = data.memos || [];
          if (memos.length === 0) {
            memoBody.textContent = 'No memos yet.';
            return;
          }
          memos.forEach(function(m) {
            var entry = el('div', 'wiki-memo-entry');
            var dec = el('strong', 'wiki-memo-decision');
            dec.textContent = m.decision;
            var rat = el('div', 'wiki-memo-rationale');
            rat.textContent = m.rationale || '';
            var by = el('div', 'wiki-memo-author');
            by.textContent = (m.author || 'system') + ' \u00B7 ' + (m.created_at || '');
            entry.appendChild(dec);
            entry.appendChild(rat);
            entry.appendChild(by);
            memoBody.appendChild(entry);
          });
        })
        .catch(function() { memoBody.textContent = 'Failed to load memos.'; });
    });
    return details;
  }

  function buildInspectLine(label, value) {
    var row = el('div', 'wiki-inspect-row');
    var l = el('span', 'wiki-inspect-label');
    l.textContent = label;
    var v = el('span', 'wiki-inspect-val');
    v.textContent = value == null ? '—' : String(value);
    row.appendChild(l);
    row.appendChild(v);
    return row;
  }

  function buildMetaItem(label, value) {
    var item = el('div', 'wiki-meta-item');
    var l = el('span', 'wiki-meta-label');
    l.textContent = label;
    var v = el('span', 'wiki-meta-value');
    v.textContent = value || '';
    item.appendChild(l);
    item.appendChild(v);
    return item;
  }

  // ── Markdown Renderer ──
  function renderMarkdown(md) {
    if (!md) return '';
    var lines = md.split('\n');
    var html = [];
    var inCode = false;
    var codeLang = '';
    var codeLines = [];
    var inList = false;
    var listType = 'ul';
    var inTable = false;
    var tableRows = [];

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      // Fenced code blocks
      var fenceMatch = line.match(/^```(\w*)/);
      if (fenceMatch !== null) {
        if (inCode) {
          html.push('<div class="wiki-code-block"><pre><code class="lang-' + esc(codeLang) + '">' + codeLines.join('\n') + '</code></pre></div>');
          codeLines = [];
          codeLang = '';
          inCode = false;
        } else {
          closeList();
          closeTable();
          codeLang = fenceMatch[1] || '';
          inCode = true;
        }
        continue;
      }
      if (inCode) {
        codeLines.push(esc(line));
        continue;
      }

      // Detect bare JSON/code blocks — lines starting with { or [ that aren't in a fence
      if (/^\s*[\{\[]/.test(line) && !inCode) {
        closeList();
        closeTable();
        // Accumulate consecutive JSON-like lines
        var jsonLines = [];
        var braceDepth = 0;
        while (i < lines.length) {
          var jl = lines[i];
          jsonLines.push(esc(jl));
          for (var ci = 0; ci < jl.length; ci++) {
            if (jl[ci] === '{' || jl[ci] === '[') braceDepth++;
            if (jl[ci] === '}' || jl[ci] === ']') braceDepth--;
          }
          i++;
          if (braceDepth <= 0 && jsonLines.length > 1) break;
          if (/^\s*$/.test(jl) && braceDepth <= 0) break;
        }
        i--;
        html.push('<div class="wiki-code-block"><pre><code class="lang-json">' + jsonLines.join('\n') + '</code></pre></div>');
        continue;
      }

      // Blank line
      if (/^\s*$/.test(line)) {
        closeList();
        closeTable();
        continue;
      }

      // Table detection
      if (line.indexOf('|') >= 0 && line.trim().charAt(0) === '|') {
        // Is this a separator row?
        if (/^\|[\s:]*-+[\s:]*/.test(line)) {
          if (!inTable && tableRows.length > 0) {
            inTable = true;
          }
          continue;
        }
        var cells = line.split('|').slice(1);
        if (cells.length > 0 && cells[cells.length - 1].trim() === '') cells.pop();
        if (!inTable && tableRows.length === 0) {
          closeList();
        }
        tableRows.push(cells.map(function(c) { return c.trim(); }));
        if (!inTable) inTable = false; // not yet confirmed as table
        continue;
      } else if (tableRows.length > 0) {
        closeTable();
      }

      // Headings
      var hMatch = line.match(/^(#{1,4})\s+(.*)$/);
      if (hMatch) {
        closeList();
        closeTable();
        var level = hMatch[1].length;
        var id = slugify(hMatch[2]);
        html.push('<h' + level + ' id="' + id + '">' + inlineFormat(hMatch[2]) + '</h' + level + '>');
        continue;
      }

      // HR
      if (/^(-{3,}|_{3,}|\*{3,})\s*$/.test(line)) {
        closeList();
        closeTable();
        html.push('<hr>');
        continue;
      }

      // Blockquote — accumulate consecutive > lines into one block
      if (/^>\s?(.*)$/.test(line)) {
        closeList();
        closeTable();
        var bqLines = [];
        while (i < lines.length && /^>\s?(.*)$/.test(lines[i])) {
          bqLines.push(lines[i].replace(/^>\s?/, ''));
          i++;
        }
        i--; // back up since the for loop will increment
        html.push('<blockquote>' + bqLines.map(inlineFormat).join('<br>') + '</blockquote>');
        continue;
      }

      // Unordered list
      var ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
      if (ulMatch) {
        closeTable();
        if (!inList || listType !== 'ul') {
          closeList();
          html.push('<ul>');
          inList = true;
          listType = 'ul';
        }
        html.push('<li>' + inlineFormat(ulMatch[2]) + '</li>');
        continue;
      }

      // Ordered list
      var olMatch = line.match(/^(\s*)\d+[.)]\s+(.*)$/);
      if (olMatch) {
        closeTable();
        if (!inList || listType !== 'ol') {
          closeList();
          html.push('<ol>');
          inList = true;
          listType = 'ol';
        }
        html.push('<li>' + inlineFormat(olMatch[2]) + '</li>');
        continue;
      }

      // Paragraph
      closeList();
      closeTable();
      html.push('<p>' + inlineFormat(line) + '</p>');
    }

    if (inCode) {
      html.push('<div class="wiki-code-block"><pre><code>' + codeLines.join('\n') + '</code></pre></div>');
    }
    closeList();
    closeTable();

    return html.join('\n');

    function closeList() {
      if (inList) {
        html.push('</' + listType + '>');
        inList = false;
      }
    }

    function closeTable() {
      if (tableRows.length > 0) {
        var t = '<table><thead><tr>';
        var headerRow = tableRows[0];
        headerRow.forEach(function(c) {
          t += '<th>' + inlineFormat(c) + '</th>';
        });
        t += '</tr></thead>';
        if (tableRows.length > 1) {
          t += '<tbody>';
          for (var r = 1; r < tableRows.length; r++) {
            t += '<tr>';
            tableRows[r].forEach(function(c) {
              t += '<td>' + inlineFormat(c) + '</td>';
            });
            t += '</tr>';
          }
          t += '</tbody>';
        }
        t += '</table>';
        html.push(t);
        tableRows = [];
        inTable = false;
      }
    }
  }

  function inlineFormat(text) {
    var s = esc(text);

    // Code spans
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold + italic
    s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
    // Bold
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    // Italic
    s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    s = s.replace(/_([^_]+)_/g, '<em>$1</em>');

    // Images ![alt](url)
    s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" class="wiki-img" loading="lazy">');

    // Links [text](url)
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, text, url) {
      if (url.indexOf('http') !== 0 && url.indexOf('//') !== 0) {
        return '<span class="wiki-link" data-path="' + url + '">' + text + '</span>';
      }
      return '<a href="' + url + '" target="_blank" rel="noopener">' + text + '</a>';
    });

    return s;
  }

  // ── Helpers ──
  function buildErrorState(title, subtitle) {
    var wrap = el('div', 'wiki-error-state');
    var ic = el('div', 'wiki-error-icon');
    ic.innerHTML = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
    var t = el('div', 'wiki-error-title');
    t.textContent = title;
    var s = el('div', 'wiki-error-sub');
    s.textContent = subtitle;
    wrap.appendChild(ic);
    wrap.appendChild(t);
    wrap.appendChild(s);
    return wrap;
  }

  function extractDomain(page) {
    if (page.domain) return page.domain;
    var parts = (page.path || '').split('/').filter(Boolean);
    if (parts.length >= 3) return parts[1];
    return '_general';
  }

  function countKinds() {
    var kinds = {};
    pages.forEach(function(p) { kinds[p.kind || 'misc'] = true; });
    return Object.keys(kinds).length;
  }

  function slugify(text) {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }

  function esc(s) {
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function el(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  // ── Export download (Phase 10) ──
  //
  // Fetches /api/wiki/export and decides between saving the blob (on
  // success — binary Content-Type) and surfacing the error message
  // (when the server returned JSON). Using fetch avoids the old
  // <a download> trap where a JSON error response got silently saved
  // as "page.pdf" with 2 KB of error text inside.

  async function _exportDownload(relPath, fmt, btn) {
    if (btn) { btn.disabled = true; btn.textContent = fmt.toUpperCase() + '\u2026'; }
    try {
      var url = '/api/wiki/export?path=' + encodeURIComponent(relPath)
        + '&format=' + fmt;
      var resp = await fetch(url);
      var contentType = resp.headers.get('Content-Type') || '';
      if (contentType.indexOf('application/json') === 0) {
        var err = await resp.json();
        var msg = err.error || 'export failed';
        if (err.stderr) msg += '\n\nstderr:\n' + err.stderr;
        alert('Export failed (' + fmt + '):\n\n' + msg);
        return;
      }
      if (!resp.ok) {
        alert('Export failed (' + fmt + '): HTTP ' + resp.status);
        return;
      }
      var blob = await resp.blob();
      var dispo = resp.headers.get('Content-Disposition') || '';
      var m = dispo.match(/filename="([^"]+)"/);
      var filename = m ? m[1]
        : (relPath.split('/').pop() || 'page').replace(/\.md$/, '') + '.' + fmt;
      var link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      setTimeout(function() {
        URL.revokeObjectURL(link.href);
        link.remove();
      }, 200);
    } catch (err) {
      alert('Export failed (' + fmt + '): ' + (err.message || err));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = fmt.toUpperCase(); }
    }
  }

  // ── Academic rendering layer (Phase 9) ──
  //
  // Three post-render passes over the already-rendered body:
  //   1. Number headings (section numbers)         — 9.5
  //   2. Number figures + equations + tables       — 9.2
  //   3. Resolve @label cross-refs                 — 9.3
  //   4. Resolve [@citekey] citations + bibliography — 9.1
  //
  // Citation.js is lazy-loaded the first time we see a cite key on a
  // page. Bibliography files live in wiki/_bibliography/*.bib; which
  // file(s) a page uses is declared in its frontmatter
  // (bibliography: [_bibliography/foo.bib]) or, absent that, all
  // files in _bibliography/ are available.

  var _bibCache = null;         // combined cite-key → entry map
  var _bibLoadPromise = null;
  var _citationJsPromise = null;

  function _loadCitationJs() {
    if (_citationJsPromise) return _citationJsPromise;
    _citationJsPromise = import('https://esm.sh/@citation-js/core@0.7').then(function(core) {
      return Promise.all([
        import('https://esm.sh/@citation-js/plugin-bibtex@0.7'),
        import('https://esm.sh/@citation-js/plugin-csl@0.7')
      ]).then(function() { return core; });
    });
    return _citationJsPromise;
  }

  async function _ensureBibliography(meta) {
    if (_bibCache) return _bibCache;
    if (_bibLoadPromise) return _bibLoadPromise;
    _bibLoadPromise = (async function() {
      var explicit = (meta && meta.bibliography) || null;
      var list;
      try {
        if (explicit && Array.isArray(explicit)) {
          list = explicit;
        } else {
          var resp = await fetch('/api/wiki/bibliography');
          var j = await resp.json();
          list = (j.files || []).map(function(f) { return f.path; });
        }
      } catch (e) { return {}; }
      if (!list || list.length === 0) return {};

      var core = await _loadCitationJs();
      var Cite = core.Cite;
      var byKey = {};
      await Promise.all(list.map(async function(path) {
        try {
          var r = await fetch('/api/wiki/bibliography/read?path=' + encodeURIComponent(path));
          var data = await r.json();
          if (!data.content) return;
          var cite = new Cite(data.content);
          cite.data.forEach(function(entry) {
            if (entry.id) byKey[entry.id] = entry;
          });
        } catch (e) { /* skip bad file */ }
      }));
      _bibCache = byKey;
      return byKey;
    })();
    return _bibLoadPromise;
  }

  function _formatInlineCite(entry) {
    // Minimal "Author (Year)" format; Citation.js can do full CSL
    // rendering in the bibliography pass. This is just the inline
    // marker that sits where the `[@key]` was typed.
    if (!entry) return '[?]';
    var first = (entry.author && entry.author[0]) || {};
    var surname = first.family || first.literal || '?';
    var year = (entry.issued && entry.issued['date-parts'] && entry.issued['date-parts'][0] && entry.issued['date-parts'][0][0])
      || entry.year || 'n.d.';
    return surname + ' ' + year;
  }

  async function _formatBibliographyHtml(usedKeys, byKey) {
    if (!usedKeys || usedKeys.size === 0) return '';
    var core = await _loadCitationJs();
    var Cite = core.Cite;
    var entries = [];
    usedKeys.forEach(function(k) {
      if (byKey[k]) entries.push(byKey[k]);
    });
    if (entries.length === 0) return '';
    try {
      var cite = new Cite(entries);
      var html = cite.format('bibliography', { format: 'html', template: 'apa', lang: 'en-US' });
      return '<h2 id="references">References</h2>' + html;
    } catch (e) {
      // Fallback: plain list of raw ids
      return '<h2 id="references">References</h2><ul>' +
        Array.from(usedKeys).map(function(k) { return '<li>' + esc(k) + '</li>'; }).join('') +
        '</ul>';
    }
  }

  function _numberHeadings(root, enabled) {
    if (!enabled) return;
    var counters = [0, 0, 0, 0, 0, 0];
    root.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(function(h) {
      if (h.id === 'references') return; // don't number the bibliography
      var level = parseInt(h.tagName.slice(1), 10);
      counters[level - 1]++;
      for (var i = level; i < 6; i++) counters[i] = 0;
      var num = counters.slice(0, level).filter(function(n) { return n > 0; }).join('.');
      var span = document.createElement('span');
      span.className = 'wiki-section-num';
      span.textContent = num + ' ';
      h.insertBefore(span, h.firstChild);
    });
  }

  function _numberLabeled(root, selector, prefix, labelMap) {
    var i = 0;
    root.querySelectorAll(selector).forEach(function(node) {
      i++;
      var label = node.getAttribute('data-label') || null;
      node.setAttribute('data-num', String(i));
      var caption = node.querySelector('figcaption, .wiki-caption');
      if (caption) {
        var pfx = document.createElement('span');
        pfx.className = 'wiki-caption-prefix';
        pfx.textContent = prefix + ' ' + i + ': ';
        caption.insertBefore(pfx, caption.firstChild);
      }
      if (label) labelMap[label] = { prefix: prefix, num: i };
    });
  }

  function _resolveCrossRefs(root, labelMap) {
    // Replaces `{@fig:foo}` / `{@eq:bar}` / `{@sec:intro}` tokens that
    // our markdown renderer has dropped into the HTML as literal
    // text. We used `{@…}` to avoid collision with the `[@citekey]`
    // citation syntax.
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    var n;
    while ((n = walker.nextNode())) nodes.push(n);
    nodes.forEach(function(text) {
      if (text.nodeValue.indexOf('{@') < 0) return;
      var frag = document.createDocumentFragment();
      var re = /\{@([a-zA-Z0-9:_-]+)\}/g;
      var remaining = text.nodeValue;
      var lastIdx = 0;
      var m;
      while ((m = re.exec(text.nodeValue)) !== null) {
        if (m.index > lastIdx) {
          frag.appendChild(document.createTextNode(
            text.nodeValue.slice(lastIdx, m.index)
          ));
        }
        var key = m[1];
        var ref = labelMap[key];
        var out = document.createElement('a');
        out.className = 'wiki-xref';
        out.href = '#' + key;
        out.textContent = ref ? (ref.prefix + ' ' + ref.num) : ('?' + key);
        frag.appendChild(out);
        lastIdx = m.index + m[0].length;
      }
      if (lastIdx < text.nodeValue.length) {
        frag.appendChild(document.createTextNode(text.nodeValue.slice(lastIdx)));
      }
      remaining = frag;
      text.parentNode.replaceChild(frag, text);
    });
  }

  async function _resolveCitations(root, byKey, usedKeys) {
    // Replace `[@key]` and `[@k1; @k2]` tokens with formatted inline
    // citations.
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    var n;
    while ((n = walker.nextNode())) nodes.push(n);
    var re = /\[@([a-zA-Z0-9_-]+(?:\s*;\s*@[a-zA-Z0-9_-]+)*)\]/g;
    nodes.forEach(function(text) {
      if (text.nodeValue.indexOf('[@') < 0) return;
      var frag = document.createDocumentFragment();
      var lastIdx = 0;
      var m;
      while ((m = re.exec(text.nodeValue)) !== null) {
        if (m.index > lastIdx) {
          frag.appendChild(document.createTextNode(text.nodeValue.slice(lastIdx, m.index)));
        }
        var keys = m[1].split(';').map(function(s) { return s.trim().replace(/^@/, ''); });
        var parts = keys.map(function(k) {
          usedKeys.add(k);
          return _formatInlineCite(byKey[k]);
        });
        var cite = document.createElement('a');
        cite.className = 'wiki-cite';
        cite.href = '#references';
        cite.textContent = '(' + parts.join('; ') + ')';
        frag.appendChild(cite);
        lastIdx = m.index + m[0].length;
      }
      if (lastIdx < text.nodeValue.length) {
        frag.appendChild(document.createTextNode(text.nodeValue.slice(lastIdx)));
      }
      text.parentNode.replaceChild(frag, text);
    });
  }

  async function applyAcademicPasses(bodyEl, meta) {
    if (!bodyEl) return;
    var sectionNums = meta && meta.section_numbering === true;

    // 1. Section numbers
    _numberHeadings(bodyEl, sectionNums);

    // 2. Figure / equation / table numbering
    var labelMap = {};
    _numberLabeled(bodyEl, 'figure', 'Figure', labelMap);
    _numberLabeled(bodyEl, '.katex-display', 'Equation', labelMap);
    _numberLabeled(bodyEl, 'table', 'Table', labelMap);

    // 3. Cross-references
    _resolveCrossRefs(bodyEl, labelMap);

    // 4. Citations (async — loads Citation.js + bibliography)
    var hasCite = /\[@[a-zA-Z0-9_-]/.test(bodyEl.textContent);
    if (hasCite) {
      try {
        var byKey = await _ensureBibliography(meta);
        var usedKeys = new Set();
        await _resolveCitations(bodyEl, byKey, usedKeys);
        var refsHtml = await _formatBibliographyHtml(usedKeys, byKey);
        if (refsHtml) {
          var refs = document.createElement('section');
          refs.className = 'wiki-bibliography';
          refs.innerHTML = refsHtml;
          bodyEl.appendChild(refs);
        }
      } catch (e) { console.warn('[cortex] citation pass failed:', e); }
    }
  }

  // ── Inline editor (Phase 8.3) ──
  //
  // Lazy-loads CodeMirror 6 from esm.sh the first time the user clicks
  // Edit. Keeps the initial wiki page load light (~200KB CM6 bundle
  // isn't paid until needed). Split-pane: left = source, right = live
  // markdown preview via the existing renderMarkdown + KaTeX.

  var _cmModulesPromise = null;
  function _loadCodeMirror() {
    if (_cmModulesPromise) return _cmModulesPromise;
    _cmModulesPromise = (async function() {
      // Core + markdown mode + theme — via esm.sh (zero build, cached)
      var urls = {
        view: 'https://esm.sh/@codemirror/view@6',
        state: 'https://esm.sh/@codemirror/state@6',
        commands: 'https://esm.sh/@codemirror/commands@6',
        lang: 'https://esm.sh/@codemirror/lang-markdown@6',
        oneDark: 'https://esm.sh/@codemirror/theme-one-dark@6',
        autoClose: 'https://esm.sh/@codemirror/autocomplete@6'
      };
      var mods = {};
      await Promise.all(Object.keys(urls).map(async function(k) {
        mods[k] = await import(urls[k]);
      }));
      return mods;
    })();
    return _cmModulesPromise;
  }

  async function openEditor(main, data, pmeta) {
    var original = main.innerHTML;
    main.innerHTML = '<div class="wiki-loading"><div class="wiki-loading-spinner"></div>Loading editor\u2026</div>';

    var mods;
    try {
      mods = await _loadCodeMirror();
    } catch (err) {
      console.warn('[cortex] CodeMirror load failed', err);
      main.innerHTML = original;
      alert('Editor failed to load. See console for details.');
      return;
    }

    main.innerHTML = '';
    var wrap = el('div', 'wiki-editor-wrap');

    // Toolbar: title, save, cancel
    var toolbar = el('div', 'wiki-editor-toolbar');
    var title = el('h2', 'wiki-editor-title');
    title.textContent = (data.meta && data.meta.title) || data.path;
    var spacer = el('span', 'wiki-editor-spacer');
    var cancelBtn = el('button', 'wiki-editor-btn wiki-editor-cancel');
    cancelBtn.type = 'button';
    cancelBtn.textContent = 'Cancel';
    var saveBtn = el('button', 'wiki-editor-btn wiki-editor-save');
    saveBtn.type = 'button';
    saveBtn.textContent = 'Save';
    toolbar.appendChild(title);
    toolbar.appendChild(spacer);
    toolbar.appendChild(cancelBtn);
    toolbar.appendChild(saveBtn);
    wrap.appendChild(toolbar);

    // Split pane: left editor, right preview
    var split = el('div', 'wiki-editor-split');
    var leftCol = el('div', 'wiki-editor-pane wiki-editor-source');
    var rightCol = el('div', 'wiki-editor-pane wiki-editor-preview');
    var previewBody = el('div', 'wiki-body wiki-preview-body');
    rightCol.appendChild(previewBody);
    split.appendChild(leftCol);
    split.appendChild(rightCol);
    wrap.appendChild(split);
    main.appendChild(wrap);

    // Reconstruct full source (frontmatter + body) so the user can
    // edit metadata inline. If server gave us both, merge them.
    var fullSource = _reconstructSource(data.meta || {}, data.body || '');

    // Preview renderer with KaTeX
    function rerender(src) {
      var parts = _splitFrontmatter(src);
      previewBody.innerHTML = renderMarkdown(parts.body);
      if (window.renderMathInElement) {
        try {
          window.renderMathInElement(previewBody, {
            delimiters: [
              { left: '$$', right: '$$', display: true },
              { left: '$',  right: '$',  display: false },
              { left: '\\(', right: '\\)', display: false },
              { left: '\\[', right: '\\]', display: true }
            ],
            throwOnError: false
          });
        } catch (e) { /* noop */ }
      }
    }

    // Build CM6 state + view
    var EditorState = mods.state.EditorState;
    var EditorView  = mods.view.EditorView;
    var keymap      = mods.view.keymap;
    var basicSetup  = mods.commands.history ? [mods.commands.history()] : [];
    var markdownLang = mods.lang.markdown();
    var oneDark = mods.oneDark.oneDark;
    var updateListener = EditorView.updateListener.of(function(upd) {
      if (upd.docChanged) rerender(upd.state.doc.toString());
    });
    var cm = new EditorView({
      state: EditorState.create({
        doc: fullSource,
        extensions: [
          markdownLang,
          oneDark,
          updateListener,
          EditorView.lineWrapping
        ]
      }),
      parent: leftCol
    });
    rerender(fullSource);

    cancelBtn.addEventListener('click', function() {
      if (!confirm('Discard changes?')) return;
      loadPage(data.path);
    });

    saveBtn.addEventListener('click', async function() {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving\u2026';
      var newSource = cm.state.doc.toString();
      try {
        var resp = await fetch('/api/wiki/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rel_path: data.path, body: newSource })
        });
        var result = await resp.json();
        if (!resp.ok || result.error) {
          throw new Error(result.error || 'save failed');
        }
        saveBtn.textContent = 'Saved';
        setTimeout(function() { loadPage(data.path); }, 300);
      } catch (err) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
        alert('Save failed: ' + err.message);
      }
    });
  }

  function _splitFrontmatter(src) {
    // Returns {frontmatter: str|'', body: str}. Recognises the standard
    // `---\n…\n---\n` envelope; preserves everything else as body.
    if (!src.startsWith('---\n') && !src.startsWith('---\r\n')) {
      return { frontmatter: '', body: src };
    }
    var rest = src.slice(4);
    var endRe = /(^|\n)---\s*(\n|$)/;
    var m = endRe.exec(rest);
    if (!m) return { frontmatter: '', body: src };
    var fm = rest.slice(0, m.index);
    var body = rest.slice(m.index + m[0].length);
    return { frontmatter: fm, body: body };
  }

  function _reconstructSource(meta, body) {
    // Server gives us parsed frontmatter + body separately; rebuild the
    // full source for editing. Users can edit frontmatter directly.
    if (!meta || Object.keys(meta).length === 0) return body || '';
    var lines = ['---'];
    Object.keys(meta).forEach(function(k) {
      var v = meta[k];
      if (v === null || v === undefined || v === '') return;
      if (Array.isArray(v)) {
        lines.push(k + ': [' + v.map(function(x) { return String(x); }).join(', ') + ']');
      } else {
        lines.push(k + ': ' + String(v));
      }
    });
    lines.push('---', '', body || '');
    return lines.join('\n');
  }

  // ── Init ──
  document.addEventListener('DOMContentLoaded', init);
})();
