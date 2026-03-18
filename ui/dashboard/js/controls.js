// JARVIS Memory Dashboard — UI Controls
// Sidebar navigation, filter buttons, search, reset camera, analytics.

(function() {

  // ── Sidebar Navigation (view switching) ───────────────────────
  document.querySelectorAll('#sidebar .nav-item').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('#sidebar .nav-item').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      JMD.setState('activeView', btn.dataset.view);
    });
  });

  JMD.on('state:activeView', function(e) {
    var tlOverlay = document.getElementById('timeline-overlay');
    var catOverlay = document.getElementById('categories-overlay');
    var graphContainer = document.getElementById('graph-container');
    var kpiStrip = document.getElementById('kpi-strip');
    var bottombar = document.getElementById('bottombar');

    tlOverlay.classList.toggle('open', e.value === 'timeline');
    catOverlay.classList.toggle('open', e.value === 'categories');

    // Show/hide graph-specific elements
    var show3d = e.value === 'graph';
    if (graphContainer) graphContainer.style.display = show3d ? '' : 'none';
    if (kpiStrip) kpiStrip.style.display = show3d ? '' : 'none';
    if (bottombar) bottombar.style.display = show3d ? '' : 'none';

    // Re-sync renderer size when switching back to graph
    if (show3d && JMD.resizeToContainer) {
      requestAnimationFrame(function() { JMD.resizeToContainer(); });
    }
  });

  // ── Type Filter ───────────────────────────────────────────────
  document.querySelectorAll('#type-filter-bar .filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('#type-filter-bar .filter-btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      JMD.setState('activeFilter', btn.dataset.type);
    });
  });

  // ── Search ────────────────────────────────────────────────────
  document.getElementById('search-box').addEventListener('input', function(e) {
    JMD.setState('searchQuery', e.target.value.toLowerCase());
  });

  // ── Reset Camera ──────────────────────────────────────────────
  document.getElementById('reset-cam').addEventListener('click', function() {
    if (JMD.resetCamera) JMD.resetCamera();
  });

  // ── Analytics Toggle ──────────────────────────────────────────
  document.getElementById('analytics-toggle').addEventListener('click', function() {
    JMD.setState('analyticsOpen', !JMD.state.analyticsOpen);
  });

  var analyticsClose = document.getElementById('analytics-close');
  if (analyticsClose) {
    analyticsClose.addEventListener('click', function() {
      JMD.setState('analyticsOpen', false);
    });
  }
})();
