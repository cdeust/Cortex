"""Canonical pruned source-tree traversal.

A single home for the ``os.walk`` idiom that skips ignored directories
(``node_modules``, ``.venv``, ``deps``, ``site-packages``, …) by pruning
``dirnames`` in place so they are **never descended into**.

source: ADR-0448"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from mcp_server.handlers.seed_project_constants import IGNORE_DIRS

__all__ = ["walk_pruned"]


def walk_pruned(root: Path) -> Iterator[Path]:
    """Yield every file under ``root`` skipping ``IGNORE_DIRS`` subtrees.

    Preconditions:
        - ``root`` is an existing directory (a non-directory yields nothing).

    Postconditions:
        - No path under any directory whose name is in ``IGNORE_DIRS`` is
          yielded, and such directories are never descended into — peak work
          is O(files in the kept subtree), not O(whole tree).
        - Symlinked directories are not followed (``followlinks=False``).
        - Yields ``Path`` objects for regular directory entries only;
          existence/type of each yielded path is the caller's filter concern.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        dp = Path(dirpath)
        for name in filenames:
            yield dp / name
