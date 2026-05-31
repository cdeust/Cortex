// Cortex — Workflow Graph (LOD canvas overview).
// Replaces the 600K-node D3 force simulation with a level-of-detail map:
//   L0  → one labelled bubble per domain (sized by node count), laid out
//         on a deterministic spiral. No physics, no per-frame ticking.
//   L1  → click a domain bubble to fan its children around the hub.
//   Any non-domain click → JUG.emit('chain:open', {id, label}) so the
//         chain panel renders a bounded Mermaid DAG for that node.
//
// Public API (unchanged surface): JUG.renderWorkflowGraph(container, data)
//   → { destroy, select, reflow, data }. The bridge calls this with the
//   L0 payload; this module also self-loads L0 on 'graph:ready'.
//
// Schema (server: workflow_graph.v1):
//   node: { id, kind, label|name, domain_id?, size?|count?|weight? }
//   edge: { source, target, kind }  (in_domain links child → domain)
(function () {
  var KIND_COLOR = {
    domain: '#FCD34D', tool_hub: '#F97316', skill: '#FB923C',
    command: '#FACC15', hook: '#A855F7', agent: '#EC4899', mcp: '#6366F1',
    memory: '#10B981', discussion: '#EF4444', entity: '#50B0C8',
    file: '#06B6D4', symbol: '#64748B',
  };
  var MIN_R = 14, MAX_R = 64;       // domain bubble radius range
  var CHILD_R = 7;                  // L1 child node radius
  var CHILD_RING = 130;             // base orbit distance for children

  function colorOf(n) { return n.color || KIND_COLOR[n.kind] || '#50C8E0'; }
  function labelOf(n) {
    return n.label || n.name || n.title || n.path || n.id || '';
  }
  function countOf(n) {
    if (n.count != null) return n.count;
    if (n.size != null) return n.size;
    if (n.node_count != null) return n.node_count;
    if (n.weight != null) return n.weight;
    return 1;
  }

  // ── Deterministic spiral layout for domain hubs (Fibonacci angle) ──
  function layoutDomains(domains, w, h) {
    var cx = w / 2, cy = h / 2;
    var N = Math.max(domains.length, 1);
    var phi = Math.PI * (3 - Math.sqrt(5));
    var baseR = Math.min(w, h) * 0.40;
    var maxC = 1;
    for (var i = 0; i < domains.length; i++) {
      maxC = Math.max(maxC, countOf(domains[i]));
    }
    var pos = {};
    domains.forEach(function (d, i) {
      var r = baseR * Math.sqrt((i + 0.5) / N);
      var theta = i * phi;
      var frac = Math.sqrt(countOf(d) / maxC);   // area-proportional radius
      pos[d.id] = {
        x: cx + r * Math.cos(theta),
        y: cy + r * Math.sin(theta),
        radius: MIN_R + (MAX_R - MIN_R) * frac,
      };
    });
    return pos;
  }

  function renderWorkflowGraph(container, data) {
    if (!container) throw new Error('renderWorkflowGraph: container required');
    var qs = (window.location && window.location.search) || '';
    if (qs.indexOf('viz=tilemap') !== -1
        && window.JUG && typeof window.JUG.mountTilemap === 'function') {
      var p = window.JUG.mountTilemap(container);
      var h = { destroy: function () {}, select: function () {}, data: data };
      Promise.resolve(p).then(function (impl) {
        if (impl && impl.destroy) h.destroy = impl.destroy;
      });
      return h;
    }
    return mount(container, data || { nodes: [], edges: [] });
  }

  function mount(container, data) {
    container.innerHTML = '';
    var state = {
      domains: [],
      domainPos: {},
      children: {},          // domainId → [childNode]
      expanded: {},          // domainId → true
      edges: [],
      scale: 1, panX: 0, panY: 0,
      hover: null,
    };

    var canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;cursor:grab;';
    container.appendChild(canvas);
    var ctx = canvas.getContext('2d');

    var width = container.clientWidth || window.innerWidth;
    var height = container.clientHeight || window.innerHeight;

    function resize(w, h) {
      width = w || container.clientWidth || window.innerWidth;
      height = h || container.clientHeight || window.innerHeight;
      var dpr = window.devicePixelRatio || 1;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      state.domainPos = layoutDomains(state.domains, width, height);
      draw();
    }

    function setData(d) {
      var nodes = (d && d.nodes) || [];
      var edges = (d && d.edges) || (d && d.links) || [];
      state.domains = nodes.filter(function (n) { return n.kind === 'domain'; });
      state.edges = edges;
      state.domainPos = layoutDomains(state.domains, width, height);
      draw();
    }

    // ── L0 self-load (when invoked without domain data) ──
    function loadL0() {
      fetch('/api/graph/phase?name=L0')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (pl) {
          if (!pl || !pl.ready || !(pl.nodes || []).length) {
            setTimeout(loadL0, 600);   // build not ready yet — retry
            return;
          }
          var payload = { nodes: pl.nodes, edges: pl.edges || [],
            meta: { schema: 'workflow_graph.v1' } };
          // Keep lastData populated so detail_panel.js et al. don't break.
          if (window.JUG && JUG.state) JUG.state.lastData = payload;
          setData(payload);
        })
        .catch(function () { setTimeout(loadL0, 800); });
    }

    // ── L1 expansion: fetch children, keep those belonging to domainId ──
    function expandDomain(domainId) {
      if (state.expanded[domainId]) {
        state.expanded[domainId] = false;
        draw();
        return;
      }
      fetch('/api/graph/phase?name=L1')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (pl) {
          if (!pl) return;
          var kids = (pl.nodes || []).filter(function (n) {
            return belongsTo(n, domainId, pl.edges || []);
          });
          state.children[domainId] = kids;
          state.expanded[domainId] = true;
          // Merge into lastData so other panels can resolve the nodes.
          mergeLastData(kids, pl.edges || []);
          draw();
        })
        .catch(function () {});
    }

    function belongsTo(node, domainId, edges) {
      if (node.domain_id === domainId || node.domain === domainId) return true;
      for (var i = 0; i < edges.length; i++) {
        var e = edges[i];
        if (e.kind !== 'in_domain') continue;
        if (e.source === node.id && e.target === domainId) return true;
        if (e.target === node.id && e.source === domainId) return true;
      }
      return false;
    }

    function mergeLastData(nodes, edges) {
      if (!window.JUG || !JUG.state) return;
      var cur = JUG.state.lastData || { nodes: [], edges: [],
        meta: { schema: 'workflow_graph.v1' } };
      var seen = {};
      (cur.nodes || []).forEach(function (n) { seen[n.id] = 1; });
      nodes.forEach(function (n) { if (!seen[n.id]) { cur.nodes.push(n); seen[n.id] = 1; } });
      cur.edges = (cur.edges || []).concat(edges);
      JUG.state.lastData = cur;
    }

    // ── Child layout: fan around the hub on a ring ──
    function childPositions(domainId) {
      var hub = state.domainPos[domainId];
      var kids = state.children[domainId] || [];
      if (!hub || !kids.length) return [];
      var ringR = CHILD_RING + Math.min(120, kids.length * 1.5);
      return kids.map(function (k, i) {
        var t = (i / kids.length) * Math.PI * 2;
        return {
          node: k,
          x: hub.x + ringR * Math.cos(t),
          y: hub.y + ringR * Math.sin(t),
        };
      });
    }

    // ── Rendering ──
    function draw() {
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(state.panX, state.panY);
      ctx.scale(state.scale, state.scale);

      drawDomainEdges();
      // Expanded children first (under hubs), then hubs on top.
      Object.keys(state.expanded).forEach(function (domId) {
        if (state.expanded[domId]) drawChildren(domId);
      });
      state.domains.forEach(drawDomain);

      ctx.restore();
    }

    function drawDomainEdges() {
      ctx.strokeStyle = 'rgba(120,200,220,0.10)';
      ctx.lineWidth = 1;
      var seen = {};
      for (var i = 0; i < state.edges.length; i++) {
        var e = state.edges[i];
        var a = state.domainPos[e.source], b = state.domainPos[e.target];
        if (!a || !b) continue;
        var key = e.source < e.target ? e.source + e.target : e.target + e.source;
        if (seen[key]) continue;
        seen[key] = 1;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
    }

    function drawDomain(d) {
      var p = state.domainPos[d.id];
      if (!p) return;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
      ctx.fillStyle = colorOf(d);
      ctx.globalAlpha = state.hover === d.id ? 1 : 0.85;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = state.expanded[d.id] ? 3 : 1.5;
      ctx.strokeStyle = state.expanded[d.id] ? '#00d4ff' : 'rgba(255,255,255,0.5)';
      ctx.stroke();
      // Label.
      ctx.fillStyle = '#0d1117';
      ctx.font = '600 ' + Math.max(10, Math.min(16, p.radius / 2.4)) + 'px Inter, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      var lbl = labelOf(d);
      if (lbl.length > 18) lbl = lbl.slice(0, 17) + '…';
      ctx.fillText(lbl, p.x, p.y);
    }

    function drawChildren(domId) {
      var hub = state.domainPos[domId];
      if (!hub) return;
      var positions = childPositions(domId);
      ctx.strokeStyle = 'rgba(120,200,220,0.18)';
      ctx.lineWidth = 1;
      positions.forEach(function (cp) {
        ctx.beginPath();
        ctx.moveTo(hub.x, hub.y); ctx.lineTo(cp.x, cp.y); ctx.stroke();
      });
      positions.forEach(function (cp) {
        ctx.beginPath();
        ctx.arc(cp.x, cp.y, CHILD_R, 0, Math.PI * 2);
        ctx.fillStyle = colorOf(cp.node);
        ctx.globalAlpha = state.hover === cp.node.id ? 1 : 0.9;
        ctx.fill();
        ctx.globalAlpha = 1;
      });
    }

    // ── Hit testing (screen → world) ──
    function toWorld(sx, sy) {
      return { x: (sx - state.panX) / state.scale, y: (sy - state.panY) / state.scale };
    }
    function dist2(a, b) {
      var dx = a.x - b.x, dy = a.y - b.y;
      return dx * dx + dy * dy;
    }
    function hitTest(sx, sy) {
      var w = toWorld(sx, sy);
      // Children of expanded domains take priority (drawn under hubs only).
      var domIds = Object.keys(state.expanded);
      for (var di = 0; di < domIds.length; di++) {
        if (!state.expanded[domIds[di]]) continue;
        var positions = childPositions(domIds[di]);
        for (var ci = 0; ci < positions.length; ci++) {
          var cp = positions[ci];
          if (dist2(w, cp) <= (CHILD_R + 3) * (CHILD_R + 3)) {
            return { kind: 'child', node: cp.node };
          }
        }
      }
      for (var i = 0; i < state.domains.length; i++) {
        var d = state.domains[i];
        var p = state.domainPos[d.id];
        if (p && dist2(w, p) <= p.radius * p.radius) {
          return { kind: 'domain', node: d };
        }
      }
      return null;
    }

    // ── Interaction: pan, zoom, click ──
    var dragging = false, dragMoved = false, lastX = 0, lastY = 0;

    function onDown(e) {
      dragging = true; dragMoved = false;
      lastX = e.clientX; lastY = e.clientY;
      canvas.style.cursor = 'grabbing';
    }
    function onMove(e) {
      var rect = canvas.getBoundingClientRect();
      if (dragging) {
        var dx = e.clientX - lastX, dy = e.clientY - lastY;
        if (Math.abs(dx) + Math.abs(dy) > 3) dragMoved = true;
        state.panX += dx; state.panY += dy;
        lastX = e.clientX; lastY = e.clientY;
        draw();
        return;
      }
      var hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
      var newHover = hit ? hit.node.id : null;
      if (newHover !== state.hover) { state.hover = newHover; draw(); }
      canvas.style.cursor = hit ? 'pointer' : 'grab';
    }
    function onUp(e) {
      canvas.style.cursor = 'grab';
      if (!dragging) return;
      dragging = false;
      if (dragMoved) return;
      var rect = canvas.getBoundingClientRect();
      var hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
      if (!hit) return;
      if (hit.kind === 'domain') {
        expandDomain(hit.node.id);
      } else if (hit.kind === 'child') {
        if (window.JUG && JUG.emit) {
          JUG.emit('chain:open', { id: hit.node.id, label: labelOf(hit.node) });
        }
      }
    }
    function onWheel(e) {
      e.preventDefault();
      var rect = canvas.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      var newScale = Math.max(0.2, Math.min(6, state.scale * factor));
      // Zoom toward cursor.
      state.panX = mx - (mx - state.panX) * (newScale / state.scale);
      state.panY = my - (my - state.panY) * (newScale / state.scale);
      state.scale = newScale;
      draw();
    }

    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    function onResize() { resize(); }
    window.addEventListener('resize', onResize);

    // Reset button (existing #reset-btn) — re-center the view.
    function resetView() {
      state.scale = 1; state.panX = 0; state.panY = 0; draw();
    }
    var resetBtn = document.getElementById('reset-btn');
    if (resetBtn) resetBtn.addEventListener('click', resetView);

    // Boot: render passed data, else self-load L0.
    resize();
    if ((data.nodes || []).some(function (n) { return n.kind === 'domain'; })) {
      setData(data);
    } else {
      loadL0();
    }

    return {
      data: data,
      destroy: function () {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
        window.removeEventListener('resize', onResize);
        if (resetBtn) resetBtn.removeEventListener('click', resetView);
        if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
      },
      select: function (id) { state.hover = id; draw(); },
      reflow: function () { resize(); },
      applyFilter: function () {},   // LOD overview has no per-node filter
    };
  }

  window.JUG = window.JUG || {};
  window.JUG._wfg = window.JUG._wfg || {};
  window.JUG._wfg.nodeColor = colorOf;
  window.JUG._wfg.labelOf = labelOf;
  window.JUG.renderWorkflowGraph = renderWorkflowGraph;
  // ``resetCamera`` / ``selectNodeById`` / ``deselectNode`` were provided by
  // the removed renderer.js / graph.js. controls.js (Reset, R key) and
  // detail_panel.js (related-node links, close) call them unguarded, so keep
  // safe no-op defaults — the LOD canvas owns its own select/reset via hover
  // state and the #reset-btn handler bound in mount().
  if (!window.JUG.resetCamera) window.JUG.resetCamera = function () {};
  if (!window.JUG.selectNodeById) window.JUG.selectNodeById = function () {};
  if (!window.JUG.deselectNode) window.JUG.deselectNode = function () {};

  // When the graph becomes ready, prime lastData with L0 domains so the
  // bridge (state:lastData → renderWorkflowGraph) mounts the overview.
  if (window.JUG && JUG.on) {
    JUG.on('graph:ready', function () {
      var d = JUG.state && JUG.state.lastData;
      if (d && (d.nodes || []).some(function (n) { return n.kind === 'domain'; })) {
        return;
      }
      fetch('/api/graph/phase?name=L0')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (pl) {
          if (pl && pl.ready && (pl.nodes || []).length && JUG.state) {
            JUG.state.lastData = { nodes: pl.nodes, edges: pl.edges || [],
              meta: { schema: 'workflow_graph.v1' } };
          }
        })
        .catch(function () {});
    });
  }
})();
