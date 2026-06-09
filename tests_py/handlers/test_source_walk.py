"""Pruned source-tree traversal — ``walk_pruned``.

Regression coverage for the ingestion-side counterpart of the wiki-drift
hang: a repo carrying a vendored subtree (``deps/``, ``node_modules/``,
``site-packages/``) must never be descended into. ``rglob`` enumerated those
entries before the caller could reject them; ``walk_pruned`` prunes them in
place so the work is bounded to the kept subtree.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.handlers.seed_project_constants import IGNORE_DIRS
from mcp_server.handlers.source_walk import walk_pruned


def test_yields_kept_files(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")
    (tmp_path / "top.py").write_text("y = 2\n")

    names = {p.name for p in walk_pruned(tmp_path)}
    assert names == {"mod.py", "top.py"}


def test_does_not_descend_into_ignored_dirs(tmp_path: Path) -> None:
    """A file under any IGNORE_DIRS subtree is never yielded."""
    (tmp_path / "keep.py").write_text("x = 1\n")
    for d in ["deps", "node_modules", "site-packages", ".venv"]:
        sub = tmp_path / d / "nested"
        sub.mkdir(parents=True)
        (sub / "vendored.py").write_text("import this\n")

    yielded = list(walk_pruned(tmp_path))
    assert [p.name for p in yielded] == ["keep.py"]
    assert not any("vendored.py" == p.name for p in yielded)


def test_ignored_dir_nested_deep_is_pruned(tmp_path: Path) -> None:
    """Pruning happens at the ignored dir wherever it appears in the tree."""
    deep = tmp_path / "a" / "b" / "node_modules" / "c"
    deep.mkdir(parents=True)
    (deep / "x.py").write_text("x = 1\n")
    (tmp_path / "a" / "real.py").write_text("y = 2\n")

    names = {p.name for p in walk_pruned(tmp_path)}
    assert names == {"real.py"}


def test_does_not_follow_symlinked_dirs(tmp_path: Path) -> None:
    """``followlinks=False`` — symlinked directories are not traversed."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "f.py").write_text("x = 1\n")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        return  # platform without symlink support — nothing to assert

    paths = list(walk_pruned(tmp_path))
    # The real file is yielded once (via ``real/``); the symlink is not
    # descended into, so we never get a second ``f.py`` via ``link/``.
    assert [p.name for p in paths].count("f.py") == 1


def test_empty_for_missing_directory(tmp_path: Path) -> None:
    assert list(walk_pruned(tmp_path / "does-not-exist")) == []


def test_constants_cover_flagged_offenders() -> None:
    """The vendored trees that caused the original stalls are ignored."""
    for d in ("deps", "site-packages", "node_modules", ".venv", "vendor"):
        assert d in IGNORE_DIRS
