// Cortex Neural Graph — Interaction
(function() {
  var raycaster = new THREE.Raycaster();
  var mouse = new THREE.Vector2();
  var hoveredIdx = -1;
  var tip = null;

  function getHoveredNode(clientX, clientY) {
    var container = document.getElementById('graph-container');
    if (!container) return null;
    var rect = container.getBoundingClientRect();
    var lx = clientX - rect.left;
    var ly = clientY - rect.top;
    if (lx < 0 || ly < 0 || lx > rect.width || ly > rect.height) return null;
    mouse.x = (lx / rect.width) * 2 - 1;
    mouse.y = -(ly / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, JUG.camera);

    var coreMeshes = [];
    for (var i = 0; i < JUG.allNodes.length; i++) {
      var n = JUG.allNodes[i];
      if (!n.group.visible) continue;
      var core = n.group.userData.coreMesh;
      if (core) coreMeshes.push(core);
    }

    var intersects = raycaster.intersectObjects(coreMeshes, false);
    if (intersects.length > 0) {
      var hit = intersects[0].object;
      for (var j = 0; j < JUG.allNodes.length; j++) {
        if (JUG.allNodes[j].group.userData.coreMesh === hit) {
          return { idx: j, node: JUG.allNodes[j] };
        }
      }
    }
    return null;
  }

  // -- Get connected nodes and edges for a given node index --

  function getConnections(idx) {
    var connected = {};
    var connectedEdges = [];
    connected[idx] = true;
    var edges = JUG.getActiveEdges();
    var map = JUG.edgeNodeMap || {};
    (map[idx] || []).forEach(function(ei) {
      var e = edges[ei];
      if (e) {
        connected[e.srcIdx] = true;
        connected[e.tgtIdx] = true;
        connectedEdges.push(e);
      }
    });
    return { nodeSet: connected, edges: connectedEdges };
  }

  // -- Mouse events --

  window.addEventListener('mousemove', function(e) {
    var hit = getHoveredNode(e.clientX, e.clientY);
    tip = document.getElementById('tooltip');

    if (hit) {
      document.body.style.cursor = 'pointer';
      hoveredIdx = hit.idx;
      JUG.highlightMesh.visible = true;
      JUG.highlightMesh.position.copy(hit.node.group.position);
      JUG.highlightMesh.scale.setScalar(hit.node.group.userData.baseScale * 1.8);
      JUG.highlightNodeEdges(hit.idx);
      showTooltip(hit.node.data, e.clientX, e.clientY);
    } else {
      document.body.style.cursor = 'default';
      JUG.highlightMesh.visible = false;
      if (hoveredIdx >= 0) {
        hoveredIdx = -1;
        if (JUG.state.selectedId === null) JUG.resetEdgeHighlight();
        hideTooltip();
      }
    }
  });

  window.addEventListener('click', function(e) {
    if (e.target.closest('#info-panel, #filter-bar, #detail-panel, #legend, #status-bar, #reset-btn, #monitor-panel, #monitor-toggle')) return;

    var hit = getHoveredNode(e.clientX, e.clientY);
    if (hit) {
      if (JUG.state.selectedId === hit.node.data.id) {
        deselectNode();
      } else {
        selectNode(hit.idx, hit.node);
      }
    } else if (JUG.state.selectedId !== null) {
      deselectNode();
    }
  });

  // -- Select by index (from graph click) --

  function selectNode(idx, node) {
    JUG.state.selectedId = node.data.id;
    JUG.controls.autoRotate = false;
    JUG.highlightNodeEdges(idx);

    var conn = getConnections(idx);

    JUG.allNodes.forEach(function(n, i) {
      JUG.setGroupOpacity(n.group, conn.nodeSet[i] ? 1.0 : 0.08);
    });

    JUG.openDetailPanel(node.data, idx, conn);
    flyToNode(node);
  }

  // -- Select by ID (from monitor log click) --

  function selectNodeById(nodeId) {
    for (var i = 0; i < JUG.allNodes.length; i++) {
      if (JUG.allNodes[i].data.id === nodeId) {
        selectNode(i, JUG.allNodes[i]);
        return true;
      }
    }
    return false;
  }

  function deselectNode() {
    JUG.state.selectedId = null;
    JUG.resetEdgeHighlight();
    JUG.allNodes.forEach(function(n) { JUG.setGroupOpacity(n.group, 1.0); });
    JUG.closeDetailPanel();
  }

  // -- Camera fly-to --

  function flyToNode(node) {
    var pos = node.group.position;
    var dist = 80 + (node.data.size || 5) * 8;
    var targetPos = new THREE.Vector3(pos.x, pos.y, pos.z + dist);
    var targetLook = new THREE.Vector3(pos.x, pos.y, pos.z);
    var startPos = JUG.camera.position.clone();
    var startTarget = JUG.controls.target.clone();
    var startTime = performance.now();

    function step() {
      var t = Math.min((performance.now() - startTime) / 800, 1);
      var e = 1 - Math.pow(1 - t, 3);
      JUG.camera.position.lerpVectors(startPos, targetPos, e);
      JUG.controls.target.lerpVectors(startTarget, targetLook, e);
      JUG.controls.update();
      if (t < 1) requestAnimationFrame(step);
    }
    step();
  }

  // -- Tooltip --

  function showTooltip(data, x, y) {
    if (!tip) return;
    var label = document.getElementById('tt-label');
    var type = document.getElementById('tt-type');
    var meta = document.getElementById('tt-meta');
    if (label) label.textContent = data.label || '';
    if (type) {
      type.textContent = JUG.NODE_LABELS[data.type] || data.type;
      type.style.color = JUG.getNodeColor(data);
    }
    if (meta) {
      var m = [];
      if (data.domain) m.push('Domain: ' + data.domain);
      if (data.heat !== undefined) m.push('Heat: ' + data.heat);
      if (data.importance !== undefined) m.push('Importance: ' + data.importance);
      if (data.sessionCount !== undefined) m.push('Sessions: ' + data.sessionCount);
      if (data.confidence !== undefined) m.push('Confidence: ' + Math.round(data.confidence * 100) + '%');
      if (data.frequency !== undefined) m.push('Frequency: ' + data.frequency);
      if (data.ratio !== undefined) m.push('Usage: ' + Math.round(data.ratio * 100) + '%');
      if (data.entityType) m.push('Type: ' + data.entityType);
      meta.textContent = m.join('\n');
    }
    var tx = x + 16, ty = y + 16;
    if (tx + 260 > innerWidth) tx = x - 276;
    if (ty + 120 > innerHeight) ty = y - 136;
    tip.style.left = tx + 'px';
    tip.style.top = ty + 'px';
    tip.classList.add('visible');
  }

  function hideTooltip() {
    if (tip) tip.classList.remove('visible');
  }

  // Export
  JUG.selectNodeById = selectNodeById;
  JUG.deselectNode = deselectNode;
})();
