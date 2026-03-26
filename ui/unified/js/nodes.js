// Cortex Neural Graph — Node Factories
(function() {
  var GEOM_MAP = {
    'domain': JUG.icoGeo,
    'entry-point': JUG.sphereGeo,
    'recurring-pattern': JUG.octaGeo,
    'tool-preference': JUG.boxGeo,
    'behavioral-feature': JUG.tetraGeo,
    'memory': JUG.sphereGeo,
    'entity': JUG.octaGeo,
    'benchmark': JUG.icoGeo,
    'benchmark-ability': JUG.octaGeo,
  };

  function createLabel(text, color) {
    var canvas = document.createElement('canvas');
    canvas.width = 512; canvas.height = 64;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, 512, 64);
    ctx.font = '500 26px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(0,0,0,0.8)';
    ctx.shadowBlur = 6;
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.6;
    ctx.fillText('|', 10, 32);
    ctx.globalAlpha = 1.0;
    ctx.fillText(text, 30, 32);
    ctx.shadowBlur = 0;

    var tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, opacity: 0.9,
      depthWrite: false, sizeAttenuation: true,
    }));
    sprite.scale.set(24, 3, 1);
    sprite.position.set(5, 4, 0);
    sprite.name = 'label';
    sprite.visible = false;
    return sprite;
  }

  function createDomainLabel(text) {
    var canvas = document.createElement('canvas');
    canvas.width = 512; canvas.height = 128;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, 512, 128);
    ctx.font = '700 26px Orbitron, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = '#00FFFF';
    ctx.shadowBlur = 20;
    ctx.fillStyle = '#00FFFF';
    ctx.fillText(text.toUpperCase(), 256, 58);
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#E8F8FF';
    ctx.fillText(text.toUpperCase(), 256, 58);
    var w = ctx.measureText(text.toUpperCase()).width;
    ctx.strokeStyle = 'rgba(0,255,255,0.25)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(256 - w / 2, 78); ctx.lineTo(256 + w / 2, 78); ctx.stroke();

    var tex = new THREE.CanvasTexture(canvas);
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, depthWrite: false,
    }));
    return sprite;
  }

  JUG.createNode = function(nodeData) {
    var type = nodeData.type;
    var colorHex = JUG.getNodeColor(nodeData);
    var color = new THREE.Color(colorHex);
    var size = nodeData.size || 3;
    var heat = nodeData.heat || 0;
    var geo = GEOM_MAP[type] || JUG.sphereGeo;

    var group = new THREE.Group();

    // Core mesh
    var mat = new THREE.MeshStandardMaterial({
      color: color,
      emissive: color,
      emissiveIntensity: 0.4 + (heat || 0) * 0.4,
      metalness: 0.2,
      roughness: 0.3,
      transparent: true,
      opacity: 0.95,
    });
    var core = new THREE.Mesh(geo, mat);
    core.scale.setScalar(size);
    group.add(core);

    // Glow halo — arousal boosts glow for emotional memories
    var arousal = nodeData.arousal || 0;
    var glowOpacity = type === 'domain' ? 0.2 : (type === 'memory' ? 0.1 + heat * 0.1 + arousal * 0.15 : 0.12);
    var glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: JUG.glowTexture,
      color: color,
      transparent: true,
      opacity: glowOpacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }));
    var glowScale = size * 4;
    if (arousal > 0.3) glowScale *= (1 + arousal * 0.5); // Emotional memories glow larger
    glow.scale.setScalar(glowScale);
    glow.name = 'glow';
    group.add(glow);

    // Emotion ring — colored wireframe ring around emotional memories
    if (type === 'memory' && nodeData.emotion && nodeData.emotion !== 'neutral' && arousal > 0.2) {
      var ringColor = new THREE.Color(colorHex);
      var ringGeo = new THREE.TorusGeometry(size * 1.4, size * 0.08, 8, 32);
      var ringMat = new THREE.MeshBasicMaterial({
        color: ringColor, transparent: true, opacity: 0.3 + arousal * 0.3,
        wireframe: true, depthWrite: false,
      });
      var ring = new THREE.Mesh(ringGeo, ringMat);
      ring.name = 'emotionRing';
      ring.userData.pulseSpeed = 0.5 + arousal * 1.5; // Higher arousal = faster pulse
      ring.userData.baseOpacity = ringMat.opacity;
      group.add(ring);
    }

    // Label
    var labelText = (nodeData.label || '').slice(0, 25);
    if (labelText.length > 22) labelText = labelText.slice(0, 22) + '...';
    // Prefix emotional memories with emotion indicator
    if (type === 'memory' && nodeData.emotion && nodeData.emotion !== 'neutral') {
      var emoPrefix = { urgency: '!!', frustration: '><', satisfaction: ':)', discovery: '*', confusion: '??' };
      labelText = (emoPrefix[nodeData.emotion] || '') + ' ' + labelText;
    }
    group.add(createLabel(labelText, colorHex));

    // Domain hubs get a large floating label
    if (type === 'domain') {
      var domLabel = createDomainLabel(nodeData.label || nodeData.domain || '');
      domLabel.scale.set(size * 12, size * 3, 1);
      domLabel.position.set(0, size * 2, 0);
      domLabel.name = 'domainLabel';
      group.add(domLabel);
    }

    // Bloom
    core.layers.enable(JUG.BLOOM_LAYER);

    group.userData = { baseScale: size, coreMesh: core, nodeData: nodeData };
    return group;
  };
})();
