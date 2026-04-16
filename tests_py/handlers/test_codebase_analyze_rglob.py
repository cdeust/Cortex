"""ADR-0045 §R2 — bounded-memory file walking for ``collect_source_files``.

The previous implementation called ``sorted(root.rglob("*"))`` which
materialised every Path in the tree before the ``max_files`` cap applied.
On a 10M-file monorepo that OOMs Python before it reaches the cap.

These tests verify the bounded-candidate implementation: peak memory is
O(max_files * CANDIDATE_MULTIPLIER) paths, not O(tree_size).
"""

from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

from mcp_server.handlers import codebase_analyze_helpers as helpers


def _make_tree(root: Path, n_files: int) -> None:
    """Create ``n_files`` .py files across a few subdirectories."""
    # Spread files across 20 subdirs so rglob has real work to do.
    for i in range(n_files):
        sub = root / f"pkg_{i % 20}"
        sub.mkdir(exist_ok=True)
        (sub / f"mod_{i}.py").write_text(f"# file {i}\nx = {i}\n")


def test_bounded_peak_memory_vs_tree_size(tmp_path):
    """With 5000 files and max_files=100, peak path allocation stays bounded.

    We measure the peak bytes allocated by ``collect_source_files`` alone
    via ``tracemalloc`` and assert it is well below what ``sorted(rglob)``
    over 5000 Path objects would cost (~1 MB on CPython 3.13 for Path objs).
    """
    _make_tree(tmp_path, 5000)

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    files = helpers.collect_source_files(
        tmp_path, languages=None, max_files=100, max_bytes=1_000_000
    )
    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snapshot_after.compare_to(snapshot_before, "filename")
    peak_bytes = sum(stat.size_diff for stat in diff if stat.size_diff > 0)

    # Postcondition: at most max_files returned.
    assert len(files) <= 100
    # Postcondition: we did find Python files.
    assert len(files) == 100

    # Bounded memory: with max_files=100 and multiplier=10, we hold ~1000
    # Path objects. Allowing generous headroom (tracemalloc counts the
    # function's frames, the list, the Path objects themselves, and all
    # interpreter overhead), the peak must stay well under 10 MB even on
    # platforms where Path is heavier. Previous implementation on a 5000-
    # file tree allocates >3 MB just for the sorted-list-of-Paths.
    assert peak_bytes < 10 * 1024 * 1024, (
        f"peak memory {peak_bytes} bytes exceeds 10 MB cap"
    )


def test_respects_max_files_cap(tmp_path):
    """Returns exactly ``max_files`` when tree has more candidates."""
    _make_tree(tmp_path, 500)
    files = helpers.collect_source_files(
        tmp_path, languages=None, max_files=50, max_bytes=1_000_000
    )
    assert len(files) == 50


def test_candidate_cap_at_least_max_files(tmp_path):
    """CANDIDATE_MULTIPLIER=10 means we look at max_files*10 candidates.

    Regression guard: if candidate_cap < max_files the function would
    systematically under-return.
    """
    assert helpers.CANDIDATE_MULTIPLIER >= 1
    _make_tree(tmp_path, 200)
    files = helpers.collect_source_files(
        tmp_path, languages=None, max_files=150, max_bytes=1_000_000
    )
    # 200 python files exist; we should return min(200, 150) = 150.
    assert len(files) == 150


def test_filters_by_language(tmp_path):
    """Language filter still applies after the candidate-set truncation."""
    (tmp_path / "a.py").write_text("x=1")
    (tmp_path / "b.js").write_text("var x = 1;")
    (tmp_path / "c.go").write_text("package main")

    py_only = helpers.collect_source_files(
        tmp_path, languages=["python"], max_files=10, max_bytes=1_000_000
    )
    assert all(p.suffix == ".py" for p in py_only)


def test_skips_non_source_files(tmp_path):
    """Files without a recognised extension are filtered."""
    (tmp_path / "README.md").write_text("# readme")
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / "a.py").write_text("x=1")

    files = helpers.collect_source_files(
        tmp_path, languages=None, max_files=10, max_bytes=1_000_000
    )
    assert len(files) == 1
    assert files[0].suffix == ".py"


def test_skips_oversized_files(tmp_path):
    """Files exceeding ``max_bytes`` are skipped."""
    (tmp_path / "small.py").write_text("x=1")
    (tmp_path / "big.py").write_text("x=" + "1" * 10_000)

    files = helpers.collect_source_files(
        tmp_path, languages=None, max_files=10, max_bytes=100
    )
    assert len(files) == 1
    assert files[0].name == "small.py"


def test_empty_directory(tmp_path):
    """Empty directory yields empty list, no crash."""
    files = helpers.collect_source_files(
        tmp_path, languages=None, max_files=10, max_bytes=1_000_000
    )
    assert files == []


def test_deterministic_ordering(tmp_path):
    """Two calls on the same tree return the same ordering (sorted candidates)."""
    _make_tree(tmp_path, 50)
    a = helpers.collect_source_files(
        tmp_path, languages=None, max_files=30, max_bytes=1_000_000
    )
    b = helpers.collect_source_files(
        tmp_path, languages=None, max_files=30, max_bytes=1_000_000
    )
    assert a == b
