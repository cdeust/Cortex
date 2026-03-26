// Cortex Neural Graph — Incremental Batch Addition
(function() {

  function addBatchToGraph(batchData) {
    var newNodes = batchData.nodes || [];
    var newEdges = batchData.edges || [];
    if (newNodes.length === 0) return;

    var filter = JUG.state.activeFilter;
    var query = (JUG.state.searchQuery || '').toLowerCase();

    var filteredNodes = newNodes.filter(function(n) {
      if (filter === 'methodology' && (n.type === 'memory' || n.type === 'entity')) return false;
      if (filter === 'memories' && n.type !== 'memory' && n.type !== 'domain') return false;
      if (filter === 'knowledge' && n.type !== 'entity' && n.type !== 'domain') return false;
      if (query && (n.label || '').toLowerCase().indexOf(query) < 0 &&
          (n.domain || '').toLowerCase().indexOf(query) < 0) return false;
      return true;
    });
    if (filteredNodes.length === 0) return;

    // Build ID->idx map of existing nodes
    var idToIdx = {};
    JUG.allNodes.forEach(function(n, i) { idToIdx[n.data.id] = i; });

    // Create Three.js groups, position near parent domain
    var addedNodes = [];
    filteredNodes.forEach(function(n) {
      var group = JUG.createNode(n);
      JUG.nodeGroup.add(group);

      // Spawn near parent domain hub
      var parentDomain = n.domain || '';
      for (var ei = 0; ei < JUG.allNodes.length; ei++) {
        if (JUG.allNodes[ei].data.type === 'domain' && JUG.allNodes[ei].data.domain === parentDomain) {
          var pp = JUG.allNodes[ei].group.position;
          group.position.set(
            pp.x + (Math.random() - 0.5) * 60,
            pp.y + (Math.random() - 0.5) * 60,
            pp.z + (Math.random() - 0.5) * 60
          );
          break;
        }
      }

      var idx = JUG.allNodes.length;
      var entry = { group: group, data: n, type: n.type };
      JUG.allNodes.push(entry);
      addedNodes.push(entry);
      idToIdx[n.id] = idx;
    });

    // Resolve edge indices for new edges
    var newEdgeStructs = [];
    newEdges.forEach(function(e) {
      var si = idToIdx[e.source];
      var ti = idToIdx[e.target];
      if (si !== undefined && ti !== undefined && si !== ti) {
        newEdgeStructs.push({
          srcIdx: si, tgtIdx: ti,
          weight: e.weight || 0.3,
          type: e.type || 'default',
        });
      }
    });

    // Append to layout simulation (no reinit)
    JUG.addToLayout(addedNodes, newEdgeStructs);

    // Append only new edges to the visual buffer (no clear/rebuild)
    JUG.appendEdges(newEdges, JUG.allNodes);

    // Track cumulative data for filter rebuilds
    if (JUG.state.lastData) {
      JUG.state.lastData.nodes = (JUG.state.lastData.nodes || []).concat(filteredNodes);
      JUG.state.lastData.edges = (JUG.state.lastData.edges || []).concat(newEdges);
    }

    // Log to monitor
    if (JUG.logNodes) JUG.logNodes(filteredNodes);

    console.log('[cortex] +' + filteredNodes.length + ' nodes -> ' + JUG.allNodes.length + ' total');
  }

  JUG.addBatchToGraph = addBatchToGraph;
})();
