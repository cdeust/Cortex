// Cortex Methodology Map — Nodes
window.CMV = window.CMV || {};

/**
 * Create a glow sphere group: bright inner core + translucent outer shell.
 * @param {string} color - Hex color string (e.g. '#00FFFF').
 * @param {number} size - Base size for the sphere.
 * @returns {THREE.Group} Group containing inner and outer meshes.
 */
CMV.createGlowSphere = function (color, size) {
  var hex = parseInt(color.replace('#', ''), 16);

  // Inner bright core
  var inner = new THREE.Mesh(
    new THREE.SphereGeometry(size * 0.4, 16, 16),
    new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.95 })
  );

  // Outer glow shell
  var outer = new THREE.Mesh(
    new THREE.SphereGeometry(size * 0.8, 16, 16),
    new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.12 })
  );

  var group = new THREE.Group();
  group.add(inner);
  group.add(outer);
  return group;
};
