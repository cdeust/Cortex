"""Closed-form O(1) slot placement for the layout authority.

Every node's (x, y) is a pure function of:
  - its domain's anchor position (Fibonacci-spiral, derived once from
    the domain index alone — never depends on N)
  - its kind ('domain', 'tool_hub', 'file', 'symbol', 'memory', etc.)
  - its index within that (domain, kind) bucket
  - the running total of nodes seen in that bucket
  - optionally, its parent's slot (for symbols inside their file's petal)

No iteration. No graph. No simulation. The cost is constant per node
regardless of how many other nodes exist.

Memory footprint: O(domains × kinds) integer counters — ~528 bytes
for 11 domains × 6 kinds. The graph itself never lives in this module.

Match the visual conventions of ui/unified/js/workflow_graph.js so the
Python authority produces the same layout the user already approves of.
All constants below are copied verbatim from that file (lines 43-84).
"""

from __future__ import annotations

import math
from typing import Tuple

# ── Radii (workflow_graph.js lines 43-54) ────────────────────────────────
SETUP_R: float = 70.0
TOOL_R: float = 140.0
FILE_R: float = 220.0
DISC_R: float = 150.0
MEM_R: float = 150.0
MCP_R: float = 50.0
SYM_R_OUTER: float = 290.0
SYM_R_SPREAD: float = 32.0
SYM_CLUMP_R: float = 18.0

# ── Sector half-widths (workflow_graph.js lines 63-65) ──────────────────
SECTOR_SETUP_HALF: float = math.pi / 2.6  # ~69°
SECTOR_SIDE_HALF: float = math.pi / 6.5  # ~28°
SECTOR_SIDE_ANGLE: float = math.pi * 0.72  # ~130° from outward axis

# ── Per-tool angles, local to each domain's outward axis (lines 76-84) ──
TOOL_LOCAL_ANGLE: dict[str, float] = {
    "Edit": 0.0,
    "Write": -math.pi / 12,
    "Read": math.pi / 12,
    "Grep": -math.pi / 6,
    "Glob": math.pi / 6,
    "Bash": -math.pi / 3.6,
    "Task": math.pi / 3.6,
}

# Golden angle for Fibonacci-spiral domain placement (line 323).
_PHI: float = math.pi * (3.0 - math.sqrt(5.0))


# ── Domain placement (workflow_graph.js lines 313-328) ──────────────────
def base_radius(width: float, height: float, n_domains: int) -> float:
    """Pick baseR so adjacent shells never collide.

    Fibonacci-spiral average spacing is R·√(π/N); each shell occupies
    2·FILE_R + 60 px. We take the larger of (a) 42% of the smaller
    canvas dimension and (b) the spacing-driven floor.
    """
    shell = 2.0 * FILE_R + 60.0
    n = max(n_domains, 1)
    return max(min(width, height) * 0.42, shell * math.sqrt(n / math.pi) * 0.65)


def domain_anchor(
    index: int,
    total_domains: int,
    cx: float,
    cy: float,
    base_r: float,
) -> Tuple[float, float]:
    """Fibonacci spiral — same formula as workflow_graph.js line 326."""
    n = max(total_domains, 1)
    r = base_r * math.sqrt((index + 0.5) / n)
    theta = index * _PHI
    return (cx + r * math.cos(theta), cy + r * math.sin(theta))


def outward_angle(anchor: Tuple[float, float], cx: float, cy: float) -> float:
    """Radially-outward axis from graph center to the domain anchor.

    Domains within 5px of the center get a stable upward bias
    (matches workflow_graph.js line 464).
    """
    dx, dy = anchor[0] - cx, anchor[1] - cy
    if math.hypot(dx, dy) < 5.0:
        return -math.pi / 2.0
    return math.atan2(dy, dx)


# ── L1 setup ring (workflow_graph.js lines 500-507) ─────────────────────
def slot_for_setup(
    anchor: Tuple[float, float],
    outward: float,
    idx: int,
    total: int,
) -> Tuple[float, float]:
    """Skill / hook / command / agent fan inside the setup sector."""
    arc = SECTOR_SETUP_HALF * 2.0
    n = max(total, 1)
    t = outward + ((idx + 0.5) / n - 0.5) * arc
    r = SETUP_R + (idx % 2) * 8.0
    return (anchor[0] + r * math.cos(t), anchor[1] + r * math.sin(t))


# ── L2 tool hubs (workflow_graph.js lines 469-476) ──────────────────────
def slot_for_tool_hub(
    anchor: Tuple[float, float],
    outward: float,
    tool_name: str,
) -> Tuple[float, float]:
    """Tool hub at fixed per-tool angle along the outward axis."""
    local = TOOL_LOCAL_ANGLE.get(tool_name, 0.0)
    t = outward + local
    return (anchor[0] + TOOL_R * math.cos(t), anchor[1] + TOOL_R * math.sin(t))


def tool_hub_angle(outward: float, tool_name: str) -> float:
    """Return the per-tool angle (caller stores it for files to orbit)."""
    return outward + TOOL_LOCAL_ANGLE.get(tool_name, 0.0)


# ── L3 files (workflow_graph.js lines 485-495) ──────────────────────────
def slot_for_file(
    anchor: Tuple[float, float],
    hub_angle: float,
    idx_in_hub: int,
    total_in_hub: int,
) -> Tuple[float, float]:
    """File orbits its primary tool hub; arc widens with file count."""
    n = max(total_in_hub, 1)
    arc = min(0.35, 0.08 + n * 0.015)
    t = hub_angle + ((idx_in_hub + 0.5) / n - 0.5) * arc
    r = FILE_R + ((idx_in_hub % 3) - 1) * 4.0
    return (anchor[0] + r * math.cos(t), anchor[1] + r * math.sin(t))


# ── L4 discussions (workflow_graph.js lines 511-519) ────────────────────
def slot_for_discussion(
    anchor: Tuple[float, float],
    outward: float,
    idx: int,
    total: int,
) -> Tuple[float, float]:
    """Discussion lane on one side of the domain, opposite memories."""
    center = outward + SECTOR_SIDE_ANGLE
    n = max(total, 1)
    arc = SECTOR_SIDE_HALF * 2.0 + min(math.pi / 3.0, n * 0.04)
    t = center + ((idx + 0.5) / n - 0.5) * arc
    r = DISC_R + (idx % 3) * 6.0
    return (anchor[0] + r * math.cos(t), anchor[1] + r * math.sin(t))


# ── L5 memories (workflow_graph.js lines 522-531) ───────────────────────
def slot_for_memory(
    anchor: Tuple[float, float],
    outward: float,
    idx: int,
    total: int,
) -> Tuple[float, float]:
    """Memory lane on the opposite side from discussions."""
    center = outward - SECTOR_SIDE_ANGLE
    n = max(total, 1)
    arc = SECTOR_SIDE_HALF * 2.0 + min(math.pi / 2.5, n * 0.03)
    t = center + ((idx + 0.5) / n - 0.5) * arc
    r = MEM_R + (idx % 4) * 8.0
    return (anchor[0] + r * math.cos(t), anchor[1] + r * math.sin(t))


# ── MCPs (workflow_graph.js lines 536-541) ──────────────────────────────
def slot_for_mcp(
    anchor: Tuple[float, float],
    outward: float,
    idx: int,
    total: int,
) -> Tuple[float, float]:
    """MCPs sit INWARD of the domain so cross-domain edges fan visibly."""
    t = outward + math.pi
    jitter = (idx - (max(total, 1) - 1) / 2.0) * 0.25
    return (
        anchor[0] + MCP_R * math.cos(t + jitter),
        anchor[1] + MCP_R * math.sin(t + jitter),
    )


# ── L6 symbols (workflow_graph.js — petal cloud around parent file) ─────
def slot_for_symbol(
    file_slot: Tuple[float, float],
    idx_in_file: int,
    total_in_file: int,
) -> Tuple[float, float]:
    """Petal around parent file. Idx-deterministic angle around the file."""
    if total_in_file <= 0:
        return file_slot
    angle = 2.0 * math.pi * (idx_in_file + 0.5) / total_in_file
    r = SYM_CLUMP_R + (idx_in_file % 4) * 3.0
    return (file_slot[0] + r * math.cos(angle), file_slot[1] + r * math.sin(angle))


# ── Dispatcher ──────────────────────────────────────────────────────────
def compute_slot(node_kind: str, ctx: dict) -> Tuple[float, float]:
    """Closed-form slot lookup keyed by node kind.

    `ctx` is a plain dict supplying only the fields each helper needs:
      - anchor, outward, idx, total          (setup / disc / mem / mcp)
      - anchor, outward, tool_name           (tool_hub)
      - anchor, hub_angle, idx, total        (file)
      - file_slot, idx, total                (symbol)
      - index, total_domains, cx, cy, base_r (domain)

    All branches are O(1). No state mutation. Unknown kinds return the
    domain anchor as a safe fallback so the renderer never sees NaN.
    """
    if node_kind == "domain":
        return domain_anchor(
            ctx["index"], ctx["total_domains"], ctx["cx"], ctx["cy"], ctx["base_r"]
        )
    if node_kind == "tool_hub":
        return slot_for_tool_hub(ctx["anchor"], ctx["outward"], ctx["tool_name"])
    if node_kind == "file":
        return slot_for_file(ctx["anchor"], ctx["hub_angle"], ctx["idx"], ctx["total"])
    if node_kind == "symbol":
        return slot_for_symbol(ctx["file_slot"], ctx["idx"], ctx["total"])
    if node_kind in ("skill", "hook", "command", "agent"):
        return slot_for_setup(ctx["anchor"], ctx["outward"], ctx["idx"], ctx["total"])
    if node_kind == "discussion":
        return slot_for_discussion(
            ctx["anchor"], ctx["outward"], ctx["idx"], ctx["total"]
        )
    if node_kind == "memory":
        return slot_for_memory(ctx["anchor"], ctx["outward"], ctx["idx"], ctx["total"])
    if node_kind == "mcp":
        return slot_for_mcp(ctx["anchor"], ctx["outward"], ctx["idx"], ctx["total"])
    return ctx.get("anchor", (ctx.get("cx", 0.0), ctx.get("cy", 0.0)))
