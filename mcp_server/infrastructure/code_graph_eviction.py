"""Code-graph cache size cap: least-recently-used eviction (issue #711, 3b).

Each graph under ``~/.cache/cortex/code-graphs/`` weighs 0.6 to 1.1 GB, and a
machine with many worktrees held 60 entries and 12 GB (measured 2026-10-10 on a
development machine, issue #711). Orphan pruning (slices 1 and 2) removes the
graphs whose root is gone; it does not bound the graphs of projects that still
exist. This module does, under a cap the user sets.

Rules (decision comment of 2026-11-15 on issue #711):

* The cap comes from ``CORTEX_CODE_GRAPH_CACHE_MAX_GB`` (decimal gigabytes,
  10**9 bytes). Unset or blank: no eviction. No default cap is shipped: no value
  is sourced in this repository, and the measurement of the issue gives the size
  of one graph, not a user's disk budget.
* A graph is in use when its recorded root (``cortex-root.json``) is exactly the
  project root of a live window (``session_registry_roots.live_project_roots``).
  A graph in use is never evicted, and its marker is touched so that it reads as
  just used. A window opened in a subdirectory, or one that reads another
  project's graph, does not hold that graph. When the set of live roots is
  unknown, nothing is evicted.
* A directory without a readable marker cannot be tied to a root: it counts in
  the total but is never evicted (same rule as the orphan pruning).
* The others are evicted oldest marker mtime first until the total fits. A
  removal that fails does not stop the pass: the next candidate is tried.
  The marker is written when the graph is built, and touched only in a worker
  pass that runs with a cap set and known live roots, for the graphs of the
  live windows' projects; reading a cached graph does not touch it.
* Codex sessions are not registered yet (``find_claude_ancestor`` recognises
  ``claude`` only): with a cap set, a graph used only by a live Codex session
  is not protected (refinement 1 of the 2026-11-16 comment on issue #711).
"""

from __future__ import annotations

import dataclasses
import logging
import math
import os
import shutil
from pathlib import Path

from mcp_server.infrastructure.code_graph_cache import ROOT_MARKER, read_root_marker

logger = logging.getLogger(__name__)

CAP_ENV = "CORTEX_CODE_GRAPH_CACHE_MAX_GB"
# source: SI decimal prefix, giga = 10**9 (BIPM, SI Brochure 9th ed., table 7)
_BYTES_PER_GB = 10**9


@dataclasses.dataclass(frozen=True)
class GraphEntry:
    """One graph directory of the cache, as the eviction sees it."""

    name: str
    size: int
    last_used: float
    root: str | None


@dataclasses.dataclass(frozen=True)
class EvictionReport:
    """Outcome of one eviction pass."""

    removed: tuple[str, ...]
    failed: tuple[str, ...]
    total_bytes: int
    over_cap: bool


def cache_cap_bytes() -> int | None:
    """The cap in bytes, or None when no cap is set or the value is refused.

    Refused, logged, no cap: a value that is not a number; a negative one, -0
    included; one whose byte count is not finite (nan, inf, 1e300); one that is
    not 0 but below one byte (1e-10). 0 is a cap of 0 bytes. An eviction never
    runs on a value the user did not write."""
    raw = os.environ.get(CAP_ENV, "").strip()
    if not raw:
        return None
    try:
        gigabytes = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; no code-graph eviction", CAP_ENV, raw)
        return None
    size = gigabytes * _BYTES_PER_GB
    # The product, not the input, is checked: 1e300 is finite, its bytes are not.
    # The sign is read on the text, not on the float: -0.0 >= 0.0 holds, and "-0"
    # is not a size the user wrote. ``raw`` is stripped, so a negative starts with -.
    if raw.startswith("-") or not math.isfinite(size):
        logger.warning("%s=%r is not a finite size >= 0; no eviction", CAP_ENV, raw)
        return None
    if 0 < size < 1:
        logger.warning("%s=%r is below one byte; no eviction", CAP_ENV, raw)
        return None
    return int(size)


def directory_size(path: Path) -> int:
    """Bytes of the regular files under ``path``; symlinks are not followed."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            try:
                stat = os.lstat(os.path.join(dirpath, filename))
            except OSError:
                continue
            total += stat.st_size
    return total


def _marker_mtime(graph_dir: Path) -> float:
    try:
        return (graph_dir / ROOT_MARKER).stat().st_mtime
    except OSError:
        return 0.0


def scan_entries(cache_dir: Path) -> list[GraphEntry]:
    """Each graph directory under ``cache_dir``: size, marker mtime, root."""
    if not cache_dir.is_dir():
        return []
    return [
        GraphEntry(
            name=entry.name,
            size=directory_size(entry),
            last_used=_marker_mtime(entry),
            root=read_root_marker(entry),
        )
        for entry in sorted(cache_dir.iterdir())
        if entry.is_dir() and not entry.is_symlink()
    ]


def eviction_candidates(
    entries: list[GraphEntry], live_roots: frozenset[str]
) -> list[GraphEntry]:
    """The entries that may be evicted, oldest marker mtime first.

    postcondition: never an entry without a root or one whose root is in
    ``live_roots``."""
    return sorted(
        (e for e in entries if e.root is not None and e.root not in live_roots),
        key=lambda e: (e.last_used, e.name),
    )


def _touch_live_markers(
    cache_dir: Path, entries: list[GraphEntry], live: frozenset[str]
):
    for entry in entries:
        if entry.root in live:
            try:
                os.utime(cache_dir / entry.name / ROOT_MARKER)
            except OSError as exc:
                logger.warning("could not touch marker of %s: %s", entry.name, exc)


def evict_to_cap(
    cache_dir: str | Path, cap: int, live_roots: frozenset[str] | None
) -> EvictionReport:
    """Remove the least recently used graphs not in use until the cache fits ``cap``."""
    base = Path(cache_dir).expanduser()
    entries = scan_entries(base)
    total = sum(entry.size for entry in entries)
    if live_roots is None:
        logger.warning("live project roots unknown; no code-graph eviction")
        return EvictionReport((), (), total, total > cap)
    _touch_live_markers(base, entries, live_roots)
    removed: list[str] = []
    failed: list[str] = []
    # The stop test reads the total after the removals that succeeded, so a
    # graph that cannot be removed hands its turn to the next candidate.
    for entry in eviction_candidates(entries, live_roots):
        if total <= cap:
            break
        try:
            shutil.rmtree(base / entry.name)
        except OSError as exc:
            logger.warning("could not evict code graph %s: %s", base / entry.name, exc)
            failed.append(entry.name)
            continue
        removed.append(entry.name)
        total -= entry.size
    if removed:
        logger.info("evicted %d code graph(s) over the cap: %s", len(removed), removed)
    return EvictionReport(tuple(removed), tuple(failed), total, total > cap)
