// Cortex Neural Graph — Graph Orchestrator
(function() {
  var frame = 0;
  var animating = false;
  var lastInteraction = Date.now();

  JUG.allNodes = [];

  function buildGraph(data) {
    clearGraph();

    var nodes = data.nodes || [];
    var edges = data.edges || [];
    var clusters = data.clusters || [];

    var filter = JUG.state.activeFilter;
    var query = (JUG.state.searchQuery || '').toLowerCase();

    // Filter nodes by source type
    var filteredNodes = nodes.filter(function(n) {
      if (filter === 'methodology' && (n.type === 'memory' || n.type === 'entity')) return false;
      if (filter === 'memories' && n.type !== 'memory' && n.type !== 'domain') return false;
      if (filter === 'knowledge' && n.type !== 'entity' && n.type !== 'domain') return false;
      if (filter === 'emotional' && !(n.type === 'memory' && n.emotion && n.emotion !== 'neutral') && n.type !== 'domain') return false;
      if (filter === 'protected' && !n.isProtected && n.type !== 'domain') return false;
      if (filter === 'hot' && (n.heat === undefined || n.heat < 0.5) && n.type !== 'domain') return false;
      if (query && (n.label || '').toLowerCase().indexOf(query) < 0 &&
          (n.domain || '').toLowerCase().indexOf(query) < 0 &&
          (n.content || '').toLowerCase().indexOf(query) < 0) return false;
      return true;
    });

    // Apply domain/emotion dropdown filters
    if (JUG._applyExtraFilters) {
      filteredNodes = JUG._applyExtraFilters(filteredNodes);
    }

    var nodeIds = {};
    filteredNodes.forEach(function(n) { nodeIds[n.id] = true; });

    // Filter edges to only include visible nodes
    var filteredEdges = edges.filter(function(e) {
      return nodeIds[e.source] && nodeIds[e.target];
    });

    // Create Three.js nodes
    filteredNodes.forEach(function(n) {
      var group = JUG.createNode(n);
      JUG.nodeGroup.add(group);
      JUG.allNodes.push({
        group: group,
        data: n,
        type: n.type,
      });
    });

    // Log to monitor
    if (JUG.logNodes) JUG.logNodes(filteredNodes);

    // Build edge index structures
    var edgeStructs = [];
    var idToIdx = {};
    JUG.allNodes.forEach(function(n, i) { idToIdx[n.data.id] = i; });

    filteredEdges.forEach(function(e) {
      var si = idToIdx[e.source];
      var ti = idToIdx[e.target];
      if (si !== undefined && ti !== undefined) {
        edgeStructs.push({
          srcIdx: si, tgtIdx: ti,
          weight: e.weight || 0.3,
          type: e.type || 'default',
          color: JUG.getEdgeColor(e),
          isCausal: e.isCausal || false,
          source: e.source,
          target: e.target,
        });
      }
    });

    JUG.buildEdges(filteredEdges, JUG.allNodes);

    // Initialize layout
    JUG.initLayout(JUG.allNodes, edgeStructs, clusters);

    // Warm up
    JUG.warmUp(200);

    // Apply positions
    applyPositions();

    // Build clusters after positions are set
    JUG.buildClusters(clusters, JUG.allNodes);

    // Resize + fit camera
    if (JUG.resizeToContainer) JUG.resizeToContainer();
    fitCamera();

    if (!animating) { animating = true; animate(); }
  }

  function applyPositions() {
    var positions = JUG.getLayoutPositions();
    for (var i = 0; i < JUG.allNodes.length && i < positions.length; i++) {
      var p = positions[i];
      JUG.allNodes[i].group.position.set(p.x, p.y, p.z);
    }
  }

  function fitCamera() {
    if (JUG.allNodes.length === 0) return;
    var minX = Infinity, maxX = -Infinity;
    var minY = Infinity, maxY = -Infinity;
    var minZ = Infinity, maxZ = -Infinity;

    JUG.allNodes.forEach(function(n) {
      var p = n.group.position;
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
      if (p.z < minZ) minZ = p.z;
      if (p.z > maxZ) maxZ = p.z;
    });

    var cx = (minX + maxX) / 2;
    var cy = (minY + maxY) / 2;
    var cz = (minZ + maxZ) / 2;
    var bboxRadius = Math.sqrt(
      (maxX - minX) * (maxX - minX) +
      (maxY - minY) * (maxY - minY) +
      (maxZ - minZ) * (maxZ - minZ)
    ) / 2;
    var fov = JUG.camera.fov * Math.PI / 180;
    var dist = Math.max(200, (bboxRadius / Math.sin(fov / 2)) * 1.3);

    JUG.camera.position.set(cx, cy, cz + dist);
    JUG.controls.target.set(cx, cy, cz);
    JUG.controls.update();
  }

  function clearGraph() {
    while (JUG.nodeGroup.children.length) {
      var child = JUG.nodeGroup.children[0];
      JUG.nodeGroup.remove(child);
      child.traverse(function(obj) {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (obj.material.map) obj.material.map.dispose();
          obj.material.dispose();
        }
      });
    }
    JUG.allNodes = [];
    JUG.clearEdges();
    JUG.clearClusters();
    JUG.highlightMesh.visible = false;
  }

  function updateLabels() {
    var camPos = JUG.camera.position;
    var showDist = 250;

    for (var i = 0; i < JUG.allNodes.length; i++) {
      var nd = JUG.allNodes[i];
      var label = nd.group.getObjectByName('label');
      var domLabel = nd.group.getObjectByName('domainLabel');

      if (label) {
        var nodePos = nd.group.position;
        var dist = camPos.distanceTo(nodePos);
        var isType = nd.type === 'domain' || nd.type === 'entity';
        label.visible = isType ? dist < showDist * 1.5 : dist < showDist;
        if (label.visible) label.lookAt(camPos);
      }
      if (domLabel) {
        domLabel.lookAt(camPos);
        domLabel.visible = true;
      }
    }
  }

  function animate() {
    requestAnimationFrame(animate);
    frame++;

    var idleTime = Date.now() - lastInteraction;
    JUG.controls.autoRotate = JUG.state.selectedId === null && idleTime > 4000;
    JUG.controls.update();

    // Layout tick
    if (JUG.isLayoutRunning()) {
      JUG.tickLayout();
      applyPositions();
    }

    // Edge + particle updates
    JUG.updateEdgePositions();
    if (frame % 2 === 0) JUG.updateFlowParticles();
    if (frame % 3 === 0 && JUG.updateDust) JUG.updateDust();

    // Labels
    if (frame % 5 === 0) updateLabels();

    // Entity rotation + emotion ring pulse
    var time = performance.now() * 0.001;
    JUG.allNodes.forEach(function(nd) {
      if ((nd.type === 'entity' || nd.type === 'recurring-pattern') && nd.group.userData.coreMesh) {
        nd.group.userData.coreMesh.rotation.y += 0.004;
      }
      // Pulse emotion rings
      var ring = nd.group.getObjectByName('emotionRing');
      if (ring && ring.userData.pulseSpeed) {
        var pulse = 0.5 + 0.5 * Math.sin(time * ring.userData.pulseSpeed);
        ring.material.opacity = ring.userData.baseOpacity * (0.4 + pulse * 0.6);
        ring.rotation.x += 0.008;
        ring.rotation.z += 0.005;
      }
    });

    // Zoom level check
    if (frame % 10 === 0 && JUG.checkZoomLevel) JUG.checkZoomLevel();

    // Selective bloom render
    JUG.scene.traverse(JUG.darkenNonBloomed);
    JUG.bloomComposer.render();
    JUG.scene.traverse(JUG.restoreMaterials);
    JUG.composer.render();
  }

  JUG.resetCamera = function() {
    JUG.state.selectedId = null;
    JUG.resetEdgeHighlight();
    JUG.allNodes.forEach(function(n) { setGroupOpacity(n.group, 1.0); });

    var startPos = JUG.camera.position.clone();
    var startTarget = JUG.controls.target.clone();

    // Compute target
    if (JUG.allNodes.length === 0) return;
    var cx = 0, cy = 0, cz = 0;
    JUG.allNodes.forEach(function(n) {
      cx += n.group.position.x;
      cy += n.group.position.y;
      cz += n.group.position.z;
    });
    cx /= JUG.allNodes.length;
    cy /= JUG.allNodes.length;
    cz /= JUG.allNodes.length;

    var targetLook = new THREE.Vector3(cx, cy, cz);
    var targetPos = new THREE.Vector3(cx, cy, cz + 500);
    var startTime = performance.now();

    function step() {
      var t = Math.min((performance.now() - startTime) / 1000, 1);
      var e = 1 - Math.pow(1 - t, 3);
      JUG.camera.position.lerpVectors(startPos, targetPos, e);
      JUG.controls.target.lerpVectors(startTarget, targetLook, e);
      if (t < 1) requestAnimationFrame(step);
    }
    step();
  };

  function setGroupOpacity(group, opacity) {
    group.traverse(function(obj) {
      if (obj.material) {
        if (obj.material._origOpacity === undefined) obj.material._origOpacity = obj.material.opacity;
        obj.material.opacity = obj.material._origOpacity * opacity;
      }
    });
  }

  // Track interaction
  window.addEventListener('mousemove', function() { lastInteraction = Date.now(); });
  window.addEventListener('click', function() { lastInteraction = Date.now(); });

  // State listeners
  JUG.on('state:activeFilter', function() {
    if (JUG.state.lastData) buildGraph(JUG.state.lastData);
  });
  JUG.on('state:searchQuery', function() {
    if (JUG.state.lastData) buildGraph(JUG.state.lastData);
  });

  // ═══════════════════════════════════════════════════════════════
  // INCREMENTAL BATCH ADDITION — appends to running simulation
  // ═══════════════════════════════════════════════════════════════

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

    // Build ID→idx map of existing nodes
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

    console.log('[cortex] +' + filteredNodes.length + ' nodes → ' + JUG.allNodes.length + ' total');
  }

  JUG.buildGraph = buildGraph;
  JUG.addBatchToGraph = addBatchToGraph;
  JUG.setGroupOpacity = setGroupOpacity;
})();
