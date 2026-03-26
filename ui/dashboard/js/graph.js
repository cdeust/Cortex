// Cortex Memory Dashboard — Graph Orchestrator
// DNA double-helix layout: two interleaved helical strands with cross-rungs.
// Entities form the backbone spheres, memories branch off as side chains.

(function() {
  JMD.allNodes = [];

  // ═══════════════════════════════════════════════════════════════
  // DATA → NODES + HELIX LAYOUT
  // ═══════════════════════════════════════════════════════════════

  function buildGraph(data) {
    clearGraph();

    var filter = JMD.state.activeFilter;
    var query = (JMD.state.searchQuery || '').toLowerCase();
    var memories = data.hot_memories || [];
    var entities = data.entities || [];

    // Memory nodes
    if (filter !== 'entity') {
      memories.forEach(function(m) {
        if (filter !== 'all' && m.store_type !== filter) return;
        if (query && !matchMemory(m, query)) return;
        var group = JMD.createMemoryNode(m);
        JMD.nodeGroup.add(group);
        JMD.allNodes.push({
          group: group, data: m,
          isEntity: false, storeType: m.store_type || 'episodic',
          vx: 0, vy: 0, vz: 0,
        });
      });
    }

    // Entity nodes
    if (filter === 'all' || filter === 'entity') {
      entities.forEach(function(e) {
        if (query && !matchEntity(e, query)) return;
        var group = JMD.createEntityNode(e);
        JMD.nodeGroup.add(group);
        JMD.allNodes.push({
          group: group, data: e,
          isEntity: true, storeType: 'entity',
          vx: 0, vy: 0, vz: 0,
        });
      });
    }

    // Build edges (needed for memory-entity connections)
    JMD.buildEdges(data);

    // Apply DNA helix layout
    JMD.layoutDNAHelix();

    // Ensure renderer is sized to actual container before fitting camera
    if (JMD.resizeToContainer) JMD.resizeToContainer();

    // Fit camera to show everything immediately
    JMD.fitCameraImmediate();

    console.log('[cortex] Graph: ' + JMD.allNodes.length + ' nodes, DNA helix');

    if (!JMD._animating) { JMD._animating = true; JMD.startAnimation(); }
  }

  function clearGraph() {
    while (JMD.nodeGroup.children.length) {
      var child = JMD.nodeGroup.children[0];
      JMD.nodeGroup.remove(child);
      child.traverse(function(obj) {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (obj.material.map) obj.material.map.dispose();
          obj.material.dispose();
        }
      });
    }
    // Clear backbone
    JMD.clearHelixMeshes();

    JMD.allNodes = [];
    JMD.clearEdges();
    JMD.highlightMesh.visible = false;
  }

  function matchMemory(m, q) {
    return ((m.content || '') + ' ' + (m.domain || '') + ' ' + (m.tags || []).join(' ')).toLowerCase().indexOf(q) >= 0;
  }
  function matchEntity(e, q) {
    return ((e.name || '') + ' ' + (e.type || '') + ' ' + (e.domain || '')).toLowerCase().indexOf(q) >= 0;
  }

  // ═══════════════════════════════════════════════════════════════
  // EVENT LISTENERS
  // ═══════════════════════════════════════════════════════════════

  JMD.on('data:refresh', function(data) {
    if (JMD.state.activeView === 'graph') buildGraph(data);
  });
  JMD.on('state:activeFilter', function() {
    if (JMD.state.lastData) buildGraph(JMD.state.lastData);
  });
  JMD.on('state:searchQuery', function() {
    if (JMD.state.lastData) buildGraph(JMD.state.lastData);
  });
  JMD.on('state:activeView', function(e) {
    if (e.value === 'graph') {
      JMD.renderer.domElement.style.display = 'block';
      if (JMD.state.lastData) buildGraph(JMD.state.lastData);
    } else {
      JMD.renderer.domElement.style.display = 'none';
    }
  });

  JMD.buildGraph = buildGraph;
})();
