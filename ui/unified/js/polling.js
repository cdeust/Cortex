// Cortex — Polling (LOD edition).
// Does NOT fetch /api/graph (916 MB blob). Instead polls /api/graph/progress
// for stats + status. lod.js handles all graph data via /api/graph/phase.
(function() {
  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  function updateStatus(text) {
    var el = document.getElementById('status-text');
    if (el) el.textContent = text;
  }
  function hideLoading() {
    var el = document.getElementById('loading');
    if (el && !el.classList.contains('done')) {
      el.classList.add('done');
      setTimeout(function() { if (el.parentNode) el.remove(); }, 1100);
    }
  }
  function updateStats(p) {
    setText('s-dom',   p.domain_count  || 0);
    setText('s-mem',   p.memory_count  || 0);
    setText('s-ent',   p.entity_count  || 0);
    setText('s-edge',  p.edge_count    || 0);
    setText('s-nodes', p.node_count    || 0);
    var sv = p.system_vitals;
    if (sv) {
      var svEl = document.getElementById('system-vitals');
      if (svEl) svEl.style.display = 'block';
      setText('sv-heat', sv.mean_heat ? sv.mean_heat.toFixed(3) : '--');
      var cp = sv.consolidation_pipeline || {};
      setText('sv-labile', cp.labile || 0);
      setText('sv-eltp',   cp.early_ltp || 0);
      setText('sv-lltp',   cp.late_ltp || 0);
      setText('sv-cons',   cp.consolidated || 0);
      setText('sv-recon',  cp.reconsolidating || 0);
    }
    var bm = p.benchmarks;
    if (bm) {
      var bEl = document.getElementById('benchmark-summary');
      if (bEl) bEl.style.display = 'block';
      function fmtB(b) {
        var parts = [];
        if (b.recall_10 !== undefined) parts.push('R@10 ' + Math.round(b.recall_10) + '%');
        if (b.mrr !== undefined) parts.push('MRR .' + Math.round(b.mrr * 1000));
        return parts.join(' | ') || '--';
      }
      if (bm.LongMemEval) setText('b-lme', fmtB(bm.LongMemEval));
      if (bm.LoCoMo)      setText('b-loc', fmtB(bm.LoCoMo));
      if (bm.BEAM)        setText('b-beam', fmtB(bm.BEAM));
    }
  }

  var _interval = 2000;
  var _ready = false;
  var _timer = null;

  function poll() {
    var url = (JUG.API_URL || 'http://127.0.0.1:3458/api/graph')
                .replace('/api/graph', '/api/graph/progress');
    fetch(url)
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(p) {
        if (!p) return;
        updateStats(p);
        if (p.full_ready || p.baseline_ready) {
          if (!_ready) {
            _ready = true;
            hideLoading();
            updateStatus('Online — scroll to explore, click to chain');
            JUG.emit('graph:zoom', { k: 1 });  // trigger LOD eval
          }
          _interval = 15000;
        } else {
          updateStatus('Building: ' + (p.phase || 'starting') + '…');
          _interval = 2000;
        }
      })
      .catch(function() { _interval = 5000; })
      .then(function() { _timer = setTimeout(poll, _interval); });
  }

  // Clock
  setInterval(function() {
    var d = new Date();
    var el = document.getElementById('status-time');
    if (el) el.textContent = [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map(function(v) { return String(v).padStart(2, '0'); }).join(':');
  }, 1000);

  // Boot
  setTimeout(poll, 600);

  // Re-evaluate LOD when switching to graph tab
  if (window.JUG && JUG.on) {
    JUG.on('state:activeView', function(ev) {
      if (ev && ev.value === 'graph') JUG.emit('graph:zoom', { k: 1 });
    });
  }
})();
