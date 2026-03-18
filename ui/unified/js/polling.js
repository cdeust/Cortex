// JARVIS Unified Graph — Async Progressive Batch Streaming
(function() {
  var BATCH_SIZE = 150;
  var BATCH_DELAY_INITIAL = 1500; // ms for first 3 batches (layout needs to settle)
  var BATCH_DELAY_NORMAL = 600;   // ms for subsequent batches
  var abortController = null;

  function fetchGraph() {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    var signal = abortController.signal;

    // Step 1: fetch skeleton (domains + inter-domain edges)
    fetch(JUG.API_URL + '?batch=0&batch_size=' + BATCH_SIZE, { signal: signal })
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

        var totalBatches = (data.meta || {}).total_batches || 1;
        if (totalBatches > 1) {
          updateStatus('Streaming ' + (data.meta || {}).node_count + ' nodes...');
          streamBatches(1, totalBatches, signal);
        } else {
          updateStatus('Online');
        }
      })
      .catch(function(err) {
        if (err.name === 'AbortError') return;
        console.warn('[jarvis] Graph fetch error:', err.message);
        useFallback();
      });
  }

  function streamBatches(batchNum, totalBatches, signal) {
    if (signal.aborted || batchNum > totalBatches) {
      if (!signal.aborted) {
        updateStatus('Online (' + (JUG.allNodes || []).length + ' nodes)');
        // Rebuild clusters after a short settle
        setTimeout(rebuildClusters, 800);
      }
      return;
    }

    updateStatus('Loading ' + batchNum + '/' + totalBatches +
      ' (' + (JUG.allNodes || []).length + ' nodes)');

    fetch(JUG.API_URL + '?batch=' + batchNum + '&batch_size=' + BATCH_SIZE, { signal: signal })
      .then(function(res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function(batchData) {
        if (signal.aborted) return;

        JUG.addBatchToGraph(batchData);
        updateStats(batchData.meta || {});

        // Wait for layout to settle before next batch
        var delay = batchNum <= 3 ? BATCH_DELAY_INITIAL : BATCH_DELAY_NORMAL;
        setTimeout(function() {
          streamBatches(batchNum + 1, totalBatches, signal);
        }, delay);
      })
      .catch(function(err) {
        if (err.name === 'AbortError') return;
        console.warn('[jarvis] Batch ' + batchNum + ' failed:', err.message);
        var delay = batchNum <= 3 ? BATCH_DELAY_INITIAL : BATCH_DELAY_NORMAL;
        setTimeout(function() {
          streamBatches(batchNum + 1, totalBatches, signal);
        }, delay);
      });
  }

  function rebuildClusters() {
    var allNodes = JUG.allNodes || [];
    if (allNodes.length === 0) return;

    var domainGroups = {};
    allNodes.forEach(function(n) {
      var domain = (n.data || {}).domain || '_ungrouped';
      if (!domainGroups[domain]) domainGroups[domain] = [];
      domainGroups[domain].push(n.data.id);
    });

    var clusters = [];
    Object.keys(domainGroups).forEach(function(domain) {
      var ids = domainGroups[domain];
      if (ids.length < 3) return;

      var color = '#6366f1';
      for (var i = 0; i < allNodes.length; i++) {
        if (allNodes[i].data.type === 'domain' && allNodes[i].data.domain === domain) {
          color = JUG.getNodeColor(allNodes[i].data);
          break;
        }
      }

      clusters.push({
        id: 'cluster_' + domain,
        level: 'l1',
        member_ids: ids,
        domain: domain,
        color: color,
        label: domain,
      });
    });

    JUG.clearClusters();
    JUG.buildClusters(clusters, allNodes);
    if (JUG.checkZoomLevel) JUG.checkZoomLevel();
  }

  function updateStats(meta) {
    setText('s-dom', meta.domain_count || 0);
    setText('s-mem', meta.memory_count || 0);
    setText('s-ent', meta.entity_count || 0);
    setText('s-edge', meta.edge_count || 0);
    setText('s-cluster', meta.cluster_count || 0);
    setText('s-nodes', meta.node_count || 0);
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
      setTimeout(fetchGraph, 2000);
    });
  } else {
    setTimeout(fetchGraph, 2000);
  }

  // No auto-refresh — user triggers manually via Reset button or page reload
})();
