// Cortex Memory Dashboard — Neurons
(function() {
  var CMD = window.CMD;
  var geoCache = {};

  function sphereGeo(r) {
    var k = r.toFixed(1);
    if (!geoCache[k]) geoCache[k] = new THREE.SphereGeometry(r, 10, 8);
    return geoCache[k];
  }

  CMD.buildNeurons = function() {
    var neuronGroup = CMD.neuronGroup = new THREE.Group();
    var neuronMeshes = CMD.neuronMeshes = {};

    CMD.nodes.forEach(function(n) {
      var col = CMD.nodeColor(n);
      var r = CMD.neuronR(n);
      var isHub = n.nodeType === 'project-hub';
      var isGlob = n.nodeType === 'global-instruction' || n.nodeType === 'settings';
      var isConv = n.nodeType === 'conversation';
      var isEntity = n.id && n.id.startsWith('e_');
      var isGlobalMem = !!(n.is_global || n.isGlobal);
      var ei = isGlob ? 1.0 : isHub ? 0.8 : isGlobalMem ? 0.7 : isConv ? 0.3 : isEntity ? 0.4 : 0.35;

      var mat = new THREE.MeshStandardMaterial({
        color: col.clone().multiplyScalar(0.25),
        emissive: col,
        emissiveIntensity: ei,
        transparent: true,
        opacity: isConv ? 0.85 : 0.95,
        roughness: 0.3,
        metalness: 0.1,
      });
      var mesh = new THREE.Mesh(sphereGeo(r), mat);
      mesh.position.set(n.bx, n.by, n.bz);
      mesh.userData.node = n;
      neuronGroup.add(mesh);
      neuronMeshes[n.id] = mesh;
      n._mesh = mesh;
      n._baseEmit = ei;
    });
    CMD.scene.add(neuronGroup);

    // Dendrite stubs on hub nodes
    CMD.hubNs.forEach(function(hub, hi) {
      var s = CMD.neuronR(hub);
      for (var i = 0; i < 6; i++) {
        var t = (i + 0.5) / 6, inc = Math.acos(1 - 2 * t), az = hi * CMD.GOLDEN + i * CMD.GOLDEN;
        var len = s * (2.5 + Math.random() * 2);
        var dx = Math.sin(inc) * Math.cos(az), dy = Math.cos(inc) * 0.55, dz = Math.sin(inc) * Math.sin(az);
        var pts = [
          new THREE.Vector3(0, 0, 0),
          new THREE.Vector3(dx * len * 0.45, dy * len * 0.45, dz * len * 0.45),
          new THREE.Vector3(dx * len, dy * len, dz * len)
        ];
        neuronMeshes[hub.id].add(new THREE.Mesh(
          new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 5, 0.1, 4, false),
          new THREE.MeshBasicMaterial({
            color: new THREE.Color(0.7, 0.7, 0.7),
            transparent: true, opacity: 0.25,
            blending: THREE.AdditiveBlending, depthWrite: false
          })
        ));
      }
    });
  };
})();
