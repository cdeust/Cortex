"""GET /api/quadtree — gzipped Arrow IPC of every node's (id, x, y, kind).

The client builds a quadtree (e.g. flatbush) from this payload to
resolve hover/click locally in O(log N) without a server roundtrip.
``id`` and ``kind`` are dictionary-encoded so the wire size is
dominated by two Float32 columns at 1M nodes ≈ 8 MB raw / ~3-4 MB
gzipped.
"""

from __future__ import annotations

import gzip
import json


def serve(handler, store) -> None:
    try:
        import pyarrow as pa
        import pyarrow.ipc as ipc
        from mcp_server.infrastructure import layout_pg_store
    except ImportError as exc:
        body = (
            f'{{"status":"error","reason":"viz_tile_extra_missing","detail":"{exc}"}}'
        ).encode("utf-8")
        handler.send_response(503)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    rows = layout_pg_store.read_all_positions(store)
    if not rows:
        body = json.dumps({"status": "error", "reason": "no_layout"}).encode("utf-8")
        handler.send_response(503)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    ids = [r[0] for r in rows]
    xs = [r[1] for r in rows]
    ys = [r[2] for r in rows]
    kinds = [r[3] for r in rows]

    # Dict-encoded id + kind shrink the wire substantially: ``id`` is
    # high-cardinality but the dict encoding still beats UTF-8 for
    # lookup; ``kind`` collapses to ~12 distinct values.
    table = pa.table(
        {
            "id": pa.array(ids).dictionary_encode(),
            "x": pa.array(xs, type=pa.float32()),
            "y": pa.array(ys, type=pa.float32()),
            "kind": pa.array(kinds).dictionary_encode(),
        }
    )

    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    arrow_buf = sink.getvalue().to_pybytes()
    body = gzip.compress(arrow_buf, compresslevel=6)

    handler.send_response(200)
    handler.send_header("Content-Type", "application/vnd.apache.arrow.stream")
    handler.send_header("Content-Encoding", "gzip")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "max-age=60")
    handler.end_headers()
    handler.wfile.write(body)
