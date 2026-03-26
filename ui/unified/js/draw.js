// Cortex Neural Graph — Canvas Drawing
// Large glowing circles, bright cyan edges, neural network aesthetic
(function() {
  var animFrame = 0;
  (function tick() { animFrame++; requestAnimationFrame(tick); })();

  JUG._draw = {};
  JUG._draw.animFrame = function() { return animFrame; };

  // ── Node sizing — large visible circles ──
  JUG._draw.nodeRadius = function(n) {
    var base = n.size || 3;
    if (n.type === 'domain') return Math.max(6, base * 0.9);
    return Math.max(2.2, base * 0.45);
  };

  JUG._draw.hitArea = function(node, color, ctx) {
    var r = JUG._draw.nodeRadius(node) + 3;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fill();
  };

  // ── Color utilities ──
  function rgba(hex, a) {
    var r = parseInt(hex.slice(1, 3), 16) || 0;
    var g = parseInt(hex.slice(3, 5), 16) || 0;
    var b = parseInt(hex.slice(5, 7), 16) || 0;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }
  JUG._draw.colorAlpha = rgba;

  function lighten(hex, f) {
    var r = Math.min(255, (parseInt(hex.slice(1, 3), 16) || 0) * (1 + f));
    var g = Math.min(255, (parseInt(hex.slice(3, 5), 16) || 0) * (1 + f));
    var b = Math.min(255, (parseInt(hex.slice(5, 7), 16) || 0) * (1 + f));
    return 'rgb(' + Math.round(r) + ',' + Math.round(g) + ',' + Math.round(b) + ')';
  }

  // ── Node rendering — large solid glowing circles ──
  JUG._draw.node = function(node, ctx, globalScale, hoveredId, selectedId, neighbors) {
    var x = node.x, y = node.y;
    if (x === undefined || y === undefined) return;
    var r = JUG._draw.nodeRadius(node);
    var color = JUG.getNodeColor(node);
    var isHighlit = node.id === hoveredId || node.id === selectedId;
    var isDimmed = selectedId && node.id !== selectedId && !neighbors[node.id];

    ctx.globalAlpha = isDimmed ? 0.08 : 1.0;

    // Outer glow halo — wide soft bloom
    var glowR = isHighlit ? r * 5 : r * 3;
    var glowA = isHighlit ? 0.35 : (node.type === 'domain' ? 0.2 : 0.12);
    var grad = ctx.createRadialGradient(x, y, r * 0.5, x, y, glowR);
    grad.addColorStop(0, rgba(color, glowA));
    grad.addColorStop(0.5, rgba(color, glowA * 0.3));
    grad.addColorStop(1, 'transparent');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(x, y, glowR, 0, 2 * Math.PI);
    ctx.fill();

    // Solid circle body — bright fill with specular highlight
    var bodyGrad = ctx.createRadialGradient(x - r * 0.3, y - r * 0.35, r * 0.1, x, y, r);
    bodyGrad.addColorStop(0, lighten(color, 0.6));
    bodyGrad.addColorStop(0.6, color);
    bodyGrad.addColorStop(1, rgba(color, 0.85));
    ctx.fillStyle = bodyGrad;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fill();

    // Thin bright rim
    ctx.strokeStyle = rgba(lighten(color, 0.3), 0.6);
    ctx.lineWidth = 0.4;
    ctx.stroke();

    // Quality indicator ring — green (≥0.6), amber (≥0.3), red (<0.3)
    if (node.quality !== undefined && !isDimmed) {
      var q = node.quality;
      var qColor = q >= 0.6 ? '#40D870' : q >= 0.3 ? '#E0B040' : '#E05050';
      var qAlpha = 0.5 + q * 0.4;
      ctx.strokeStyle = rgba(qColor, qAlpha);
      ctx.lineWidth = 0.6;
      // Draw arc proportional to quality (full circle = 1.0)
      ctx.beginPath();
      ctx.arc(x, y, r + 1.5, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * q);
      ctx.stroke();
    }

    // Protected indicator
    if (node.isProtected && !isDimmed) {
      ctx.strokeStyle = rgba('#D4A040', 0.6);
      ctx.lineWidth = 0.5;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.arc(x, y, r + 2.8, 0, 2 * Math.PI);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Emotion pulse
    if (node.emotion && node.emotion !== 'neutral' && (node.arousal || 0) > 0.2 && !isDimmed) {
      var pulse = 0.3 + 0.5 * Math.sin(animFrame * 0.04 * (0.5 + (node.arousal || 0)));
      ctx.strokeStyle = rgba(color, Math.abs(pulse) * 0.5);
      ctx.lineWidth = 0.4;
      ctx.beginPath();
      ctx.arc(x, y, r + 3, 0, 2 * Math.PI);
      ctx.stroke();
    }

    // Labels
    if (!isDimmed) drawLabel(ctx, node, x, y, r, globalScale, isHighlit);

    ctx.globalAlpha = 1.0;
  };

  function drawLabel(ctx, node, x, y, r, scale, isHighlit) {
    var show = node.type === 'domain' || isHighlit || scale > 2.0;
    if (!show) return;
    var fs = node.type === 'domain' ? Math.max(3, r * 0.45) : Math.max(1.8, 2.2);
    ctx.font = (node.type === 'domain' ? '600 ' : '400 ') + fs + 'px "JetBrains Mono", monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillStyle = node.type === 'domain' ? rgba('#C0E8FF', 0.9) : rgba('#90B0C8', 0.7);
    ctx.fillText((node.label || '').slice(0, 24), x, y + r + 1.5);
  }

})();
