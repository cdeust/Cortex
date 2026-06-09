"""CWE-22 (path traversal) regression tests for
``mcp_server.server.http_file_diff``.

The ``/api/file-diff?name=`` endpoint takes a user-controlled path and
resolves a git root from it. These tests pin the containment barrier:
every probed path must real-path *inside* an allowed root (``$HOME`` /
cwd / system temp) — a crafted ``?name=`` can never make the server
probe ``/etc``, ``/root`` or climb out via ``..`` / symlink escapes.

The sanitiser is ``os.path.realpath`` + ``os.path.commonpath`` (the
canonical, CodeQL-recognised CWE-22 barrier). Each test would FAIL if a
regression reverted to a naive ``startswith`` prefix test, dropped the
``..`` rejection, or let the ancestor walk leave the allowed root.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from mcp_server.server.http_file_diff import (
    _allowed_probe_roots,
    _contained_resolved,
    _first_existing_dir_within,
    _git_root_for_name,
    _within,
)


def _sentinel_root():
    """Return ``find_git_root`` and a marker it yields, so we can assert the
    code fell back to the CWD repo instead of probing the tainted path."""
    sentinel = Path("/__cwd_repo_fallback__")

    def fake_find_git_root(start=None):
        # No argument => the CWD-repo fallback branch.
        return sentinel if start is None else None

    return fake_find_git_root, sentinel


# ── _within: commonpath is segment-aware, not a prefix test ──────────────


def test_within_true_for_nested_path():
    assert _within("/home/user/project", "/home/user") is True


def test_within_true_for_exact_root():
    assert _within("/home/user", "/home/user") is True


def test_within_false_for_sibling_prefix():
    # The naive ``startswith`` bug: "/home/user-evil".startswith("/home/user").
    assert _within("/home/user-evil", "/home/user") is False


def test_within_false_for_outside_path():
    assert _within("/etc/passwd", "/home/user") is False


# ── _contained_resolved: only returns paths inside an allowed root ───────


def test_contained_resolved_blocks_etc():
    assert _contained_resolved("/etc/passwd") is None


def test_contained_resolved_allows_home():
    out = _contained_resolved(str(Path.home()))
    assert out is not None
    assert _within(os.path.realpath(str(out)), os.path.realpath(str(Path.home())))


def test_contained_resolved_allows_temp():
    with tempfile.TemporaryDirectory() as td:
        # /tmp and /var/folders are allowed roots; a real temp dir resolves
        # under one of them on every supported platform.
        real = os.path.realpath(td)
        assert any(_within(real, r) for r in _allowed_probe_roots())
        assert _contained_resolved(td) is not None


# ── _first_existing_dir_within: walk never leaves the root ───────────────


def test_first_existing_dir_returns_existing_ancestor():
    with tempfile.TemporaryDirectory() as td:
        deep = Path(td) / "a" / "b" / "c.py"  # never created
        out = _first_existing_dir_within(deep)
        assert out is not None
        assert os.path.realpath(str(out)) == os.path.realpath(td)


def test_first_existing_dir_rejects_outside_root():
    # A path outside any allowed root yields None rather than probing it.
    assert _first_existing_dir_within(Path("/etc/cron.d")) is None


# ── _git_root_for_name: end-to-end traversal blocking ────────────────────


def test_git_root_dotdot_falls_back_to_cwd():
    find, sentinel = _sentinel_root()
    assert _git_root_for_name("/etc/../etc/passwd", find) is sentinel


def test_git_root_etc_falls_back_to_cwd():
    find, sentinel = _sentinel_root()
    assert _git_root_for_name("/etc/passwd", find) is sentinel


def test_git_root_nullbyte_falls_back_to_cwd():
    find, sentinel = _sentinel_root()
    assert _git_root_for_name("/home/\x00/x", find) is sentinel


def test_git_root_empty_falls_back_to_cwd():
    find, sentinel = _sentinel_root()
    assert _git_root_for_name("   ", find) is sentinel


def test_git_root_resolves_real_in_repo_path():
    # A legitimate absolute path inside this repo (cwd) must resolve to a
    # real git root, proving the barrier does not break the happy path.
    from mcp_server.infrastructure.git_diff import find_git_root

    here = os.path.realpath(__file__)
    root = _git_root_for_name(here, find_git_root)
    assert root is not None
    assert Path(root).is_dir()
