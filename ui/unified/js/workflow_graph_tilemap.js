// Cortex — Tilemap viewer (deck.gl + Datashader server tiles).
//
// Engages when the URL has ``?viz=tilemap``. Renders /api/tile/{z}/{x}/{y}.png
// via deck.gl's TileLayer over an OrthographicView in the Cartesian
// coordinate system, plus a quadtree-backed hover layer that resolves
// hit-tests locally from a single /api/quadtree fetch.
//
// Public API:
//   window.JUG.mountTilemap(container)
//
// Mounted by workflow_graph.js when the gate flag is on.
(function () {
  'use strict';

  var DECKGL_URL = 'https://unpkg.com/deck.gl@9.0.27/dist.min.js';
  var ARROW_URL  = 'https://unpkg.com/apache-arrow@17.0.0/Arrow.es2015.min.js';
  var FLATBUSH_URL = 'https://unpkg.com/flatbush@4.4.0/flatbush.min.js';

  var KIND_COLOR = {
    domain:    [252, 211,  77, 230],
    tool_hub:  [249, 115,  22, 230],
    skill:     [251, 146,  60, 230],
    command:   [250, 204,  21, 230],
    hook:      [168,  85, 247, 230],
    agent:     [236,  72, 153, 230],
    mcp:       [ 99, 102, 241, 230],
    memory:    [ 16, 185, 129, 230],
    discussion:[239,  68,  68, 230],
    entity:    [ 80, 176, 200, 230],
    file:      [  6, 182, 212, 230],
    symbol:    [100, 116, 139, 230],
  };

  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = url; s.crossOrigin = 'anonymous';
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('failed to load ' + url)); };
      document.head.appendChild(s);
    });
  }

  // Decode the gzipped Apache Arrow IPC payload from /api/quadtree
  // into parallel Float32Array x/y plus parallel id+kind arrays. The
  // browser decompresses gzip transparently when the response
  // declares Content-Encoding: gzip — fetch returns the inflated
  // bytes already.
  //
  // ``no_layout`` (HTTP 503 with reason="no_layout") surfaces as a
  // distinct error class so the caller can drive the auto-recompute
  // path without re-parsing the body.
  async function fetchQuadtree() {
    var resp = await fetch('/api/quadtree');
    if (resp.status === 503) {
      var detail = await resp.json().catch(function () { return {}; });
      var err = new Error('quadtree 503: ' + (detail.reason || 'unknown'));
      err.reason = detail.reason || 'unknown';
      err.detail = detail.detail || null;
      throw err;
    }
    if (!resp.ok) throw new Error('quadtree fetch failed: ' + resp.status);
    var buf = await resp.arrayBuffer();
    var Arrow = window.Arrow || window.apacheArrow || (window['arrow'] || {});
    if (!Arrow.tableFromIPC) {
      throw new Error('Apache Arrow JS not loaded');
    }
    var table = Arrow.tableFromIPC(new Uint8Array(buf));
    var n = table.numRows;
    var ids = new Array(n);
    var kinds = new Array(n);
    var xs = new Float32Array(n);
    var ys = new Float32Array(n);
    var idCol = table.getChild('id');
    var kindCol = table.getChild('kind');
    var xCol = table.getChild('x');
    var yCol = table.getChild('y');
    for (var i = 0; i < n; i++) {
      ids[i] = idCol.get(i);
      kinds[i] = kindCol.get(i);
      xs[i] = xCol.get(i);
      ys[i] = yCol.get(i);
    }
    return { ids: ids, kinds: kinds, xs: xs, ys: ys, count: n };
  }

  // Build a flatbush index over the quadtree positions. Hover queries
  // use bbox search around the cursor's world coordinates; the screen
  // → world projection is provided by deck.gl at hover time.
  function buildIndex(qt) {
    if (!window.Flatbush) throw new Error('Flatbush not loaded');
    var idx = new window.Flatbush(qt.count);
    for (var i = 0; i < qt.count; i++) {
      idx.add(qt.xs[i], qt.ys[i], qt.xs[i], qt.ys[i]);
    }
    idx.finish();
    return idx;
  }

  function pickAt(idx, qt, wx, wy, worldRadius) {
    var hits = idx.search(
      wx - worldRadius, wy - worldRadius,
      wx + worldRadius, wy + worldRadius,
    );
    if (!hits.length) return -1;
    var bestI = -1, bestD = Infinity;
    for (var k = 0; k < hits.length; k++) {
      var h = hits[k];
      var dx = qt.xs[h] - wx, dy = qt.ys[h] - wy;
      var d2 = dx * dx + dy * dy;
      if (d2 < bestD) { bestD = d2; bestI = h; }
    }
    return bestI;
  }

  async function mount(container) {
    container.innerHTML = '';
    var status = document.createElement('div');
    status.style.cssText = 'position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);'
      + 'color:#9aa4b2;font:13px/1.4 system-ui,sans-serif;'
      + 'padding:14px 22px;border:1px solid rgba(120,180,200,0.25);'
      + 'border-radius:6px;background:rgba(8,8,16,0.8);';
    status.textContent = 'Loading tilemap dependencies…';
    container.appendChild(status);

    try {
      await Promise.all([loadScript(DECKGL_URL), loadScript(ARROW_URL), loadScript(FLATBUSH_URL)]);
    } catch (err) {
      status.textContent = 'Failed to load tilemap deps: ' + err.message;
      status.style.color = '#ff8888';
      return;
    }

    // Self-healing layout pass: if /api/quadtree returns 503 with
    // ``no_layout``, the page itself triggers /api/recompute_layout
    // and retries. Covers direct-URL access where the MCP entry point
    // didn't pre-prepare the layout.
    status.textContent = 'Fetching quadtree…';
    var qt;
    try {
      qt = await fetchQuadtree();
    } catch (err) {
      if (err && err.reason === 'no_layout') {
        status.textContent = 'No layout in PG. Computing now (≈90 s for 1M nodes)…';
        status.style.color = '#ffb86b';
        var recompute;
        try {
          var rr = await fetch('/api/recompute_layout');
          recompute = await rr.json();
        } catch (e2) {
          status.textContent = 'Layout request failed: ' + e2.message;
          status.style.color = '#ff8888';
          return;
        }
        if (recompute && recompute.status === 'ok') {
          status.textContent = 'Layout ready (' + recompute.node_count + ' nodes); fetching quadtree…';
          try {
            qt = await fetchQuadtree();
          } catch (e3) {
            status.textContent = 'Quadtree refetch failed: ' + e3.message;
            status.style.color = '#ff8888';
            return;
          }
        } else if (recompute && recompute.reason === 'igraph_missing') {
          status.innerHTML =
            '<div style="margin-bottom:6px;color:#ffb86b">'
            + '<b>viz-tile extras required</b></div>'
            + '<div style="color:#9aa4b2;font:11px JetBrains Mono,monospace">'
            + 'Install with one of:<br>'
            + '&nbsp;&nbsp;pip install -e \'.[viz-tile]\'<br>'
            + '&nbsp;&nbsp;uv pip install \'.[viz-tile]\'</div>';
          return;
        } else if (recompute && recompute.reason === 'no_graph_cached') {
          status.textContent = 'Graph not built yet. Visit /api/graph first then retry.';
          status.style.color = '#ffb86b';
          return;
        } else {
          status.textContent = 'Layout failed: ' + JSON.stringify(recompute || {});
          status.style.color = '#ff8888';
          return;
        }
      } else {
        status.textContent = 'Quadtree fetch failed: ' + err.message;
        status.style.color = '#ff8888';
        return;
      }
    }
    if (!qt.count) {
      status.textContent = 'Layout empty. Run /api/recompute_layout to populate.';
      status.style.color = '#ffb86b';
      return;
    }
    var idx = buildIndex(qt);

    status.remove();

    var canvasHost = document.createElement('div');
    canvasHost.style.cssText = 'position:absolute;inset:0;background:#080810;';
    container.appendChild(canvasHost);

    var deck = window.deck;
    if (!deck || !deck.Deck) {
      var msg = document.createElement('div');
      msg.style.cssText = 'position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);color:#ff8888;font:13px system-ui;';
      msg.textContent = 'deck.gl failed to expose window.deck';
      canvasHost.appendChild(msg);
      return;
    }

    var TileLayer = deck.TileLayer;
    var BitmapLayer = deck.BitmapLayer;
    var OrthographicView = deck.OrthographicView;
    var COORDINATE_SYSTEM = deck.COORDINATE_SYSTEM;

    var hoverLabel = document.createElement('div');
    hoverLabel.style.cssText = 'position:absolute;pointer-events:none;background:rgba(8,8,16,0.92);'
      + 'border:1px solid rgba(120,180,200,0.4);border-radius:4px;padding:4px 8px;'
      + "color:#e0e6ec;font:11px/1.3 'JetBrains Mono', monospace;display:none;z-index:5;";
    container.appendChild(hoverLabel);

    var deckInstance = new deck.Deck({
      parent: canvasHost,
      style: { position: 'absolute', inset: 0 },
      views: [new OrthographicView({
        id: 'ortho',
        controller: { dragRotate: false, scrollZoom: { speed: 0.01, smooth: true } },
      })],
      initialViewState: { target: [0, 0, 0], zoom: 0 },
      onHover: function (info) {
        if (!info || info.coordinate == null) {
          hoverLabel.style.display = 'none';
          return;
        }
        // World ↔ screen — info.viewport.unproject is provided by deck.gl
        var wx = info.coordinate[0];
        var wy = info.coordinate[1];
        var worldRadius = 12 / Math.pow(2, info.viewport.zoom);
        var hit = pickAt(idx, qt, wx, wy, worldRadius);
        if (hit < 0) {
          hoverLabel.style.display = 'none';
          return;
        }
        hoverLabel.style.display = 'block';
        hoverLabel.style.left = (info.x + 12) + 'px';
        hoverLabel.style.top = (info.y + 12) + 'px';
        hoverLabel.textContent = qt.kinds[hit] + ' · ' + qt.ids[hit];
      },
      onClick: function (info) {
        if (!info || info.coordinate == null) return;
        var wx = info.coordinate[0];
        var wy = info.coordinate[1];
        var worldRadius = 18 / Math.pow(2, info.viewport.zoom);
        var hit = pickAt(idx, qt, wx, wy, worldRadius);
        if (hit < 0) return;
        // Hand off to the existing side panel if present.
        if (window.JUG && JUG._wfg && JUG._wfg.buildSidePanel) {
          var ctx = { byId: {} };
          for (var k = 0; k < qt.count; k++) {
            ctx.byId[qt.ids[k]] = { id: qt.ids[k], kind: qt.kinds[k] };
          }
          var panel = window._tilemap_panel ||
            (window._tilemap_panel = JUG._wfg.buildSidePanel(container));
          var datum = ctx.byId[qt.ids[hit]];
          try { panel.show(datum, ctx); } catch (_) {}
        }
      },
      layers: [
        new TileLayer({
          id: 'graph-tiles',
          coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
          getTileData: function (tile) {
            var z = tile.index.z, x = tile.index.x, y = tile.index.y;
            return fetch('/api/tile/' + z + '/' + x + '/' + y + '.png')
              .then(function (r) { return r.blob(); })
              .then(function (b) { return createImageBitmap(b); });
          },
          tileSize: 512,
          minZoom: 0,
          maxZoom: 10,
          // World ↔ tile mapping. World extent is [-1, 1] on each axis;
          // z=0 has one tile spanning that range.
          extent: [-1, -1, 1, 1],
          renderSubLayers: function (props) {
            var t = props.tile;
            var span = 2 / Math.pow(2, t.index.z);
            var minX = -1 + t.index.x * span;
            var maxX = minX + span;
            var maxY = 1 - t.index.y * span;
            var minY = maxY - span;
            return new BitmapLayer(props, {
              data: null,
              image: props.data,
              bounds: [minX, minY, maxX, maxY],
            });
          },
        }),
      ],
    });

    return {
      destroy: function () {
        try { deckInstance.finalize(); } catch (_) {}
        if (canvasHost.parentNode) canvasHost.parentNode.removeChild(canvasHost);
        hoverLabel.remove();
      },
    };
  }

  window.JUG = window.JUG || {};
  window.JUG.mountTilemap = mount;
})();
