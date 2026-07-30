"""Constant-memory streaming pipeline — ports and pure orchestration.

A producer (StreamSource) feeds a bounded queue feeding batch consumers
(BatchSink) with adaptive batch sizing (AdaptiveBatchController). Peak RAM
is provably (queue_cap + concurrency + 1) batches — independent of the total
number of rows — so the same code streams thousands or trillions of rows.

Pure business logic only. Infrastructure provides the adapters; handlers wire
them. See ~/.claude/plans/sharded-popping-harbor.md for the design and the
genius-review findings the contracts encode.
"""

from __future__ import annotations

from mcp_server.core.streaming.adaptive_controller import (
    AdaptiveBatchController,
    adaptive_batch_controller_batch_size,
    adaptive_batch_controller_observe,
)
from mcp_server.core.streaming.backpressure_pipeline import (
    BackpressurePipeline,
    PipelineResult,
    backpressure_pipeline_run,
    compute_queue_cap,
)
from mcp_server.core.streaming.ports import BatchSink, StreamSource

__all__ = [
    "AdaptiveBatchController",
    "adaptive_batch_controller_batch_size",
    "adaptive_batch_controller_observe",
    "BackpressurePipeline",
    "PipelineResult",
    "backpressure_pipeline_run",
    "compute_queue_cap",
    "BatchSink",
    "StreamSource",
]
