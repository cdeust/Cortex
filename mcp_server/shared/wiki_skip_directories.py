"""Directories never worth scanning for wiki source-file checks — vendored
deps, build artifacts, generated caches, IDE state. Pure data shared by
core/wiki_coverage.py and infrastructure/wiki_drift_fs.py (infrastructure
may not import core, so this lives in shared/ rather than one importing
the other's copy).

source: issue #560
"""

from __future__ import annotations

from typing import Final

SKIP_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "env",
        "deps",
        "site-packages",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        ".next",
        ".turbo",
        "coverage",
        ".cache",
        ".tox",
        ".eggs",
        ".gradle",
        ".idea",
        ".vscode",
    }
)
