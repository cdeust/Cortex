// Cortex — Workflow Graph: SVG renderer (used for nodes <= threshold).
// Exposes JUG._wfg.mountSVG(container, ctx, sim, panel, width, height).
(function () {
  function mountSVG(container, ctx, sim, panel, width, height) {
    var d3 = window.d3;
    var wfg = window.JUG._wfg;
    var svg = d3.select(container).append('svg')
      .attr('class', 'wfg-svg').attr('width', width).attr('height', height);
    var root = svg.append('g').attr('class', 'wfg-root');
    var zoom = d3.zoom().scaleExtent([0.05, 6]).on('zoom', function (ev) {
      root.attr('transform', ev.transform);
    });
    svg.call(zoom).on('dblclick.zoom', null);

    // Faint shell rings per domain + level labels — makes the
    // L1/L2/L3 hierarchy visible as concentric bands, and places
    // the discussion/memory sector arcs visibly apart.
    var shellG = root.append('g').attr('class', 'wfg-shells');
    drawShells(shellG, ctx);

    var linkSel = root.append('g').attr('class', 'wfg-links')
      .selectAll('line').data(ctx.edges).enter().append('line')
      .attr('class', function (e) {
        return 'wfg-link' + (e._crossDomain ? ' wfg-link--cross' : '') + ' wfg-link--' + (e.kind || 'x');
      })
      .attr('stroke-width', function (e) {
        if (e._crossDomain) return 0.6;
        return 0.8 + (e.weight != null ? e.weight : 0.3) * 1.2;
      });

    var nodeSel = root.append('g').attr('class', 'wfg-nodes')
      .selectAll('g.wfg-node').data(ctx.nodes).enter().append('g')
      .attr('class', function (n) { return 'wfg-node wfg-node--' + n.kind; })
      .style('cursor', 'pointer');
    nodeSel.append('circle')
      .attr('r', function (n) { return wfg.nodeRadius(n); })
      .attr('fill', function (n) { return wfg.nodeColor(n); });
    nodeSel.filter(function (n) {
      return n.kind === 'domain' || n.kind === 'tool_hub' || n.kind === 'agent';
    }).append('text').attr('class', 'wfg-label')
      .attr('dy', function (n) { return -(wfg.nodeRadius(n) + 4); })
      .attr('text-anchor', 'middle')
      .text(function (n) { return wfg.labelOf(n); });

    nodeSel.call(d3.drag()
      .on('start', function (ev, n) {
        if (!ev.active) sim.alphaTarget(0.2).restart();
        n.fx = n.x; n.fy = n.y;
      })
      .on('drag', function (ev, n) { n.fx = ev.x; n.fy = ev.y; })
      .on('end', function (ev, n) {
        if (!ev.active) sim.alphaTarget(0);
        if (n.kind !== 'domain') { n.fx = null; n.fy = null; }
      }));

    var selected = null;
    function highlight(id) {
      var adj = id ? ctx.adj[id] || {} : {};
      nodeSel.classed('wfg-dim',   function (n) { return !!id && n.id !== id && !adj[n.id]; });
      nodeSel.classed('wfg-focus', function (n) { return !!id && n.id === id; });
      linkSel.classed('wfg-link--dim',    function (e) { return !!id && e.source.id !== id && e.target.id !== id; });
      linkSel.classed('wfg-link--active', function (e) { return !!id && (e.source.id === id || e.target.id === id); });
    }
    function pick(n) { selected = n; highlight(n.id); panel.show(n, ctx); }
    function clear() { selected = null; highlight(null); panel.hide(); }
    nodeSel.on('mouseenter', function (_e, n) { if (!selected) highlight(n.id); });
    nodeSel.on('mouseleave', function () { if (!selected) highlight(null); });
    nodeSel.on('click', function (_e, n) { pick(n); });
    svg.on('click', function (ev) { if (ev.target === svg.node()) clear(); });

    sim.on('tick', function () {
      linkSel.attr('x1', function (e) { return e.source.x; })
             .attr('y1', function (e) { return e.source.y; })
             .attr('x2', function (e) { return e.target.x; })
             .attr('y2', function (e) { return e.target.y; });
      nodeSel.attr('transform', function (n) { return 'translate(' + n.x + ',' + n.y + ')'; });
    });

    // Initial fit-to-content zoom so all domains and their L3 shells fit the viewport.
    setTimeout(function () { fitToContent(); }, 80);

    function fitToContent() {
      var pad = 60;
      var r = ctx.baseR + Math.max(220, 260) + pad;    // domain spread + outer shell
      var w = svg.node().clientWidth  || width;
      var h = svg.node().clientHeight || height;
      var cx = ctx.cx, cy = ctx.cy;
      var k = Math.min(w / (2 * r), h / (2 * r), 1);
      var tx = w / 2 - cx * k;
      var ty = h / 2 - cy * k;
      svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
    }

    function applyFilter(pred, fctx) {
      if (typeof pred !== 'function') {
        nodeSel.classed('wfg-filter-out', false);
        linkSel.classed('wfg-filter-out', false);
        return;
      }
      var keep = {};
      for (var i = 0; i < fctx.nodes.length; i++) {
        var n = fctx.nodes[i];
        try { if (pred(n, fctx)) keep[n.id] = true; }
        catch (_) { keep[n.id] = true; }
      }
      nodeSel.classed('wfg-filter-out', function (n) { return !keep[n.id]; });
      linkSel.classed('wfg-filter-out', function (e) {
        return !(keep[e.source.id] && keep[e.target.id]);
      });
    }

    return {
      destroy: function () { svg.remove(); },
      resize: function (w, h) {
        svg.attr('width', w).attr('height', h);
        fitToContent();
      },
      selectId: function (id) { var n = ctx.byId[id]; if (n) pick(n); },
      fit: fitToContent,
      applyFilter: applyFilter,
    };
  }

  // Draw five shell bands per domain: L1/L2/L3 full circles, L4/L5 arcs.
  function drawShells(g, ctx) {
    var d3 = window.d3;
    var anchors = ctx.anchors;
    var TAU = Math.PI * 2;
    ctx.domains.forEach(function (d) {
      var a = anchors[d.id];
      if (!a) return;
      var outward = Math.atan2(a.y - ctx.cy, a.x - ctx.cx);
      if (Math.hypot(a.x - ctx.cx, a.y - ctx.cy) < 5) outward = -Math.PI / 2;
      var domG = g.append('g').attr('class', 'wfg-shell-domain');
      // L1/L2/L3 full rings
      ctx.shells.forEach(function (lv) {
        domG.append('circle')
          .attr('cx', a.x).attr('cy', a.y).attr('r', lv.r)
          .attr('fill', 'none')                         // override SVG default
          .attr('class', 'wfg-shell wfg-shell--' + lv.key);
        // level token, placed on the outward side
        domG.append('text')
          .attr('x', a.x + lv.r * Math.cos(outward))
          .attr('y', a.y + lv.r * Math.sin(outward))
          .attr('class', 'wfg-shell-label wfg-shell-label--' + lv.key)
          .attr('text-anchor', 'middle')
          .attr('dy', -4)
          .text(lv.key);
      });
      // L4/L5: explicit `path` arcs render as filled quadrilaterals
      // under d3-zoom transforms in Safari (fill-attr inheritance quirk).
      // We keep just the level tokens — the discussion/memory sectors
      // are already unmistakable from their colored nodes.
      ctx.sideShells.forEach(function (lv) {
        var mid = outward + lv.angle;
        domG.append('text')
          .attr('x', a.x + lv.r * Math.cos(mid))
          .attr('y', a.y + lv.r * Math.sin(mid))
          .attr('class', 'wfg-shell-label wfg-shell-label--' + lv.key)
          .attr('text-anchor', 'middle')
          .attr('dy', -4)
          .text(lv.key);
      });
    });
  }

  window.JUG = window.JUG || {};
  window.JUG._wfg = window.JUG._wfg || {};
  window.JUG._wfg.mountSVG = mountSVG;
})();
