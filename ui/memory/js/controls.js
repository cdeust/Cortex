// Cortex Memory Dashboard — Controls
(function() {
  var CMD = window.CMD;

  CMD.initControls = function() {
    // Filter buttons
    document.querySelectorAll('.fbtn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        document.querySelectorAll('.fbtn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        CMD.activeFilter = btn.dataset.type;
        CMD.applyFilters();
      });
    });

    // Search
    document.getElementById('search-brain').addEventListener('input', function(e) {
      CMD.searchQuery = e.target.value;
      CMD.applyFilters();
    });

    // Conversation toggle
    var convToggleBtn = document.getElementById('conv-toggle-brain');
    if (convToggleBtn) {
      convToggleBtn.addEventListener('click', function() {
        CMD.showConvs = !CMD.showConvs;
        convToggleBtn.textContent = CMD.showConvs ? 'Hide chatlogs' : 'Show chatlogs';
        convToggleBtn.classList.toggle('active', CMD.showConvs);
        CMD.applyFilters();
      });
    }

    // Category bar
    CMD.buildCategoryBar();
    var catBar = document.getElementById('cat-bar-brain');
    if (catBar) {
      catBar.addEventListener('click', function(e) {
        var btn = e.target.closest('.cbtn');
        if (!btn) return;
        document.querySelectorAll('.cbtn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        CMD.activeCategory = btn.dataset.cat;
        CMD.applyFilters();
      });
    }

    // Thread select
    CMD.buildThreadSelect();
    var threadSel = document.getElementById('thread-select-brain');
    if (threadSel) {
      threadSel.addEventListener('change', function(e) {
        CMD.activeThread = e.target.value;
        CMD.applyFilters();
      });
    }

    // Status bar
    document.querySelectorAll('.sbtn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        document.querySelectorAll('.sbtn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        CMD.activeStatus = btn.dataset.status;
        CMD.applyFilters();
      });
    });

    // Layout toggle
    var layoutBtn = document.getElementById('layout-toggle-brain');
    layoutBtn.addEventListener('click', function() {
      CMD.layoutMode = CMD.layoutMode === 'cluster' ? 'timeline' : 'cluster';
      layoutBtn.textContent = CMD.layoutMode === 'cluster' ? 'Cluster' : 'Timeline';
      layoutBtn.classList.toggle('active', CMD.layoutMode === 'timeline');
      if (CMD.layoutMode === 'timeline') {
        CMD.showTimelineView();
      } else {
        CMD.showBrainView();
      }
    });

    // Analytics toggle
    document.getElementById('analytics-toggle-brain').addEventListener('click', CMD.toggleAnalytics);

    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === 'a' || e.key === 'A') CMD.toggleAnalytics();
      if (e.key === 't' || e.key === 'T') layoutBtn.click();
      if (e.key === 'Escape') { CMD.closePanel(); CMD.closeAnalytics(); }
    });
  };

  CMD.buildCategoryBar = function() {
    var bar = document.getElementById('cat-bar-brain');
    if (!bar) return;
    var cats = new Set();
    CMD.nodes.forEach(function(n) { if (n.category) cats.add(n.category); });
    cats.forEach(function(cat) {
      var btn = document.createElement('button');
      btn.className = 'cbtn';
      btn.dataset.cat = cat;
      btn.textContent = cat;
      bar.appendChild(btn);
    });
  };

  CMD.buildThreadSelect = function() {
    var sel = document.getElementById('thread-select-brain');
    if (!sel) return;
    var threads = new Set();
    CMD.nodes.forEach(function(n) { if (n.threadId) threads.add(n.threadId); });
    threads.forEach(function(tid) {
      var opt = document.createElement('option');
      opt.value = tid;
      opt.textContent = tid;
      sel.appendChild(opt);
    });
  };
})();
