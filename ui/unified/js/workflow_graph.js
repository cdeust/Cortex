// Cortex — Workflow Graph (D3 v7 force layout): orchestration + forces.
// Target: many small brain-region clouds, each internally structured,
// with thin long-range threads between clouds where files/entities are shared.
// Schema: mcp_server/core/workflow_graph_schema.py
//   node kinds: domain, skill, command, hook, agent, tool_hub, file, memory, discussion, entity
//   edge kinds: in_domain, tool_used_file, command_in_hub, invoked_skill, triggered_hook, spawned_agent, about_entity
// Public API: window.JUG.renderWorkflowGraph(container, data) -> { destroy, select, data }.
// Renderers are provided by workflow_graph_render_svg.js / _canvas.js on JUG._wfg.
(function () {
  var D3_URL = 'https://cdn.jsdelivr.net/npm/d3@7.8.5/dist/d3.min.js';
  var CANVAS_THRESHOLD = 2000;

  // Tokens — kind-driven radii, colors, edge distances, strengths.
  var KIND_RADIUS = {
    domain: 26, tool_hub: 14, agent: 10, skill: 10, command: 8,
    hook: 9, memory: 7, discussion: 8, entity: 6, file: 5, mcp: 12,
    symbol: 2,
  };
  var KIND_COLOR = {
    domain: '#FCD34D',     // gold hub
    tool_hub: '#F97316',   // fallback (per-tool colors override in node.color)
    skill: '#FB923C',      // orange
    command: '#FACC15',    // yellow — distinct from Bash-tool orange
    hook: '#A855F7',       // purple
    agent: '#EC4899',      // pink
    mcp: '#6366F1',        // indigo
    memory: '#10B981',     // emerald fallback
    discussion: '#EF4444', // red
    entity: '#50B0C8',     // teal
    file: '#06B6D4',       // cyan fallback — primary-tool color overrides
    symbol: '#64748B',     // slate — inherits parent-file color via node.color
  };
  // Radial hierarchy inside each domain cloud — FIVE concentric/sector levels:
  //   L1 setup  (skills/hooks/commands/agents)   @ r = SETUP_R   front sector
  //   L2 tools  (tool_hub)                        @ r = TOOL_R    front sector
  //   L3 files  (primary-tool colored)            @ r = FILE_R    front sector
  //   L4 discussions                              @ r = DISC_R    side sector A
  //   L5 memories                                 @ r = MEM_R     side sector B
  //   MCPs sit INWARD (between domains) and bridge out.
  // Radii are sized so the rings are visually separated — each shell has
  // a band of at least 40px between it and the next. Large enough that
  // even dense domains keep their structure legible when zoomed out.
  var SETUP_R = 70;
  var TOOL_R  = 140;
  var FILE_R  = 220;
  var DISC_R  = 150;
  var MEM_R   = 150;
  var MCP_R   = 50;
  // Symbols form a dense cloud JUST outside the file ring — this is the
  // "petal" shell that gives the graph the screenshot look.  The cloud
  // is anchored per-file so each file becomes a small satellite clump.
  var SYM_R_OUTER = 290;    // outer edge of the symbol shell
  var SYM_R_SPREAD = 32;    // radial jitter per-file-group
  var SYM_CLUMP_R = 18;     // tight clumping distance around parent file
  var SECTOR_SETUP_HALF = Math.PI / 2.6;   // ~69°
  var SECTOR_SIDE_HALF  = Math.PI / 6.5;   // ~28°
  var SECTOR_SIDE_ANGLE = Math.PI * 0.72;  // ~130° from outward axis
  // Shells drawn as faint guide arcs behind the nodes (one per L1/L2/L3
  // per domain, plus disc/mem arcs). Level tokens consumed by the SVG
  // renderer to paint ring outlines + labels.
  var SHELL_LEVELS = [
    { key: 'L1', r: SETUP_R,     label: 'L1 setup' },
    { key: 'L2', r: TOOL_R,      label: 'L2 tools' },
    { key: 'L3', r: FILE_R,      label: 'L3 files' },
    { key: 'L6', r: SYM_R_OUTER, label: 'L6 symbols' },
  ];
  // Per-tool angles (local to the domain's outward axis), in radians.
  var TOOL_LOCAL_ANGLE = {
    Edit:  0,
    Write: -Math.PI / 12,
    Read:   Math.PI / 12,
    Grep:  -Math.PI /  6,
    Glob:   Math.PI /  6,
    Bash:  -Math.PI / 3.6,
    Task:   Math.PI / 3.6,
  };
  var EDGE_DISTANCE = {
    in_domain: 0,                        // satisfied by slot-anchoring, keep slack
    tool_used_file: 0,
    command_in_hub: 0,                   // bash_hub → command containment
    invoked_skill: 0,
    triggered_hook: 0,
    spawned_agent: 0,
    about_entity: 20,
    discussion_touched_file: 80,
    command_touched_file: 60,
    invoked_mcp: 90,
    defined_in: 22,                      // symbol sits close to its file
    calls: 24,                           // caller ↔ callee tight
    imports: 60,                         // short effective length — gain-bounded
    member_of: 10,                       // method ↔ class tight
  };
  var EDGE_STRENGTH = {
    in_domain: 0.0,                      // layout is slot-anchored; links = slack
    tool_used_file: 0.0,
    command_in_hub: 0.0,                 // containment — zero extra pull
    invoked_skill: 0.0,
    triggered_hook: 0.0,
    spawned_agent: 0.0,
    about_entity: 0.2,
    discussion_touched_file: 0.08,
    command_touched_file: 0.08,
    invoked_mcp: 0.04,                   // long springs — MCPs bridge domains
    defined_in: 0.95,                    // dominant anchor
    calls: 0.12,                         // halved
    imports: 0.04,                       // 4.5× gain cut — no runaway resonance
    member_of: 0.60,
  };
  var CROSS_DOMAIN_DISTANCE = 260;
  var CROSS_DOMAIN_STRENGTH = 0.02;

  function ensureD3(cb) {
    if (window.d3 && window.d3.forceSimulation) return cb();
    var existing = document.querySelector('script[data-cortex-d3]');
    if (existing) { existing.addEventListener('load', cb); return; }
    var s = document.createElement('script');
    s.src = D3_URL; s.async = true; s.defer = true;
    s.setAttribute('data-cortex-d3', '1');
    s.onload = cb;
    s.onerror = function () { console.error('[cortex] failed to load d3 from ' + D3_URL); };
    document.head.appendChild(s);
  }

  function renderWorkflowGraph(container, data) {
    if (!container) throw new Error('renderWorkflowGraph: container required');
    container.innerHTML = '';
    var handle = { destroy: function () {}, select: function () {}, data: data };
    ensureD3(function () {
      var impl = mount(container, data || { nodes: [], edges: [] });
      handle.destroy = impl.destroy;
      handle.select = impl.select;
    });
    return handle;
  }

  function mount(container, data) {
    var d3 = window.d3;
    var wfg = window.JUG._wfg;
    var nodes = (data.nodes || []).map(function (n) { return Object.assign({}, n); });
    // For very large graphs (>15k nodes) skip the simulation-visible
    // edges entirely — symbol→file/symbol→symbol edges number in the
    // tens of thousands and d3.forceLink on that many pairs freezes
    // the main thread. The slot layout already encodes containment
    // geometrically, so the visual edge of every symbol→file pair is
    // redundant. Keep only structural edges (domain hubs, tools,
    // files ↔ tools, discussions ↔ files, memories) for rendering.
    var HEAVY = nodes.length > 8000;
    var _nidSet = {};
    for (var _ni = 0; _ni < nodes.length; _ni++) _nidSet[nodes[_ni].id] = 1;
    // Keep AST edges in the simulation — they carry real semantic
    // meaning (symbol contained in file, symbol calls another symbol,
    // file imports symbol, method belongs to class). Layout should
    // REFLECT this connectivity, not randomize it. Only drop the
    // really dense symbol↔symbol edges (`calls`) under extreme load
    // to keep tick-rate manageable.
    var EXTREME = nodes.length > 25000;
    var renderedEdges;
    if (EXTREME) {
      renderedEdges = (data.edges || []).filter(function (e) {
        return e.kind !== 'calls';
      });
    } else {
      renderedEdges = data.edges || [];
    }
    // Drop dangling edges — endpoints must exist in the nodes array.
    renderedEdges = renderedEdges.filter(function (e) {
      var s = typeof e.source === 'object' ? e.source.id : e.source;
      var t = typeof e.target === 'object' ? e.target.id : e.target;
      return _nidSet[s] && _nidSet[t];
    });
    var edges = renderedEdges.map(function (e) {
      return Object.assign({}, e, {
        source: typeof e.source === 'object' ? e.source.id : e.source,
        target: typeof e.target === 'object' ? e.target.id : e.target,
      });
    });
    var width  = container.clientWidth  || window.innerWidth;
    var height = container.clientHeight || window.innerHeight;

    // Topology prep uses the FULL edge set (parent-file map needs
    // `defined_in` edges) but the simulation only sees the rendered set.
    var ctx = prepareTopology(nodes, data.edges || [], width, height);
    ctx.edges = edges;                // simulation edges (possibly filtered)
    ctx.KIND_RADIUS = KIND_RADIUS;
    ctx.KIND_COLOR  = KIND_COLOR;
    // HEAVY: pin symbols at their slot positions so d3 treats them as
    // immovable anchors (skip charge, skip link, skip collide for
    // pinned nodes). The layout is already deterministic via slotOf;
    // simulating 10k+ symbols adds no visual value, only CPU cost.
    // Seed symbols ALONG THE OUTWARD RAY from the domain hub through
    // their parent file, at a random distance past the file. This is
    // the starting configuration that lets symbols flow naturally
    // into the inter-domain gap space rather than orbiting the hub.
    for (var pi = 0; pi < nodes.length; pi++) {
      var pn = nodes[pi];
      if (pn.kind !== 'symbol') continue;
      var dId = ctx.domainOf[pn.id] || 'domain:__global__';
      var anc = ctx.anchors[dId] || ctx.anchors['domain:__global__'];
      var pfId = ctx.parentFile[pn.id];
      var fileSlot = pfId ? ctx.slotOf[pfId] : null;
      if (!anc) continue;
      var origin = fileSlot || anc;
      // Outward unit vector from domain anchor → origin.
      var dx = origin.x - anc.x, dy = origin.y - anc.y;
      var d = Math.hypot(dx, dy);
      var ox, oy;
      if (d < 1) {
        // Fallback: pseudo-random outward ray.
        var t = (pi * 0.37) % (Math.PI * 2);
        ox = Math.cos(t); oy = Math.sin(t);
      } else {
        ox = dx / d; oy = dy / d;
      }
      var pastFile = 30 + Math.random() * 120;  // 30..150 px past file
      var angJitter = (Math.random() - 0.5) * 0.15;  // ±4° lateral spread
      var cs = Math.cos(angJitter), sn = Math.sin(angJitter);
      var rx = ox * cs - oy * sn;
      var ry = ox * sn + oy * cs;
      pn.x = origin.x + rx * pastFile;
      pn.y = origin.y + ry * pastFile;
    }
    var panel = wfg.buildSidePanel(container);

    // Maxwell-damped config: ζ ≈ 0.55 via velocityDecay 0.72, and
    // local-range charge so long-distance repulsion doesn't oscillate.
    var slotK    = HEAVY ? 1.2  : 0.85;
    var chargeEn = true;
    var collideI = HEAVY ? 2    : 3;
    var alphaDK  = HEAVY ? 0.028 : 0.022;

    var sim = d3.forceSimulation(nodes)
      .alpha(1.0).alphaDecay(alphaDK).velocityDecay(0.72)
      .force('link', d3.forceLink(edges).id(function (n) { return n.id; })
        .distance(linkDistance).strength(linkStrength))
      .force('slot',        slotForce(ctx, slotK))
      .force('interdomain', interDomainRepelForce(ctx, 0.08))
      .force('symmulti', symbolMultiCenterForce(ctx))
      .force('collide', d3.forceCollide()
        .radius(function (n) { return collisionRadius(n, ctx); })
        .strength(0.92).iterations(collideI));
    if (chargeEn) {
      // Local charge (distanceMax 180) so symbol-symbol repulsion
      // doesn't create long-range feedback with the multi-centroid
      // attraction; domains still repel each other via interdomain.
      sim.force('charge', d3.forceManyBody().strength(chargeStrength).distanceMax(180));
    }

    var useCanvas = nodes.length > CANVAS_THRESHOLD;
    var renderer = useCanvas
      ? wfg.mountCanvas(container, ctx, sim, panel, width, height)
      : wfg.mountSVG(container, ctx, sim, panel, width, height);

    function onResize() {
      var w = container.clientWidth || window.innerWidth;
      var h = container.clientHeight || window.innerHeight;
      renderer.resize(w, h);
      sim.alpha(0.3).restart();
    }
    window.addEventListener('resize', onResize);

    var handle = {
      destroy: function () {
        window.removeEventListener('resize', onResize);
        sim.stop();
        renderer.destroy();
        if (panel.root && panel.root.parentNode) panel.root.parentNode.removeChild(panel.root);
      },
      select: function (id) { renderer.selectId(id); },
      reflow: function () { onResize(); },
      applyFilter: function (pred) {
        if (typeof renderer.applyFilter === 'function') renderer.applyFilter(pred, ctx);
      },
    };
    // Expose a stable hook so the filter-bar driver can reach us.
    window.JUG.wfgApplyFilter = function (pred) { handle.applyFilter(pred); };
    return handle;
  }

  // ── Topology: Fibonacci-spiral domain anchors; domainOf; primary tool_hub;
  //    degree; adjacency; per-node slot (radial hierarchy).
  function prepareTopology(nodes, edges, width, height) {
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    var domains = nodes.filter(function (n) { return n.kind === 'domain'; });

    var cx = width / 2, cy = height / 2;
    // Each domain's outer shell is roughly FILE_R + cushion; Fibonacci
    // spiral average spacing is R·√(π/N). Pick baseR so the spacing
    // exceeds the shell diameter — rings never collide.
    var N = Math.max(domains.length, 1);
    var shellDiameter = 2 * FILE_R + 60;
    var baseR = Math.max(
      Math.min(width, height) * 0.42,
      shellDiameter * Math.sqrt(N / Math.PI) * 0.65,
    );
    var phi = Math.PI * (3 - Math.sqrt(5));  // golden angle
    var anchors = {};
    domains.forEach(function (d, i) {
      var r = baseR * Math.sqrt((i + 0.5) / N);
      var theta = i * phi;
      anchors[d.id] = { x: cx + r * Math.cos(theta), y: cy + r * Math.sin(theta) };
      d.x = anchors[d.id].x; d.y = anchors[d.id].y;
      d.fx = d.x; d.fy = d.y;                // pin domain anchors — L1/L2/L3 rings orbit them.
    });

    var domainOf = {};
    nodes.forEach(function (n) {
      if (n.kind === 'domain') { domainOf[n.id] = n.id; return; }
      if (n.domain && byId[n.domain] && byId[n.domain].kind === 'domain') domainOf[n.id] = n.domain;
      else if (n.domain_id && byId[n.domain_id]) domainOf[n.id] = n.domain_id;
    });
    edges.forEach(function (e) {
      if (e.kind !== 'in_domain') return;
      var s = byId[e.source], t = byId[e.target];
      if (!s || !t) return;
      if (s.kind === 'domain' && !domainOf[t.id]) domainOf[t.id] = s.id;
      if (t.kind === 'domain' && !domainOf[s.id]) domainOf[s.id] = t.id;
    });

    // Parent file per symbol — drives the symbol-petal clustering.
    // Prefer `defined_in` edges; fall back to `path` string match.
    var parentFile = {};
    edges.forEach(function (e) {
      if (e.kind !== 'defined_in') return;
      var s = byId[e.source], t = byId[e.target];
      if (!s || !t) return;
      if (s.kind === 'symbol' && t.kind === 'file') parentFile[s.id] = t.id;
      else if (t.kind === 'symbol' && s.kind === 'file') parentFile[t.id] = s.id;
    });
    var filesByPath = {};
    nodes.forEach(function (n) {
      if (n.kind === 'file' && n.path) filesByPath[n.path] = n.id;
    });
    nodes.forEach(function (n) {
      if (n.kind !== 'symbol' || parentFile[n.id]) return;
      if (n.path && filesByPath[n.path]) parentFile[n.id] = filesByPath[n.path];
    });
    // Every symbol MUST have a domain or the containment force can't
    // constrain it. Priority:
    //   1. Parent file's domain (derived from `defined_in` edge)
    //   2. node.domain_id / node.domain (server already tags each
    //      symbol with its project's domain id)
    //   3. GLOBAL fallback if somehow neither resolves.
    nodes.forEach(function (n) {
      if (n.kind !== 'symbol') return;
      var pf = parentFile[n.id];
      if (pf && domainOf[pf]) { domainOf[n.id] = domainOf[pf]; return; }
      var did = n.domain_id || (n.domain ? 'domain:' + n.domain : '');
      if (did && byId[did]) { domainOf[n.id] = did; return; }
      if (!domainOf[n.id]) domainOf[n.id] = 'domain:__global__';
    });

    var primaryHub = {}, hubWeight = {};
    edges.forEach(function (e) {
      if (e.kind !== 'tool_used_file') return;
      var s = byId[e.source], t = byId[e.target];
      if (!s || !t) return;
      var hub = s.kind === 'tool_hub' ? s : (t.kind === 'tool_hub' ? t : null);
      var f = s.kind === 'file' ? s : (t.kind === 'file' ? t : null);
      if (!hub || !f) return;
      if (domainOf[hub.id] && domainOf[hub.id] === domainOf[f.id]) {
        var w = e.weight != null ? e.weight : 1;
        if (!(f.id in hubWeight) || w > hubWeight[f.id]) { hubWeight[f.id] = w; primaryHub[f.id] = hub.id; }
      }
    });

    var degree = {}, adj = {};
    edges.forEach(function (e) {
      degree[e.source] = (degree[e.source] || 0) + 1;
      degree[e.target] = (degree[e.target] || 0) + 1;
      var sd = domainOf[e.source], td = domainOf[e.target];
      e._crossDomain = !!(sd && td && sd !== td);
      if (!adj[e.source]) adj[e.source] = {};
      if (!adj[e.target]) adj[e.target] = {};
      adj[e.source][e.target] = true; adj[e.target][e.source] = true;
    });

    var slotOf = computeSlots(nodes, domains, anchors, domainOf, primaryHub, parentFile, cx, cy);

    return { byId: byId, nodes: nodes, edges: edges, domains: domains,
      anchors: anchors, domainOf: domainOf, primaryHub: primaryHub,
      parentFile: parentFile,
      degree: degree, adj: adj, slotOf: slotOf,
      shells: SHELL_LEVELS, sideShells: [
        { key: 'L4', r: DISC_R, label: 'L4 discussions', angle: SECTOR_SIDE_ANGLE },
        { key: 'L5', r: MEM_R,  label: 'L5 memories',    angle: -SECTOR_SIDE_ANGLE },
      ], cx: cx, cy: cy, baseR: baseR,
      width: width, height: height };
  }

  // Assign each non-domain node a target (x,y) slot expressing the hierarchy:
  //   domain → L1 (setup) → L2 (tools) → L3 (files);  discussions lane;  memories lane.
  function computeSlots(nodes, domains, anchors, domainOf, primaryHub, parentFile, cx, cy) {
    // Group non-domain nodes by (domain, kind).
    var groups = {};
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.kind === 'domain') continue;
      var dom = domainOf[n.id];
      if (!dom || !anchors[dom]) continue;
      if (!groups[dom]) groups[dom] = {};
      if (!groups[dom][n.kind]) groups[dom][n.kind] = [];
      groups[dom][n.kind].push(n);
    }
    var slotOf = {};
    var setupKinds = ['skill', 'hook', 'command', 'agent'];

    Object.keys(groups).forEach(function (domId) {
      var a = anchors[domId];
      var outward = Math.atan2(a.y - cy, a.x - cx);  // radially outward from graph center
      // For domains near the center the outward axis is unstable — bias upward.
      if (Math.hypot(a.x - cx, a.y - cy) < 5) outward = -Math.PI / 2;
      var g = groups[domId];

      // L2: tool_hubs at fixed per-tool angles within the setup sector.
      var hubAngle = {};
      (g.tool_hub || []).forEach(function (h) {
        var local = TOOL_LOCAL_ANGLE[h.tool];
        if (local == null) local = 0;
        var t = outward + local;
        hubAngle[h.id] = t;
        slotOf[h.id] = { x: a.x + TOOL_R * Math.cos(t),
                         y: a.y + TOOL_R * Math.sin(t) };
      });

      // L3: files orbit their primary tool_hub (same angle + small jitter).
      var filesByHub = {};
      (g.file || []).forEach(function (f) {
        var hid = primaryHub[f.id];
        if (!filesByHub[hid]) filesByHub[hid] = [];
        filesByHub[hid].push(f);
      });
      Object.keys(filesByHub).forEach(function (hid) {
        var theta = hubAngle[hid];
        if (theta == null) theta = outward;  // hub in another domain (cross-domain file)
        var arr = filesByHub[hid];
        var arc = Math.min(0.35, 0.08 + arr.length * 0.015);
        arr.forEach(function (f, i) {
          var t = theta + ((i + 0.5) / arr.length - 0.5) * arc;
          var r = FILE_R + ((i % 3) - 1) * 4;  // radial stagger to reduce overlap
          slotOf[f.id] = { x: a.x + r * Math.cos(t), y: a.y + r * Math.sin(t) };
        });
      });

      // L1: skills, hooks, commands, agents — fanned inner ring.
      var setup = [];
      setupKinds.forEach(function (k) { (g[k] || []).forEach(function (x) { setup.push(x); }); });
      if (setup.length) {
        var arc1 = SECTOR_SETUP_HALF * 2;
        setup.forEach(function (n, i) {
          var t = outward + ((i + 0.5) / setup.length - 0.5) * arc1;
          var r = SETUP_R + (i % 2) * 8;
          slotOf[n.id] = { x: a.x + r * Math.cos(t), y: a.y + r * Math.sin(t) };
        });
      }

      // Discussions lane (opposite side from setup, one side).
      var disc = g.discussion || [];
      if (disc.length) {
        var center = outward + SECTOR_SIDE_ANGLE;
        var arc2 = SECTOR_SIDE_HALF * 2 + Math.min(Math.PI / 3, disc.length * 0.04);
        disc.forEach(function (n, i) {
          var t = center + ((i + 0.5) / disc.length - 0.5) * arc2;
          var r = DISC_R + (i % 3) * 6;
          slotOf[n.id] = { x: a.x + r * Math.cos(t), y: a.y + r * Math.sin(t) };
        });
      }

      // Memories lane (opposite side from setup, other side).
      var mem = g.memory || [];
      if (mem.length) {
        var center2 = outward - SECTOR_SIDE_ANGLE;
        var arc3 = SECTOR_SIDE_HALF * 2 + Math.min(Math.PI / 2.5, mem.length * 0.03);
        mem.forEach(function (n, i) {
          var t = center2 + ((i + 0.5) / mem.length - 0.5) * arc3;
          var r = MEM_R + (i % 4) * 8;
          slotOf[n.id] = { x: a.x + r * Math.cos(t), y: a.y + r * Math.sin(t) };
        });
      }

      // MCPs sit INSIDE the domain (between the center of the graph and the
      // domain anchor), so their long INVOKED_MCP edges fan visibly between
      // domains that share the MCP.
      (g.mcp || []).forEach(function (n, i) {
        var t = outward + Math.PI;  // inward
        var jitter = (i - (g.mcp.length - 1) / 2) * 0.25;
        slotOf[n.id] = { x: a.x + MCP_R * Math.cos(t + jitter),
                         y: a.y + MCP_R * Math.sin(t + jitter) };
      });

      // L6 symbols intentionally have NO slot — their final position
      // is determined by the codebase-analysis edges the force
      // simulation operates on (`defined_in` pulls toward the parent
      // file, `calls` pulls toward callers/callees, `imports` bridges
      // files, `member_of` clusters methods with their class). The
      // initial x/y seeding happens in mount() from the parent file's
      // position, then the force simulation does the layout work.
    });
    return slotOf;
  }

  // ── Force helpers (pure closures) ──
  function linkDistance(e) {
    if (e._crossDomain) return CROSS_DOMAIN_DISTANCE;
    return EDGE_DISTANCE[e.kind] != null ? EDGE_DISTANCE[e.kind] : 30;
  }
  function linkStrength(e) {
    if (e._crossDomain) return CROSS_DOMAIN_STRENGTH;
    var s = EDGE_STRENGTH[e.kind] != null ? EDGE_STRENGTH[e.kind] : 0.4;
    return s * (e.weight != null ? Math.min(1, 0.3 + e.weight * 0.7) : 1);
  }
  function chargeStrength(n) {
    if (n.kind === 'domain')   return -620;
    if (n.kind === 'tool_hub') return -140;
    if (n.kind === 'agent' || n.kind === 'skill') return -80;
    // Symbols: enough mutual repulsion to spread laterally in the
    // interlock space (Maxwell: -22, local distanceMax).
    if (n.kind === 'symbol')   return -22;
    return -28;
  }
  function slotForce(ctx, k) {
    return function (alpha) {
      var s = k * alpha;
      for (var i = 0; i < ctx.nodes.length; i++) {
        var n = ctx.nodes[i];
        if (n.kind === 'domain') continue;
        var slot = ctx.slotOf[n.id];
        if (!slot) continue;
        n.vx += (slot.x - n.x) * s;
        n.vy += (slot.y - n.y) * s;
      }
    };
  }
  // Multi-centroid attraction (Alexander's deep interlock): a symbol
  // is pulled by EVERY domain it touches via its edges, weighted 1/N
  // where N = number of distinct domains touched. Symbols connected
  // only to their home domain sit near it; cross-domain symbols
  // literally fall into the interlock space between two or more hubs.
  // No containment — position emerges from connectivity alone.
  function symbolMultiCenterForce(ctx) {
    // Precompute each symbol's domain centroid list ONCE.
    var symDomains = {};
    for (var i = 0; i < ctx.nodes.length; i++) {
      var n = ctx.nodes[i];
      if (n.kind !== 'symbol') continue;
      var set = {};
      // Home domain (from parent file or node's own domain_id).
      var home = ctx.domainOf[n.id];
      if (home && ctx.anchors[home]) set[home] = 1;
      symDomains[n.id] = set;
    }
    // Walk every AST edge; for each symbol endpoint, add the OTHER
    // endpoint's domain to its centroid set.
    ctx.edges.forEach(function (e) {
      var k = e.kind;
      if (k !== 'defined_in' && k !== 'calls' &&
          k !== 'imports' && k !== 'member_of') return;
      var sId = typeof e.source === 'object' ? e.source.id : e.source;
      var tId = typeof e.target === 'object' ? e.target.id : e.target;
      var sN = ctx.byId[sId], tN = ctx.byId[tId];
      if (!sN || !tN) return;
      if (sN.kind === 'symbol' && ctx.domainOf[tId] && ctx.anchors[ctx.domainOf[tId]]) {
        symDomains[sId] = symDomains[sId] || {};
        symDomains[sId][ctx.domainOf[tId]] = 1;
      }
      if (tN.kind === 'symbol' && ctx.domainOf[sId] && ctx.anchors[ctx.domainOf[sId]]) {
        symDomains[tId] = symDomains[tId] || {};
        symDomains[tId][ctx.domainOf[sId]] = 1;
      }
    });
    ctx._symDomains = symDomains;

    return function (alpha) {
      var s = 0.06 * alpha;
      for (var i = 0; i < ctx.nodes.length; i++) {
        var n = ctx.nodes[i];
        if (n.kind !== 'symbol') continue;
        var set = symDomains[n.id];
        if (!set) continue;
        var keys = Object.keys(set);
        if (!keys.length) continue;
        var w = s / keys.length;
        for (var j = 0; j < keys.length; j++) {
          var a = ctx.anchors[keys[j]];
          if (!a) continue;
          n.vx += (a.x - n.x) * w;
          n.vy += (a.y - n.y) * w;
        }
      }
    };
  }
  function interDomainRepelForce(ctx, k) {
    return function (alpha) {
      var doms = ctx.domains, strength = k * alpha * 8000;
      for (var i = 0; i < doms.length; i++) {
        var a = doms[i];
        for (var j = i + 1; j < doms.length; j++) {
          var b = doms[j];
          var dx = b.x - a.x, dy = b.y - a.y;
          var d2 = dx * dx + dy * dy + 1;
          var f = strength / d2, inv = 1 / Math.sqrt(d2);
          a.vx -= dx * inv * f; a.vy -= dy * inv * f;
          b.vx += dx * inv * f; b.vy += dy * inv * f;
        }
      }
    };
  }
  function collisionRadius(n, ctx) {
    var base = KIND_RADIUS[n.kind] != null ? KIND_RADIUS[n.kind] : 6;
    return base + Math.min(8, Math.sqrt(ctx.degree[n.id] || 0));
  }

  // Exposed shared utilities for renderer modules.
  function nodeRadius(n) {
    var base = KIND_RADIUS[n.kind] != null ? KIND_RADIUS[n.kind] : 6;
    var bump = 0;
    if (n.size != null) bump = Math.max(-2, Math.min(6, n.size - base));
    else if (n.weight != null) bump = Math.min(4, n.weight * 2);
    return base + bump;
  }
  function nodeColor(n) { return n.color || KIND_COLOR[n.kind] || '#50C8E0'; }
  function labelOf(n) { return n.label || n.name || n.title || n.path || n.id || ''; }

  window.JUG = window.JUG || {};
  window.JUG._wfg = window.JUG._wfg || {};
  window.JUG._wfg.nodeRadius = nodeRadius;
  window.JUG._wfg.nodeColor  = nodeColor;
  window.JUG._wfg.labelOf    = labelOf;
  window.JUG.renderWorkflowGraph = renderWorkflowGraph;
})();
