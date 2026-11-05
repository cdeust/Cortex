"""Code-graph cache ownership: root markers and orphan pruning (issue #711).

Every project or worktree where a session opens gets its own graph under
``~/.cache/cortex/code-graphs/<project key>/`` (0.6 to 1.1 GB each, measured
2026-10-10 on a development machine, issue #711). Nothing tied a directory to
the project it was built from, so a deleted worktree left its graph behind.

Cortex now writes its own marker, ``cortex-root.json``, next to the graph it
asks the upstream analyzer to build. The upstream ``meta.json`` belongs to the
automatised-pipeline (ADR-0052: it writes it "for cortex-viz") and its schema
is not defined in this repository, so it is never read or rewritten here.

Pruning rule: a graph directory whose marker names a root that no longer exists
is removed; no session can be using a graph whose project directory is gone. A
directory without a readable marker cannot be tied to a root, so it is reported
and kept, never deleted on a guess.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
from pathlib import Path

from mcp_server.shared import gated_files

logger = logging.getLogger(__name__)

ROOT_MARKER = "cortex-root.json"


@dataclasses.dataclass(frozen=True)
class PruneReport:
    """Outcome of one pruning pass over a code-graph cache directory."""

    removed: tuple[str, ...]
    unattributed: tuple[str, ...]
    failed: tuple[str, ...]


def managed_cache_dir() -> Path:
    """The only directory whose entries pruning may remove."""
    return Path.home() / ".cache" / "cortex" / "code-graphs"


def record_root(graph_dir: str | Path, project_root: str | Path) -> None:
    """Write the marker when both directories exist; a failed write is logged.

    A root that is not an existing directory is never recorded: such a marker
    would read as orphaned at once and let the next prune remove ``graph_dir``."""
    if not Path(graph_dir).expanduser().is_dir():
        return
    if not Path(project_root).expanduser().is_dir():
        return
    try:
        write_root_marker(graph_dir, project_root)
    except OSError as exc:
        logger.warning("could not write root marker in %s: %s", graph_dir, exc)


def write_root_marker(graph_dir: str | Path, project_root: str | Path) -> None:
    """Record ``project_root`` (resolved) as the root ``graph_dir`` was built from.

    The write goes through the redaction gate (ADR-1110). If redaction altered
    the path, the marker would name a root that does not exist and the graph
    would be pruned; the marker is removed instead, leaving it unattributed."""
    target = Path(graph_dir).expanduser()
    root = str(Path(project_root).expanduser().resolve())
    marker = target / ROOT_MARKER
    gated_files.write_json(marker, {"project_root": root})
    if read_root_marker(target) != root:
        marker.unlink()
        logger.warning("root marker for %s was altered by redaction; removed", target)


def read_root_marker(graph_dir: Path) -> str | None:
    """The recorded project root, or None when the marker is absent or unreadable."""
    try:
        data = json.loads((graph_dir / ROOT_MARKER).read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    root = data.get("project_root")
    return root if isinstance(root, str) and root else None


def prune_orphan_graphs(cache_dir: str | Path) -> PruneReport:
    """Remove graphs whose recorded root is gone; report the unattributed ones."""
    base = Path(cache_dir).expanduser()
    removed: list[str] = []
    unattributed: list[str] = []
    failed: list[str] = []
    if not base.is_dir():
        return PruneReport((), (), ())
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        root = read_root_marker(entry)
        if root is None:
            unattributed.append(entry.name)
        elif not Path(root).exists():
            try:
                shutil.rmtree(entry)
                removed.append(entry.name)
            except OSError as exc:
                logger.warning("could not prune orphan graph %s: %s", entry, exc)
                failed.append(entry.name)
    _log_report(base, removed, unattributed)
    return PruneReport(tuple(removed), tuple(unattributed), tuple(failed))


def _log_report(base: Path, removed: list[str], unattributed: list[str]) -> None:
    if removed:
        logger.info("pruned %d orphan code graph(s): %s", len(removed), removed)
    if unattributed:
        logger.warning(
            "%d code graph(s) under %s carry no %s and cannot be tied to a "
            "project root; kept, remove by hand if unused: %s",
            len(unattributed),
            base,
            ROOT_MARKER,
            unattributed,
        )
