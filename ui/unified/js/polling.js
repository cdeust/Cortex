// Cortex Neural Graph — Async Progressive Batch Streaming
// Fetches skeleton first (batch=0), then child nodes in pages.
(function() {
  var abortController = null;
  var BATCH_SIZE = 500;

  function fetchGraph() {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    var signal = abortController.signal;

    // Batch 0: skeleton (root, categories, domains, agents, type-groups)
    var url0 = JUG.API_URL + '?batch=0&batch_size=' + BATCH_SIZE;
    fetch(url0, { signal: signal })
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

        var total = (data.meta || {}).total_batches || 1;
        var nodeCount = (data.meta || {}).node_count || 0;
        updateStatus('Loading (' + nodeCount + ' nodes, batch 0/' + total + ')');

        // Fetch remaining batches progressively
        if (total > 1) {
          fetchBatches(1, total, signal);
        } else {
          updateStatus('Online (' + nodeCount + ' nodes)');
        }
      })
      .catch(function(err) {
        if (err.name === 'AbortError') return;
        console.warn('[cortex] Graph fetch error:', err.message);
        useFallback();
      });
  }

  function fetchBatches(current, total, signal) {
    if (current > total || signal.aborted) {
      var nc = (JUG.state.lastData || {}).meta || {};
      updateStatus('Online (' + (nc.node_count || '?') + ' nodes)');
      return;
    }
    var url = JUG.API_URL + '?batch=' + current + '&batch_size=' + BATCH_SIZE;
    fetch(url, { signal: signal })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        if (signal.aborted) return;

        // Merge batch into existing graph
        if (JUG.addBatchToGraph) {
          JUG.addBatchToGraph(data);
        } else if (JUG.buildGraph) {
          // Fallback: merge nodes/edges into lastData and rebuild
          var ld = JUG.state.lastData || { nodes: [], edges: [], clusters: [] };
          ld.nodes = (ld.nodes || []).concat(data.nodes || []);
          ld.edges = (ld.edges || []).concat(data.edges || []);
          JUG.state.lastData = ld;
          JUG.buildGraph(ld);
        }

        updateStatus('Loading (batch ' + current + '/' + total + ')');

        // Next batch with small delay to keep UI responsive
        setTimeout(function() { fetchBatches(current + 1, total, signal); }, 50);
      })
      .catch(function(err) {
        if (err.name !== 'AbortError') {
          console.warn('[cortex] Batch ' + current + ' error:', err.message);
        }
      });
  }

  function updateStats(meta) {
    setText('s-dom', meta.domain_count || 0);
    setText('s-mem', meta.memory_count || 0);
    setText('s-ent', meta.entity_count || 0);
    setText('s-edge', meta.edge_count || 0);
    setText('s-nodes', meta.node_count || 0);

    var sv = meta.system_vitals;
    if (sv) {
      var svEl = document.getElementById('system-vitals');
      if (svEl) svEl.style.display = 'block';
      setText('sv-heat', sv.mean_heat ? sv.mean_heat.toFixed(3) : '--');
      var cp = sv.consolidation_pipeline || {};
      setText('sv-labile', cp.labile || 0);
      setText('sv-eltp', cp.early_ltp || 0);
      setText('sv-lltp', cp.late_ltp || 0);
      setText('sv-cons', cp.consolidated || 0);
      setText('sv-recon', cp.reconsolidating || 0);
    }

    var bm = meta.benchmarks;
    if (bm) {
      var el = document.getElementById('benchmark-summary');
      if (el) el.style.display = 'block';
      if (bm.LongMemEval) setText('b-lme', fmtBench(bm.LongMemEval));
      if (bm.LoCoMo) setText('b-loc', fmtBench(bm.LoCoMo));
      if (bm.BEAM) setText('b-beam', fmtBench(bm.BEAM));
    }
  }

  function fmtBench(bm) {
    var parts = [];
    if (bm.recall_10 !== undefined) parts.push('R@10 ' + Math.round(bm.recall_10) + '%');
    if (bm.mrr !== undefined) parts.push('MRR .' + Math.round(bm.mrr * 1000));
    return parts.join(' | ') || '--';
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

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(fetchGraph, 500);
    });
  } else {
    setTimeout(fetchGraph, 500);
  }
})();
