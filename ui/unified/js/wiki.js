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

    fetch('/api/wiki/page?path=' + encodeURIComponent(path))
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(data) {
        if (data.error) throw new Error(data.error);
        renderPage(main, data);
      })
      .catch(function(err) {
        console.warn('[cortex] Wiki page fetch error:', err.message);
        main.innerHTML = '';
        main.appendChild(buildErrorState('Page not found', 'Could not load ' + path));
      });
  }

  // ── Page Rendering ──
  function renderPage(main, data) {
    main.innerHTML = '';
    var meta = data.meta || {};
    var body = data.body || '';

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

    pageHeader.appendChild(titleRow);

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

    article.appendChild(pageHeader);

    // Body
    var bodyEl = el('div', 'wiki-body');
    bodyEl.innerHTML = renderMarkdown(body);

    // Wire internal wiki links
    bodyEl.querySelectorAll('.wiki-link').forEach(function(link) {
      link.addEventListener('click', function() {
        var target = link.getAttribute('data-path');
        if (target) loadPage(target);
      });
    });

    article.appendChild(bodyEl);
    main.appendChild(article);
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

  // ── Init ──
  document.addEventListener('DOMContentLoaded', init);
})();
