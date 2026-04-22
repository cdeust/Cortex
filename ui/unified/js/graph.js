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

  JUG.appendGraphDelta = function(nodes, edges) {
    nodes = nodes || []; edges = edges || [];
    if (!JUG.state.lastData) {
      JUG.state.lastData = { nodes: [], edges: [], links: [], meta: { schema: 'workflow_graph.v1' } };
    }
    _seedSets();
    var added = 0, addedE = 0;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!n || !n.id || JUG._existingIdSet[n.id]) continue;
      JUG._existingIdSet[n.id] = true;
      JUG.state.lastData.nodes.push(n);
      added++;
    }
    for (var j = 0; j < edges.length; j++) {
      var e = edges[j];
      if (!e) continue;
      var k = _edgeKey(e);
      if (JUG._existingEdgeSet[k]) continue;
      JUG._existingEdgeSet[k] = true;
      JUG.state.lastData.edges.push(e);
      JUG.state.lastData.links.push(e);
      addedE++;
    }
    if (added || addedE) _scheduleRebuild();
    // Recompute sidebar stats live from the cumulative nodes array.
    // Without this the legend reads `meta.*_count` from the ONE
    // /api/graph snapshot fetched at page load — which can race and
    // report zero for categories that arrive later (memories land in
    // L5, symbols in L6:*). Reading from lastData.nodes is always
    // current regardless of which phases have landed.
    try {
      var nl = JUG.state.lastData.nodes;
      var counts = { domain: 0, memory: 0, discussion: 0 };
      for (var ci = 0; ci < nl.length; ci++) {
        var k = nl[ci].kind || nl[ci].type || '';
        counts[k] = (counts[k] || 0) + 1;
      }
      var entityCount = nl.length - (counts.domain || 0) - (counts.memory || 0);
      var setTxt = function(id, v){ var el = document.getElementById(id); if(el) el.textContent = v; };
      setTxt('s-dom',   counts.domain || 0);
      setTxt('s-mem',   counts.memory || 0);
      setTxt('s-ent',   entityCount);
      setTxt('s-nodes', nl.length);
      setTxt('s-edge',  JUG.state.lastData.edges.length);
      setTxt('s-disc',  counts.discussion || 0);
    } catch(_e){}
    // Fire the legacy event bus so any listener (bridge, sidebar)
    // sees the updated data without re-fetching. The reactive setter
    // in state.js emits `{value, old}` — match that shape.
    if (typeof JUG.emit === 'function') {
      try { JUG.emit('state:lastData', { value: JUG.state.lastData, old: null }); } catch(_e){}
    }
  };

  JUG.buildGraph = buildGraph;
  JUG.addBatchToGraph = addBatchToGraph;
  JUG.getActiveEdges = function() { return JUG._activeEdges || []; };
})();
