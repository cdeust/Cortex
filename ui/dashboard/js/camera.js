// Cortex Memory Dashboard — Camera
// Always fit all data, no fixed starting position.

(function() {

  function fitCameraImmediate() {
    var nodes = JMD.allNodes;
    if (nodes.length === 0) return;

    // Compute bounding box
    var minX = Infinity, maxX = -Infinity;
    var minY = Infinity, maxY = -Infinity;
    var minZ = Infinity, maxZ = -Infinity;

    nodes.forEach(function(n) {
      var p = n.group.position;
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
      if (p.z < minZ) minZ = p.z;
      if (p.z > maxZ) maxZ = p.z;
    });

    var cx = (minX + maxX) / 2;
    var cy = (minY + maxY) / 2;
    var cz = (minZ + maxZ) / 2;

    // Distance: use bounding sphere radius, pull camera back to see everything
    var bboxRadius = Math.sqrt(
      (maxX - minX) * (maxX - minX) +
      (maxY - minY) * (maxY - minY) +
      (maxZ - minZ) * (maxZ - minZ)
    ) / 2;
    var fov = JMD.camera.fov * Math.PI / 180;
    var dist = bboxRadius / Math.sin(fov / 2);
    dist = Math.max(200, dist * 1.3); // 30% padding

    // Place camera looking at the helix from the side
    JMD.camera.position.set(cx, cy, cz + dist);
    JMD.controls.target.set(cx, cy, cz);
    JMD.controls.update();
  }

  function fitCameraSmooth() {
    var nodes = JMD.allNodes;
    if (nodes.length === 0) return;

    var minX = Infinity, maxX = -Infinity;
    var minY = Infinity, maxY = -Infinity;
    var minZ = Infinity, maxZ = -Infinity;

    nodes.forEach(function(n) {
      var p = n.group.position;
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
      if (p.z < minZ) minZ = p.z;
      if (p.z > maxZ) maxZ = p.z;
    });

    var cx = (minX + maxX) / 2;
    var cy = (minY + maxY) / 2;
    var cz = (minZ + maxZ) / 2;
    var bboxRadius = Math.sqrt(
      (maxX - minX) * (maxX - minX) +
      (maxY - minY) * (maxY - minY) +
      (maxZ - minZ) * (maxZ - minZ)
    ) / 2;
    var fov = JMD.camera.fov * Math.PI / 180;
    var dist = Math.max(200, (bboxRadius / Math.sin(fov / 2)) * 1.3);

    var targetPos = new THREE.Vector3(cx, cy, cz + dist);
    var targetLook = new THREE.Vector3(cx, cy, cz);
    var startPos = JMD.camera.position.clone();
    var startTarget = JMD.controls.target.clone();
    var startTime = performance.now();

    function step() {
      var t = Math.min((performance.now() - startTime) / 1000, 1);
      var e = 1 - Math.pow(1 - t, 3);
      JMD.camera.position.lerpVectors(startPos, targetPos, e);
      JMD.controls.target.lerpVectors(startTarget, targetLook, e);
      if (t < 1) requestAnimationFrame(step);
    }
    step();
  }

  // Export
  JMD.fitCameraImmediate = fitCameraImmediate;
  JMD.fitCameraSmooth = fitCameraSmooth;

  JMD.resetCamera = function() {
    JMD.deselectNode();
    fitCameraSmooth();
  };
})();
