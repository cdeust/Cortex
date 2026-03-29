// Cortex Memory Dashboard — Filtering
(function() {
  var CMD = window.CMD;

  CMD.buildConnectionIndex = function() {
    CMD.tubeEdgeSet = new Set(CMD.tubeEdges);
    CMD.lineEdgeSet = new Set(CMD.lineEdges);

    CMD.edgeToTubeIdx = new Map();
    var tubeIdx = 0;
    CMD.tubeEdges.forEach(function(e) {
      var a = CMD.nodeMap[e.source], b = CMD.nodeMap[e.target];
      if (a && b && a.bx !== undefined && b.bx !== undefined) {
        var dist = Math.sqrt((b.bx - a.bx) ** 2 + (b.by - a.by) ** 2 + (b.bz - a.bz) ** 2);
        if (dist >= 0.1 && tubeIdx < CMD.tractGroup.children.length) {
          CMD.edgeToTubeIdx.set(e, tubeIdx);
          tubeIdx++;
        }
      }
    });

    CMD.edgeToLineIdx = new Map();
    CMD.lineEdges.forEach(function(e, i) { CMD.edgeToLineIdx.set(e, i); });

    CMD.nodeEdgeMap = {};
    CMD.allDrawEdges.forEach(function(e) {
      var entry = { edge: e, other: e.target, isTube: CMD.tubeEdgeSet.has(e) };
      if (!CMD.nodeEdgeMap[e.source]) CMD.nodeEdgeMap[e.source] = [];
      CMD.nodeEdgeMap[e.source].push(entry);
      var entry2 = { edge: e, other: e.source, isTube: CMD.tubeEdgeSet.has(e) };
      if (!CMD.nodeEdgeMap[e.target]) CMD.nodeEdgeMap[e.target] = [];
      CMD.nodeEdgeMap[e.target].push(entry2);
    });
  };

  CMD.highlightConnections = function(nodeId) {
    CMD.clearConnectionHighlights();
    var conns = CMD.nodeEdgeMap[nodeId];
    if (!conns) return;

    conns.forEach(function(c) {
      CMD._connectedNodeIds.add(c.other);
      var e = c.edge;
      var w = e.weight || 0.3;

      if (c.isTube) {
        var ti = CMD.edgeToTubeIdx.get(e);
        if (ti !== undefined && CMD.tractGroup.children[ti]) {
          var tube = CMD.tractGroup.children[ti];
          tube._origOpacity = tube.material.opacity;
          tube._origEmissive = tube.material.emissiveIntensity;
          tube.material.opacity = 0.95;
          tube.material.emissiveIntensity = 1.0 + w * 1.0;
          CMD._highlightedTubes.push(tube);
        }
      } else {
        var li = CMD.edgeToLineIdx.get(e);
        if (li !== undefined) {
          var srcNode = CMD.nodeMap[e.source];
          var col = srcNode ? CMD.nodeColor(srcNode) : new THREE.Color(1, 1, 1);
          var brightness = 0.7 + w * 0.3;
          CMD.eColBuf.setXYZ(li * 2, col.r * brightness, col.g * brightness, col.b * brightness);
          CMD.eColBuf.setXYZ(li * 2 + 1, col.r * brightness, col.g * brightness, col.b * brightness);
          CMD._highlightedLines.push(li);
        }
      }
    });
    CMD.eColBuf.needsUpdate = true;

    CMD._connectedNodeIds.forEach(function(id) {
      var mesh = CMD.neuronMeshes[id];
      if (mesh) {
        mesh._preHighlightEmit = mesh.material.emissiveIntensity;
        mesh.material.emissiveIntensity = mesh.material.emissiveIntensity * 1.8;
      }
    });
  };

  CMD.clearConnectionHighlights = function() {
    CMD._highlightedTubes.forEach(function(tube) {
      if (tube._origOpacity !== undefined) tube.material.opacity = tube._origOpacity;
      if (tube._origEmissive !== undefined) tube.material.emissiveIntensity = tube._origEmissive;
    });
    CMD._highlightedTubes = [];
    CMD._highlightedLines = [];

    CMD._connectedNodeIds.forEach(function(id) {
      var mesh = CMD.neuronMeshes[id];
      if (mesh && mesh._preHighlightEmit !== undefined) {
        mesh.material.emissiveIntensity = mesh._preHighlightEmit;
        delete mesh._preHighlightEmit;
      }
    });
    CMD._connectedNodeIds = new Set();
    CMD.applyFilters();
  };

  CMD.applyFilters = function() {
    var q = CMD.searchQuery.toLowerCase();

    CMD.nodes.forEach(function(n) {
      var mesh = CMD.neuronMeshes[n.id];
      if (!mesh) return;
      var vis = true;

      if (vis && CMD.activeFilter !== 'all') {
        if (CMD.activeFilter === 'episodic') {
          vis = n.store_type === 'episodic';
        } else if (CMD.activeFilter === 'semantic') {
          vis = n.store_type === 'semantic';
        } else if (CMD.activeFilter === 'entity') {
          vis = n.id && n.id.startsWith('e_');
        } else if (CMD.activeFilter === 'global') {
          vis = !!(n.is_global || n.isGlobal);
        } else {
          vis = n.type === CMD.activeFilter || n.nodeType === CMD.activeFilter;
        }
      }

      if (vis && q) {
        var haystack = ((n.name || '') + ' ' + (n.description || '') + ' ' + (n.body || '')).toLowerCase();
        vis = haystack.includes(q);
      }

      mesh.visible = vis;
      n._vis = vis;
    });

    // Rebuild edge colors
    CMD.drawEdges.forEach(function(e, i) {
      var a = CMD.nodeMap[e.source], b = CMD.nodeMap[e.target];
      var aVis = a ? a._vis !== false : true;
      var bVis = b ? b._vis !== false : true;
      if (!aVis || !bVis) {
        CMD.eColBuf.setXYZ(i * 2, 0, 0, 0);
        CMD.eColBuf.setXYZ(i * 2 + 1, 0, 0, 0);
      } else {
        var col = a ? CMD.nodeColor(a) : new THREE.Color(0x4488aa);
        var isContext = e.type === 'context';
        var w = isContext ? 0.03 + (e.weight || 0.1) * 0.05 : 0.05 + (e.weight || 0.3) * 0.08;
        CMD.eColBuf.setXYZ(i * 2, col.r * w, col.g * w, col.b * w);
        CMD.eColBuf.setXYZ(i * 2 + 1, col.r * w, col.g * w, col.b * w);
      }
    });
    CMD.eColBuf.needsUpdate = true;
    CMD.updateStats();

    if (CMD.layoutMode === 'timeline' && typeof CMD.buildTimelineTable === 'function') {
      CMD.buildTimelineTable();
    }
  };

  CMD.updateStats = function() {
    var vis = CMD.nodes.filter(function(n) { return n._vis !== false; });
    var ents = vis.filter(function(n) { return n.id && n.id.startsWith('e_'); }).length;
    var mems = vis.filter(function(n) { return n.id && n.id.startsWith('m_'); }).length;
    var globals = vis.filter(function(n) { return n.is_global || n.isGlobal; }).length;
    var edges_vis = CMD.drawEdges.filter(function(e) {
      var s = CMD.nodeMap[e.source], t = CMD.nodeMap[e.target];
      return (s ? s._vis !== false : true) && (t ? t._vis !== false : true);
    }).length;
    var statsHtml = '<span>' + ents + '</span> entities \xb7 <span>' + mems + '</span> memories \xb7 <span>' + edges_vis + '</span> synapses';
    if (globals > 0) statsHtml += ' \xb7 <span style="color:#FF4081">' + globals + '</span> global';
    document.getElementById('stats-brain').innerHTML = statsHtml;
  };
})();
