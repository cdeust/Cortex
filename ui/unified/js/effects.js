// Cortex Neural Graph — Ambient Effects
(function() {
  // Dust particles
  var DUST_COUNT = 120;
  var dustPositions = new Float32Array(DUST_COUNT * 3);
  var dustVelocities = [];

  for (var i = 0; i < DUST_COUNT; i++) {
    dustPositions[i * 3] = (Math.random() - 0.5) * 1200;
    dustPositions[i * 3 + 1] = (Math.random() - 0.5) * 1200;
    dustPositions[i * 3 + 2] = (Math.random() - 0.5) * 1200;
    dustVelocities.push({
      x: (Math.random() - 0.5) * 0.15,
      y: (Math.random() - 0.5) * 0.15,
      z: (Math.random() - 0.5) * 0.15,
    });
  }

  var dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3));
  var dustMat = new THREE.PointsMaterial({
    color: 0x00ccff, size: 0.8, transparent: true, opacity: 0.06,
    blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
  });
  var dust = new THREE.Points(dustGeo, dustMat);
  JUG.scene.add(dust);

  function updateDust() {
    var pos = dustGeo.attributes.position.array;
    for (var i = 0; i < DUST_COUNT; i++) {
      pos[i * 3] += dustVelocities[i].x;
      pos[i * 3 + 1] += dustVelocities[i].y;
      pos[i * 3 + 2] += dustVelocities[i].z;
      // Wrap around
      if (Math.abs(pos[i * 3]) > 600) pos[i * 3] *= -0.9;
      if (Math.abs(pos[i * 3 + 1]) > 600) pos[i * 3 + 1] *= -0.9;
      if (Math.abs(pos[i * 3 + 2]) > 600) pos[i * 3 + 2] *= -0.9;
    }
    dustGeo.attributes.position.needsUpdate = true;
  }

  JUG.updateDust = updateDust;
})();
