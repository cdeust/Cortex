// Cortex Memory Dashboard — Layout
(function() {
  var CMD = window.CMD;

  CMD.fibPlace = function(arr, cx, cy, cz, r, ry, phase) {
    var N = arr.length;
    arr.forEach(function(n, i) {
      var t = (i + 0.5) / Math.max(N, 1);
      var inc = Math.acos(1 - 2 * t), az = phase + i * CMD.GOLDEN;
      var rr = r * (0.82 + (i % 3) * 0.12);
      var pos = CMD.clamp(
        cx + Math.sin(inc) * Math.cos(az) * rr,
        cy + Math.cos(inc) * ry,
        cz + Math.sin(inc) * Math.sin(az) * rr
      );
      n.bx = pos[0]; n.by = pos[1]; n.bz = pos[2];
    });
  };

  CMD.computeClusterLayout = function() {
    var S = CMD.brainScale;
    var nodes = CMD.nodes;

    CMD.globalNs.forEach(function(n, i) {
      var a = i * CMD.GOLDEN;
      var pos = CMD.clamp(Math.cos(a) * 12 * S, -18 * S + i * 8 * S, Math.sin(a) * 12 * S);
      n.bx = pos[0]; n.by = pos[1]; n.bz = pos[2];
    });
    CMD.fibPlace(CMD.planNs, 0, 25 * S, 50 * S, 70 * S, 46 * S, 0);
    CMD.fibPlace(CMD.pluginNs, 0, 8 * S, -20 * S, 46 * S, 30 * S, Math.PI);
    CMD.fibPlace(CMD.todoNs, 0, 12 * S, 0, 88 * S, 58 * S, CMD.GOLDEN * 4);

    var N_HUBS = CMD.hubNs.length;
    CMD.hubNs.forEach(function(hub, hi) {
      var t = (hi + 0.5) / Math.max(N_HUBS, 1);
      var inc = Math.acos(1 - 2 * t), az = hi * CMD.GOLDEN;
      var pos = CMD.clamp(
        Math.sin(inc) * Math.cos(az) * 95 * S,
        Math.cos(inc) * 74 * S,
        Math.sin(inc) * Math.sin(az) * 93 * S
      );
      hub.bx = pos[0]; hub.by = pos[1]; hub.bz = pos[2];

      var children = nodes.filter(function(n) {
        return n.project === hub.project &&
          (n.nodeType === 'memory' || n.nodeType === 'memory-index' || n.nodeType === 'project-file' || n.nodeType === 'mcp-tool');
      });
      children.forEach(function(c, ci) {
        var ct = (ci + 0.5) / Math.max(children.length, 1);
        var cinc = Math.acos(1 - 2 * ct), caz = az + ci * CMD.GOLDEN, dr = (34 + (ci % 3) * 8) * S;
        var cpos = CMD.clamp(
          hub.bx + Math.sin(cinc) * Math.cos(caz) * dr,
          hub.by + Math.cos(cinc) * dr * 0.5,
          hub.bz + Math.sin(cinc) * Math.sin(caz) * dr
        );
        c.bx = cpos[0]; c.by = cpos[1]; c.bz = cpos[2];
      });

      var hubConvs = CMD.convNs.filter(function(c) { return c.project === hub.project; });
      if (hubConvs.length) {
        var cx2 = Math.sin(inc) * Math.cos(az) * 48 * S;
        var cy2 = Math.cos(inc) * 38 * S;
        var cz2 = Math.sin(inc) * Math.sin(az) * 48 * S;
        hubConvs.forEach(function(c, ci) {
          var ct = (ci + 0.5) / Math.max(hubConvs.length, 1);
          var cinc2 = Math.acos(1 - 2 * ct), caz2 = az + ci * CMD.GOLDEN;
          var dr = (22 + (ci % 5) * 7) * S;
          var cpos = CMD.clamp(
            cx2 + Math.sin(cinc2) * Math.cos(caz2) * dr,
            cy2 + Math.cos(cinc2) * dr,
            cz2 + Math.sin(cinc2) * Math.sin(caz2) * dr
          );
          c.bx = cpos[0]; c.by = cpos[1]; c.bz = cpos[2];
        });
      }
    });

    // Orphan fallback
    nodes.forEach(function(n, ni) {
      if (n.bx !== undefined) return;
      var t = (ni + 0.5) / nodes.length, inc = Math.acos(1 - 2 * t), az = ni * CMD.GOLDEN;
      var pos = CMD.clamp(
        Math.sin(inc) * Math.cos(az) * 75 * S,
        Math.cos(inc) * 55 * S,
        Math.sin(inc) * Math.sin(az) * 75 * S
      );
      n.bx = pos[0]; n.by = pos[1]; n.bz = pos[2];
    });
  };

  CMD.computeTimelineLayout = function() {
    var S = CMD.brainScale;
    var nodes = CMD.nodes;
    var minTime = Infinity, maxTime = -Infinity;
    nodes.forEach(function(n) {
      var ts = n.startedAt || n.modifiedAt;
      if (ts) { var t = new Date(ts).getTime(); if (t < minTime) minTime = t; if (t > maxTime) maxTime = t; }
    });
    var projects = {};
    nodes.forEach(function(n) { if (!projects[n.project]) projects[n.project] = []; projects[n.project].push(n); });
    var projKeys = Object.keys(projects).sort();
    var timeRange = maxTime - minTime || 1;

    projKeys.forEach(function(proj, pi) {
      var bandZ = (pi - projKeys.length / 2) * 55 * S;
      projects[proj].forEach(function(n) {
        var ts = n.startedAt || n.modifiedAt;
        var t = ts ? new Date(ts).getTime() : (minTime + maxTime) / 2;
        var x = ((t - minTime) / timeRange - 0.5) * 260 * S;
        var y = (Math.random() - 0.5) * 18 * S;
        var pos = CMD.clamp(x, y, bandZ + (Math.random() - 0.5) * 22 * S);
        n.bx = pos[0]; n.by = pos[1]; n.bz = pos[2];
      });
    });
  };
})();
