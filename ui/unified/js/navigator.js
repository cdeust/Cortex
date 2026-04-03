// Cortex Neural Graph — Navigator (breadcrumb trail + back/forward)
// Tracks navigation history as the user clicks through memories and entities.
(function() {
  var history = [];
  var currentIndex = -1;
  var MAX_HISTORY = 50;

  function push(entry) {
    // Deduplicate consecutive same entries
    if (currentIndex >= 0 && history[currentIndex] &&
        history[currentIndex].id === entry.id) return;

    // Trim forward history on new navigation
    history = history.slice(0, currentIndex + 1);
    history.push(entry);
    if (history.length > MAX_HISTORY) history.shift();
    currentIndex = history.length - 1;
    render();
  }

  function goBack() {
    if (currentIndex <= 0) return;
    currentIndex--;
    navigateTo(history[currentIndex]);
  }

  function goForward() {
    if (currentIndex >= history.length - 1) return;
    currentIndex++;
    navigateTo(history[currentIndex]);
  }

  function navigateTo(entry) {
    if (!entry) return;
    render();
    if (entry.type === 'memory' && entry.memoryId) {
      if (JUG._localGraph) JUG._localGraph.loadGraph(entry.memoryId);
      if (JUG.selectNodeById) JUG.selectNodeById(entry.id);
    } else if (entry.nodeId && JUG.selectNodeById) {
      JUG.selectNodeById(entry.nodeId);
    }
  }

  function render() {
    var bar = document.getElementById('navigator-bar');
    if (!bar) return;

    if (history.length === 0) {
      bar.style.display = 'none';
      return;
    }
    bar.style.display = 'flex';

    var h = '';
    // Back/forward buttons
    h += '<button class="nav-btn" id="nav-back"' +
      (currentIndex <= 0 ? ' disabled' : '') + '>&larr;</button>';
    h += '<button class="nav-btn" id="nav-forward"' +
      (currentIndex >= history.length - 1 ? ' disabled' : '') + '>&rarr;</button>';

    // Breadcrumbs — show last 5 entries
    var start = Math.max(0, currentIndex - 4);
    h += '<div class="nav-crumbs">';
    for (var i = start; i < history.length; i++) {
      var entry = history[i];
      var active = i === currentIndex ? ' nav-crumb-active' : '';
      var label = entry.label || entry.id || '?';
      if (label.length > 25) label = label.substring(0, 22) + '...';
      h += '<span class="nav-crumb' + active + '" data-idx="' + i + '">';
      h += esc(label);
      h += '</span>';
      if (i < history.length - 1) h += '<span class="nav-sep">/</span>';
    }
    h += '</div>';

    bar.innerHTML = h;

    // Wire events
    var backBtn = document.getElementById('nav-back');
    if (backBtn) backBtn.addEventListener('click', goBack);
    var fwdBtn = document.getElementById('nav-forward');
    if (fwdBtn) fwdBtn.addEventListener('click', goForward);

    bar.querySelectorAll('.nav-crumb[data-idx]').forEach(function(el) {
      el.addEventListener('click', function() {
        var idx = parseInt(el.dataset.idx, 10);
        if (idx >= 0 && idx < history.length) {
          currentIndex = idx;
          navigateTo(history[idx]);
        }
      });
    });
  }

  function esc(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // Track node selections
  JUG.on('graph:selectNode', function(node) {
    push({
      id: node.id,
      nodeId: node.id,
      type: node.type,
      memoryId: node.memoryId || null,
      label: JUG.cleanText ? JUG.cleanText(node.label || node.id) : (node.label || node.id),
    });
  });

  // Track local graph navigation
  JUG.on('localgraph:navigate', function(data) {
    if (data.memory_id) {
      push({
        id: 'mem-' + data.memory_id,
        nodeId: 'mem-' + data.memory_id,
        type: 'memory',
        memoryId: data.memory_id,
        label: 'Memory #' + data.memory_id,
      });
    }
  });

  JUG._navigator = { push: push, goBack: goBack, goForward: goForward };
})();
