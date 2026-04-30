// Cortex Neural Graph — Async Progressive Batch Streaming
(function() {
  var abortController = null;

  function fetchGraph() {
    // Lazy-load: only pay the multi-MB /api/graph cost when the
    // user is actually on the Graph tab. Knowledge / Board / Wiki
    // each own their own paged data path and don't need this.
    if (window.JUG && JUG.state && JUG.state.activeView !== 'graph') {
      updateStatus('Online — graph standby');
      hideLoading();
      return;
    }
    if (abortController) abortController.abort();
    abortController = new AbortController();
    var signal = abortController.signal;

    fetch(JUG.API_URL, { signal: signal })
      .then(function(res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function(data) {
        if (signal.aborted) return;

        // Retry if server is still building the graph cache
        if (data.meta && (data.meta.warming || data.meta.stage === 'building')) {
          updateStatus('Building graph...');
          setTimeout(function() { if (!signal.aborted) fetchGraph(); }, 1000);
          // Stats from progress meta so the panel isn't stuck at '--'
          updateStats(data.meta || {});
          return;
        }

        // Phase-driven loader owns `lastData` — don't clobber it if it's
        // already been populated via /api/graph/phase appends. Only seed
        // from the /api/graph snapshot when the phase loader hasn't
        // landed anything yet (fast-boot case where the cache was warm).
        var cur = JUG.state.lastData;
        var phaseBootstrapped = cur && cur.nodes && cur.nodes.length > 0;
        if (!phaseBootstrapped) {
          JUG.state.lastData = data;
          JUG.buildGraph(data);
        }
        updateStats(data.meta || {});
        hideLoading();
        _loadDiscussionBatch(0);

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

    setText('s-nodes', meta.node_count || 0);

    // System vitals
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

    // Benchmark summary — R@10 + MRR side by side
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

  // Boot — delay initial fetch. fetchGraph() short-circuits unless
  // activeView === 'graph', so this is cheap on Knowledge / Board /
  // Wiki landings.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(fetchGraph, 500);
    });
  } else {
    setTimeout(fetchGraph, 500);
  }

  // Trigger the graph fetch when the user actually switches to the
  // Graph tab (lazy-load semantics).
  if (window.JUG && JUG.on) {
    JUG.on('state:activeView', function(ev) {
      if (ev && ev.value === 'graph') setTimeout(fetchGraph, 50);
    });
  }

  function _loadDiscussionBatch(batch) {
    var batchSize = 500;
    fetch(JUG.API_URL.replace('/api/graph', '/api/discussions') + '?batch=' + batch + '&batch_size=' + batchSize)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (!data.nodes || !data.nodes.length) return;
        JUG.addBatchToGraph(data);
        var discEl = document.getElementById('s-disc');
        if (discEl && JUG.state.lastData) {
          var count = JUG.state.lastData.nodes.filter(function(n) { return n.type === 'discussion'; }).length;
          discEl.textContent = count;
        }
        if (data.meta && batch < (data.meta.total_batches || 1) - 1) {
          setTimeout(function() { _loadDiscussionBatch(batch + 1); }, 200);
        }
      })
      .catch(function(err) {
        console.warn('[cortex] Discussion batch error:', err.message);
      });
  }

  // No auto-refresh — user triggers manually via Reset button or page reload
})();
