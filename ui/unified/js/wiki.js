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

    // \u2500\u2500 Project-first grouping: Domain \u2192 Kind \u2192 Pages \u2500\u2500
    // The user opens the wiki and sees every project as the top axis;
    // inside each project, kinds (architecture/services/api/adr/lesson\u2026)
    // expand to the pages. This replaces the older kind-first layout
    // which buried project structure under taxonomy.
    var byDomain = {};
    filtered.forEach(function(p) {
      var d = extractDomain(p) || '_general';
      if (!byDomain[d]) byDomain[d] = [];
      byDomain[d].push(p);
    });

    var domainKeys = Object.keys(byDomain).sort(function(a, b) {
      // Push catch-all buckets to the bottom so real projects surface first.
      var aLow = (a === '_general' || /^\d{4}$/.test(a)) ? 1 : 0;
      var bLow = (b === '_general' || /^\d{4}$/.test(b)) ? 1 : 0;
      if (aLow !== bLow) return aLow - bLow;
      return a.localeCompare(b);
    });

    if (domainKeys.length === 0) {
      var emptyMsg = el('div', 'wiki-tree-empty');
      emptyMsg.textContent = searchQuery ? 'No pages match "' + searchQuery + '"' : 'No pages found';
      tree.appendChild(emptyMsg);
      return;
    }

    domainKeys.forEach(function(domain) {
      var section = el('div', 'wiki-tree-section');
      var domainPages = byDomain[domain];

      // Domain header \u2014 the primary expander.
      var domHeader = el('div', 'wiki-tree-kind');
      var domExpanded = expandedDomains[domain] !== false;

      var domArrow = el('span', 'wiki-tree-arrow');
      domArrow.textContent = '\u25B6';
      if (domExpanded) domArrow.classList.add('expanded');

      var domLabel = el('span', 'wiki-tree-kind-label');
      domLabel.textContent = domain;

      var domCount = el('span', 'wiki-tree-count');
      domCount.textContent = domainPages.length;

      domHeader.appendChild(domArrow);
      domHeader.appendChild(domLabel);
      domHeader.appendChild(domCount);

      var kindContainer = el('div', 'wiki-tree-items');
      if (!domExpanded) kindContainer.classList.add('collapsed');

      domHeader.addEventListener('click', function() {
        var nowExpanded = kindContainer.classList.contains('collapsed');
        if (nowExpanded) {
          kindContainer.classList.remove('collapsed');
          domArrow.classList.add('expanded');
          expandedDomains[domain] = true;
        } else {
          kindContainer.classList.add('collapsed');
          domArrow.classList.remove('expanded');
          expandedDomains[domain] = false;
        }
      });

      section.appendChild(domHeader);

      // Inside the domain, group by kind.
      var byKindInDomain = {};
      domainPages.forEach(function(p) {
        var k = p.kind || 'misc';
        if (!byKindInDomain[k]) byKindInDomain[k] = [];
        byKindInDomain[k].push(p);
      });

      var kindsInOrder = KIND_ORDER.filter(function(k) { return byKindInDomain[k]; });
      Object.keys(byKindInDomain).forEach(function(k) {
        if (kindsInOrder.indexOf(k) < 0) kindsInOrder.push(k);
      });

      kindsInOrder.forEach(function(kind) {
        var kindPages = byKindInDomain[kind];
        var kindKey = domain + '/' + kind;
        var kindExpanded = expandedKinds[kindKey] !== false;

        var kindHeader = el('div', 'wiki-tree-domain');
        var kindArrow = el('span', 'wiki-tree-arrow wiki-tree-arrow-sm');
        kindArrow.textContent = '\u25B6';
        if (kindExpanded) kindArrow.classList.add('expanded');

        var kindLabel = el('span', 'wiki-tree-domain-label');
        kindLabel.textContent = KIND_LABELS[kind] || kind;

        var kindCount = el('span', 'wiki-tree-count');
        kindCount.textContent = kindPages.length;

        kindHeader.appendChild(kindArrow);
        kindHeader.appendChild(kindLabel);
        kindHeader.appendChild(kindCount);

        var kindItems = el('div', 'wiki-tree-domain-items');
        if (!kindExpanded) kindItems.classList.add('collapsed');

        kindHeader.addEventListener('click', function(e) {
          e.stopPropagation();
          var nowOpen = kindItems.classList.contains('collapsed');
          if (nowOpen) {
            kindItems.classList.remove('collapsed');
            kindArrow.classList.add('expanded');
            expandedKinds[kindKey] = true;
          } else {
            kindItems.classList.add('collapsed');
            kindArrow.classList.remove('expanded');
            expandedKinds[kindKey] = false;
          }
        });

        kindContainer.appendChild(kindHeader);
        _renderCollapsedList(kindPages).forEach(function(row) {
          kindItems.appendChild(buildTreeItem(row));
        });
        kindContainer.appendChild(kindItems);
      });

      section.appendChild(kindContainer);
      tree.appendChild(section);
    });

    // Restore scroll position after DOM rebuild
    tree.scrollTop = savedScroll;
  }

  // Collapse pages that share an identical (title) within the same
  // (kind, domain) bucket into a single tree entry with a count
  // badge. The tree row exposes all underlying paths so the user can
  // still pick an individual copy if they want — clicking the
  // collapsed row opens the newest (largest memory_id prefix) by
  // default, and Alt-click opens a disambiguation popover.
  function _renderCollapsedList(pages) {
    var groups = {};
    var order = [];
    pages.forEach(function(p) {
      var key = (p.title || p.path || '').trim().toLowerCase();
      if (!groups[key]) {
        groups[key] = { title: p.title || p.path, pages: [] };
        order.push(key);
      }
      groups[key].pages.push(p);
    });
    return order.map(function(k) {
      var g = groups[k];
      // Newest first (biggest memory_id prefix in filename)
      g.pages.sort(function(a, b) {
        var na = _idFromPath(a.path);
        var nb = _idFromPath(b.path);
        return nb - na;
      });
      return {
        title: g.title,
        path: g.pages[0].path,
        duplicates: g.pages.length,
        siblings: g.pages
      };
    });
  }

  function _idFromPath(p) {
    var m = String(p).match(/\/(\d+)-/);
    return m ? parseInt(m[1], 10) : 0;
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
    if (p.duplicates && p.duplicates > 1) {
      var badge = el('span', 'wiki-tree-dup-badge');
      badge.textContent = '\u00D7' + p.duplicates;
      badge.title = p.duplicates + ' pages share this title — Alt-click to pick';
      item.appendChild(badge);
      item._siblings = p.siblings;
    }
    item.addEventListener('click', function(e) {
      e.stopPropagation();
      if (e.altKey && item._siblings) {
        _openSiblingPicker(item, p);
        return;
      }
      loadPage(p.path);
    });
    return item;
  }

  function _openSiblingPicker(anchor, group) {
    var existing = document.querySelector('.wiki-sibling-picker');
    if (existing) existing.remove();
    var picker = el('div', 'wiki-sibling-picker');
    group.siblings.forEach(function(s) {
      var row = el('div', 'wiki-sibling-row');
      row.textContent = s.path;
      row.addEventListener('click', function(e) {
        e.stopPropagation();
        loadPage(s.path);
        picker.remove();
      });
      picker.appendChild(row);
    });
    document.body.appendChild(picker);
    var r = anchor.getBoundingClientRect();
    picker.style.left = r.right + 'px';
    picker.style.top = r.top + 'px';
    setTimeout(function() {
      document.addEventListener('click', function h() {
        picker.remove();
        document.removeEventListener('click', h);
      });
    }, 0);
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

    // ── Projects landing grid ──
    // The primary organizing axis: every project the user has, what's
    // documented under it, what's still missing. Fetched from
    // /api/wiki/projects so coverage stats stay in sync with the
    // server-side audit (wiki_coverage). Renders as a card grid.
    var projectsSection = el('div', 'wiki-welcome-section');
    var projectsTitle = el('h2', 'wiki-welcome-section-title');
    projectsTitle.textContent = 'Projects';
    var projectsSub = el('p', 'wiki-welcome-section-sub');
    projectsSub.textContent = 'Every project with its documented coverage. Click to drill in.';
    projectsSection.appendChild(projectsTitle);
    projectsSection.appendChild(projectsSub);

    var projectsGrid = el('div', 'wiki-welcome-kinds');
    projectsGrid.id = 'wiki-projects-grid';
    var projectsLoading = el('div', 'wiki-welcome-kind-card');
    projectsLoading.textContent = 'Loading projects…';
    projectsGrid.appendChild(projectsLoading);
    projectsSection.appendChild(projectsGrid);
    wrap.appendChild(projectsSection);

    // Fire and forget — the grid populates async without blocking the
    // rest of the welcome render.
    fetch('/api/wiki/projects')
      .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)); })
      .then(function(data) {
        var grid = document.getElementById('wiki-projects-grid');
        if (!grid) return;
        grid.innerHTML = '';
        var projects = (data && data.projects) || [];
        // Sort: real projects (with scope coverage data) first, by
        // scope ratio ascending (most-uncovered surface to the top so
        // the user sees what needs work). Buckets with null coverage
        // (e.g. `_general`, year buckets) trail.
        projects.sort(function(a, b) {
          var ar = a.scope_coverage_ratio;
          var br = b.scope_coverage_ratio;
          if (ar === null && br === null) return a.domain.localeCompare(b.domain);
          if (ar === null) return 1;
          if (br === null) return -1;
          return ar - br;
        });
        projects.forEach(function(p) {
          var card = el('div', 'wiki-welcome-kind-card');
          card.style.cursor = 'pointer';
          card.addEventListener('click', function() {
            searchQuery = p.domain;
            var search = document.querySelector('.wiki-search');
            if (search) search.value = p.domain;
            rebuildTree();
          });
          var info = el('div', 'wiki-welcome-kind-info');
          var ct = el('span', 'wiki-welcome-kind-count');
          ct.textContent = p.page_total;
          var lb = el('span', 'wiki-welcome-kind-label');
          lb.textContent = p.domain;
          info.appendChild(ct);
          info.appendChild(lb);
          card.appendChild(info);
          // Coverage badges line — scope ratio + file ratio + missing scopes.
          var badges = el('div', 'wiki-welcome-kind-badges');
          badges.style.fontSize = '11px';
          badges.style.marginTop = '6px';
          badges.style.opacity = '0.8';
          var lines = [];
          if (p.scope_coverage_ratio !== null && p.scope_coverage_ratio !== undefined) {
            lines.push('scope: ' + Math.round(p.scope_coverage_ratio * 100) + '%');
          }
          if (p.file_coverage_ratio !== null && p.file_coverage_ratio !== undefined) {
            lines.push('files: ' + Math.round(p.file_coverage_ratio * 100) + '% (' + p.file_covered + '/' + p.file_total + ')');
          }
          if (p.missing_scopes && p.missing_scopes.length) {
            lines.push('missing: ' + p.missing_scopes.slice(0, 3).join(', ') + (p.missing_scopes.length > 3 ? '…' : ''));
          }
          badges.textContent = lines.join(' • ');
          card.appendChild(badges);
          grid.appendChild(card);
        });
        if (!projects.length) {
          var empty = el('div', 'wiki-welcome-kind-card');
          empty.textContent = 'No projects detected yet.';
          grid.appendChild(empty);
        }
      })
      .catch(function(err) {
        console.warn('[cortex] wiki projects fetch error:', err.message);
        var grid = document.getElementById('wiki-projects-grid');
        if (grid) {
          grid.innerHTML = '';
          var card = el('div', 'wiki-welcome-kind-card');
          card.textContent = 'Could not load project index.';
          grid.appendChild(card);
        }
      });

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

    // ── Curation gap banner ──
    // For file-doc pages produced by the skeleton generator, the
    // frontmatter carries ``curation_gaps: [...]`` — the canonical
    // sections that still need a real explanation. Render a visible
    // banner above the body so the reader sees what's not yet
    // documented and the in-session LLM has a concrete queue. Deletion
    // is not curation; visibility is.
    var gaps = meta.curation_gaps;
    if (Array.isArray(gaps) && gaps.length > 0) {
      var totalSections = 14;  // matches FILE_DOC_SECTIONS (incl. sequence-diagram + flow-diagram + parameters + request/response-example)
      var coveredCount = Math.max(0, totalSections - gaps.length);
      var pct = Math.round(100 * coveredCount / totalSections);
      var banner = el('aside', 'wiki-curation-banner');
      banner.style.cssText = (
        'border:1px solid #b58900;background:rgba(181,137,0,0.08);' +
        'padding:14px 18px;border-radius:6px;margin:14px 0 18px;' +
        'font-size:14px;line-height:1.55;'
      );
      var summary = el('div', 'wiki-curation-summary');
      summary.style.cssText = 'margin-bottom:8px;color:#b58900;font-weight:600;';
      summary.textContent =
        '⚠ Page ' + pct + '% curated — ' + gaps.length + ' of ' +
        totalSections + ' canonical sections are still missing or thin.';
      banner.appendChild(summary);
      var listIntro = el('div');
      listIntro.style.cssText = 'opacity:0.85;margin-bottom:6px;';
      listIntro.textContent =
        'The autonomous re-author loop will fill these; a human author can also write them now:';
      banner.appendChild(listIntro);
      var ul = el('ul');
      ul.style.cssText = 'margin:0;padding-left:22px;';
      var gapLabels = {
        purpose:            'Purpose — what this file is responsible for',
        'public-api':       'Public API — semantics of each exported symbol',
        dependencies:       'Dependencies — why each import is here',
        callers:            'Callers — which files in the project use this one',
        behaviour:          'How it works — entry point + main flow',
        invariants:         'Invariants — what must always be true',
        'failure-modes':    'What can go wrong — failure modes + symptoms',
        tests:              'Tests — which test files exercise this',
        'see-also':         'See also — cross-links to architecture / services / api',
        'sequence-diagram': 'Sequence diagram — mermaid sequenceDiagram of caller → this file → callees',
        'flow-diagram':     'Flow diagram — mermaid flowchart/stateDiagram of branching, lifecycle, decision tree',
        parameters:         'Parameters — exhaustive table (name, type, required, default, description)',
        'request-example':  'Request example — curl + headers / JSON-RPC envelope / call site',
        'response-example': 'Response example — every field annotated, success + error shapes',
      };
      gaps.forEach(function(g) {
        var li = el('li');
        li.textContent = gapLabels[g] || g;
        ul.appendChild(li);
      });
      banner.appendChild(ul);
      article.appendChild(banner);
    }

    // Body
    var bodyEl = el('div', 'wiki-body');
    bodyEl.innerHTML = renderMarkdown(body);

    // Mermaid diagrams — renders ```mermaid blocks to SVG. Lazy-loads
    // mermaid.js from esm.sh on first encounter so pages without
    // diagrams pay no cost.
    if (bodyEl.querySelector('.wiki-mermaid')) {
      _ensureMermaid().then(function(mermaid) {
        if (!mermaid) return;
        try {
          var p = mermaid.run({ querySelector: '.wiki-mermaid', suppressErrors: false });
          // After mermaid finishes rendering, attach a lens button to
          // every diagram so a reader can pop it into a full-viewport
          // overlay with zoom + pan controls. ``mermaid.run`` returns
          // a Promise in v10+; attaching the buttons after it resolves
          // guarantees the SVGs exist.
          if (p && typeof p.then === 'function') {
            p.then(function() { _attachMermaidLenses(bodyEl); }).catch(function() {});
          } else {
            // v9 / older — best-effort retry.
            setTimeout(function() { _attachMermaidLenses(bodyEl); }, 50);
          }
        } catch (e) { /* mermaid optional; swallow failures */ }
      });
    }

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

    // Wire internal wiki links. `[[path]]` references render as
    // `.wiki-link` spans with a data-path attribute. Click flow:
    //   1. If the path looks resolvable (contains '/'), load it.
    //   2. Otherwise treat the raw token as a search query so a bare
    //      `[[adr]]` or `[[code-walkthrough]]` lands the user on a
    //      filtered tree view rather than a dead 404.
    bodyEl.querySelectorAll('.wiki-link').forEach(function(link) {
      link.addEventListener('click', function() {
        var target = link.getAttribute('data-path') || '';
        var raw = link.getAttribute('data-raw') || target;
        // Bare slug — route to search.
        if (!target || target.indexOf('/') < 0) {
          searchQuery = raw;
          var searchInput = document.querySelector('.wiki-search');
          if (searchInput) searchInput.value = raw;
          rebuildTree();
          return;
        }
        // Check the page exists; fall back to search if not.
        var exists = (pages || []).some(function(p) { return (p.path || '') === target; });
        if (exists) {
          loadPage(target);
        } else {
          searchQuery = raw;
          var si = document.querySelector('.wiki-search');
          if (si) si.value = raw;
          rebuildTree();
        }
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

  // ── Mermaid lazy-loader ──
  // Loaded once per page session via dynamic import from esm.sh.
  // Themed to match the wiki's dark background; arrows / nodes use the
  // gold accent that the rest of the UI uses.
  var _mermaidPromise = null;
  function _ensureMermaid() {
    if (_mermaidPromise) return _mermaidPromise;
    _mermaidPromise = import('https://esm.sh/mermaid@10.9.0')
      .then(function(mod) {
        var mermaid = mod.default || mod;
        mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          themeVariables: {
            primaryColor: '#1a1a1a',
            primaryTextColor: '#f0e6d2',
            primaryBorderColor: '#c9a96e',
            lineColor: '#daa520',
            secondaryColor: '#2a2a2a',
            secondaryTextColor: '#f0e6d2',
            secondaryBorderColor: '#c9a96e',
            tertiaryColor: '#0f0f0f',
            tertiaryTextColor: '#f0e6d2',
            tertiaryBorderColor: '#c9a96e',
            background: '#0a0a0a',
            mainBkg: '#1a1a1a',
            secondBkg: '#2a2a2a',
            // Edge label readability — opaque dark pill behind the
            // gold text so the label never blends into a node fill.
            edgeLabelBackground: '#0a0a0a',
            // For nodes whose mermaid source forces a light fill via
            // `style X fill:#ffe4b5`, the LLM-authored diagrams need
            // the node text to stay readable. We bump font size and
            // weight globally and use a high-contrast text colour
            // that works on both dark and light fills (CSS layer
            // overrides below tighten this further).
            fontFamily: 'system-ui, -apple-system, sans-serif',
            fontSize: '18px',
            nodeTextColor: '#1a1a1a',
          },
          flowchart: { htmlLabels: true, curve: 'basis', useMaxWidth: false },
          sequence: { mirrorActors: false, actorMargin: 60, messageFontSize: 15 },
          securityLevel: 'loose',
        });
        // Inject a CSS layer that fixes the contrast issues mermaid's
        // theme variables can't fully reach (edge labels, nodes with
        // custom fills, font sizing). Idempotent — only added once.
        if (!document.getElementById('wiki-mermaid-style-overrides')) {
          var style = document.createElement('style');
          style.id = 'wiki-mermaid-style-overrides';
          style.textContent = [
            '.wiki-mermaid svg { font-size: 16px !important; }',
            '.wiki-mermaid .nodeLabel, .wiki-mermaid .label foreignObject div',
            '  { color: #f0e6d2 !important; font-weight: 500; }',
            // Light-fill nodes (orange / pale-green custom styles) get
            // dark text for contrast. Mermaid sets these via inline
            // style attribute; we target them with attribute selectors.
            '.wiki-mermaid g.node[style*="fill:#ff"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#dd"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#ee"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#fa"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#f0"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#e0"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#cc"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#bb"] .nodeLabel,',
            '.wiki-mermaid g.node[style*="fill:#aa"] .nodeLabel',
            '  { color: #0a0a0a !important; font-weight: 600 !important; }',
            // Edge labels — solid dark pill with gold text for contrast.
            '.wiki-mermaid .edgeLabel, .wiki-mermaid .edgeLabel span,',
            '.wiki-mermaid .edgeLabel foreignObject div',
            '  { background: #0a0a0a !important; color: #daa520 !important;',
            '    padding: 2px 6px !important; border-radius: 3px !important;',
            '    font-size: 14px !important; font-weight: 500 !important; }',
            // Sequence-diagram message text + actor labels.
            '.wiki-mermaid .messageText { fill: #daa520 !important; font-size: 14px !important; }',
            '.wiki-mermaid .actor { stroke: #c9a96e !important; }',
            '.wiki-mermaid text.actor, .wiki-mermaid .actor text',
            '  { fill: #f0e6d2 !important; font-size: 15px !important;',
            '    font-weight: 600 !important; }',
            // Lens hint that the inline diagram is interactive.
            '.wiki-mermaid { padding: 8px; border: 1px solid rgba(218,165,32,0.15);',
            '  border-radius: 6px; background: rgba(10,10,10,0.4); }',
          ].join('\n');
          document.head.appendChild(style);
        }
        return mermaid;
      })
      .catch(function() { return null; });
    return _mermaidPromise;
  }

  // ── Mermaid lens overlay ──
  // After mermaid renders a diagram, attach a small magnifier button
  // in the diagram's top-right corner. Clicking it opens a viewport-
  // sized modal with the same SVG cloned in, plus zoom (+ / - /
  // mouse-wheel) and pan (drag) controls. Esc / click-outside closes.
  // Implementation notes:
  //   * No external libraries — vanilla DOM + a CSS transform.
  //   * The modal is created lazily on first open and reused.
  //   * Each click clones the source SVG into the modal so the inline
  //     diagram's layout never changes.

  function _attachMermaidLenses(scope) {
    var diagrams = scope.querySelectorAll('.wiki-mermaid');
    diagrams.forEach(function(diagramEl) {
      if (diagramEl.dataset.lensAttached === '1') return;
      if (!diagramEl.querySelector('svg')) return;
      diagramEl.dataset.lensAttached = '1';
      // Wrap the diagram so the button can position absolutely
      // relative to it.
      diagramEl.style.position = 'relative';
      var btn = document.createElement('button');
      btn.className = 'wiki-mermaid-lens';
      btn.title = 'Open diagram (zoom + pan)';
      btn.setAttribute('aria-label', 'Open diagram in full-viewport viewer');
      // Inline styles keep this self-contained — no CSS file edits.
      btn.style.cssText = (
        'position:absolute;top:8px;right:8px;z-index:2;' +
        'width:32px;height:32px;border-radius:6px;' +
        'border:1px solid rgba(218,165,32,0.4);' +
        'background:rgba(20,20,20,0.85);color:#daa520;' +
        'cursor:pointer;display:flex;align-items:center;' +
        'justify-content:center;font-size:16px;line-height:1;' +
        'transition:background 0.15s;'
      );
      btn.innerHTML = (
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round">' +
        '<circle cx="11" cy="11" r="8"/>' +
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/>' +
        '<line x1="11" y1="8" x2="11" y2="14"/>' +
        '<line x1="8" y1="11" x2="14" y2="11"/>' +
        '</svg>'
      );
      btn.addEventListener('mouseenter', function() {
        btn.style.background = 'rgba(40,40,40,0.95)';
      });
      btn.addEventListener('mouseleave', function() {
        btn.style.background = 'rgba(20,20,20,0.85)';
      });
      btn.addEventListener('click', function(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        _openMermaidLens(diagramEl);
      });
      diagramEl.appendChild(btn);
    });
  }

  // Singleton modal — created on first open, reused thereafter.
  var _lensModal = null;
  var _lensState = { scale: 1, tx: 0, ty: 0, dragging: false, dragX: 0, dragY: 0 };

  function _ensureLensModal() {
    if (_lensModal) return _lensModal;
    var overlay = document.createElement('div');
    overlay.className = 'wiki-mermaid-lens-overlay';
    overlay.style.cssText = (
      'position:fixed;inset:0;background:rgba(0,0,0,0.92);' +
      'z-index:9999;display:none;cursor:grab;' +
      'align-items:center;justify-content:center;'
    );
    // Inner viewport that holds the cloned SVG. We translate/scale this.
    var stage = document.createElement('div');
    stage.className = 'wiki-mermaid-lens-stage';
    stage.style.cssText = (
      'transform-origin:center center;transition:transform 0.05s linear;' +
      'will-change:transform;user-select:none;'
    );
    overlay.appendChild(stage);

    // Controls toolbar (zoom +, zoom -, reset, close).
    var toolbar = document.createElement('div');
    toolbar.className = 'wiki-mermaid-lens-toolbar';
    toolbar.style.cssText = (
      'position:absolute;top:18px;right:18px;display:flex;gap:8px;' +
      'background:rgba(20,20,20,0.92);padding:8px 10px;border-radius:8px;' +
      'border:1px solid rgba(218,165,32,0.3);'
    );
    function ctrlBtn(label, title, onClick) {
      var b = document.createElement('button');
      b.textContent = label;
      b.title = title;
      b.style.cssText = (
        'background:transparent;border:1px solid rgba(218,165,32,0.4);' +
        'color:#daa520;width:32px;height:32px;border-radius:4px;' +
        'cursor:pointer;font-size:16px;font-family:monospace;'
      );
      b.addEventListener('click', function(ev) {
        ev.stopPropagation();
        onClick();
      });
      return b;
    }
    var btnIn = ctrlBtn('+', 'Zoom in', function() { _lensZoom(1.25); });
    var btnOut = ctrlBtn('−', 'Zoom out', function() { _lensZoom(0.8); });
    var btnReset = ctrlBtn('⟲', 'Reset zoom / pan', _lensReset);
    var btnClose = ctrlBtn('×', 'Close (Esc)', _lensClose);
    btnClose.style.color = '#ff6b6b';
    btnClose.style.borderColor = 'rgba(255,107,107,0.4)';
    toolbar.appendChild(btnOut);
    toolbar.appendChild(btnIn);
    toolbar.appendChild(btnReset);
    toolbar.appendChild(btnClose);
    overlay.appendChild(toolbar);

    // Hint at bottom: pan / zoom shortcuts.
    var hint = document.createElement('div');
    hint.textContent = 'Drag to pan · scroll to zoom · Esc to close';
    hint.style.cssText = (
      'position:absolute;bottom:18px;left:50%;transform:translateX(-50%);' +
      'color:rgba(218,165,32,0.7);font-size:12px;font-family:monospace;'
    );
    overlay.appendChild(hint);

    // Mouse-wheel zoom anywhere on the overlay.
    overlay.addEventListener('wheel', function(ev) {
      ev.preventDefault();
      var delta = -ev.deltaY;
      _lensZoom(delta > 0 ? 1.1 : 0.9);
    }, { passive: false });

    // Drag-to-pan.
    overlay.addEventListener('mousedown', function(ev) {
      if (ev.target.closest('.wiki-mermaid-lens-toolbar')) return;
      _lensState.dragging = true;
      _lensState.dragX = ev.clientX - _lensState.tx;
      _lensState.dragY = ev.clientY - _lensState.ty;
      overlay.style.cursor = 'grabbing';
    });
    window.addEventListener('mousemove', function(ev) {
      if (!_lensState.dragging) return;
      _lensState.tx = ev.clientX - _lensState.dragX;
      _lensState.ty = ev.clientY - _lensState.dragY;
      _lensApply();
    });
    window.addEventListener('mouseup', function() {
      if (_lensState.dragging) {
        _lensState.dragging = false;
        overlay.style.cursor = 'grab';
      }
    });

    // Close on Esc or click on the empty overlay background.
    overlay.addEventListener('click', function(ev) {
      if (ev.target === overlay) _lensClose();
    });
    window.addEventListener('keydown', function(ev) {
      if (_lensModal && overlay.style.display !== 'none') {
        if (ev.key === 'Escape') _lensClose();
        else if (ev.key === '+' || ev.key === '=') _lensZoom(1.25);
        else if (ev.key === '-' || ev.key === '_') _lensZoom(0.8);
        else if (ev.key === '0') _lensReset();
      }
    });

    document.body.appendChild(overlay);
    _lensModal = { overlay: overlay, stage: stage };
    return _lensModal;
  }

  function _lensApply() {
    if (!_lensModal) return;
    var s = _lensState;
    _lensModal.stage.style.transform =
      'translate(' + s.tx + 'px,' + s.ty + 'px) scale(' + s.scale + ')';
  }

  function _lensZoom(factor) {
    _lensState.scale = Math.max(0.25, Math.min(8, _lensState.scale * factor));
    _lensApply();
  }

  function _lensReset() {
    // Default to 1.5× so the diagram is comfortably readable on the
    // first open without the user needing to zoom; reset key (`0`)
    // also lands here so it stays consistent.
    _lensState.scale = 1.5;
    _lensState.tx = 0;
    _lensState.ty = 0;
    _lensApply();
  }

  function _lensClose() {
    if (_lensModal) _lensModal.overlay.style.display = 'none';
  }

  function _openMermaidLens(diagramEl) {
    var modal = _ensureLensModal();
    var svg = diagramEl.querySelector('svg');
    if (!svg) return;
    // Clone the rendered SVG so the inline diagram remains unaffected.
    var clone = svg.cloneNode(true);
    // Strip width/height so the SVG can scale up to the viewport.
    clone.removeAttribute('width');
    clone.removeAttribute('height');
    clone.style.cssText = 'max-width:90vw;max-height:88vh;display:block;';
    modal.stage.innerHTML = '';
    modal.stage.appendChild(clone);
    _lensReset();
    modal.overlay.style.display = 'flex';
  }

  // ── Markdown Renderer ──
  function renderMarkdown(md) {
    if (!md) return '';
    var lines = md.split('\n');
    var html = [];
    var inCode = false;
    var codeLang = '';
    var codeLines = [];
    var rawCodeLines = [];  // unescaped — for mermaid which needs raw syntax
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
          // 2026-05-17: mermaid blocks get their own marker div so the
          // post-render pass can call mermaid.run() on them. The graph
          // text itself must NOT be HTML-escaped — mermaid expects raw
          // syntax with literal "->" arrows, "&" etc. Other code blocks
          // keep their escaped <pre><code> rendering.
          if (codeLang === 'mermaid') {
            // Use the unescaped raw lines for mermaid input. We
            // re-collected them below in rawCodeLines.
            html.push('<div class="mermaid wiki-mermaid">' + rawCodeLines.join('\n') + '</div>');
          } else {
            html.push('<div class="wiki-code-block"><pre><code class="lang-' + esc(codeLang) + '">' + codeLines.join('\n') + '</code></pre></div>');
          }
          codeLines = [];
          rawCodeLines = [];
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
        rawCodeLines.push(line);
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

    // ── Wikilinks [[path]] and [[path|label]] ──
    // The pages everyone writes use this notation for cross-references
    // (e.g. ``[[reference/cortex/architecture-overview]]``). Without
    // this rule the page renders the literal ``[[…]]`` text, which
    // looks like a broken link. The replacement runs BEFORE the
    // regular ``[text](url)`` rule because the wikilink syntax is a
    // strict subset and uses different delimiters; running it earlier
    // guarantees the regular rule never sees these tokens.
    s = s.replace(/\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]/g, function(_match, raw, label) {
      var path = raw.trim();
      var display = (label || raw).trim();
      // Normalise: append .md if no extension and it looks like a path.
      // A bare slug like ``adr`` stays unchanged so the click handler
      // can route it to a search instead of a 404.
      if (path.indexOf('/') >= 0 && !/\.[a-z]{2,4}$/i.test(path)) {
        path = path + '.md';
      }
      return '<span class="wiki-link" data-path="' + path + '" data-raw="' + raw + '">' + display + '</span>';
    });

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
