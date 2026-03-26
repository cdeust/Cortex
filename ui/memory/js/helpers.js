// Cortex Memory Dashboard — Helpers
(function() {
  var CMD = window.CMD;

  CMD.escHtml = function(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  };

  CMD.cleanProject = function(raw) {
    if (!raw) return 'unknown';
    var p = raw.replace(/^-Users-[^-]+-/, '').replace(/-/g, '/');
    p = p.replace(/^Developments\//, '').replace(/\/worktrees\/.*$/, '');
    p = p.replace(/\/+/g, '/').replace(/\/$/, '');
    var segs = p.split('/').filter(Boolean);
    return segs.length > 3 ? segs.slice(-3).join('/') : (p || 'unknown');
  };

  CMD.formatDuration = function(start, end) {
    if (!start || !end) return '\u2014';
    var ms = new Date(end) - new Date(start);
    var m = Math.floor(ms / 60000);
    if (m < 1) return '<1 min';
    if (m < 60) return m + ' min';
    var h = Math.floor(m / 60), rm = m % 60;
    return h + 'h' + (rm ? ' ' + rm + 'm' : '');
  };

  CMD.smartTrunc = function(s, n) {
    if (s.length <= n) return s;
    var h = Math.floor((n - 1) / 2);
    return s.slice(0, h) + '\u2026' + s.slice(-(n - h - 1));
  };

  CMD.lerpColor = function(t) {
    var r = Math.round(10 + (0 - 10) * t);
    var g = Math.round(15 + (210 - 15) * t);
    var b = Math.round(20 + (255 - 20) * t);
    return 'rgb(' + r + ',' + g + ',' + b + ')';
  };
})();
