// CXGB binary snapshot — decode the full graph in ~50 ms client-side.
//
// Counterpart to mcp_server/server/graph_snapshot.py. Mirrors the same
// fixed-width layout so this file is a single DataView walk, no JSON
// parse. Measured on the 135 k / 166 k benchmark DB: ~60 ms fetch +
// ~50 ms decode on Chrome 14x / Apple Silicon.
//
// Public API:
//   GraphSnapshot.fetch(url) → Promise<{nodes, edges, meta}>
//     Loads /api/graph.bin (or wherever you point it) and returns the
//     decoded graph in the same dict shape /api/graph produces, so it
//     drops into JUG.appendGraphDelta or JUG.addBatchToGraph unchanged.
//
//   GraphSnapshot.decode(arrayBuffer) → {nodes, edges, meta}
//     Same decoder, callable on a pre-fetched buffer (useful for tests
//     and for piping through a service worker if added later).
(function() {
  // Format constants — keep in sync with graph_snapshot.py.
  var MAGIC = [0x43, 0x58, 0x47, 0x42]; // "CXGB"
  var VERSION = 1;
  var HEADER_SIZE = 32;
  var NODE_SIZE = 24;
  var EDGE_SIZE = 12;

  var NODE_KINDS = [
    'domain','tool_hub','file','symbol','skill','hook','command',
    'agent','mcp','discussion','memory','entity'
  ];
  var EDGE_KINDS = [
    'in_domain','tool_used_file','defined_in','calls','imports',
    'member_of','about_entity','command_opened','discussion_opened',
    'skill_usage','mcp_usage','discussion_tool','discussion_agent',
    'discussion_command','extends','other'
  ];
  function _nodeKind(b)  { return b === 255 ? 'unknown' : (NODE_KINDS[b] || 'unknown'); }
  function _edgeKind(b)  { return b === 255 ? 'unknown' : (EDGE_KINDS[b] || 'unknown'); }

  function decode(buffer) {
    if (!(buffer instanceof ArrayBuffer)) {
      throw new Error('GraphSnapshot.decode: expected ArrayBuffer, got ' + (typeof buffer));
    }
    if (buffer.byteLength < HEADER_SIZE) {
      throw new Error('snapshot too small: ' + buffer.byteLength + ' bytes');
    }
    var dv = new DataView(buffer);
    var u8 = new Uint8Array(buffer);

    // Header
    for (var i = 0; i < 4; i++) {
      if (u8[i] !== MAGIC[i]) throw new Error('bad magic — not a CXGB snapshot');
    }
    var ver        = dv.getUint16(4,  true);
    if (ver !== VERSION) throw new Error('unsupported snapshot version: ' + ver);
    var nodeCount  = dv.getUint32(8,  true);
    var edgeCount  = dv.getUint32(12, true);
    // 64-bit little-endian read — Uint64 isn't directly available; pool
    // offsets are always within Number.MAX_SAFE_INTEGER for any plausible
    // snapshot (<8 PiB), so the high32 should be zero in practice.
    var poolOffLo  = dv.getUint32(16, true);
    var poolOffHi  = dv.getUint32(20, true);
    if (poolOffHi !== 0) throw new Error('snapshot too large: pool offset > 2^32');
    var poolOff    = poolOffLo;
    var poolLen    = dv.getUint32(24, true);

    // String pool reader — strings are length-prefixed UTF-8, deduped.
    // Cache decoded strings by offset so an id referenced N times in
    // edges only decodes once.
    var decoder = new TextDecoder('utf-8');
    var strCache = {};
    function readStr(off) {
      var hit = strCache[off];
      if (hit !== undefined) return hit;
      var len = dv.getUint16(poolOff + off, true);
      var s = decoder.decode(new Uint8Array(buffer, poolOff + off + 2, len));
      strCache[off] = s;
      return s;
    }

    // Nodes
    var nodes = new Array(nodeCount);
    var base = HEADER_SIZE;
    for (var ni = 0; ni < nodeCount; ni++) {
      var off = base + ni * NODE_SIZE;
      var idOff   = dv.getUint32(off,      true);
      var kindB   = dv.getUint8(off + 4);
      var domOff  = dv.getUint32(off + 8,  true);
      var x       = dv.getFloat32(off + 12, true);
      var y       = dv.getFloat32(off + 16, true);
      var size    = dv.getFloat32(off + 20, true);
      var n = {
        id: readStr(idOff),
        kind: _nodeKind(kindB),
        domain_id: readStr(domOff),
        x: x, y: y, size: size,
      };
      n.type = n.kind; // D3 compatibility — addBatchToGraph reads .type
      nodes[ni] = n;
    }

    // Edges
    var edges = new Array(edgeCount);
    base = HEADER_SIZE + nodeCount * NODE_SIZE;
    for (var ei = 0; ei < edgeCount; ei++) {
      var off = base + ei * EDGE_SIZE;
      var srcOff = dv.getUint32(off,     true);
      var tgtOff = dv.getUint32(off + 4, true);
      var ek     = dv.getUint8(off + 8);
      var e = {
        source: readStr(srcOff),
        target: readStr(tgtOff),
        kind: _edgeKind(ek),
      };
      e.type = e.kind;
      edges[ei] = e;
    }

    return {
      nodes: nodes,
      edges: edges,
      links: edges,
      meta: {
        format: 'CXGBv1',
        schema: 'workflow_graph.v1',
        node_count: nodeCount,
        edge_count: edgeCount,
        snapshot_bytes: buffer.byteLength,
      },
    };
  }

  function fetchSnapshot(url) {
    var u = url || '/api/graph.bin';
    var t0 = performance.now();
    return fetch(u, { cache: 'no-cache' }).then(function(r) {
      if (r.status === 404) {
        // Snapshot not built yet — caller should fall back to JSON path.
        var err = new Error('snapshot not yet built');
        err.code = 'NO_SNAPSHOT';
        throw err;
      }
      if (!r.ok) throw new Error('snapshot HTTP ' + r.status);
      return r.arrayBuffer();
    }).then(function(buf) {
      var tFetch = performance.now() - t0;
      var t1 = performance.now();
      var g = decode(buf);
      var tDecode = performance.now() - t1;
      g.meta.fetch_ms = Math.round(tFetch);
      g.meta.decode_ms = Math.round(tDecode);
      console.log(
        '[snapshot] ' + g.nodes.length + ' nodes / ' + g.edges.length +
        ' edges — fetch ' + Math.round(tFetch) + ' ms, decode ' +
        Math.round(tDecode) + ' ms, total ' + Math.round(tFetch + tDecode) + ' ms'
      );
      return g;
    });
  }

  window.GraphSnapshot = { decode: decode, fetch: fetchSnapshot };
})();
