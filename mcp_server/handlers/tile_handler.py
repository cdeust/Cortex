"""GET /api/tile/{z}/{x}/{y}.png — composition root.

Pulls positions from PG via the layout store, hands them to the
Datashader-backed tile renderer, returns PNG bytes. No caching in
v1 — render cost is ~50-200 ms per tile and we want to validate the
pipeline end-to-end before adding the cache layer.
"""

from __future__ import annotations

import re

_PATH_RE = re.compile(r"^/api/tile/(\d+)/(\d+)/(\d+)\.png$")


def _parse(path: str) -> tuple[int, int, int] | None:
    m = _PATH_RE.match(path)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def serve(handler, store) -> None:
    parsed = _parse(handler.path.split("?")[0])
    if not parsed:
        handler.send_response(404)
        handler.end_headers()
        return
    z, x, y = parsed

    try:
        from mcp_server.core import tile_renderer
        from mcp_server.infrastructure import layout_pg_store
    except ImportError as exc:
        # ``viz-tile`` extra not installed.
        body = (
            f'{{"status":"error","reason":"viz_tile_extra_missing","detail":"{exc}"}}'
        ).encode("utf-8")
        handler.send_response(503)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    min_x, min_y, max_x, max_y = tile_renderer.tile_world_bbox(z, x, y)
    rows = layout_pg_store.read_positions_in_bbox(
        store,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
    )
    try:
        png = tile_renderer.render_tile_png(rows, z=z, x=x, y=y)
    except ImportError as exc:
        body = (
            f'{{"status":"error","reason":"datashader_missing","detail":"{exc}"}}'
        ).encode("utf-8")
        handler.send_response(503)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(png)))
    handler.send_header("Cache-Control", "max-age=300")
    handler.end_headers()
    handler.wfile.write(png)
