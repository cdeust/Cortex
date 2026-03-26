// Cortex Memory Dashboard — Raycasting, Mouse Events, Selection, Animation

(function() {
  var raycaster = new THREE.Raycaster();
  var mouse = new THREE.Vector2();
  var hoveredNode = null;
  var selectedIdx = -1;
  var frame = 0;
  var lastInteraction = Date.now();

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

  // ═══════════════════════════════════════════════════════════════
  // SELECTION
  // ═══════════════════════════════════════════════════════════════

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

  // Export
  JMD.startAnimation = animate;
  JMD.deselectNode = deselectNode;
})();
