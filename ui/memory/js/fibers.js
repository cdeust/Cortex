// Cortex Memory Dashboard — Fiber Tracts
(function() {
  var CMD = window.CMD;

  CMD.buildFibers = function() {
    var S = CMD.brainScale;
    var nodeMap = CMD.nodeMap;
    var edges = CMD.edges;

    CMD.allDrawEdges = edges.filter(function(e) {
      var a = nodeMap[e.source], b = nodeMap[e.target];
      return a && b && a.bx !== undefined && b.bx !== undefined && (e.weight || 0) >= 0.05;
    });

    var sortedEdges = CMD.allDrawEdges.slice().sort(function(a, b) { return (b.weight || 0) - (a.weight || 0); });
    CMD.tubeCount = Math.min(Math.max(Math.floor(sortedEdges.length * 0.15), 20), 800);
    CMD.tubeEdges = sortedEdges.slice(0, CMD.tubeCount);
    CMD.lineEdges = sortedEdges.slice(CMD.tubeCount);
    CMD.drawEdges = CMD.allDrawEdges;

    // Curved tube tracts
    var tractGroup = CMD.tractGroup = new THREE.Group();
    CMD.tubeEdges.forEach(function(e) {
      try {
        var a = nodeMap[e.source], b = nodeMap[e.target];
        if (!a || !b || a.bx === undefined || b.bx === undefined) return;
        var ax = a.bx, ay = a.by, az = a.bz, bx = b.bx, by = b.by, bz = b.bz;
        var mx = (ax + bx) / 2, my = (ay + by) / 2, mz = (az + bz) / 2;
        var dist = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2);
        if (dist < 0.1) return;
        var sag = dist * 0.15;
        var norm = Math.sqrt(mx * mx + my * my + mz * mz) || 1;
        var mid = new THREE.Vector3(mx - mx / norm * sag, my - my / norm * sag, mz - mz / norm * sag);
        var curve = new THREE.CatmullRomCurve3([
          new THREE.Vector3(ax, ay, az), mid, new THREE.Vector3(bx, by, bz)
        ]);
        var w = e.weight || 0.3;
        var radius = (0.01 + w * 0.025) * S;
        var tubeGeo = new THREE.TubeGeometry(curve, 12, radius, 3, false);
        var col = CMD.nodeColor(a);
        var tubeMat = new THREE.MeshStandardMaterial({
          color: col.clone().multiplyScalar(0.15),
          emissive: col,
          emissiveIntensity: 0.15 + w * 0.25,
          transparent: true, opacity: 0.12 + w * 0.18,
          roughness: 0.2, metalness: 0.0, depthWrite: false,
        });
        tractGroup.add(new THREE.Mesh(tubeGeo, tubeMat));
      } catch (_) {}
    });
    CMD.scene.add(tractGroup);

    // Thin lines for weak connections
    var _lineEdges = CMD.lineEdges.length > 0 ? CMD.lineEdges : [];
    var ePosArr = new Float32Array(Math.max(_lineEdges.length, 1) * 6);
    var eColArr = new Float32Array(Math.max(_lineEdges.length, 1) * 6);
    _lineEdges.forEach(function(e, i) {
      var a = nodeMap[e.source], b = nodeMap[e.target];
      if (!a || !b) return;
      ePosArr.set([a.bx, a.by, a.bz, b.bx, b.by, b.bz], i * 6);
      var col = CMD.nodeColor(a);
      var w = 0.08 + (e.weight || 0.1) * 0.12;
      eColArr.set([col.r * w, col.g * w, col.b * w, col.r * w, col.g * w, col.b * w], i * 6);
    });
    var eGeo = CMD.eGeo = new THREE.BufferGeometry();
    eGeo.setAttribute('position', new THREE.BufferAttribute(ePosArr, 3));
    eGeo.setAttribute('color', new THREE.BufferAttribute(eColArr, 3));
    CMD.scene.add(new THREE.LineSegments(eGeo, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.15,
      blending: THREE.NormalBlending, depthWrite: false
    })));
    CMD.eColBuf = eGeo.attributes.color;

    // Build AP curves
    CMD.buildAPCurves();
  };

  CMD.buildAPCurves = function() {
    var S = CMD.brainScale;
    var nodeMap = CMD.nodeMap;
    CMD.AP_CURVES = [];

    CMD.tubeEdges.forEach(function(e) {
      var a = nodeMap[e.source], b = nodeMap[e.target];
      if (!a || !b || a.bx === undefined || b.bx === undefined) { CMD.AP_CURVES.push(null); return; }
      var ax = a.bx, ay = a.by, az = a.bz, bx = b.bx, by = b.by, bz = b.bz;
      var dist = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2);
      if (dist < 0.1) { CMD.AP_CURVES.push(null); return; }
      var mx = (ax + bx) / 2, my = (ay + by) / 2, mz = (az + bz) / 2;
      var sag = dist * 0.15;
      var norm = Math.sqrt(mx * mx + my * my + mz * mz) || 1;
      var mid = new THREE.Vector3(mx - mx / norm * sag, my - my / norm * sag, mz - mz / norm * sag);
      CMD.AP_CURVES.push(new THREE.CatmullRomCurve3([
        new THREE.Vector3(ax, ay, az), mid, new THREE.Vector3(bx, by, bz)
      ]));
    });
    CMD.AP_VALID = CMD.AP_CURVES.map(function(c, i) { return c ? i : -1; }).filter(function(i) { return i >= 0; });
    CMD.AP_GEO = new THREE.SphereGeometry(0.4 * S, 6, 4);
    CMD.AP_TRAIL_GEO = new THREE.CylinderGeometry(0.15 * S, 0.02 * S, 3 * S, 4, 1);
    CMD.AP_TRAIL_GEO.rotateX(Math.PI / 2);
  };

  CMD.fireAP = function() {
    if (CMD.AP_POOL.length >= 80 || !CMD.AP_VALID.length) return;
    var ci = CMD.AP_VALID[Math.floor(Math.random() * CMD.AP_VALID.length)];
    var curve = CMD.AP_CURVES[ci];
    var e = CMD.tubeEdges[ci];
    var src = CMD.nodeMap[e.source], tgt = CMD.nodeMap[e.target];
    if (!src || !tgt || !curve) return;

    var srcCol = CMD.nodeColor(src);
    var w = Math.min(e.weight || 0.5, 1);

    var coreMat = new THREE.MeshBasicMaterial({
      color: srcCol.clone().lerp(new THREE.Color(1, 1, 1), 0.5),
      transparent: true, opacity: 0.6,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    var core = new THREE.Mesh(CMD.AP_GEO, coreMat);
    core.scale.setScalar(0.3 + w * 0.3);

    var trailMat = new THREE.MeshBasicMaterial({
      color: srcCol.clone().lerp(new THREE.Color(1, 1, 1), 0.15),
      transparent: true, opacity: 0.4,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    var trail = new THREE.Mesh(CMD.AP_TRAIL_GEO, trailMat);

    var group = new THREE.Group();
    group.add(core);
    group.add(trail);
    CMD.scene.add(group);

    var speed = (0.008 + Math.random() * 0.015) * (0.8 + w * 0.4);
    CMD.AP_POOL.push({ group: group, core: core, trail: trail, curve: curve, src: src, tgt: tgt, t: 0, speed: speed, w: w });
  };
})();
