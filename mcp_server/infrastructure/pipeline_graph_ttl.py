"""Freshness policy for the codebase graph.

When a user runs ``ingest_codebase``, the pipeline produces a graph at
``<output_dir>/graph.ladybug`` and Cortex memoises the path in a
protected memory. The graph is stale when:

  * the path no longer exists (someone cleaned /tmp), OR
  * the mtime is older than ``CORTEX_PIPELINE_GRAPH_TTL_HOURS`` (default 24h).

The same TTL bounds the background re-analysis SessionStart spawns: at most
one per project per window, whatever its outcome, so a failed, slow or
concurrent ingest never makes every session start another one.

source: ADR-0585"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

from mcp_server.shared.log_rotation import methodology_log_path

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


def claim_reanalysis_slot(project_root: str) -> bool:
    """True, and records the attempt, when no background re-analysis of
    ``project_root`` was claimed in the current TTL window; False otherwise.

    The claim is one atomic create (``O_CREAT | O_EXCL``) of a stamp under
    ``~/.claude/methodology`` keyed by the resolved project path and the
    window (``now // TTL``): of two sessions racing for one window, exactly
    one wins, and the stamp holds whether the worker succeeds, fails, or is
    still running when the next session starts. The winner removes the
    project's stamps from earlier windows, so one file remains per project.
    A zero TTL bounds nothing, as it makes every graph stale.

    source: ADR-0585"""
    ttl_seconds = graph_ttl_hours() * 3600.0
    if ttl_seconds <= 0.0:
        return True
    resolved = str(Path(project_root).expanduser().resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    window = int(time.time() // ttl_seconds)
    stamp = methodology_log_path(f"pipeline_reanalyze.{digest}.{window}.stamp")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(stamp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    for old in stamp.parent.glob(f"pipeline_reanalyze.{digest}.*.stamp"):
        if old != stamp:
            old.unlink(missing_ok=True)
    return True
