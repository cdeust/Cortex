// Cortex Memory Dashboard — Animation
(function() {
  var CMD = window.CMD;

  CMD.startAnimation = function() {
    (function animate() {
      requestAnimationFrame(animate);
      CMD.frame++;
      var t = CMD.frame * 0.016;

      // Brain shell breathe + neuron pulse
      if (window._brainShellMat) window._brainShellMat.uniforms.uTime.value = t;
      var br = 1 + Math.sin(t * 0.34) * 0.012;
      CMD.neuronGroup.scale.setScalar(br);

      // Hover: tooltip + highlight
      CMD.ray.setFromCamera(CMD.mouse, CMD.camera);
      var hits = CMD.ray.intersectObjects(
        CMD.neuronGroup.children.filter(function(m) { return m.visible; }), false
      );
      var newHov = hits.length ? hits[0].object.userData.node : null;
      if (newHov !== CMD.hoveredNode) {
        if (CMD.hoveredNode && CMD.hoveredNode !== CMD.selectedNode)
          CMD.hoveredNode._mesh.material.emissiveIntensity = CMD.hoveredNode._baseEmit;
        if (newHov && newHov !== CMD.selectedNode)
          newHov._mesh.material.emissiveIntensity = newHov._baseEmit * 1.5;
        CMD.hoveredNode = newHov;
        CMD.renderer.domElement.style.cursor = newHov ? 'pointer' : 'default';
        if (newHov) CMD.showTooltip(newHov, CMD.mouseScreen.x, CMD.mouseScreen.y);
        else CMD.hideTooltip();
      } else if (newHov) {
        CMD.showTooltip(newHov, CMD.mouseScreen.x, CMD.mouseScreen.y);
      }

      // Neuron subtle pulse
      CMD.nodes.forEach(function(n) {
        if (!n._mesh || n === CMD.selectedNode) return;
        var phase = (n.bx + n.by * 0.7 + n.bz * 0.5) * 0.02;
        n._mesh.material.emissiveIntensity = n._baseEmit + Math.sin(t * 1.1 + phase) * 0.15 * n._baseEmit;
      });

      // Action potentials
      if (CMD.frame - CMD.lastAP > 2 + Math.floor(Math.random() * 4)) {
        CMD.fireAP(); CMD.fireAP();
        if (Math.random() < 0.5) CMD.fireAP();
        CMD.lastAP = CMD.frame;
      }
      for (var i = CMD.AP_POOL.length - 1; i >= 0; i--) {
        var ap = CMD.AP_POOL[i];
        ap.t += ap.speed;
        if (ap.t >= 1) {
          CMD.scene.remove(ap.group);
          ap.core.material.dispose();
          ap.trail.material.dispose();
          CMD.AP_POOL.splice(i, 1);
          var tm = CMD.neuronMeshes[ap.tgt.id];
          if (tm) {
            var b = ap.tgt._baseEmit;
            tm.material.emissiveIntensity = b * 2.0;
            setTimeout(function(mesh, base) {
              return function() { if (mesh.material) mesh.material.emissiveIntensity = base; };
            }(tm, b), 160);
          }
        } else {
          var pos = ap.curve.getPointAt(Math.min(ap.t, 1));
          ap.group.position.copy(pos).multiplyScalar(br);
          var tangent = ap.curve.getTangentAt(Math.min(ap.t, 1));
          ap.trail.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), tangent.normalize());
          ap.trail.material.opacity = 0.7 * (1 - ap.t * 0.5);
          ap.core.material.opacity = 0.8 + 0.2 * Math.sin(ap.t * 20);
        }
      }

      CMD.controls.update();
      CMD.composer.render();
    })();
  };

  CMD.init = async function() {
    try {
      await CMD.initData();
      CMD.initScene();
      CMD.computeClusterLayout();
      CMD.buildBrainShell();
      CMD.buildNeurons();
      CMD.buildFibers();
      CMD.buildConnectionIndex();
      CMD.initPanelClose();
      CMD.initControls();
      CMD.initInteraction();

      // HUD
      document.getElementById('hud').textContent =
        CMD.nodes.length + ' neurons \xb7 ' + CMD.drawEdges.length + ' synapses \xb7 ' + CMD.tubeCount + ' fiber tracts';

      CMD.applyFilters();
      CMD.startAnimation();
    } catch (err) {
      var d = document.createElement('div');
      d.style.cssText = 'position:fixed;top:0;left:0;right:0;background:rgba(255,0,0,0.95);color:#fff;padding:16px;z-index:9999;font:12px monospace;white-space:pre-wrap';
      d.textContent = 'BRAIN ERROR: ' + err.message + '\n' + err.stack;
      document.body.appendChild(d);
      console.error(err);
    }
  };
})();
