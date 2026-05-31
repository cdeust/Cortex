// Cortex Neural Graph — LOD status + stats poller.
// The 916 MB /api/graph + /api/discussions payload fetchers are GONE.
// Stats now come from the lightweight /api/graph/progress meta; the
// graph view (workflow_graph.js) owns L0/L1 loading via /api/graph/phase.
(function() {
  var _readyEmitted = false;

  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function updateStatus(text) {
    setText('status-text', text);
  }

  function hideLoading() {
    var el = document.getElementById('loading');
    if (el && !el.classList.contains('done')) {
      el.classList.add('done');
      setTimeout(function() { if (el.parentNode) el.remove(); }, 1100);
    }
  }

  function updateStats(meta) {
    if (!meta) return;
    setText('s-dom', meta.domain_count || 0);
    setText('s-mem', meta.memory_count || 0);
    setText('s-ent', meta.entity_count || 0);
    setText('s-edge', meta.edge_count || 0);
    setText('s-nodes', meta.node_count || 0);
  }

  function emitReady() {
    if (_readyEmitted) return;
    _readyEmitted = true;
    if (window.JUG && JUG.emit) JUG.emit('graph:ready', {});
  }

  function boot() {
    hideLoading();
    fetch('/api/graph/progress')
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(p) {
        if (p) { updateStats(p); updateStatus('Online'); }
        emitReady();
      })
      .catch(function(err) {
        console.warn('[cortex] progress fetch error:', err.message);
        updateStatus('Offline');
        emitReady();
      });
  }

  // Clock.
  setInterval(function() {
    var d = new Date();
    setText('status-time', [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map(function(v) { return String(v).padStart(2, '0'); }).join(':'));
  }, 1000);

  // Boot once the DOM is ready.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // When the user switches to the Graph tab, make sure L0 has been kicked.
  if (window.JUG && JUG.on) {
    JUG.on('state:activeView', function(ev) {
      if (ev && ev.value === 'graph') emitReady();
    });
  }
})();
