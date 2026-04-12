"""Handler: consolidate — run decay, compression, and CLS maintenance cycles.

Thin orchestrator that delegates each cycle to a focused sub-module in
mcp_server.handlers.consolidation/.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp_server.core import emergence_tracker
from mcp_server.handlers.consolidation.cascade import run_cascade_advancement
from mcp_server.handlers.consolidation.cls import run_cls_cycle
from mcp_server.handlers.consolidation.compression import run_compression_cycle
from mcp_server.handlers.consolidation.decay import run_decay_cycle
from mcp_server.handlers.consolidation.homeostatic import run_homeostatic_cycle
from mcp_server.handlers.consolidation.memify import run_memify_cycle
from mcp_server.handlers.consolidation.plasticity import run_plasticity_cycle
from mcp_server.handlers.consolidation.pruning import run_pruning_cycle
from mcp_server.handlers.consolidation.sleep import run_deep_sleep
from mcp_server.handlers.consolidation.transfer import run_two_stage_transfer
from mcp_server.infrastructure.embedding_engine import (
    EmbeddingEngine,
    get_embedding_engine,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

schema = {
    "description": "Run memory maintenance: heat decay, compression, and CLS consolidation cycles.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "decay": {
                "type": "boolean",
                "description": "Run heat decay cycle (default true)",
            },
            "compress": {
                "type": "boolean",
                "description": "Run compression cycle (default true)",
            },
            "cls": {
                "type": "boolean",
                "description": "Run CLS episodic→semantic consolidation (default true)",
            },
            "memify": {
                "type": "boolean",
                "description": "Run memify self-improvement cycle (default true)",
            },
            "deep": {
                "type": "boolean",
                "description": "Run deep sleep compute: dream replay, cluster summarization, re-embedding, auto-narration (default false)",
            },
        },
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run maintenance cycles on the memory system."""
    args = args or {}
    settings = get_memory_settings()
    store = _get_store()
    embeddings = get_embedding_engine()
    start = time.monotonic()

    stats = _run_cycles(args, store, settings, embeddings)
    stats = _run_always_cycles(args, store, stats)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    stats["duration_ms"] = elapsed_ms
    _log_consolidation(store, stats, elapsed_ms)
    return stats


def _run_cycles(
    args: dict,
    store: MemoryStore,
    settings: Any,
    embeddings: EmbeddingEngine,
) -> dict[str, Any]:
    """Run optional maintenance cycles based on args flags."""
    stats: dict[str, Any] = {}

    if args.get("decay", True):
        stats["decay"] = run_decay_cycle(store, settings)
        stats["plasticity"] = run_plasticity_cycle(store)
        stats["pruning"] = run_pruning_cycle(store)

    if args.get("compress", True):
        stats["compression"] = run_compression_cycle(store, settings, embeddings)

    if args.get("cls", True):
        stats["cls"] = run_cls_cycle(store, settings, embeddings)

    if args.get("memify", True):
        stats["memify"] = run_memify_cycle(store)

    if args.get("deep", False):
        stats["deep_sleep"] = run_deep_sleep(store, embeddings)

    return stats


def _run_always_cycles(
    args: dict,
    store: MemoryStore,
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Run cycles that always execute regardless of flags."""
    stats["cascade"] = run_cascade_advancement(store)
    stats["homeostatic"] = run_homeostatic_cycle(store)

    if args.get("deep", False):
        stats["transfer"] = run_two_stage_transfer(store)

    try:
        all_mems = store.get_all_memories_for_decay()
        stats["emergence"] = emergence_tracker.generate_emergence_report(all_mems)
    except Exception:
        pass

    return stats


def _log_consolidation(
    store: MemoryStore,
    stats: dict[str, Any],
    elapsed_ms: int,
) -> None:
    """Log consolidation event to the store."""
    store.log_consolidation(
        {
            "memories_added": stats.get("cls", {}).get("new_semantics_created", 0),
            "memories_updated": stats.get("decay", {}).get("memories_decayed", 0),
            "memories_archived": stats.get("compression", {}).get(
                "compressed_to_tag", 0
            ),
            "duration_ms": elapsed_ms,
        }
    )
