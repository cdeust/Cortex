// Cortex Memory Dashboard — Scene
(function() {
  var CMD = window.CMD;

  CMD.initScene = function() {
    var S = CMD.brainScale = Math.max(1.0, Math.sqrt(CMD.nodes.length / 100));
    var W = CMD.W, H = CMD.H;

    var scene = CMD.scene = new THREE.Scene();
    var camera = CMD.camera = new THREE.PerspectiveCamera(50, W / H, 0.5, 3000 * S);
    camera.position.set(0, 40 * S, 560 * S);

    var renderer = CMD.renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(W, H);
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    document.body.appendChild(renderer.domElement);

    var controls = CMD.controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.04;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.25;
    controls.minDistance = 60 * S;
    controls.maxDistance = 1400 * S;

    // Post-processing — subtle bloom
    var composer = CMD.composer = new THREE.EffectComposer(renderer);
    composer.addPass(new THREE.RenderPass(scene, camera));
    var bloom = new THREE.UnrealBloomPass(new THREE.Vector2(W, H), 0.15, 0.6, 0.6);
    composer.addPass(bloom);

    // Vignette
    composer.addPass(new THREE.ShaderPass({
      uniforms: { tDiffuse: { value: null } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }',
      fragmentShader: 'uniform sampler2D tDiffuse; varying vec2 vUv;' +
        'void main(){' +
        '  vec4 c = texture2D(tDiffuse,vUv);' +
        '  vec2 uv=(vUv-.5)*2.;' +
        '  gl_FragColor = vec4(c.rgb*clamp(1.-dot(uv,uv)*.42,0.,1.),c.a);' +
        '}',
    }));

    // Lights
    scene.add(new THREE.AmbientLight(0x111111, 0.4));
    var pl = new THREE.PointLight(0xffffff, 0.25, 600 * S);
    pl.position.set(0, 0, 0);
    scene.add(pl);

    // Raycaster
    CMD.ray = new THREE.Raycaster();
    CMD.mouse = new THREE.Vector2(-9, -9);
  };

  CMD.handleResize = function() {
    var W2 = window.innerWidth, H2 = window.innerHeight;
    CMD.camera.aspect = W2 / H2;
    CMD.camera.updateProjectionMatrix();
    CMD.renderer.setSize(W2, H2);
    CMD.composer.setSize(W2, H2);
  };
})();
