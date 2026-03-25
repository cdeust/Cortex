// Cortex Memory Dashboard — Visual Effects
// Ambient dust particles only. Clean, minimal.

(function() {
  var scene = JMD.scene;

  // ─── Dust particles ──────────────────────────────────────────
  var NUM_DUST = 2000;
  var dustPositions = new Float32Array(NUM_DUST * 3);
  var dustVelocities = [];
  var BOUND = 600, BOUND_Y = 300;

  for (var i = 0; i < NUM_DUST; i++) {
    dustPositions[i * 3]     = (Math.random() - 0.5) * BOUND * 2;
    dustPositions[i * 3 + 1] = (Math.random() - 0.5) * BOUND_Y * 2;
    dustPositions[i * 3 + 2] = (Math.random() - 0.5) * BOUND * 2;
    dustVelocities.push({
      x: (Math.random() - 0.5) * 0.06,
      y: (Math.random() - 0.5) * 0.03,
      z: (Math.random() - 0.5) * 0.06,
    });
  }

  var dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3));

  var dustMat = new THREE.PointsMaterial({
    color: 0x4488aa, size: 0.6,
    transparent: true, opacity: 0.1,
    blending: THREE.AdditiveBlending, depthWrite: false,
    sizeAttenuation: true,
  });
  scene.add(new THREE.Points(dustGeo, dustMat));

  function updateDust() {
    var pos = dustGeo.attributes.position.array;
    for (var j = 0; j < NUM_DUST; j++) {
      var v = dustVelocities[j];
      pos[j * 3] += v.x; pos[j * 3 + 1] += v.y; pos[j * 3 + 2] += v.z;
      if (pos[j * 3] > BOUND)       pos[j * 3] = -BOUND;
      if (pos[j * 3] < -BOUND)      pos[j * 3] = BOUND;
      if (pos[j * 3 + 1] > BOUND_Y) pos[j * 3 + 1] = -BOUND_Y;
      if (pos[j * 3 + 1] < -BOUND_Y) pos[j * 3 + 1] = BOUND_Y;
      if (pos[j * 3 + 2] > BOUND)   pos[j * 3 + 2] = -BOUND;
      if (pos[j * 3 + 2] < -BOUND)  pos[j * 3 + 2] = BOUND;
    }
    dustGeo.attributes.position.needsUpdate = true;
  }

  // Export
  JMD.updateDust = updateDust;
})();
