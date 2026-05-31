"""Fractal level-of-detail subsampler for the layout authority.

Principle (Mandelbrot 1982, *The Fractal Geometry of Nature*):
    Graph structure is self-similar across scales. At full zoom the user
    needs every symbol; at far zoom only domain/tool/file scaffolding
    matters. Decimation by a deterministic hash keyed on (node_id, zoom)
    yields the SAME visible subset across reconnects — clients can drop
    and rejoin without the visible population shifting.

The decimation rule is power-law in stride:

    stride(zoom) = max(1, int(2 ** (3 - zoom * 4)))

    zoom=1.00 → stride=1   (all symbols visible)
    zoom=0.75 → stride=1
    zoom=0.50 → stride=2   (≈ half)
    zoom=0.25 → stride=4   (≈ quarter)
    zoom=0.00 → stride=8   (≈ 1/8)

Visible-count vs stride is approximately a power law (slope -1 on log-log)
because |visible| ≈ N / stride. This is the Mandelbrot signature: the
information density scales as a power of the resolution, not as a
constant. See `tasks/layout-authority/audits/mandelbrot.md`.

This module is pure logic. Imports stdlib only. No I/O.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Iterator

from mcp_server.server.layout_authority_protocol import NodeDelta


# ── Kinds that are ALWAYS visible regardless of zoom ─────────────
# These form the structural scaffolding; their cardinality is bounded
# (typically O(domains) + O(tools) + O(files)) so emitting all of them
# at every zoom is cheap.
_ALWAYS_VISIBLE: frozenset[str] = frozenset(
    {
        "domain",
        "tool_hub",
        "file",
        "discussion",
        "skill",
        "hook",
        "command",
        "agent",
        "mcp",
    }
)

# Kinds that are decimated by the power-law stride.
_DECIMATED: frozenset[str] = frozenset({"symbol"})

# Kinds that are reduced (stride=2) only at far zoom (< 0.4).
_FAR_REDUCED: frozenset[str] = frozenset({"memory", "entity"})

# Threshold below which memory/entity get reduced.
_FAR_ZOOM_THRESHOLD: float = 0.4

# Stride applied to memory/entity when zoom < threshold.
_FAR_REDUCED_STRIDE: int = 2


def stride(zoom: float) -> int:
    """Power-law stride for the symbol decimation.

    stride(zoom) = max(1, int(2 ** (3 - zoom * 4)))

    The exponent 3 - 4*zoom is linear in zoom, so stride is exponential
    in zoom — visible-count is therefore power-law in stride. This is
    the Mandelbrot self-similarity property: zooming by a factor of 2
    in resolution multiplies visible symbols by ~2.

    Clamps zoom to [0.0, 1.0] before computing.
    """
    z = 0.0 if zoom < 0.0 else (1.0 if zoom > 1.0 else zoom)
    exponent = 3.0 - z * 4.0
    s = int(2**exponent)
    return s if s >= 1 else 1


def _stable_hash(node_id: str) -> int:
    """Deterministic, reconnection-stable hash of a node id.

    Uses BLAKE2b with a fixed digest size. CPython's `hash()` is salted
    per-process and would NOT yield identical visible subsets across
    reconnects — that violates the contract. BLAKE2b is content-only.
    """
    h = hashlib.blake2b(node_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "big", signed=False)


def visible_at_zoom(node_id: str, kind: str, zoom: float) -> bool:
    """True iff this node should be emitted at this zoom level.

    Decimation per kind:
        domain, tool_hub, file, discussion, skill, hook, command,
            agent, mcp                        → always visible
        symbol                                → hash(id) % stride(zoom) == 0
        memory, entity                        → reduced at zoom < 0.4
        unknown kind                          → always visible (fail open)

    The decision is a pure function of (node_id, kind, zoom). No state.
    Identical inputs always produce identical outputs — the SSE handler
    can run this at reconnect time and reproduce the prior visible set
    exactly.
    """
    if kind in _ALWAYS_VISIBLE:
        return True

    if kind in _DECIMATED:
        s = stride(zoom)
        if s <= 1:
            return True
        return _stable_hash(node_id) % s == 0

    if kind in _FAR_REDUCED:
        if zoom >= _FAR_ZOOM_THRESHOLD:
            return True
        return _stable_hash(node_id) % _FAR_REDUCED_STRIDE == 0

    # Unknown kind: be conservative and emit it. The client decides
    # what to do with it. We never silently drop unrecognized data.
    return True


def visible_subset(
    nodes: Iterable[NodeDelta],
    zoom: float,
) -> Iterator[NodeDelta]:
    """Yield only the nodes that pass `visible_at_zoom` at this zoom.

    Used by the SSE handler when the client passes `?zoom=0.5` on
    (re)connect: the handler streams only the surviving subset rather
    than the full population. The client never sees nodes it can't
    render at the current zoom.

    Streaming (Iterator return) is intentional — the node population
    can be 10^6+ symbols and we must not materialize the full filtered
    list before sending the first delta.
    """
    for n in nodes:
        if visible_at_zoom(n.node_id, n.kind, zoom):
            yield n


# ── Self-check: roughness measure ─────────────────────────────────
#
# Mandelbrot's signature on the decimation: visible-count vs stride
# should be approximately a power law (slope ≈ -1 on log-log). We
# verify on a sample population of 10^6 symbol ids by counting how
# many pass the filter at each canonical zoom level and comparing
# against N / stride(zoom).


def _selfcheck_powerlaw(
    n_symbols: int = 1_000_000,
) -> list[tuple[float, int, int, float]]:
    """Return rows of (zoom, stride, visible_count, ratio_to_ideal).

    `ratio_to_ideal` should be close to 1.0 if the hash is uniform.
    """
    rows: list[tuple[float, int, int, float]] = []
    zooms = [0.0, 0.25, 0.5, 0.75, 1.0]
    # Pre-render symbol ids deterministically.
    ids = [f"sym:{i}" for i in range(n_symbols)]
    for z in zooms:
        s = stride(z)
        if s == 1:
            visible = n_symbols
        else:
            visible = sum(1 for nid in ids if _stable_hash(nid) % s == 0)
        ideal = n_symbols / s
        ratio = visible / ideal if ideal > 0 else 0.0
        rows.append((z, s, visible, ratio))
    return rows


if __name__ == "__main__":  # pragma: no cover
    import math

    print("Mandelbrot LOD self-check — power-law decimation")
    print("=" * 64)
    print(f"{'zoom':>6} {'stride':>8} {'visible':>12} {'ideal':>12} {'ratio':>8}")
    print("-" * 64)
    rows = _selfcheck_powerlaw(n_symbols=1_000_000)
    for z, s, v, r in rows:
        ideal = 1_000_000 / s
        print(f"{z:>6.2f} {s:>8d} {v:>12d} {ideal:>12.0f} {r:>8.4f}")

    # Log-log slope check: log(visible) vs log(stride) should be ≈ -1.
    print("-" * 64)
    log_strides = [math.log(s) for _, s, _, _ in rows if s > 1]
    log_visible = [math.log(v) for _, s, v, _ in rows if s > 1]
    if len(log_strides) >= 2:
        # Simple two-point slope between extremes.
        slope = (log_visible[-1] - log_visible[0]) / (log_strides[-1] - log_strides[0])
        print(f"log-log slope (visible vs stride): {slope:+.4f}  (expected ≈ -1.0)")
        assert -1.05 < slope < -0.95, f"slope {slope} outside Mandelbrot tolerance"
        print("PASS: decimation is power-law within tolerance.")
    else:
        print("SKIP: not enough non-unit strides to fit a slope.")
