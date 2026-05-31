// Cortex Neural Graph — Sidebar counters + status from /api/graph/progress.
//
// Original implementation downloaded the full /api/graph payload
// (80+ MB once L6 lands) on every page load just to read meta.* and
// drive the stats panel. The phase loader (phase_loader.js) now owns
// node/edge population via /api/graph/phase deltas, so this file's
// only remaining job is to keep the stats card and clock current —
// done with a tiny /api/graph/progress poll instead of the full graph.
(function() {
  function fetchGraph() {
    // Lazy-load: only poll while the user is actually on the Graph
    // tab. The poll is now a tiny /api/graph/progress hit (not the
    // multi-MB /api/graph it used to be), but the activeView listener
    // below still re-triggers it on tab switch, so gating here keeps
    // idle tabs quiet. No abortController needed — the progress poll
    // is a few hundred bytes and re-polls itself via setTimeout.
    if (window.JUG && JUG.state && JUG.state.activeView !== 'graph') {
      updateStatus('Online — graph standby');
      hideLoading();
      return;
    }

    fetch('/api/graph/progress')
      .then(function(res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function(p) {
        // Counts come from the phase loader's cumulative store
        // (JUG.state.lastData). progress.node_count reflects the
        // server-side cache, but we want the panel to mirror what
        // the user can actually see in the graph — so fall back to
        // server counts only until the first phase lands.
        var d = JUG.state && JUG.state.lastData;
        var localCount = d && d.nodes ? d.nodes.length : 0;
        if (localCount > 0) {
          // The phase loader's appendGraphDelta already updates the
          // sidebar counters from lastData.nodes (see graph.js line
          // ~250). Nothing more to do here for counts.
        } else {
          updateStats({
            node_count: p.node_count,
            edge_count: p.edge_count,
          });
        }
        var phase = p.phase || '';
        var pct = Math.round((p.pct || 0) * 100);
        if (p.full_ready) {
          updateStatus('Ready · ' + (localCount || p.node_count) + ' nodes');
        } else if (p.baseline_ready) {
          updateStatus('Baseline ready · loading L6 (' + pct + '%)');
        } else {
          updateStatus('Building · ' + phase + ' (' + pct + '%)');
        }
        hideLoading();
        // Keep polling progress while the build is still active.
        if (!p.full_ready) setTimeout(fetchGraph, 2000);
      })
      .catch(function(err) {
        console.warn('[cortex] progress poll error:', err.message);
        setTimeout(fetchGraph, 4000);
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
