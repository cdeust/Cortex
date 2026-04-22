// Cortex — Workflow Graph: Canvas renderer (used for nodes > threshold).
// Exposes JUG._wfg.mountCanvas(container, ctx, sim, panel, width, height).
(function () {
  function mountCanvas(container, ctx, sim, panel, width, height) {
    var d3 = window.d3;
    var wfg = window.JUG._wfg;
    var canvas = document.createElement('canvas');
    canvas.className = 'wfg-canvas';
    canvas.width = width; canvas.height = height;
    canvas.style.width = width + 'px'; canvas.style.height = height + 'px';
    container.appendChild(canvas);
    var g = canvas.getContext('2d');
    var transform = d3.zoomIdentity;
    var hoverId = null, selectedId = null;

    var sel = d3.select(canvas);
    sel.call(d3.zoom().scaleExtent([0.15, 6]).on('zoom', function (ev) {
      transform = ev.transform; draw();
    })).on('dblclick.zoom', null);
    sel.call(d3.drag()
      .subject(function (ev) {
        var p = transform.invert([ev.x, ev.y]);
        return findNode(p[0], p[1]);
      })
      .on('start', function (ev) {
        if (!ev.subject) return;
        if (!ev.active) sim.alphaTarget(0.2).restart();
        ev.subject.fx = ev.subject.x; ev.subject.fy = ev.subject.y;
      })
      .on('drag', function (ev) {
        if (!ev.subject) return;
        var p = transform.invert([ev.x, ev.y]);
        ev.subject.fx = p[0]; ev.subject.fy = p[1];
      })
      .on('end', function (ev) {
        if (!ev.subject) return;
        if (!ev.active) sim.alphaTarget(0);
        if (ev.subject.kind !== 'domain') { ev.subject.fx = null; ev.subject.fy = null; }
      }));

    canvas.addEventListener('mousemove', function (ev) {
      var rect = canvas.getBoundingClientRect();
      var p = transform.invert([ev.clientX - rect.left, ev.clientY - rect.top]);
      var n = findNode(p[0], p[1]);
      var next = n ? n.id : null;
      if (next !== hoverId) { hoverId = next; canvas.style.cursor = n ? 'pointer' : 'default'; draw(); }
    });
    canvas.addEventListener('click', function (ev) {
      var rect = canvas.getBoundingClientRect();
      var p = transform.invert([ev.clientX - rect.left, ev.clientY - rect.top]);
      var n = findNode(p[0], p[1]);
      if (n) { selectedId = n.id; panel.show(n, ctx); } else { selectedId = null; panel.hide(); }
      draw();
    });

    function findNode(x, y) {
      for (var i = ctx.nodes.length - 1; i >= 0; i--) {
        var n = ctx.nodes[i]; var r = wfg.nodeRadius(n) + 2;
        var dx = n.x - x, dy = n.y - y;
        if (dx * dx + dy * dy <= r * r) return n;
      }
      return null;
    }

    // Edge rendering — density-aware.
    // Root cause of the "grey rectangle" users see: each domain has hundreds
    // of in-domain tool_hub→file edges that originate at a single tool_hub
    // point and fan into a bounded angular sector at FILE_R. Canvas 2D
    // additively stacks the stroke alpha across the wedge, so the fan
    // saturates into a solid-looking cyan trapezoid. With 16k+ edges across
    // ~8 domains the trapezoids cover half the viewport. Fix:
    //   (1) drop base alpha to 0.04 so stacking does NOT saturate;
    //   (2) skip in-domain structural edges when zoomed out — the hierarchy
    //       is already visible from the slot layout (node arrangement);
    //   (3) keep cross-domain threads (they're the whole point of the map)
    //       and keep active/focus highlighting so selection still works.
    var STRUCTURAL_KINDS = { in_domain: 1, tool_used_file: 1, invoked_skill: 1,
                             triggered_hook: 1, spawned_agent: 1, command_in_hub: 1 };
    function drawEdges(focusId) {
      var k = transform.k || 1;
      var hideStructural = k < 0.9 && !focusId;
      for (var i = 0; i < ctx.edges.length; i++) {
        var e = ctx.edges[i];
        var dim = focusId && e.source.id !== focusId && e.target.id !== focusId;
        var act = focusId && (e.source.id === focusId || e.target.id === focusId);
        // When zoomed out and nothing is selected, skip the structural fan.
        if (hideStructural && !e._crossDomain && STRUCTURAL_KINDS[e.kind]) continue;
        if (e._crossDomain) {
          g.strokeStyle = act ? 'rgba(240,210,100,0.85)' : (dim ? 'rgba(200,150,255,0.03)' : 'rgba(200,150,255,0.12)');
          g.lineWidth = act ? 1.2 : 0.4;
        } else {
          g.strokeStyle = act ? 'rgba(240,210,100,0.9)' : (dim ? 'rgba(120,180,200,0.02)' : 'rgba(120,180,200,0.04)');
          g.lineWidth = act ? 1.6 : (0.4 + (e.weight != null ? e.weight : 0.3) * 0.5);
        }
        g.beginPath(); g.moveTo(e.source.x, e.source.y); g.lineTo(e.target.x, e.target.y); g.stroke();
      }
    }
    function drawNodes(focusId, adj) {
      // At low zoom, symbols blur into a cloud and drawing each one
      // wastes ~10 ms per frame with 10k+ of them. Skip them below
      // a threshold — the domain/file scaffolding conveys shape.
      // Symbols form the dense cloud that makes the graph look "alive"
      // in the target screenshot. Drawing 10k+ circles at 60 fps costs
      // ~10 ms/frame on desktop — well within budget — so we always
      // draw them regardless of zoom. (Skipping them at zoom<0.4 was
      // hiding the entire cloud at default fit and making the graph
      // look empty.)
      var zoom = transform.k || 1;
      var skipSymbols = zoom < 0.08;   // effectively always show
      for (var j = 0; j < ctx.nodes.length; j++) {
        var n = ctx.nodes[j];
        if (skipSymbols && n.kind === 'symbol' && !focusId) continue;
        var r = wfg.nodeRadius(n);
        var isFocus = focusId === n.id;
        var isDim = focusId && n.id !== focusId && !adj[n.id];
        g.globalAlpha = isDim ? 0.15 : 1.0;
        g.fillStyle = wfg.nodeColor(n);
        g.beginPath(); g.arc(n.x, n.y, r, 0, Math.PI * 2); g.fill();
        if (isFocus) { g.lineWidth = 2; g.strokeStyle = '#F0D870'; g.stroke(); }
        if ((n.kind === 'domain' || n.kind === 'tool_hub') && transform.k > 0.5) {
          g.globalAlpha = isDim ? 0.3 : 0.95;
          g.fillStyle = '#E8E4D8';
          g.font = (n.kind === 'domain' ? '12px ' : '10px ') + "'Inter Tight', system-ui, sans-serif";
          g.textAlign = 'center'; g.textBaseline = 'bottom';
          g.fillText(wfg.labelOf(n), n.x, n.y - r - 3);
        }
        g.globalAlpha = 1.0;
      }
    }
    function drawShells() {
      if (!ctx.shells) return;
      for (var di = 0; di < ctx.domains.length; di++) {
        var d = ctx.domains[di];
        var a = ctx.anchors[d.id];
        if (!a) continue;
        // L1/L2/L3 dashed full circles
        var palette = { L1: 'rgba(255,180,100,0.18)', L2: 'rgba(120,220,200,0.18)', L3: 'rgba(120,180,250,0.14)' };
        g.setLineDash([3, 5]); g.lineWidth = 1;
        for (var k = 0; k < ctx.shells.length; k++) {
          var lv = ctx.shells[k];
          g.strokeStyle = palette[lv.key] || 'rgba(160,150,140,0.12)';
          g.beginPath(); g.arc(a.x, a.y, lv.r, 0, Math.PI * 2); g.stroke();
        }
        g.setLineDash([]);
        // L4/L5 arcs (solid, colored)
        var sidePalette = { L4: 'rgba(244,63,94,0.5)', L5: 'rgba(192,112,208,0.5)' };
        var outward = Math.atan2(a.y - ctx.cy, a.x - ctx.cx);
        for (var s = 0; s < ctx.sideShells.length; s++) {
          var sv = ctx.sideShells[s];
          var mid = outward + sv.angle;
          var half = Math.PI / 4;
          g.strokeStyle = sidePalette[sv.key] || 'rgba(160,150,140,0.3)';
          g.lineWidth = 1.5;
          g.beginPath(); g.arc(a.x, a.y, sv.r, mid - half, mid + half); g.stroke();
        }
        // Level tokens (L1..L5)
        if (transform.k > 0.35) {
          g.font = "9px 'JetBrains Mono', monospace";
          g.textAlign = 'center'; g.textBaseline = 'bottom';
          var labelPalette = {
            L1: 'rgba(255,180,100,0.7)', L2: 'rgba(120,220,200,0.7)', L3: 'rgba(120,180,250,0.55)',
            L4: 'rgba(244,63,94,0.9)',   L5: 'rgba(192,112,208,0.9)',
          };
          var outA = Math.atan2(a.y - ctx.cy, a.x - ctx.cx);
          if (Math.hypot(a.x - ctx.cx, a.y - ctx.cy) < 5) outA = -Math.PI / 2;
          for (var m = 0; m < ctx.shells.length; m++) {
            var lvl = ctx.shells[m];
            g.fillStyle = labelPalette[lvl.key] || 'rgba(160,150,140,0.6)';
            g.fillText(lvl.key, a.x + lvl.r * Math.cos(outA), a.y + lvl.r * Math.sin(outA) - 4);
          }
          for (var n = 0; n < ctx.sideShells.length; n++) {
            var slv = ctx.sideShells[n]; var sideMid = outA + slv.angle;
            g.fillStyle = labelPalette[slv.key] || 'rgba(160,150,140,0.8)';
            g.fillText(slv.key, a.x + slv.r * Math.cos(sideMid), a.y + slv.r * Math.sin(sideMid) - 4);
          }
        }
      }
    }

    function draw() {
      g.save();
      g.clearRect(0, 0, canvas.width, canvas.height);
      g.translate(transform.x, transform.y); g.scale(transform.k, transform.k);
      var focusId = hoverId || selectedId;
      var adj = focusId ? ctx.adj[focusId] || {} : {};
      drawShells();
      drawEdges(focusId);
      drawNodes(focusId, adj);
      g.restore();
    }
    sim.on('tick', draw);

    function fitToContent() {
      var pad = 60;
      var r = (ctx.baseR || 400) + 240 + pad;
      var w = canvas.width, h = canvas.height;
      var cx = ctx.cx || w / 2, cy = ctx.cy || h / 2;
      var k = Math.min(w / (2 * r), h / (2 * r), 1);
      var tx = w / 2 - cx * k, ty = h / 2 - cy * k;
      transform = d3.zoomIdentity.translate(tx, ty).scale(k);
      sel.call(d3.zoom().transform, transform);
      draw();
    }
    setTimeout(fitToContent, 80);

    var filterKeep = null;    // null = show all; map of id → bool otherwise
    function applyFilter(pred, fctx) {
      if (typeof pred !== 'function') { filterKeep = null; draw(); return; }
      filterKeep = {};
      for (var i = 0; i < fctx.nodes.length; i++) {
        var n = fctx.nodes[i];
        try { if (pred(n, fctx)) filterKeep[n.id] = true; }
        catch (_) { filterKeep[n.id] = true; }
      }
      draw();
    }
    // Patch drawEdges + drawNodes via closure: filterKeep gates visibility.
    var origDrawEdges = drawEdges, origDrawNodes = drawNodes;
    drawEdges = function (focusId) {
      if (!filterKeep) return origDrawEdges(focusId);
      var k = transform.k || 1;
      var hideStructural = k < 0.9 && !focusId;
      for (var i = 0; i < ctx.edges.length; i++) {
        var e = ctx.edges[i];
        if (!(filterKeep[e.source.id] && filterKeep[e.target.id])) continue;
        var dim = focusId && e.source.id !== focusId && e.target.id !== focusId;
        var act = focusId && (e.source.id === focusId || e.target.id === focusId);
        // Same structural-fan suppression as the unfiltered path.
        if (hideStructural && !e._crossDomain && STRUCTURAL_KINDS[e.kind]) continue;
        if (e._crossDomain) {
          g.strokeStyle = act ? 'rgba(240,210,100,0.85)' : (dim ? 'rgba(200,150,255,0.03)' : 'rgba(200,150,255,0.12)');
          g.lineWidth = act ? 1.2 : 0.4;
        } else {
          g.strokeStyle = act ? 'rgba(240,210,100,0.9)' : (dim ? 'rgba(120,180,200,0.02)' : 'rgba(120,180,200,0.04)');
          g.lineWidth = act ? 1.6 : (0.4 + (e.weight != null ? e.weight : 0.3) * 0.5);
        }
        g.beginPath(); g.moveTo(e.source.x, e.source.y); g.lineTo(e.target.x, e.target.y); g.stroke();
      }
    };
    drawNodes = function (focusId, adj) {
      if (!filterKeep) return origDrawNodes(focusId, adj);
      // Symbols form the dense cloud that makes the graph look "alive"
      // in the target screenshot. Drawing 10k+ circles at 60 fps costs
      // ~10 ms/frame on desktop — well within budget — so we always
      // draw them regardless of zoom. (Skipping them at zoom<0.4 was
      // hiding the entire cloud at default fit and making the graph
      // look empty.)
      var zoom = transform.k || 1;
      var skipSymbols = zoom < 0.08;   // effectively always show
      for (var j = 0; j < ctx.nodes.length; j++) {
        var n = ctx.nodes[j];
        if (skipSymbols && n.kind === 'symbol' && !focusId) continue;
        var kept = !!filterKeep[n.id];
        var r = wfg.nodeRadius(n);
        var isFocus = focusId === n.id;
        var isDim = !kept || (focusId && n.id !== focusId && !adj[n.id]);
        g.globalAlpha = kept ? (isDim ? 0.06 : 1.0) : 0.04;
        g.fillStyle = wfg.nodeColor(n);
        g.beginPath(); g.arc(n.x, n.y, r, 0, Math.PI * 2); g.fill();
        if (isFocus) { g.lineWidth = 2; g.strokeStyle = '#F0D870'; g.stroke(); }
        if (kept && (n.kind === 'domain' || n.kind === 'tool_hub') && transform.k > 0.5) {
          g.globalAlpha = isDim ? 0.3 : 0.95;
          g.fillStyle = '#E8E4D8';
          g.font = (n.kind === 'domain' ? '12px ' : '10px ') + "'Inter Tight', system-ui, sans-serif";
          g.textAlign = 'center'; g.textBaseline = 'bottom';
          g.fillText(wfg.labelOf(n), n.x, n.y - r - 3);
        }
        g.globalAlpha = 1.0;
      }
    };

    return {
      destroy: function () { if (canvas.parentNode) canvas.parentNode.removeChild(canvas); },
      resize: function (w, h) {
        canvas.width = w; canvas.height = h;
        canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
        fitToContent();
      },
      selectId: function (id) { var n = ctx.byId[id]; if (n) { selectedId = id; panel.show(n, ctx); draw(); } },
      fit: fitToContent,
      applyFilter: applyFilter,
    };
  }

  window.JUG = window.JUG || {};
  window.JUG._wfg = window.JUG._wfg || {};
  window.JUG._wfg.mountCanvas = mountCanvas;
})();
