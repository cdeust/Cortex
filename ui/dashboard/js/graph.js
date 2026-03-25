// Cortex Memory Dashboard — Graph Orchestrator
// DNA double-helix layout: two interleaved helical strands with cross-rungs.
// Entities form the backbone spheres, memories branch off as side chains.

(function() {
  var raycaster = new THREE.Raycaster();
  var mouse = new THREE.Vector2();
  var hoveredNode = null;
  var selectedIdx = -1;
  var frame = 0;
  var animating = false;
  var lastInteraction = Date.now();

  // Helix backbone geometry (rendered as tube curves)
  var helixMeshes = [];

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
    layoutDNAHelix();

    // Ensure renderer is sized to actual container before fitting camera
    if (JMD.resizeToContainer) JMD.resizeToContainer();

    // Fit camera to show everything immediately
    fitCameraImmediate();

    console.log('[cortex] Graph: ' + JMD.allNodes.length + ' nodes, DNA helix');

    if (!animating) { animating = true; animate(); }
  }

  // ═══════════════════════════════════════════════════════════════
  // DNA DOUBLE-HELIX LAYOUT
  // ═══════════════════════════════════════════════════════════════
  //
  // The double helix is built like real DNA:
  //   - Two helical strands (backbone curves) rotate around a central axis
  //   - Strands are 180° apart (phase offset = PI)
  //   - Each "rung" connects nodes on opposite strands
  //   - Rotation: ~30° per step (like real DNA: 36° per base pair)
  //   - Vertical pitch: proportional to node count
  //
  // Entities are placed as the backbone nodes (the big spheres on the helix).
  // Memories are placed as "base pairs" branching inward between the strands.

  function layoutDNAHelix() {
    var nodes = JMD.allNodes;
    var N = nodes.length;
    if (N === 0) return;

    // Separate into entities and memories
    var entityIndices = [];
    var memoryIndices = [];
    nodes.forEach(function(n, i) {
      if (n.isEntity) entityIndices.push(i);
      else memoryIndices.push(i);
    });

    // Sort entities by heat/connectivity for interesting placement
    var edgeMap = JMD.edgeNodeMap || {};
    entityIndices.sort(function(a, b) {
      return (edgeMap[b] || []).length - (edgeMap[a] || []).length;
    });

    // ── Helix parameters ──
    var helixR = 60;                // radius of each strand from center axis
    var rotPerStep = 30;            // degrees rotation per step (DNA = 36°)
    var verticalSpacing = 6;        // vertical distance between rows
    var totalRows = Math.max(entityIndices.length, Math.ceil(memoryIndices.length / 2));
    var helixHeight = totalRows * verticalSpacing;

    // Center the helix vertically
    var yOffset = -helixHeight / 2;

    // ── Place entities on the two helix strands ──
    entityIndices.forEach(function(nodeIdx, i) {
      var row = i;
      var strand = i % 2; // alternate: strand 0 and strand 1
      var actualRow = Math.floor(i / 2);

      var angle = (actualRow * rotPerStep) * Math.PI / 180;
      var phase = strand * Math.PI; // 180° offset for second strand

      var x = Math.cos(angle + phase) * helixR;
      var y = actualRow * verticalSpacing + yOffset;
      var z = Math.sin(angle + phase) * helixR;

      nodes[nodeIdx].group.position.set(x, y, z);
    });

    // ── Place memories as "base pairs" between the strands ──
    var edges = JMD.getActiveEdges ? JMD.getActiveEdges() : [];

    memoryIndices.forEach(function(memIdx, mi) {
      // Find connected entity
      var bestEntity = -1;
      var bestWeight = -1;
      var memEdges = edgeMap[memIdx] || [];

      memEdges.forEach(function(ei) {
        var e = edges[ei];
        if (!e) return;
        var otherIdx = e.srcIdx === memIdx ? e.tgtIdx : e.srcIdx;
        if (nodes[otherIdx] && nodes[otherIdx].isEntity) {
          if (e.weight > bestWeight) {
            bestWeight = e.weight;
            bestEntity = otherIdx;
          }
        }
      });

      if (bestEntity >= 0) {
        // Place between the entity and the center axis (like DNA base pairs)
        var entPos = nodes[bestEntity].group.position;
        var toCenter = -Math.sign(entPos.x || 0.001);
        var pullIn = 0.3 + Math.random() * 0.4; // 30-70% toward center

        var x = entPos.x * (1 - pullIn) + (Math.random() - 0.5) * 8;
        var y = entPos.y + (Math.random() - 0.5) * verticalSpacing * 0.8;
        var z = entPos.z * (1 - pullIn) + (Math.random() - 0.5) * 8;

        nodes[memIdx].group.position.set(x, y, z);
      } else {
        // No entity connection — place on a third inner helix
        var row = mi;
        var angle = (row * rotPerStep * 0.7) * Math.PI / 180;
        var innerR = helixR * 0.3;

        var x = Math.cos(angle) * innerR;
        var y = (mi / Math.max(1, memoryIndices.length - 1)) * helixHeight + yOffset;
        var z = Math.sin(angle) * innerR;

        nodes[memIdx].group.position.set(x, y, z);
      }
    });

    // ── Build helix backbone curves (visual strands) ──
    buildHelixBackbone(entityIndices, nodes, helixR, rotPerStep, verticalSpacing, yOffset);
  }

  // ── Build visible backbone curves connecting the helix nodes ──
  function buildHelixBackbone(entityIndices, nodes, helixR, rotPerStep, verticalSpacing, yOffset) {
    // Clear old backbone meshes
    helixMeshes.forEach(function(m) {
      JMD.scene.remove(m);
      m.geometry.dispose();
      m.material.dispose();
    });
    helixMeshes = [];

    if (entityIndices.length < 4) return;

    // Collect points for each strand
    var strand0 = [];
    var strand1 = [];

    var maxRow = Math.floor(entityIndices.length / 2);
    for (var row = 0; row <= maxRow + 2; row++) {
      var angle = (row * rotPerStep) * Math.PI / 180;
      var y = row * verticalSpacing + yOffset;

      strand0.push(new THREE.Vector3(
        Math.cos(angle) * helixR,
        y,
        Math.sin(angle) * helixR
      ));
      strand1.push(new THREE.Vector3(
        Math.cos(angle + Math.PI) * helixR,
        y,
        Math.sin(angle + Math.PI) * helixR
      ));
    }

    // Create smooth backbone curves
    if (strand0.length >= 2) {
      var curve0 = new THREE.CatmullRomCurve3(strand0);
      var curve1 = new THREE.CatmullRomCurve3(strand1);

      var tubeMat = new THREE.MeshStandardMaterial({
        color: 0x00d2ff,
        emissive: 0x00d2ff,
        emissiveIntensity: 0.25,
        transparent: true,
        opacity: 0.18,
        roughness: 0.4,
        metalness: 0.3,
      });

      var tube0 = new THREE.Mesh(
        new THREE.TubeGeometry(curve0, strand0.length * 8, 0.6, 6, false),
        tubeMat
      );
      var tube1 = new THREE.Mesh(
        new THREE.TubeGeometry(curve1, strand1.length * 8, 0.6, 6, false),
        tubeMat.clone()
      );

      tube0.layers.enable(JMD.BLOOM_LAYER);
      tube1.layers.enable(JMD.BLOOM_LAYER);

      JMD.scene.add(tube0);
      JMD.scene.add(tube1);
      helixMeshes.push(tube0, tube1);
    }
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
    helixMeshes.forEach(function(m) {
      JMD.scene.remove(m);
      m.geometry.dispose();
      m.material.dispose();
    });
    helixMeshes = [];

    JMD.allNodes = [];
    JMD.clearEdges();
    hoveredNode = null;
    selectedIdx = -1;
    JMD.highlightMesh.visible = false;
  }

  function matchMemory(m, q) {
    return ((m.content || '') + ' ' + (m.domain || '') + ' ' + (m.tags || []).join(' ')).toLowerCase().indexOf(q) >= 0;
  }
  function matchEntity(e, q) {
    return ((e.name || '') + ' ' + (e.type || '') + ' ' + (e.domain || '')).toLowerCase().indexOf(q) >= 0;
  }

  // ═══════════════════════════════════════════════════════════════
  // CAMERA — Always fit all data, no fixed starting position
  // ═══════════════════════════════════════════════════════════════

  function fitCameraImmediate() {
    var nodes = JMD.allNodes;
    if (nodes.length === 0) return;

    // Compute bounding box
    var minX = Infinity, maxX = -Infinity;
    var minY = Infinity, maxY = -Infinity;
    var minZ = Infinity, maxZ = -Infinity;

    nodes.forEach(function(n) {
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

    var spanX = maxX - minX;
    var spanY = maxY - minY;
    var spanZ = maxZ - minZ;
    var maxSpan = Math.max(spanX, spanY, spanZ);

    // Distance to fit the bounding sphere
    // Distance: use bounding sphere radius, pull camera back 2.5x to see everything
    var bboxRadius = Math.sqrt(
      (maxX - minX) * (maxX - minX) +
      (maxY - minY) * (maxY - minY) +
      (maxZ - minZ) * (maxZ - minZ)
    ) / 2;
    var fov = JMD.camera.fov * Math.PI / 180;
    var dist = bboxRadius / Math.sin(fov / 2);
    dist = Math.max(200, dist * 1.3); // 30% padding

    // Place camera looking at the helix from the side (like your reference image)
    JMD.camera.position.set(cx, cy, cz + dist);
    JMD.controls.target.set(cx, cy, cz);
    JMD.controls.update();
  }

  function fitCameraSmooth() {
    var nodes = JMD.allNodes;
    if (nodes.length === 0) return;

    var minX = Infinity, maxX = -Infinity;
    var minY = Infinity, maxY = -Infinity;
    var minZ = Infinity, maxZ = -Infinity;

    nodes.forEach(function(n) {
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
    var fov = JMD.camera.fov * Math.PI / 180;
    var dist = Math.max(200, (bboxRadius / Math.sin(fov / 2)) * 1.3);

    var targetPos = new THREE.Vector3(cx, cy, cz + dist);
    var targetLook = new THREE.Vector3(cx, cy, cz);
    var startPos = JMD.camera.position.clone();
    var startTarget = JMD.controls.target.clone();
    var startTime = performance.now();

    function step() {
      var t = Math.min((performance.now() - startTime) / 1000, 1);
      var e = 1 - Math.pow(1 - t, 3);
      JMD.camera.position.lerpVectors(startPos, targetPos, e);
      JMD.controls.target.lerpVectors(startTarget, targetLook, e);
      if (t < 1) requestAnimationFrame(step);
    }
    step();
  }

  // ═══════════════════════════════════════════════════════════════
  // RAYCASTING
  // ═══════════════════════════════════════════════════════════════

  function getHoveredNode(clientX, clientY) {
    var container = document.getElementById('graph-container');
    if (!container) return null;
    var rect = container.getBoundingClientRect();
    var localX = clientX - rect.left;
    var localY = clientY - rect.top;
    if (localX < 0 || localY < 0 || localX > rect.width || localY > rect.height) return null;
    mouse.x = (localX / rect.width) * 2 - 1;
    mouse.y = -(localY / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, JMD.camera);

    var coreMeshes = [];
    for (var i = 0; i < JMD.allNodes.length; i++) {
      var n = JMD.allNodes[i];
      if (!n.group.visible) continue;
      var core = n.group.userData.coreMesh;
      if (core) coreMeshes.push(core);
    }

    var intersects = raycaster.intersectObjects(coreMeshes, false);
    if (intersects.length > 0) {
      var hit = intersects[0].object;
      for (var j = 0; j < JMD.allNodes.length; j++) {
        if (JMD.allNodes[j].group.userData.coreMesh === hit) {
          return { idx: j, node: JMD.allNodes[j] };
        }
      }
    }
    return null;
  }

  // ═══════════════════════════════════════════════════════════════
  // LABEL VISIBILITY
  // ═══════════════════════════════════════════════════════════════

  function updateLabels() {
    var camPos = JMD.camera.position;
    var showDist = 200;

    for (var i = 0; i < JMD.allNodes.length; i++) {
      var nd = JMD.allNodes[i];
      var label = nd.group.getObjectByName('label');
      if (!label) continue;

      var nodePos = nd.group.position;
      var dist = camPos.distanceTo(nodePos);
      var isHovered = hoveredNode && hoveredNode.idx === i;
      var isSelected = selectedIdx === i;

      label.visible = isHovered || isSelected || (nd.isEntity && dist < showDist * 1.5) || dist < showDist;

      if (label.visible) {
        label.lookAt(camPos);
      }
    }
  }

  // ═══════════════════════════════════════════════════════════════
  // MOUSE EVENTS
  // ═══════════════════════════════════════════════════════════════

  window.addEventListener('mousemove', function(e) {
    lastInteraction = Date.now();
    var hit = getHoveredNode(e.clientX, e.clientY);
    if (hit) {
      document.body.style.cursor = 'pointer';
      hoveredNode = hit;
      JMD.highlightMesh.visible = true;
      JMD.highlightMesh.position.copy(hit.node.group.position);
      JMD.highlightMesh.scale.setScalar(hit.node.group.userData.baseScale * 1.8);
      JMD.highlightNodeEdges(hit.idx);
      JMD.emit('graph:showTooltip', { node: hit.node, x: e.clientX, y: e.clientY });
    } else {
      document.body.style.cursor = 'default';
      JMD.highlightMesh.visible = false;
      if (hoveredNode) {
        hoveredNode = null;
        JMD.resetEdgeHighlight();
        JMD.emit('graph:hideTooltip');
      }
    }
  });

  window.addEventListener('click', function(e) {
    if (e.target.closest('#sidebar, #topbar, #kpi-strip, #bottombar, #panel, #analytics-panel, .overlay-panel')) return;

    var hit = getHoveredNode(e.clientX, e.clientY);
    if (hit) {
      if (selectedIdx === hit.idx) {
        deselectNode();
      } else {
        selectNode(hit.idx, hit.node);
      }
    } else if (selectedIdx >= 0) {
      deselectNode();
    }
  });

  function selectNode(idx, node) {
    selectedIdx = idx;
    JMD.controls.autoRotate = false;
    JMD.highlightNodeEdges(idx);

    var connected = getConnectedSet(idx);
    JMD.allNodes.forEach(function(n, i) {
      setGroupOpacity(n.group, connected[i] ? 1.0 : 0.12);
    });

    JMD.emit('graph:openPanel', node);
  }

  function deselectNode() {
    selectedIdx = -1;
    JMD.controls.autoRotate = Date.now() - lastInteraction > 4000;
    JMD.resetEdgeHighlight();
    JMD.allNodes.forEach(function(n) { setGroupOpacity(n.group, 1.0); });
    JMD.emit('graph:closePanel');
  }

  function getConnectedSet(nodeIdx) {
    var set = {};
    set[nodeIdx] = true;
    var edges = JMD.getActiveEdges ? JMD.getActiveEdges() : [];
    edges.forEach(function(e) {
      if (e.srcIdx === nodeIdx) set[e.tgtIdx] = true;
      if (e.tgtIdx === nodeIdx) set[e.srcIdx] = true;
    });
    return set;
  }

  function setGroupOpacity(group, opacity) {
    group.traverse(function(obj) {
      if (obj.material) {
        if (obj.material._origOpacity === undefined) obj.material._origOpacity = obj.material.opacity;
        obj.material.opacity = obj.material._origOpacity * opacity;
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════
  // ANIMATION LOOP
  // ═══════════════════════════════════════════════════════════════

  function animate() {
    requestAnimationFrame(animate);
    frame++;

    var idleTime = Date.now() - lastInteraction;
    JMD.controls.autoRotate = selectedIdx < 0 && idleTime > 4000;
    JMD.controls.update();

    // Edge + particle updates
    JMD.updateEdgePositions();
    if (frame % 2 === 0) JMD.updateFlowParticles();
    if (frame % 3 === 0 && JMD.updateDust) JMD.updateDust();

    // Label visibility
    if (frame % 5 === 0) updateLabels();

    // Subtle entity rotation
    JMD.allNodes.forEach(function(nd) {
      if (nd.isEntity && nd.group.userData.coreMesh) {
        nd.group.userData.coreMesh.rotation.y += 0.004;
      }
    });

    // Selective bloom render
    JMD.scene.traverse(JMD.darkenNonBloomed);
    JMD.bloomComposer.render();
    JMD.scene.traverse(JMD.restoreMaterials);
    JMD.composer.render();
  }

  // ═══════════════════════════════════════════════════════════════
  // RESET CAMERA — always fits all data
  // ═══════════════════════════════════════════════════════════════

  JMD.resetCamera = function() {
    deselectNode();
    fitCameraSmooth();
  };

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
