"""Freshness policy for the codebase graph.

When a user runs ``ingest_codebase``, the pipeline produces a graph at
``<output_dir>/graph.ladybug`` and Cortex memoises the path in a
protected memory. The graph is stale when:

  * the path no longer exists (someone cleaned /tmp), OR
  * the mtime is older than ``CORTEX_PIPELINE_GRAPH_TTL_HOURS`` (default 24h).

Stale graphs trigger a background re-analysis on the next SessionStart
so the following session has a fresh graph — without blocking the
current session.

Source: user directive "codebase analysis feeding the memory and wiki"
— runs automatically, off the hot path.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Default 24h. Tune via CORTEX_PIPELINE_GRAPH_TTL_HOURS.
_DEFAULT_TTL_HOURS = 24.0


def graph_ttl_hours() -> float:
    raw = os.environ.get("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "")
    if not raw:
        return _DEFAULT_TTL_HOURS
    try:
        return max(0.0, float(raw))
    except (ValueError, TypeError):
        return _DEFAULT_TTL_HOURS


def graph_is_stale(graph_path: str | None) -> bool:
    """True when the graph is missing or older than the TTL."""
    if not graph_path:
        return True
    path = Path(graph_path).expanduser()
    if not path.exists():
        return True
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    return age_hours > graph_ttl_hours()
