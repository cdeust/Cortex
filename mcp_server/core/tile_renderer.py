"""Datashader-backed tile rendering for the workflow graph.

Pure rendering logic: takes a list of ``(node_id, x, y, kind)`` tuples
plus tile coordinates and produces PNG bytes. No PostgreSQL imports —
the handler layer composes this with ``layout_pg_store.read_positions_in_bbox``.

World coordinate system: ``[-1, 1] × [-1, 1]``. The layout engine
normalises into this range; the tile pyramid maps each ``(z, x, y)`` to
a sub-rectangle of the world.
"""

from __future__ import annotations

import io

# Fixed palette. Palette changes invalidate the tile cache via
# ``PALETTE_VERSION`` — bump it whenever any colour below changes.
PALETTE_VERSION = 1
KIND_COLOR_HEX = {
    "domain": "#FCD34D",
    "tool_hub": "#F97316",
    "skill": "#FB923C",
    "command": "#FACC15",
    "hook": "#A855F7",
    "agent": "#EC4899",
    "mcp": "#6366F1",
    "memory": "#10B981",
    "discussion": "#EF4444",
    "entity": "#50B0C8",
    "file": "#06B6D4",
    "symbol": "#64748B",
}
DEFAULT_HEX = "#888888"

WORLD_MIN = -1.0
WORLD_MAX = 1.0


def tile_world_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Map XYZ tile coordinates to ``(min_x, min_y, max_x, max_y)``.

    z=0 covers the whole [-1, 1] world in a single tile. Each level
    halves the tile span so z=10 has ~1M tiles and a per-tile span of
    2/1024 ≈ 0.002 in world units (sub-pixel at any practical zoom).
    """
    span = (WORLD_MAX - WORLD_MIN) / (1 << z)
    min_x = WORLD_MIN + x * span
    max_x = min_x + span
    # Tile y axis runs top-down (XYZ convention); flip so the world's
    # +y is the top of tile (0,0) at every zoom.
    max_y_world = WORLD_MAX - y * span
    min_y_world = max_y_world - span
    return (min_x, min_y_world, max_x, max_y_world)


def render_tile_png(
    rows: list[tuple[str, float, float, str]],
    *,
    z: int,
    x: int,
    y: int,
    tile_size: int = 512,
) -> bytes:
    """Rasterise ``rows`` (already prefiltered to the tile's world bbox)
    into a ``tile_size × tile_size`` PNG.

    Returns PNG bytes ready for HTTP transport. Empty input renders a
    fully-transparent tile (still valid PNG; client compositors expect
    that).
    """
    try:
        import datashader as ds
        import datashader.transfer_functions as tf
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "datashader + pandas are required for tile rendering — install "
            "the 'viz-tile' extra: pip install neuro-cortex-memory[viz-tile]"
        ) from exc

    min_x, min_y, max_x, max_y = tile_world_bbox(z, x, y)
    if not rows:
        # Empty frame still produces a valid 512×512 transparent PNG
        # via Datashader's spread([]) → to_pil().
        return _empty_tile_png(tile_size)

    # Datashader requires categorical kind to be a pandas Categorical
    # for ``count_cat`` aggregation. Pre-encode here.
    df = pd.DataFrame(rows, columns=["id", "x", "y", "kind"])
    kinds_present = sorted(df["kind"].unique())
    df["kind"] = pd.Categorical(df["kind"], categories=kinds_present)

    canvas = ds.Canvas(
        plot_width=tile_size,
        plot_height=tile_size,
        x_range=(min_x, max_x),
        y_range=(min_y, max_y),
    )
    agg = canvas.points(df, x="x", y="y", agg=ds.count_cat("kind"))
    color_key = {k: KIND_COLOR_HEX.get(k, DEFAULT_HEX) for k in kinds_present}
    img = tf.shade(agg, color_key=color_key, how="eq_hist")
    img = tf.spread(img, px=1, shape="circle")
    pil = img.to_pil()
    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _empty_tile_png(tile_size: int) -> bytes:
    """Cheap transparent PNG, used when the bbox query returns no rows."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Pillow is required for tile rendering") from exc
    img = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
