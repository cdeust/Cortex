// Cortex Methodology Map — Labels
window.CMV = window.CMV || {};

/**
 * Create a canvas texture with Orbitron text, neon cyan glow, and underline.
 * Used for domain hub labels rendered as THREE.Sprite.
 * @param {string} text - Label text to render.
 * @returns {THREE.CanvasTexture} Texture for sprite material.
 */
CMV.makeLabel = function (text) {
  var c = document.createElement('canvas');
  c.width = 512;
  c.height = 128;
  var ctx = c.getContext('2d');
  ctx.clearRect(0, 0, 512, 128);
  ctx.font = '700 26px Orbitron, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  // Glow pass
  ctx.shadowColor = '#00FFFF';
  ctx.shadowBlur = 20;
  ctx.fillStyle = '#00FFFF';
  ctx.fillText(text.toUpperCase(), 256, 58);

  // Crisp pass
  ctx.shadowBlur = 0;
  ctx.fillStyle = '#E8F8FF';
  ctx.fillText(text.toUpperCase(), 256, 58);

  // Underline
  var w = ctx.measureText(text.toUpperCase()).width;
  ctx.strokeStyle = 'rgba(0,255,255,0.25)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(256 - w / 2, 78);
  ctx.lineTo(256 + w / 2, 78);
  ctx.stroke();

  return new THREE.CanvasTexture(c);
};
