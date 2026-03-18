// JARVIS Unified Graph — UI Controls
(function() {
  document.addEventListener('DOMContentLoaded', function() {
    // ── Filter buttons (source type) ──
    var filterBtns = document.querySelectorAll('#filter-bar .filter-btn[data-filter]');
    filterBtns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        filterBtns.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        JUG.state.activeFilter = btn.dataset.filter || 'all';
      });
    });

    // ── Domain dropdown ──
    var domainSelect = document.getElementById('domain-select');
    if (domainSelect) {
      // Populate on data load
      JUG.on('state:lastData', function() {
        populateDomainDropdown();
      });
      domainSelect.addEventListener('change', function() {
        JUG.state.domainFilter = domainSelect.value;
        if (JUG.state.lastData) rebuildWithFilters();
      });
    }

    // ── Emotion dropdown ──
    var emotionSelect = document.getElementById('emotion-select');
    if (emotionSelect) {
      emotionSelect.addEventListener('change', function() {
        JUG.state.emotionFilter = emotionSelect.value;
        if (JUG.state.lastData) rebuildWithFilters();
      });
    }

    // ── Search ──
    var searchBox = document.getElementById('search-box');
    var searchTimer = null;
    if (searchBox) {
      searchBox.addEventListener('input', function() {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function() {
          JUG.state.searchQuery = searchBox.value;
        }, 300);
      });
    }

    // ── Reset ──
    var resetBtn = document.getElementById('reset-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', function() {
        // Clear all filters
        filterBtns.forEach(function(b) { b.classList.remove('active'); });
        filterBtns[0] && filterBtns[0].classList.add('active');
        if (domainSelect) domainSelect.value = '';
        if (emotionSelect) emotionSelect.value = '';
        if (searchBox) searchBox.value = '';
        JUG.state.activeFilter = 'all';
        JUG.state.domainFilter = '';
        JUG.state.emotionFilter = '';
        JUG.state.searchQuery = '';
        JUG.resetCamera();
      });
    }

    // ── Glossary ──
    var glossaryPanel = document.getElementById('glossary-panel');
    var glossaryToggle = document.getElementById('glossary-toggle');
    var glossaryClose = document.getElementById('glossary-close');

    if (glossaryToggle && glossaryPanel) {
      glossaryToggle.addEventListener('click', function() {
        glossaryPanel.classList.toggle('open');
      });
    }
    if (glossaryClose && glossaryPanel) {
      glossaryClose.addEventListener('click', function() {
        glossaryPanel.classList.remove('open');
      });
    }

    // ── Keyboard shortcuts ──
    window.addEventListener('keydown', function(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === 'r' || e.key === 'R') JUG.resetCamera();
      if (e.key === '?') {
        if (glossaryPanel) glossaryPanel.classList.toggle('open');
      }
    });
  });

  function populateDomainDropdown() {
    var select = document.getElementById('domain-select');
    if (!select || !JUG.state.lastData) return;
    var domains = {};
    (JUG.state.lastData.nodes || []).forEach(function(n) {
      if (n.domain) domains[n.domain] = true;
    });
    var current = select.value;
    select.innerHTML = '<option value="">All Domains</option>';
    Object.keys(domains).sort().forEach(function(d) {
      var opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d.length > 30 ? d.slice(0, 30) + '...' : d;
      select.appendChild(opt);
    });
    select.value = current;
  }

  function rebuildWithFilters() {
    // Trigger a full graph rebuild by toggling the filter state
    // The graph.js listener on state:activeFilter handles the rebuild
    var current = JUG.state.activeFilter;
    JUG.state.activeFilter = '_force_rebuild';
    JUG.state.activeFilter = current;
  }

  // Extend the graph filter logic to respect domain and emotion filters
  var origFilter = JUG.state.activeFilter;
  JUG._applyExtraFilters = function(nodes) {
    var domain = JUG.state.domainFilter || '';
    var emotion = JUG.state.emotionFilter || '';

    if (domain) {
      nodes = nodes.filter(function(n) { return n.domain === domain || n.type === 'domain'; });
    }
    if (emotion) {
      nodes = nodes.filter(function(n) {
        if (n.type !== 'memory') return true; // Don't filter non-memories by emotion
        return n.emotion === emotion;
      });
    }
    return nodes;
  };
})();
