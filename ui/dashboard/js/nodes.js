// Cortex Memory Dashboard — Node Builder
// Glowing neural nodes: spheres for memories, octahedrons for entities.
// Strong bloom + halo for DNA-helix visual.

(function() {

  // Shared label canvas
  function createLabel(text, color) {
    var canvas = document.createElement('canvas');
    var w = 512, h = 64;
    canvas.width = w; canvas.height = h;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, w, h);

    // Draw pipe separator + text
    ctx.font = '500 28px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';

    // Shadow for readability
    ctx.shadowColor = 'rgba(0,0,0,0.8)';
    ctx.shadowBlur = 6;
    ctx.shadowOffsetX = 1;
    ctx.shadowOffsetY = 1;

    // Pipe separator
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.6;
    ctx.fillText('|', 10, h / 2);
    ctx.globalAlpha = 1.0;
    ctx.fillText(text, 30, h / 2);

    ctx.shadowBlur = 0;

    var tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    var mat = new THREE.SpriteMaterial({
      map: tex, transparent: true, opacity: 0.9,
      depthWrite: false, sizeAttenuation: true,
    });
    var sprite = new THREE.Sprite(mat);
    sprite.scale.set(24, 3, 1);
    sprite.position.set(5, 4, 0);
    sprite.name = 'label';
    sprite.visible = false;
    return sprite;
  }

  // ─── Memory Node ─────────────────────────────────────────────
  JMD.createMemoryNode = function(m) {
    var typeColor = new THREE.Color(JMD.TYPE_COLORS[m.store_type] || JMD.TYPE_COLORS.episodic);
    var heat = m.heat || 0;
    var importance = m.importance || 0.5;
    var scale = 1.5 + importance * 1.2 + heat * 0.8;

    var group = new THREE.Group();

    // Core sphere — colored with moderate emissive
    var mat = new THREE.MeshStandardMaterial({
      color: typeColor,
      emissive: typeColor,
      emissiveIntensity: 0.5 + heat * 0.3,
      metalness: 0.2, roughness: 0.3,
      transparent: true, opacity: 0.95,
    });
    var core = new THREE.Mesh(JMD.sphereGeo, mat);
    core.scale.setScalar(scale);
    group.add(core);

    // Glow halo
    var glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: JMD.glowTexture, color: typeColor,
      transparent: true, opacity: 0.15 + heat * 0.1,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    glow.scale.setScalar(scale * 4);
    group.add(glow);

    // Label
    var labelText = (m.content || '').slice(0, 25).replace(/\n/g, ' ');
    if (labelText.length > 22) labelText = labelText.slice(0, 22) + '...';
    group.add(createLabel(labelText, '#' + typeColor.getHexString()));

    // Bloom
    core.layers.enable(JMD.BLOOM_LAYER);

    group.userData = { baseScale: scale, coreMesh: core };
    return group;
  };

  // ─── Entity Node ─────────────────────────────────────────────
  JMD.createEntityNode = function(e) {
    var color = new THREE.Color(JMD.TYPE_COLORS.entity);
    var heat = e.heat || 0.5;
    var scale = 2.0 + heat * 1.5;

    var group = new THREE.Group();

    // Octahedron core — colored
    var mat = new THREE.MeshStandardMaterial({
      color: color,
      emissive: color,
      emissiveIntensity: 0.6,
      metalness: 0.3, roughness: 0.2,
      transparent: true, opacity: 0.95,
    });
    var core = new THREE.Mesh(JMD.octaGeo || JMD.sphereGeo, mat);
    core.scale.setScalar(scale);
    group.add(core);

    // Glow halo
    var glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: JMD.glowTexture, color: color,
      transparent: true, opacity: 0.2,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    glow.scale.setScalar(scale * 4.5);
    group.add(glow);

    // Label
    var labelText = (e.name || 'entity').toUpperCase().slice(0, 20);
    group.add(createLabel(labelText, '#' + color.getHexString()));

    // Bloom
    core.layers.enable(JMD.BLOOM_LAYER);

    group.userData = { baseScale: scale, coreMesh: core };
    return group;
  };
})();
