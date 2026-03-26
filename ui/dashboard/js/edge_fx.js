// Cortex Memory Dashboard — Edge Effects
// Per-frame updates: edge positions, flow particles, highlight/reset.

(function() {
  var es = JMD._edgeState;

  // ─── Update edge positions each frame ─────────────────────────────
  function updateEdgePositions() {
    var allNodes = JMD.allNodes || [];
    var activeEdges = es.activeEdges;
    var pos = es.edgeGeo.attributes.position.array;

    for (var i = 0; i < activeEdges.length && i < es.MAX_EDGES; i++) {
      var e = activeEdges[i];
      var a = allNodes[e.srcIdx], b = allNodes[e.tgtIdx];
      if (!a || !b) {
        pos[i*6]=9999; pos[i*6+1]=9999; pos[i*6+2]=9999;
        pos[i*6+3]=9999; pos[i*6+4]=9999; pos[i*6+5]=9999;
        continue;
      }
      var ap = a.group.position, bp = b.group.position;
      pos[i*6]=ap.x; pos[i*6+1]=ap.y; pos[i*6+2]=ap.z;
      pos[i*6+3]=bp.x; pos[i*6+4]=bp.y; pos[i*6+5]=bp.z;
    }
    es.edgeGeo.attributes.position.needsUpdate = true;
  }

  // ─── Update flow particles each frame ─────────────────────────────
  function updateFlowParticles() {
    var activeEdges = es.activeEdges;
    if (activeEdges.length === 0) return;
    var allNodes = JMD.allNodes || [];
    var pos = es.flowGeo.attributes.position.array;

    for (var i = 0; i < es.NUM_PARTICLES; i++) {
      var p = es.flowData[i];
      p.progress += p.speed;
      if (p.progress > 1) {
        p.edgeIdx = Math.floor(Math.random() * activeEdges.length);
        p.progress = 0;
      }
      var e = activeEdges[p.edgeIdx];
      if (!e) continue;
      var a = allNodes[e.srcIdx], b = allNodes[e.tgtIdx];
      if (!a || !b) { pos[i*3]=9999; continue; }
      var ap = a.group.position, bp = b.group.position;
      var t = p.progress;
      pos[i*3]   = ap.x + (bp.x - ap.x) * t;
      pos[i*3+1] = ap.y + (bp.y - ap.y) * t;
      pos[i*3+2] = ap.z + (bp.z - ap.z) * t;
    }
    es.flowGeo.attributes.position.needsUpdate = true;
  }

  // ─── Highlight edges connected to a node ──────────────────────────
  function highlightNodeEdges(nodeIdx) {
    var activeEdges = es.activeEdges;
    var edgeColors = es.edgeColors;
    var connected = (es.edgeNodeMap[nodeIdx]) || [];

    activeEdges.forEach(function(e, i) {
      if (i >= es.MAX_EDGES) return;
      var isConnected = connected.indexOf(i) >= 0;
      var bright = isConnected ? 0.9 : 0.06;
      var color = isConnected ? new THREE.Color(0xf59e0b) : (e.isCausal ? new THREE.Color(0xff4444) : new THREE.Color(0x90a4ae));
      edgeColors[i*6]   = color.r * bright;
      edgeColors[i*6+1] = color.g * bright;
      edgeColors[i*6+2] = color.b * bright;
      edgeColors[i*6+3] = color.r * bright;
      edgeColors[i*6+4] = color.g * bright;
      edgeColors[i*6+5] = color.b * bright;
    });
    es.edgeGeo.attributes.color.needsUpdate = true;
  }

  function resetEdgeHighlight() {
    var activeEdges = es.activeEdges;
    var edgeColors = es.edgeColors;
    var causalColor = new THREE.Color(0xff4444);
    var defaultColor = new THREE.Color(0x90a4ae);
    var coOccColor = new THREE.Color(0xd946ef);

    activeEdges.forEach(function(e, i) {
      if (i >= es.MAX_EDGES) return;
      var color = e.isVirtual ? new THREE.Color(0x556677) : (e.isCausal ? causalColor : (e.type === 'co_occurrence' ? coOccColor : defaultColor));
      var dim = e.isVirtual ? 0.06 + e.weight * 0.12 : 0.15 + e.weight * 0.35;
      edgeColors[i*6]   = color.r * dim;
      edgeColors[i*6+1] = color.g * dim;
      edgeColors[i*6+2] = color.b * dim;
      edgeColors[i*6+3] = color.r * dim;
      edgeColors[i*6+4] = color.g * dim;
      edgeColors[i*6+5] = color.b * dim;
    });
    es.edgeGeo.attributes.color.needsUpdate = true;
  }

  // Export
  JMD.updateEdgePositions = updateEdgePositions;
  JMD.updateFlowParticles = updateFlowParticles;
  JMD.highlightNodeEdges = highlightNodeEdges;
  JMD.resetEdgeHighlight = resetEdgeHighlight;
})();
