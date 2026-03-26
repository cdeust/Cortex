// Cortex Memory Dashboard — DNA Double-Helix Layout
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

(function() {
  // Helix backbone geometry (rendered as tube curves)
  var helixMeshes = [];

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
        var pullIn = 0.3 + Math.random() * 0.4; // 30-70% toward center

        var x = entPos.x * (1 - pullIn) + (Math.random() - 0.5) * 8;
        var y = entPos.y + (Math.random() - 0.5) * verticalSpacing * 0.8;
        var z = entPos.z * (1 - pullIn) + (Math.random() - 0.5) * 8;

        nodes[memIdx].group.position.set(x, y, z);
      } else {
        // No entity connection — place on a third inner helix
        var angle = (mi * rotPerStep * 0.7) * Math.PI / 180;
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
    clearHelixMeshes();

    if (entityIndices.length < 4) return;

    // Collect points for each strand
    var strand0 = [];
    var strand1 = [];

    var maxRow = Math.floor(entityIndices.length / 2);
    for (var row = 0; row <= maxRow + 2; row++) {
      var angle = (row * rotPerStep) * Math.PI / 180;
      var y = row * verticalSpacing + yOffset;

      strand0.push(new THREE.Vector3(
        Math.cos(angle) * helixR, y, Math.sin(angle) * helixR
      ));
      strand1.push(new THREE.Vector3(
        Math.cos(angle + Math.PI) * helixR, y, Math.sin(angle + Math.PI) * helixR
      ));
    }

    // Create smooth backbone curves
    if (strand0.length >= 2) {
      var curve0 = new THREE.CatmullRomCurve3(strand0);
      var curve1 = new THREE.CatmullRomCurve3(strand1);

      var tubeMat = new THREE.MeshStandardMaterial({
        color: 0x00d2ff, emissive: 0x00d2ff, emissiveIntensity: 0.25,
        transparent: true, opacity: 0.18, roughness: 0.4, metalness: 0.3,
      });

      var tube0 = new THREE.Mesh(
        new THREE.TubeGeometry(curve0, strand0.length * 8, 0.6, 6, false), tubeMat
      );
      var tube1 = new THREE.Mesh(
        new THREE.TubeGeometry(curve1, strand1.length * 8, 0.6, 6, false), tubeMat.clone()
      );

      tube0.layers.enable(JMD.BLOOM_LAYER);
      tube1.layers.enable(JMD.BLOOM_LAYER);

      JMD.scene.add(tube0);
      JMD.scene.add(tube1);
      helixMeshes.push(tube0, tube1);
    }
  }

  function clearHelixMeshes() {
    helixMeshes.forEach(function(m) {
      JMD.scene.remove(m);
      m.geometry.dispose();
      m.material.dispose();
    });
    helixMeshes = [];
  }

  // Export
  JMD.layoutDNAHelix = layoutDNAHelix;
  JMD.clearHelixMeshes = clearHelixMeshes;
})();
