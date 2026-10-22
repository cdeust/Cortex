"""Streaming buffer, batch, and concurrency constants.

source: ADR-0270
"""

from __future__ import annotations

from mcp_server.core.streaming.adaptive_controller import AdaptiveBatchController
from mcp_server.core.streaming.adaptive_writer import compute_queue_cap

# source: ADR-0270

WRITE_RAM_BUDGET_BYTES = 256 * 1024 * 1024

# Entity staging path (COPY → INSERT … SELECT … WHERE NOT EXISTS).
ENTITY_B_MIN = 500
ENTITY_B_MAX = 5000
ENTITY_W_TARGET_S = 0.111

# Edge staging path (COPY → INSERT … JOIN entities … ON CONFLICT DO NOTHING).
EDGE_B_MIN = 1000
EDGE_B_MAX = 10000
EDGE_W_TARGET_S = 0.131
EDGE_ROW_BYTES = 206

# source: ADR-0270

_MAX_QUEUE_CAP = 8


def make_entity_controller() -> AdaptiveBatchController:
    """Create the entity-stage AIMD controller.

    source: ADR-0270
    """
    return AdaptiveBatchController(ENTITY_B_MIN, ENTITY_B_MAX, ENTITY_W_TARGET_S)


def make_edge_controller() -> AdaptiveBatchController:
    """Create the edge-stage AIMD controller.

    source: ADR-0270
    """
    return AdaptiveBatchController(EDGE_B_MIN, EDGE_B_MAX, EDGE_W_TARGET_S)


def edge_queue_cap() -> int:
    return min(
        _MAX_QUEUE_CAP,
        compute_queue_cap(WRITE_RAM_BUDGET_BYTES, EDGE_B_MAX, EDGE_ROW_BYTES),
    )
