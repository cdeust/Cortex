// Cortex Neural Graph — Graph Orchestrator (2D force-graph)
(function() {
  JUG.allNodes = [];
  JUG._currentEdges = [];
  JUG.edgeNodeMap = {};

  function buildGraph(data) {
    var nodes = data.nodes || [];
    var edges = data.edges || [];

    var filter = JUG.state.activeFilter;
    var query = (JUG.state.searchQuery || '').toLowerCase();

    // Filter nodes — structural nodes always pass, collapsed nodes hidden by default
    var expandedParents = JUG._expandedParents || {};
    var filteredNodes = nodes.filter(function(n) {
      // Collapsed degree-1 leaves: only show if parent is expanded
      if (n.collapsed && !expandedParents[n._parentId]) return false;

      var isStructural = JUG.STRUCTURAL_TYPES && JUG.STRUCTURAL_TYPES[n.type];
      if (isStructural) return true;
      if (filter === 'methodology' && (n.type === 'memory' || n.type === 'entity' || n.type === 'bridge-entity' || n.type === 'topic' || n.type === 'discussion')) return false;
      if (filter === 'memories' && n.type !== 'memory' && n.type !== 'topic') return false;
      if (filter === 'knowledge' && n.type !== 'entity' && n.type !== 'bridge-entity') return false;
      if (filter === 'discussions' && n.type !== 'discussion') return false;
      if (filter === 'emotional' && !(n.type === 'memory' && n.emotion && n.emotion !== 'neutral')) return false;
      if (filter === 'protected' && !n.isProtected) return false;
      if (filter === 'hot' && (n.heat === undefined || n.heat < 0.5)) return false;
      if (filter === 'global' && !n.isGlobal) return false;
      if (query && (n.label || '').toLowerCase().indexOf(query) < 0 &&
          (n.domain || '').toLowerCase().indexOf(query) < 0 &&
          (n.content || '').toLowerCase().indexOf(query) < 0) return false;
      return true;
    });

    // Apply domain/emotion filters
    if (JUG._applyExtraFilters) {
      filteredNodes = JUG._applyExtraFilters(filteredNodes);
    }

    // Build node ID set
    var nodeIds = {};
    filteredNodes.forEach(function(n) { nodeIds[n.id] = true; });

    // Filter edges (source/target may be objects after force-graph mutation)
    var filteredEdges = edges.filter(function(e) {
      var sid = typeof e.source === 'object' ? e.source.id : e.source;
      var tid = typeof e.target === 'object' ? e.target.id : e.target;
      return nodeIds[sid] && nodeIds[tid];
    });

    // Store for monitor/detail panel
    JUG.allNodes = filteredNodes.map(function(n) { return { data: n, type: n.type }; });

    // Build edge node map
    var idToIdx = {};
    filteredNodes.forEach(function(n, i) { idToIdx[n.id] = i; });

    JUG.edgeNodeMap = {};
    var activeEdges = [];
    filteredEdges.forEach(function(e, ei) {
      var sid = typeof e.source === 'object' ? e.source.id : e.source;
      var tid = typeof e.target === 'object' ? e.target.id : e.target;
      var si = idToIdx[sid];
      var ti = idToIdx[tid];
      if (si !== undefined && ti !== undefined) {
        activeEdges.push({
          srcIdx: si, tgtIdx: ti,
          weight: e.weight || 0.3,
          type: e.type || 'default'
        });
        if (!JUG.edgeNodeMap[si]) JUG.edgeNodeMap[si] = [];
        if (!JUG.edgeNodeMap[ti]) JUG.edgeNodeMap[ti] = [];
        JUG.edgeNodeMap[si].push(ei);
        JUG.edgeNodeMap[ti].push(ei);
      }
    });
    JUG._activeEdges = activeEdges;

    // Log to monitor
    if (JUG.logNodes) JUG.logNodes(filteredNodes);

    // Send to renderer
    JUG.setGraphData(filteredNodes, filteredEdges);

    console.log('[cortex] Graph: ' + filteredNodes.length + ' nodes, ' + filteredEdges.length + ' edges');
  }

  function addBatchToGraph(batchData) {
    var newNodes = batchData.nodes || [];
    var newEdges = batchData.edges || [];
    if (newNodes.length === 0) return;

    // Merge into lastData
    if (JUG.state.lastData) {
      JUG.state.lastData.nodes = (JUG.state.lastData.nodes || []).concat(newNodes);
      JUG.state.lastData.edges = (JUG.state.lastData.edges || []).concat(newEdges);
    }

    // Full rebuild with merged data
    if (JUG.state.lastData) buildGraph(JUG.state.lastData);

    if (JUG.logNodes) JUG.logNodes(newNodes);
    console.log('[cortex] +' + newNodes.length + ' nodes');
  }

  // State listeners
  JUG.on('state:activeFilter', function() {
    if (JUG.state.lastData) buildGraph(JUG.state.lastData);
  });
  JUG.on('state:searchQuery', function() {
    if (JUG.state.lastData) buildGraph(JUG.state.lastData);
  });

  // ── Expand/collapse degree-1 children ──
  JUG._expandedParents = {};

  JUG.toggleExpand = function(parentId) {
    if (JUG._expandedParents[parentId]) {
      delete JUG._expandedParents[parentId];
    } else {
      JUG._expandedParents[parentId] = true;
      // Position collapsed children around parent.
      // For large sets (topics with 50+ memories), use a spiral layout
      // so children don't overlap each other.
      if (JUG.state.lastData) {
        var nodes = JUG.state.lastData.nodes || [];
        var parent = null;
        for (var i = 0; i < nodes.length; i++) {
          if (nodes[i].id === parentId) { parent = nodes[i]; break; }
        }
        if (parent) {
          var children = nodes.filter(function(n) { return n._parentId === parentId; });
          var count = children.length;
          // Sort by heat descending so hottest memories are closest
          children.sort(function(a, b) { return (b.heat || 0) - (a.heat || 0); });
          var px = parent.x || 0;
          var py = parent.y || 0;

          if (count <= 20) {
            // Small set: simple ring
            var radius = 18 + count * 1.2;
            for (var j = 0; j < count; j++) {
              var angle = (2 * Math.PI * j) / count;
              children[j].x = px + Math.cos(angle) * radius;
              children[j].y = py + Math.sin(angle) * radius;
              children[j].fx = children[j].x;
              children[j].fy = children[j].y;
            }
          } else {
            // Large set: Archimedean spiral — no overlaps
            var spacing = 5;
            for (var j = 0; j < count; j++) {
              var t = j * 0.5;
              var r = spacing + t * 2.2;
              children[j].x = px + Math.cos(t) * r;
              children[j].y = py + Math.sin(t) * r;
              children[j].fx = children[j].x;
              children[j].fy = children[j].y;
            }
          }

          // Mark for fade-in animation
          var fadeIds = {};
          for (var k = 0; k < count; k++) fadeIds[children[k].id] = true;
          JUG._fadeInNodes = fadeIds;
          JUG._fadeInStart = Date.now();
          JUG._fadeInDuration = 800;

          // Release pins after layout settles
          setTimeout(function() {
            for (var k = 0; k < children.length; k++) {
              delete children[k].fx;
              delete children[k].fy;
            }
          }, 1200);
        }
      }
    }
    // Rebuild to apply filter change
    if (JUG.state.lastData) buildGraph(JUG.state.lastData);
  };

  // Phase-append entry point used by the /api/graph/phase loader.
  // Deduplicates on node.id and on (source,target,type) so repeated
  // applies are a no-op. Coalesces rebuilds with requestAnimationFrame
  // so a burst of phase applies yields at most one redraw per frame.
  JUG._existingIdSet = null;
  JUG._existingEdgeSet = null;
  JUG._rebuildQueued = false;

  function _edgeKey(e) {
    var s = typeof e.source === 'object' ? e.source.id : e.source;
    var t = typeof e.target === 'object' ? e.target.id : e.target;
    return s + '' + t + '' + (e.type || e.kind || 'default');
  }

  function _seedSets() {
    if (JUG._existingIdSet && JUG._existingEdgeSet) return;
    JUG._existingIdSet = {};
    JUG._existingEdgeSet = {};
    var d = JUG.state.lastData || {};
    (d.nodes || []).forEach(function(n){ JUG._existingIdSet[n.id] = true; });
    (d.edges || []).forEach(function(e){ JUG._existingEdgeSet[_edgeKey(e)] = true; });
  }

  function _scheduleRebuild() {
    if (JUG._rebuildQueued) return;
    JUG._rebuildQueued = true;
    var run = function() {
      JUG._rebuildQueued = false;
      if (JUG.state.lastData) buildGraph(JUG.state.lastData);
    };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run);
    else setTimeout(run, 16);
  }

  // Running totals kept on the JUG namespace so appendGraphDelta
  // stays O(batch_size) instead of O(N_accumulated) per call. Reset
  // by _seedSets when lastData is replaced wholesale.
  JUG._statCounts = JUG._statCounts || { domain: 0, memory: 0, discussion: 0,
                                          totalNodes: 0, totalEdges: 0 };

  JUG.appendGraphDelta = function(nodes, edges) {
    nodes = nodes || []; edges = edges || [];
    if (!JUG.state.lastData) {
      JUG.state.lastData = { nodes: [], edges: [], links: [], meta: { schema: 'workflow_graph.v1' } };
      JUG._statCounts = { domain: 0, memory: 0, discussion: 0,
                          totalNodes: 0, totalEdges: 0 };
    }
    _seedSets();
    // Track which items were ACTUALLY added so subscribers can
    // process the delta in O(batch_size) instead of re-scanning the
    // accumulated state.lastData. With 114 SSE chunks growing to
    // 135 k nodes, re-scanning the full set per batch is ~9 billion
    // iterations — that OOMs the tab. The delta payload keeps the
    // hot path O(1000).
    //
    // Memory cap REMOVED — user requirement: every node must be
    // clickable / inspectable, including the cold-tail memories
    // and symbols. The per-batch loop is O(batch_size) thanks to
    // the dedup map, and the running counters never recompute
    // O(N) again, so even on a 600 k+ accumulated graph the per-
    // batch work stays bounded by the SSE batch chunk (≤ 1000).
    var addedNodes = [];
    var addedEdges = [];
    var c = JUG._statCounts;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!n || !n.id || JUG._existingIdSet[n.id]) continue;
      JUG._existingIdSet[n.id] = true;
      JUG.state.lastData.nodes.push(n);
      addedNodes.push(n);
      var kind = n.kind || n.type || '';
      if (kind === 'domain') c.domain++;
      else if (kind === 'memory') c.memory++;
      else if (kind === 'discussion') c.discussion++;
      c.totalNodes++;
    }
    for (var j = 0; j < edges.length; j++) {
      var e = edges[j];
      if (!e) continue;
      var k = _edgeKey(e);
      if (JUG._existingEdgeSet[k]) continue;
      JUG._existingEdgeSet[k] = true;
      JUG.state.lastData.edges.push(e);
      JUG.state.lastData.links.push(e);
      addedEdges.push(e);
      c.totalEdges++;
    }
    // Sidebar update — O(1) DOM writes, no node scan.
    try {
      var setTxt = function(id, v){ var el = document.getElementById(id); if(el) el.textContent = v; };
      var entityCount = c.totalNodes - c.domain - c.memory;
      setTxt('s-dom',   c.domain);
      setTxt('s-mem',   c.memory);
      setTxt('s-ent',   entityCount);
      setTxt('s-nodes', c.totalNodes);
      setTxt('s-edge',  c.totalEdges);
      setTxt('s-disc',  c.discussion);
    } catch(_e){}
    // Legacy force-graph rebuild — only run when the workflow-graph
    // renderer (the one the bridge installs and the page actually
    // shows) is NOT active. With ~135 k nodes accumulated, calling
    // buildGraph on every batch rebuilds a hidden canvas at a cost
    // that alone OOMs the tab. The bridge sets
    // window.JUG.__wfgActive=true on first seed so this guard kicks
    // in for every subsequent append.
    if ((addedNodes.length || addedEdges.length) && !(JUG.__wfgActive)) {
      _scheduleRebuild();
    }
    // Fire the legacy event bus with a delta payload so the bridge
    // can append O(batch_size) instead of re-diffing N accumulated.
    if (typeof JUG.emit === 'function') {
      try {
        JUG.emit('state:lastData', {
          value: JUG.state.lastData,
          delta: { nodes: addedNodes, edges: addedEdges },
          old: null,
        });
      } catch(_e){}
    }
  };

  JUG.buildGraph = buildGraph;
  JUG.addBatchToGraph = addBatchToGraph;
  JUG.getActiveEdges = function() { return JUG._activeEdges || []; };
})();
