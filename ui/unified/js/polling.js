// Cortex Neural Graph — Async Progressive Batch Streaming
(function() {
  var abortController = null;

  function fetchGraph() {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    var signal = abortController.signal;

    // Single fetch — no batching. Domain dedup keeps node count manageable.
    fetch(JUG.API_URL, { signal: signal })
      .then(function(res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function(data) {
        if (signal.aborted) return;

        JUG.state.lastData = data;
        JUG.buildGraph(data);
        updateStats(data.meta || {});
        hideLoading();

        var count = (data.meta || {}).node_count || (data.nodes || []).length;
        updateStatus('Online (' + count + ' nodes)');
      })
      .catch(function(err) {
        if (err.name === 'AbortError') return;
        console.warn('[cortex] Graph fetch error:', err.message);
        useFallback();
      });
  }

  function updateStats(meta) {
    setText('s-dom', meta.domain_count || 0);
    setText('s-mem', meta.memory_count || 0);
    setText('s-ent', meta.entity_count || 0);
    setText('s-edge', meta.edge_count || 0);
    setText('s-cluster', meta.cluster_count || 0);
    setText('s-nodes', meta.node_count || 0);

    // Benchmark summary
    var bm = meta.benchmarks;
    if (bm) {
      var el = document.getElementById('benchmark-summary');
      if (el) el.style.display = 'block';
      if (bm.LongMemEval) setText('b-lme', 'R@10 ' + Math.round(bm.LongMemEval.recall_10) + '%');
      if (bm.LoCoMo) setText('b-loc', 'R@10 ' + Math.round(bm.LoCoMo.recall_10) + '%');
      if (bm.BEAM) setText('b-beam', 'R@10 ' + Math.round(bm.BEAM.recall_10) + '%');
    }
  }

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

  function useFallback() {
    var fallback = {
      nodes: [
        { id: 'dom_1', type: 'domain', label: 'Sample Domain', domain: 'sample', color: '#6366f1', size: 8, group: 'sample', sessionCount: 10, confidence: 0.8 },
        { id: 'entry_1', type: 'entry-point', label: 'system design', domain: 'sample', color: '#00d4ff', size: 5, group: 'sample', frequency: 4 },
      ],
      edges: [
        { source: 'dom_1', target: 'entry_1', type: 'has-entry', weight: 0.7 },
      ],
      clusters: [],
      meta: { domain_count: 1, node_count: 2, edge_count: 1, total_batches: 1 },
    };
    JUG.state.lastData = fallback;
    JUG.buildGraph(fallback);
    updateStats(fallback.meta);
    hideLoading();
    updateStatus('Offline (sample)');
  }

  // Clock
  setInterval(function() {
    var d = new Date();
    var el = document.getElementById('status-time');
    if (el) el.textContent = [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map(function(v) { return String(v).padStart(2, '0'); }).join(':');
  }, 1000);

  // Boot — delay initial fetch to let Three.js scene fully initialize
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(fetchGraph, 500);
    });
  } else {
    setTimeout(fetchGraph, 500);
  }

  // No auto-refresh — user triggers manually via Reset button or page reload
})();
