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

  JUG.buildGraph = buildGraph;
  JUG.addBatchToGraph = addBatchToGraph;
  JUG.getActiveEdges = function() { return JUG._activeEdges || []; };
})();
