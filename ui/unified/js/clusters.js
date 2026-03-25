// Cortex Neural Graph — Cluster Visualization
(function() {
  var clusterMeshes = [];

  function buildClusters(clusterData, allNodes) {
    clearClusters();
    if (!clusterData || !clusterData.length) return;

    // Build node ID → index map
    var idMap = {};
    allNodes.forEach(function(n, i) {
      var d = n.data || (n.group && n.group.userData.nodeData);
      if (d) idMap[d.id] = i;
    });

    clusterData.forEach(function(cluster) {
      var members = cluster.member_ids || [];
      if (members.length < 3) return;

      // Collect positions
      var positions = [];
      members.forEach(function(mid) {
        var idx = idMap[mid];
        if (idx !== undefined && allNodes[idx]) {
          positions.push(allNodes[idx].group.position);
        }
      });
      if (positions.length < 3) return;

      // Compute centroid and bounding sphere
      var cx = 0, cy = 0, cz = 0;
      positions.forEach(function(p) { cx += p.x; cy += p.y; cz += p.z; });
      cx /= positions.length;
      cy /= positions.length;
      cz /= positions.length;

      var maxR = 0;
      positions.forEach(function(p) {
        var d = Math.sqrt((p.x - cx) * (p.x - cx) + (p.y - cy) * (p.y - cy) + (p.z - cz) * (p.z - cz));
        if (d > maxR) maxR = d;
      });
      maxR = Math.max(maxR + 20, 40); // padding

      var color = new THREE.Color(cluster.color || '#6366f1');

      // Translucent sphere boundary
      var shellGeo = new THREE.SphereGeometry(maxR, 24, 24);
      var shellMat = new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0.02,
        wireframe: false,
        side: THREE.BackSide,
        depthWrite: false,
      });
      var shell = new THREE.Mesh(shellGeo, shellMat);
      shell.position.set(cx, cy, cz);
      shell.name = 'clusterShell';
      JUG.scene.add(shell);
      clusterMeshes.push(shell);

      // Wireframe ring
      var ringGeo = new THREE.TorusGeometry(maxR * 0.8, 0.3, 8, 48);
      var ringMat = new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0.06,
        wireframe: true,
        depthWrite: false,
      });
      var ring = new THREE.Mesh(ringGeo, ringMat);
      ring.position.set(cx, cy, cz);
      ring.rotation.x = Math.PI / 2;
      ring.name = 'clusterRing';
      JUG.scene.add(ring);
      clusterMeshes.push(ring);

      // Nebula particle cloud
      var cloudCount = Math.min(positions.length * 3, 60);
      var cloudPositions = new Float32Array(cloudCount * 3);
      var cloudColors = new Float32Array(cloudCount * 3);
      for (var ci = 0; ci < cloudCount; ci++) {
        var theta = Math.random() * Math.PI * 2;
        var phi = Math.acos(2 * Math.random() - 1);
        var r = maxR * Math.pow(Math.random(), 0.5) * 0.8;
        cloudPositions[ci * 3] = cx + r * Math.sin(phi) * Math.cos(theta);
        cloudPositions[ci * 3 + 1] = cy + r * Math.sin(phi) * Math.sin(theta);
        cloudPositions[ci * 3 + 2] = cz + r * Math.cos(phi);
        cloudColors[ci * 3] = color.r;
        cloudColors[ci * 3 + 1] = color.g;
        cloudColors[ci * 3 + 2] = color.b;
      }
      var cloudGeo = new THREE.BufferGeometry();
      cloudGeo.setAttribute('position', new THREE.BufferAttribute(cloudPositions, 3));
      cloudGeo.setAttribute('color', new THREE.BufferAttribute(cloudColors, 3));
      var cloudMat = new THREE.PointsMaterial({
        size: 2, vertexColors: true, transparent: true, opacity: 0.08,
        blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
      });
      var cloud = new THREE.Points(cloudGeo, cloudMat);
      cloud.name = 'clusterCloud';
      JUG.scene.add(cloud);
      clusterMeshes.push(cloud);
    });
  }

  function updateClusterVisibility(zoomLevel) {
    var opacity = zoomLevel === 'L2' ? 1.0 : zoomLevel === 'L1' ? 0.7 : 0.4;
    clusterMeshes.forEach(function(m) {
      m.visible = true;
      if (m.material) {
        if (m.material._baseOpacity === undefined) m.material._baseOpacity = m.material.opacity;
        m.material.opacity = m.material._baseOpacity * opacity;
      }
    });
  }

  function clearClusters() {
    clusterMeshes.forEach(function(m) {
      JUG.scene.remove(m);
      if (m.geometry) m.geometry.dispose();
      if (m.material) m.material.dispose();
    });
    clusterMeshes = [];
  }

  JUG.buildClusters = buildClusters;
  JUG.updateClusterVisibility = updateClusterVisibility;
  JUG.clearClusters = clearClusters;
})();
