// JARVIS Unified Graph — Three.js Scene
(function() {
  var W = 800, H = 600;

  var scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0a0f);
  scene.fog = new THREE.FogExp2(0x0a0a0f, 0.0003);

  var camera = new THREE.PerspectiveCamera(60, W / H, 1, 6000);
  camera.position.set(0, 0, 500);

  var renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(W, H);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.4;

  function insertCanvas() {
    var container = document.getElementById('graph-container');
    if (container) {
      container.appendChild(renderer.domElement);
      resizeToContainer();
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', insertCanvas);
  } else {
    requestAnimationFrame(insertCanvas);
  }

  function resizeToContainer() {
    var container = document.getElementById('graph-container');
    if (!container) return;
    var rect = container.getBoundingClientRect();
    W = Math.max(rect.width, 100);
    H = Math.max(rect.height, 100);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
    renderer.setSize(W, H);
    if (composer) composer.setSize(W, H);
    if (bloomComposer) bloomComposer.setSize(W, H);
  }

  var controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.rotateSpeed = 0.4;
  controls.zoomSpeed = 0.8;
  controls.minDistance = 30;
  controls.maxDistance = 3000;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.2;

  // Lights
  scene.add(new THREE.AmbientLight(0x101520, 2));
  var pl1 = new THREE.PointLight(0x00d2ff, 30, 1500);
  pl1.position.set(0, 300, 100);
  scene.add(pl1);
  var pl2 = new THREE.PointLight(0xd946ef, 15, 1000);
  pl2.position.set(-300, -150, -300);
  scene.add(pl2);
  var pl3 = new THREE.PointLight(0x26de81, 15, 1000);
  pl3.position.set(200, -80, 200);
  scene.add(pl3);
  var dl = new THREE.DirectionalLight(0x4060a0, 1);
  dl.position.set(100, 300, 200);
  scene.add(dl);

  // Selective bloom
  var BLOOM_LAYER = 1;
  var bloomLayer = new THREE.Layers();
  bloomLayer.set(BLOOM_LAYER);
  var darkMat = new THREE.MeshBasicMaterial({ color: 0x000000 });
  var savedMaterials = {};

  var bloomComposer = new THREE.EffectComposer(renderer);
  bloomComposer.renderToScreen = false;
  bloomComposer.addPass(new THREE.RenderPass(scene, camera));
  bloomComposer.addPass(new THREE.UnrealBloomPass(
    new THREE.Vector2(W, H), 0.8, 0.4, 0.3
  ));

  var finalShader = {
    uniforms: {
      baseTexture: { value: null },
      bloomTexture: { value: bloomComposer.renderTarget2.texture },
    },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: [
      'uniform sampler2D baseTexture;',
      'uniform sampler2D bloomTexture;',
      'varying vec2 vUv;',
      'void main() {',
      '  gl_FragColor = texture2D(baseTexture, vUv) + texture2D(bloomTexture, vUv);',
      '}',
    ].join('\n'),
  };

  var composer = new THREE.EffectComposer(renderer);
  composer.addPass(new THREE.RenderPass(scene, camera));
  var finalPass = new THREE.ShaderPass(new THREE.ShaderMaterial(finalShader), 'baseTexture');
  finalPass.needsSwap = true;
  composer.addPass(finalPass);

  // Vignette + film grain
  var vignetteShader = {
    uniforms: { tDiffuse: { value: null }, darkness: { value: 1.0 } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: [
      'uniform sampler2D tDiffuse; uniform float darkness; varying vec2 vUv;',
      'void main() {',
      '  vec4 c = texture2D(tDiffuse, vUv);',
      '  vec2 u = (vUv - 0.5) * 2.0;',
      '  float v = 1.0 - dot(u,u) * darkness * 0.25;',
      '  float grain = (fract(sin(dot(vUv*1000.0,vec2(12.9898,78.233)))*43758.5453)-0.5)*0.02;',
      '  gl_FragColor = vec4(c.rgb * clamp(v,0.0,1.0) + grain, c.a);',
      '}',
    ].join('\n'),
  };
  composer.addPass(new THREE.ShaderPass(vignetteShader));

  function darkenNonBloomed(obj) {
    if ((obj.isMesh || obj.isSprite || obj.isLine) && !bloomLayer.test(obj.layers)) {
      savedMaterials[obj.uuid] = obj.material;
      obj.material = darkMat;
    }
  }
  function restoreMaterials(obj) {
    if (savedMaterials[obj.uuid]) {
      obj.material = savedMaterials[obj.uuid];
      delete savedMaterials[obj.uuid];
    }
  }

  var nodeGroup = new THREE.Group();
  scene.add(nodeGroup);

  // Shared geometries
  var sphereGeo = new THREE.IcosahedronGeometry(1, 2);
  var octaGeo = new THREE.OctahedronGeometry(1, 0);
  var boxGeo = new THREE.BoxGeometry(1.4, 1.4, 1.4);
  var tetraGeo = new THREE.TetrahedronGeometry(1, 0);
  var icoGeo = new THREE.IcosahedronGeometry(1, 1);

  // Glow texture
  function createGlowTexture() {
    var s = 128, c = document.createElement('canvas');
    c.width = s; c.height = s;
    var ctx = c.getContext('2d');
    var g = ctx.createRadialGradient(s/2,s/2,0, s/2,s/2,s/2);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.15, 'rgba(255,255,255,0.6)');
    g.addColorStop(0.4, 'rgba(255,255,255,0.15)');
    g.addColorStop(0.7, 'rgba(255,255,255,0.03)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, s, s);
    return new THREE.CanvasTexture(c);
  }

  // Highlight mesh
  var hlMat = new THREE.MeshBasicMaterial({
    color: 0xf59e0b, transparent: true, opacity: 0.2,
    blending: THREE.AdditiveBlending, wireframe: true,
  });
  var highlightMesh = new THREE.Mesh(sphereGeo, hlMat);
  highlightMesh.visible = false;
  scene.add(highlightMesh);

  window.addEventListener('resize', resizeToContainer);

  // Export
  JUG.scene = scene;
  JUG.camera = camera;
  JUG.renderer = renderer;
  JUG.composer = composer;
  JUG.bloomComposer = bloomComposer;
  JUG.controls = controls;
  JUG.nodeGroup = nodeGroup;
  JUG.glowTexture = createGlowTexture();
  JUG.sphereGeo = sphereGeo;
  JUG.octaGeo = octaGeo;
  JUG.boxGeo = boxGeo;
  JUG.tetraGeo = tetraGeo;
  JUG.icoGeo = icoGeo;
  JUG.highlightMesh = highlightMesh;
  JUG.BLOOM_LAYER = BLOOM_LAYER;
  JUG.darkenNonBloomed = darkenNonBloomed;
  JUG.restoreMaterials = restoreMaterials;
  JUG.resizeToContainer = resizeToContainer;
})();
