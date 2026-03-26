// Cortex Methodology Map — Tooltip
window.CMV = window.CMV || {};

/**
 * Show tooltip near the cursor for a hovered node.
 * @param {Object} n - Graph node object.
 * @param {number} x - Mouse X position.
 * @param {number} y - Mouse Y position.
 */
CMV.showTip = function (n, x, y) {
  var tip = document.getElementById('tooltip');
  document.getElementById('tt-label').textContent = n.label;
  document.getElementById('tt-type').textContent = CMV.LABELS[n.type] || n.type;
  document.getElementById('tt-type').style.color = CMV.COLORS[n.type] || '#00FFFF';

  var meta = '';
  if (n.sessionCount != null) meta += 'Sessions: ' + n.sessionCount + '\n';
  if (n.frequency != null) meta += 'Freq: ' + n.frequency + '\n';
  if (n.confidence != null) meta += 'Conf: ' + Math.round(n.confidence * 100) + '%\n';
  if (n.ratio != null) meta += 'Usage: ' + Math.round(n.ratio * 100) + '%\n';
  document.getElementById('tt-meta').textContent = meta.trim();

  var tx = x + 16, ty = y + 16;
  if (tx + 240 > innerWidth) tx = x - 256;
  if (ty + 100 > innerHeight) ty = y - 116;
  tip.style.left = tx + 'px';
  tip.style.top = ty + 'px';
  tip.classList.add('visible');
};
