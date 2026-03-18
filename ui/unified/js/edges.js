// JARVIS Unified Graph — Edge Rendering
(function() {
  var MAX_EDGES = 3000;
  var NUM_PARTICLES = 400;

  var edgePositions = new Float32Array(MAX_EDGES * 6);
  var edgeColors = new Float32Array(MAX_EDGES * 6);
  var edgeGeo = new THREE.BufferGeometry();
  edgeGeo.setAttribute('position', new THREE.BufferAttribute(edgePositions, 3));
  edgeGeo.setAttribute('color', new THREE.BufferAttribute(edgeColors, 3));

  var edgeMat = new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.4,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  var edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
  JUG.scene.add(edgeLines);

  // Fiber tracts
  var fiberGroup = new THREE.Group();
  JUG.scene.add(fiberGroup);

  // Flow particles
  var flowData = [];
  var flowPositions = new Float32Array(NUM_PARTICLES * 3);
  var flowColors = new Float32Array(NUM_PARTICLES * 3);
  var flowSizes = new Float32Array(NUM_PARTICLES);

  for (var i = 0; i < NUM_PARTICLES; i++) {
    flowData.push({ edgeIdx: 0, progress: Math.random(), speed: 0.003 + Math.random() * 0.007 });
    flowPositions[i * 3] = 9999;
    flowPositions[i * 3 + 1] = 9999;
    flowPositions[i * 3 + 2] = 9999;
    flowSizes[i] = 1.0 + Math.random() * 1.0;
  }

  var flowGeo = new THREE.BufferGeometry();
  flowGeo.setAttribute('position', new THREE.BufferAttribute(flowPositions, 3));
  flowGeo.setAttribute('color', new THREE.BufferAttribute(flowColors, 3));
  flowGeo.setAttribute('size', new THREE.BufferAttribute(flowSizes, 1));

  var flowMat = new THREE.ShaderMaterial({
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    vertexShader: [
      'attribute float size; attribute vec3 color; varying vec3 vColor;',
      'void main() {',
      '  vColor = color;',
      '  vec4 mv = modelViewMatrix * vec4(position,1.0);',
      '  gl_PointSize = size * (200.0 / -mv.z);',
      '  gl_Position = projectionMatrix * mv;',
      '}',
    ].join('\n'),
    fragmentShader: [
      'varying vec3 vColor;',
      'void main() {',
      '  float d = length(gl_PointCoord - 0.5);',
      '  if (d > 0.5) discard;',
      '  float a = smoothstep(0.5, 0.0, d) * 0.7;',
      '  gl_FragColor = vec4(vColor, a);',
      '}',
    ].join('\n'),
  });
  var flowPoints = new THREE.Points(flowGeo, flowMat);
  JUG.scene.add(flowPoints);

  var activeEdges = [];
  var edgeNodeMap = {};
  var nodeIdToIdx = {};

  function clearEdges() {
    activeEdges = [];
    edgeNodeMap = {};
    nodeIdToIdx = {};
    edgeGeo.setDrawRange(0, 0);
    while (fiberGroup.children.length) {
      var child = fiberGroup.children[0];
      child.geometry.dispose();
      child.material.dispose();
      fiberGroup.remove(child);
    }
    var pos = flowGeo.attributes.position.array;
    for (var i = 0; i < NUM_PARTICLES * 3; i++) pos[i] = 9999;
    flowGeo.attributes.position.needsUpdate = true;
  }

  function buildEdges(edgesData, allNodes) {
    activeEdges = [];
    edgeNodeMap = {};
    nodeIdToIdx = {};

    // Build ID → index map
    for (var ni = 0; ni < allNodes.length; ni++) {
      var nd = allNodes[ni].data || (allNodes[ni].group && allNodes[ni].group.userData.nodeData);
      if (nd) nodeIdToIdx[nd.id] = ni;
    }

    edgesData.forEach(function(e) {
      var srcIdx = nodeIdToIdx[e.source];
      var tgtIdx = nodeIdToIdx[e.target];
      if (srcIdx === undefined || tgtIdx === undefined) return;
      if (srcIdx === tgtIdx) return;

      var edge = {
        srcIdx: srcIdx, tgtIdx: tgtIdx,
        weight: e.weight || 0.3,
        type: e.type || 'default',
        color: JUG.getEdgeColor(e),
        isCausal: e.isCausal || false,
      };
      var idx = activeEdges.length;
      activeEdges.push(edge);

      if (!edgeNodeMap[srcIdx]) edgeNodeMap[srcIdx] = [];
      if (!edgeNodeMap[tgtIdx]) edgeNodeMap[tgtIdx] = [];
      edgeNodeMap[srcIdx].push(idx);
      edgeNodeMap[tgtIdx].push(idx);
    });

    // Color edges
    activeEdges.forEach(function(e, i) {
      if (i >= MAX_EDGES) return;
      var c = new THREE.Color(e.color);
      var isWeak = e.type === 'memory-entity' || e.type === 'domain-entity';
      var dim = isWeak ? 0.08 + e.weight * 0.15 : 0.15 + e.weight * 0.4;
      edgeColors[i * 6] = c.r * dim;
      edgeColors[i * 6 + 1] = c.g * dim;
      edgeColors[i * 6 + 2] = c.b * dim;
      edgeColors[i * 6 + 3] = c.r * dim;
      edgeColors[i * 6 + 4] = c.g * dim;
      edgeColors[i * 6 + 5] = c.b * dim;
    });

    edgeGeo.setDrawRange(0, Math.min(activeEdges.length, MAX_EDGES) * 2);
    edgeGeo.attributes.color.needsUpdate = true;

    // Assign flow particles
    if (activeEdges.length > 0) {
      for (var fi = 0; fi < NUM_PARTICLES; fi++) {
        flowData[fi].edgeIdx = Math.floor(Math.random() * activeEdges.length);
        var fe = activeEdges[flowData[fi].edgeIdx];
        var fc = new THREE.Color(fe.color);
        flowColors[fi * 3] = fc.r;
        flowColors[fi * 3 + 1] = fc.g;
        flowColors[fi * 3 + 2] = fc.b;
      }
      flowGeo.attributes.color.needsUpdate = true;
    }

    JUG.edgeNodeMap = edgeNodeMap;
    buildFiberTracts();
  }

  function buildFiberTracts() {
    while (fiberGroup.children.length) {
      var child = fiberGroup.children[0];
      child.geometry.dispose();
      child.material.dispose();
      fiberGroup.remove(child);
    }
    if (activeEdges.length < 2) return;

    // Top 8 strongest edges get fiber tracts
    var sorted = activeEdges.slice().sort(function(a, b) { return b.weight - a.weight; });
    var topCount = Math.min(8, sorted.length);
    var allNodes = JUG.allNodes || [];

    for (var ti = 0; ti < topCount; ti++) {
      var e = sorted[ti];
      var src = allNodes[e.srcIdx], tgt = allNodes[e.tgtIdx];
      if (!src || !tgt) continue;

      var start = src.group.position.clone();
      var end = tgt.group.position.clone();
      var mid = start.clone().add(end).multiplyScalar(0.5);
      var dist = start.distanceTo(end);
      if (dist < 1) continue;
      var dir = end.clone().sub(start).normalize();
      var perp = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0)).normalize();
      if (perp.length() < 0.01) perp.set(1, 0, 0);
      mid.add(perp.multiplyScalar(dist * 0.08));
      mid.y += dist * 0.06;

      var curve = new THREE.CatmullRomCurve3([start, mid, end]);
      var radius = 0.12 + e.weight * 0.2;
      var color = new THREE.Color(e.color);
      var tubeGeo = new THREE.TubeGeometry(curve, 12, radius, 4, false);
      var tubeMat = new THREE.MeshStandardMaterial({
        color: color, emissive: color, emissiveIntensity: 0.3,
        transparent: true, opacity: 0.12, roughness: 0.6, metalness: 0.2,
      });
      fiberGroup.add(new THREE.Mesh(tubeGeo, tubeMat));
    }
  }

  function updateEdgePositions() {
    var allNodes = JUG.allNodes || [];
    var pos = edgeGeo.attributes.position.array;
    for (var i = 0; i < activeEdges.length && i < MAX_EDGES; i++) {
      var e = activeEdges[i];
      var a = allNodes[e.srcIdx], b = allNodes[e.tgtIdx];
      if (!a || !b) {
        pos[i * 6] = 9999; pos[i * 6 + 1] = 9999; pos[i * 6 + 2] = 9999;
        pos[i * 6 + 3] = 9999; pos[i * 6 + 4] = 9999; pos[i * 6 + 5] = 9999;
        continue;
      }
      var ap = a.group.position, bp = b.group.position;
      pos[i * 6] = ap.x; pos[i * 6 + 1] = ap.y; pos[i * 6 + 2] = ap.z;
      pos[i * 6 + 3] = bp.x; pos[i * 6 + 4] = bp.y; pos[i * 6 + 5] = bp.z;
    }
    edgeGeo.attributes.position.needsUpdate = true;
  }

  function updateFlowParticles() {
    if (activeEdges.length === 0) return;
    var allNodes = JUG.allNodes || [];
    var pos = flowGeo.attributes.position.array;
    for (var i = 0; i < NUM_PARTICLES; i++) {
      var p = flowData[i];
      p.progress += p.speed;
      if (p.progress > 1) {
        p.edgeIdx = Math.floor(Math.random() * activeEdges.length);
        p.progress = 0;
      }
      var e = activeEdges[p.edgeIdx];
      if (!e) continue;
      var a = allNodes[e.srcIdx], b = allNodes[e.tgtIdx];
      if (!a || !b) { pos[i * 3] = 9999; continue; }
      var ap = a.group.position, bp = b.group.position;
      var t = p.progress;
      pos[i * 3] = ap.x + (bp.x - ap.x) * t;
      pos[i * 3 + 1] = ap.y + (bp.y - ap.y) * t;
      pos[i * 3 + 2] = ap.z + (bp.z - ap.z) * t;
    }
    flowGeo.attributes.position.needsUpdate = true;
  }

  function highlightNodeEdges(nodeIdx) {
    var connected = edgeNodeMap[nodeIdx] || [];
    activeEdges.forEach(function(e, i) {
      if (i >= MAX_EDGES) return;
      var isConn = connected.indexOf(i) >= 0;
      var bright = isConn ? 0.9 : 0.04;
      var c = isConn ? new THREE.Color(0xf59e0b) : new THREE.Color(e.color);
      edgeColors[i * 6] = c.r * bright;
      edgeColors[i * 6 + 1] = c.g * bright;
      edgeColors[i * 6 + 2] = c.b * bright;
      edgeColors[i * 6 + 3] = c.r * bright;
      edgeColors[i * 6 + 4] = c.g * bright;
      edgeColors[i * 6 + 5] = c.b * bright;
    });
    edgeGeo.attributes.color.needsUpdate = true;
  }

  function resetEdgeHighlight() {
    activeEdges.forEach(function(e, i) {
      if (i >= MAX_EDGES) return;
      var c = new THREE.Color(e.color);
      var isWeak = e.type === 'memory-entity' || e.type === 'domain-entity';
      var dim = isWeak ? 0.08 + e.weight * 0.15 : 0.15 + e.weight * 0.4;
      edgeColors[i * 6] = c.r * dim;
      edgeColors[i * 6 + 1] = c.g * dim;
      edgeColors[i * 6 + 2] = c.b * dim;
      edgeColors[i * 6 + 3] = c.r * dim;
      edgeColors[i * 6 + 4] = c.g * dim;
      edgeColors[i * 6 + 5] = c.b * dim;
    });
    edgeGeo.attributes.color.needsUpdate = true;
  }

  // Incrementally append new edges without clearing existing ones
  function appendEdges(newEdgesData, allNodes) {
    // Update ID→index map with any new nodes
    for (var ni = 0; ni < allNodes.length; ni++) {
      var nd = allNodes[ni].data || (allNodes[ni].group && allNodes[ni].group.userData.nodeData);
      if (nd) nodeIdToIdx[nd.id] = ni;
    }

    var startIdx = activeEdges.length;

    newEdgesData.forEach(function(e) {
      var srcIdx = nodeIdToIdx[e.source];
      var tgtIdx = nodeIdToIdx[e.target];
      if (srcIdx === undefined || tgtIdx === undefined) return;
      if (srcIdx === tgtIdx) return;

      var edge = {
        srcIdx: srcIdx, tgtIdx: tgtIdx,
        weight: e.weight || 0.3,
        type: e.type || 'default',
        color: JUG.getEdgeColor(e),
        isCausal: e.isCausal || false,
      };
      var idx = activeEdges.length;
      activeEdges.push(edge);

      if (!edgeNodeMap[srcIdx]) edgeNodeMap[srcIdx] = [];
      if (!edgeNodeMap[tgtIdx]) edgeNodeMap[tgtIdx] = [];
      edgeNodeMap[srcIdx].push(idx);
      edgeNodeMap[tgtIdx].push(idx);
    });

    // Color only the new edges
    for (var i = startIdx; i < activeEdges.length && i < MAX_EDGES; i++) {
      var e = activeEdges[i];
      var c = new THREE.Color(e.color);
      var isWeak = e.type === 'memory-entity' || e.type === 'domain-entity';
      var dim = isWeak ? 0.08 + e.weight * 0.15 : 0.15 + e.weight * 0.4;
      edgeColors[i * 6] = c.r * dim;
      edgeColors[i * 6 + 1] = c.g * dim;
      edgeColors[i * 6 + 2] = c.b * dim;
      edgeColors[i * 6 + 3] = c.r * dim;
      edgeColors[i * 6 + 4] = c.g * dim;
      edgeColors[i * 6 + 5] = c.b * dim;
    }

    edgeGeo.setDrawRange(0, Math.min(activeEdges.length, MAX_EDGES) * 2);
    edgeGeo.attributes.color.needsUpdate = true;

    // Reassign some flow particles to new edges
    if (activeEdges.length > 0) {
      var newCount = activeEdges.length - startIdx;
      var particlesToReassign = Math.min(Math.floor(NUM_PARTICLES * newCount / activeEdges.length), NUM_PARTICLES);
      for (var fi = 0; fi < particlesToReassign; fi++) {
        var pi = Math.floor(Math.random() * NUM_PARTICLES);
        flowData[pi].edgeIdx = startIdx + Math.floor(Math.random() * newCount);
        var fe = activeEdges[flowData[pi].edgeIdx];
        if (fe) {
          var fc = new THREE.Color(fe.color);
          flowColors[pi * 3] = fc.r;
          flowColors[pi * 3 + 1] = fc.g;
          flowColors[pi * 3 + 2] = fc.b;
        }
      }
      flowGeo.attributes.color.needsUpdate = true;
    }

    JUG.edgeNodeMap = edgeNodeMap;
  }

  JUG.clearEdges = clearEdges;
  JUG.buildEdges = buildEdges;
  JUG.appendEdges = appendEdges;
  JUG.updateEdgePositions = updateEdgePositions;
  JUG.updateFlowParticles = updateFlowParticles;
  JUG.highlightNodeEdges = highlightNodeEdges;
  JUG.resetEdgeHighlight = resetEdgeHighlight;
  JUG.edgeNodeMap = edgeNodeMap;
  JUG.getActiveEdges = function() { return activeEdges; };
})();
