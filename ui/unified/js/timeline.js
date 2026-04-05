// Cortex Memory Board — Kanban-style columns by consolidation stage
// Cards stack vertically within each stage column, scrollable per-column
(function() {
  var container = null;
  var visible = false;
  var currentData = null;
  var selectedId = null;
  var _emitting = false;

  var STAGES = ['labile', 'early_ltp', 'late_ltp', 'consolidated', 'reconsolidating'];
  var STAGE_COLORS = JUG.CONSOLIDATION_COLORS;
  var STAGE_LABELS = JUG.CONSOLIDATION_LABELS || {};
  var EMO_COLORS = {
    urgency: '#ff3366', frustration: '#ef4444',
    satisfaction: '#22c55e', discovery: '#f59e0b',
    confusion: '#8b5cf6'
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
    if (JUG.state.lastData) { currentData = JUG.state.lastData; rebuild(); }
    // Restore selection from graph view
    if (JUG.state.selectedId) highlightMemory(JUG.state.selectedId);
  }
  function hide() {
    visible = false;
    if (container) container.style.display = 'none';
  }
  function rebuildIfVisible() { if (visible && currentData) rebuild(); }

  function extractMemories(data) {
    var nodes = data.nodes ? data.nodes.filter(function(n) {
      return n.type === 'memory';
    }) : [];
    if (JUG._applyExtraFilters) nodes = JUG._applyExtraFilters(nodes);
    // Parse timestamps
    nodes.forEach(function(n) {
      n._ts = parseTs(n.createdAt) || 0;
    });
    return nodes;
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
      var s = m.consolidationStage || 'labile';
      if (!groups[s]) s = 'labile';
      groups[s].push(m);
    });

    // Sort each group: most recent first
    STAGES.forEach(function(s) {
      groups[s].sort(function(a, b) { return b._ts - a._ts; });
    });

    // Build board
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

      // Cards container (scrollable)
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
  }

  function buildCard(mem, stageColor) {
    var card = el('div', 'kb-card');
    card.dataset.memId = mem.id;

    var color = stageColor;
    if (mem.emotion && mem.emotion !== 'neutral' && EMO_COLORS[mem.emotion]) {
      color = EMO_COLORS[mem.emotion];
    }

    // Color indicator
    var indicator = el('div', 'kb-card-indicator');
    indicator.style.background = color;
    card.appendChild(indicator);

    // Content area
    var body = el('div', 'kb-card-body');

    // Label
    var label = el('div', 'kb-card-label');
    label.textContent = (mem.label || mem.content || '').slice(0, 80);
    body.appendChild(label);

    // Meta row
    var meta = el('div', 'kb-card-meta');

    // Domain
    var domain = el('span', 'kb-card-domain');
    domain.textContent = (mem.domain || '').slice(0, 18);
    meta.appendChild(domain);

    // Time
    if (mem._ts) {
      var time = el('span', 'kb-card-time');
      time.textContent = formatTime(mem._ts);
      meta.appendChild(time);
    }

    body.appendChild(meta);

    // Tags row
    if (mem.tags && mem.tags.length > 0) {
      var tagsRow = el('div', 'kb-card-tags');
      mem.tags.slice(0, 3).forEach(function(t) {
        var tag = el('span', 'kb-card-tag');
        tag.textContent = t;
        tagsRow.appendChild(tag);
      });
      body.appendChild(tagsRow);
    }

    // Bottom: metrics + badges
    var bottom = el('div', 'kb-card-bottom');
    var heat = Math.max(0, Math.min(1, mem.heat || 0));
    var imp = Math.max(0, Math.min(1, mem.importance || 0));

    // Heat bar
    var heatBar = el('div', 'kb-heat-bar');
    var heatFill = el('div', 'kb-heat-fill');
    heatFill.style.width = (heat * 100) + '%';
    heatFill.style.background = color;
    heatBar.appendChild(heatFill);
    bottom.appendChild(heatBar);

    var metrics = el('span', 'kb-card-metrics');
    metrics.textContent = 'H:' + heat.toFixed(2) + ' I:' + imp.toFixed(2);
    bottom.appendChild(metrics);

    // Badges
    if (mem.isProtected) {
      var shield = el('span', 'kb-badge kb-badge-protected');
      shield.textContent = '\u26A1';
      bottom.appendChild(shield);
    }
    if (mem.storeType === 'semantic') {
      var sem = el('span', 'kb-badge kb-badge-semantic');
      sem.textContent = 'SEM';
      bottom.appendChild(sem);
    }
    if (mem.emotion && mem.emotion !== 'neutral') {
      var emo = el('span', 'kb-badge');
      emo.textContent = mem.emotion.slice(0, 4).toUpperCase();
      emo.style.color = color;
      bottom.appendChild(emo);
    }

    body.appendChild(bottom);
    card.appendChild(body);

    // Interactions
    card.addEventListener('mouseenter', function() { JUG._tooltip.show(mem); });
    card.addEventListener('mouseleave', function() { JUG._tooltip.hide(); });
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
