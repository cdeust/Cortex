// Cortex Memory Dashboard — Edge Rendering
// Relationship lines, fiber tracts for strong connections, flow particles.

(function() {
  var scene = JMD.scene;

  // ─── Edge line segments ───────────────────────────────────────────
  var MAX_EDGES = 2000;
  var edgePositions = new Float32Array(MAX_EDGES * 6);
  var edgeColors = new Float32Array(MAX_EDGES * 6);
  var edgeGeo = new THREE.BufferGeometry();
  edgeGeo.setAttribute('position', new THREE.BufferAttribute(edgePositions, 3));
  edgeGeo.setAttribute('color', new THREE.BufferAttribute(edgeColors, 3));

  var edgeMat = new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.35,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  var edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
  scene.add(edgeLines);

  // ─── Fiber tracts (curved tubes for top weighted connections) ─────
  var fiberGroup = new THREE.Group();
  scene.add(fiberGroup);

  // ─── Flow particles ──────────────────────────────────────────────
  var NUM_PARTICLES = 300;
  var flowData = [];
  var flowPositions = new Float32Array(NUM_PARTICLES * 3);
  var flowColors = new Float32Array(NUM_PARTICLES * 3);
  var flowSizes = new Float32Array(NUM_PARTICLES);

  for (var i = 0; i < NUM_PARTICLES; i++) {
    flowData.push({ edgeIdx: 0, progress: Math.random(), speed: 0.003 + Math.random() * 0.007 });
    flowPositions[i*3] = 9999;
    flowPositions[i*3+1] = 9999;
    flowPositions[i*3+2] = 9999;
    flowSizes[i] = 1.2 + Math.random() * 1.2;
  }

  var flowGeo = new THREE.BufferGeometry();
  flowGeo.setAttribute('position', new THREE.BufferAttribute(flowPositions, 3));
  flowGeo.setAttribute('color', new THREE.BufferAttribute(flowColors, 3));
  flowGeo.setAttribute('size', new THREE.BufferAttribute(flowSizes, 1));

  var flowMat = new THREE.ShaderMaterial({
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    uniforms: {},
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
  scene.add(flowPoints);

  // ─── Clear all edge visuals ──────────────────────────────────────
  var activeEdges = [];
  var edgeNodeMap = {};

  function clearEdges() {
    activeEdges = [];
    edgeNodeMap = {};

    // Hide edge lines
    edgeGeo.setDrawRange(0, 0);

    // Clear fiber tracts
    while (fiberGroup.children.length) {
      var child = fiberGroup.children[0];
      child.geometry.dispose();
      child.material.dispose();
      fiberGroup.remove(child);
    }

    // Hide flow particles
    var pos = flowGeo.attributes.position.array;
    for (var i = 0; i < NUM_PARTICLES * 3; i++) pos[i] = 9999;
    flowGeo.attributes.position.needsUpdate = true;
  }

  // ─── Build edges from data ────────────────────────────────────────
  function buildEdges(data) {
    var rels = data.relationships || [];
    var entities = data.entities || [];
    var memories = data.hot_memories || [];
    var allNodes = JMD.allNodes || [];

    activeEdges = [];
    edgeNodeMap = {};

    // Map entity IDs to node indices
    var entityIdToIdx = {};
    allNodes.forEach(function(n, idx) {
      if (n.isEntity && n.data && n.data.id !== undefined) {
        entityIdToIdx[n.data.id] = idx;
      }
    });

    // Build edges from relationships (entity↔entity)
    rels.forEach(function(r) {
      var srcIdx = entityIdToIdx[r.source];
      var tgtIdx = entityIdToIdx[r.target];
      if (srcIdx === undefined || tgtIdx === undefined) return;
      if (srcIdx === tgtIdx) return;

      var edge = {
        srcIdx: srcIdx, tgtIdx: tgtIdx,
        weight: r.weight || 0.5,
        type: r.type || 'related',
        isCausal: r.is_causal || false,
        isVirtual: false,
      };
      var idx = activeEdges.length;
      activeEdges.push(edge);

      if (!edgeNodeMap[srcIdx]) edgeNodeMap[srcIdx] = [];
      if (!edgeNodeMap[tgtIdx]) edgeNodeMap[tgtIdx] = [];
      edgeNodeMap[srcIdx].push(idx);
      edgeNodeMap[tgtIdx].push(idx);
    });

    // Build virtual edges: memory→entity (domain match + content/name overlap)
    var entityNodes = [];
    allNodes.forEach(function(n, idx) {
      if (n.isEntity) entityNodes.push({ node: n, idx: idx });
    });

    allNodes.forEach(function(n, memIdx) {
      if (n.isEntity) return;
      var memDomain = (n.data.domain || '').toLowerCase();
      var memContent = ((n.data.content || '') + ' ' + (n.data.tags || []).join(' ')).toLowerCase();
      var bestMatch = -1;
      var bestScore = 0;

      entityNodes.forEach(function(ent) {
        var entName = (ent.node.data.name || '').toLowerCase();
        var entDomain = (ent.node.data.domain || '').toLowerCase();
        var score = 0;

        if (memDomain && entDomain && memDomain === entDomain) score += 0.5;
        if (entName.length > 2 && memContent.indexOf(entName) >= 0) score += 0.4;
        if (ent.node.data.type && memContent.indexOf(ent.node.data.type.toLowerCase()) >= 0) score += 0.2;

        if (score > bestScore) { bestScore = score; bestMatch = ent.idx; }
      });

      if (bestMatch < 0 && entityNodes.length > 0) {
        bestMatch = entityNodes[memIdx % entityNodes.length].idx;
        bestScore = 0.1;
      }

      if (bestMatch >= 0) {
        var vedge = {
          srcIdx: memIdx, tgtIdx: bestMatch,
          weight: Math.min(bestScore, 0.6),
          type: 'context',
          isCausal: false,
          isVirtual: true,
        };
        var vidx = activeEdges.length;
        activeEdges.push(vedge);
        if (!edgeNodeMap[memIdx]) edgeNodeMap[memIdx] = [];
        if (!edgeNodeMap[bestMatch]) edgeNodeMap[bestMatch] = [];
        edgeNodeMap[memIdx].push(vidx);
        edgeNodeMap[bestMatch].push(vidx);
      }
    });

    // Color edges
    var causalColor = new THREE.Color(0xff4444);
    var defaultColor = new THREE.Color(0x90a4ae);
    var coOccColor = new THREE.Color(0xd946ef);

    activeEdges.forEach(function(e, i) {
      if (i >= MAX_EDGES) return;
      var color = e.isVirtual ? new THREE.Color(0x556677) : (e.isCausal ? causalColor : (e.type === 'co_occurrence' ? coOccColor : defaultColor));
      var dim = e.isVirtual ? 0.06 + e.weight * 0.12 : 0.15 + e.weight * 0.35;
      edgeColors[i*6]   = color.r * dim;
      edgeColors[i*6+1] = color.g * dim;
      edgeColors[i*6+2] = color.b * dim;
      edgeColors[i*6+3] = color.r * dim;
      edgeColors[i*6+4] = color.g * dim;
      edgeColors[i*6+5] = color.b * dim;
    });

    edgeGeo.setDrawRange(0, Math.min(activeEdges.length, MAX_EDGES) * 2);
    edgeGeo.attributes.color.needsUpdate = true;

    // Assign flow particles to edges
    if (activeEdges.length > 0) {
      for (var fi = 0; fi < NUM_PARTICLES; fi++) {
        flowData[fi].edgeIdx = Math.floor(Math.random() * activeEdges.length);
        var e = activeEdges[flowData[fi].edgeIdx];
        var color = e.isCausal ? causalColor : (e.type === 'co_occurrence' ? coOccColor : defaultColor);
        flowColors[fi*3] = color.r;
        flowColors[fi*3+1] = color.g;
        flowColors[fi*3+2] = color.b;
      }
      flowGeo.attributes.color.needsUpdate = true;
    }

    // Update exports after rebuild
    JMD.edgeNodeMap = edgeNodeMap;

    buildFiberTracts();
  }

  // ─── Fiber tracts for top connections ─────────────────────────────
  function buildFiberTracts() {
    while (fiberGroup.children.length) {
      var child = fiberGroup.children[0];
      child.geometry.dispose();
      child.material.dispose();
      fiberGroup.remove(child);
    }
    if (activeEdges.length < 2) return;

    var sorted = activeEdges.slice().sort(function(a,b) { return b.weight - a.weight; });
    var topCount = Math.min(5, sorted.length);

    var allNodes = JMD.allNodes || [];
    for (var ti = 0; ti < topCount; ti++) {
      var e = sorted[ti];
      var src = allNodes[e.srcIdx], tgt = allNodes[e.tgtIdx];
      if (!src || !tgt) continue;

      var start = src.group.position.clone();
      var end = tgt.group.position.clone();
      var mid = start.clone().add(end).multiplyScalar(0.5);
      var dist = start.distanceTo(end);
      var dir = end.clone().sub(start).normalize();
      var perp = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0,1,0)).normalize();
      if (perp.length() < 0.01) perp.set(1,0,0);
      mid.add(perp.multiplyScalar(dist * 0.1));
      mid.y += dist * 0.08;

      var curve = new THREE.CatmullRomCurve3([start, mid, end]);
      var radius = 0.15 + e.weight * 0.25;
      var tubeGeo = new THREE.TubeGeometry(curve, 12, radius, 4, false);
      var color = e.isCausal ? 0xff4444 : 0x00d2ff;
      var tubeMat = new THREE.MeshStandardMaterial({
        color: color, emissive: color, emissiveIntensity: 0.3,
        transparent: true, opacity: 0.15, roughness: 0.6, metalness: 0.2,
      });
      fiberGroup.add(new THREE.Mesh(tubeGeo, tubeMat));
    }
  }

  // Export shared state for edge_fx.js
  JMD._edgeState = {
    get activeEdges() { return activeEdges; },
    get edgeNodeMap() { return edgeNodeMap; },
    edgeGeo: edgeGeo,
    edgeColors: edgeColors,
    flowGeo: flowGeo,
    flowData: flowData,
    MAX_EDGES: MAX_EDGES,
    NUM_PARTICLES: NUM_PARTICLES,
  };

  JMD.clearEdges = clearEdges;
  JMD.buildEdges = buildEdges;
  JMD.edgeNodeMap = edgeNodeMap;
  JMD.getActiveEdges = function() { return activeEdges; };
})();
