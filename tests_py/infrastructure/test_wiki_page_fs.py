"""Tests for infrastructure.wiki_page_fs — the WikiPagePort adapter
core/auto_curator.py's freshness check and drift re-author read used to
perform inline (issue #314). Exercises the real filesystem via
``tmp_path`` — the counterpart to test_auto_curator.py's fake-port DIP
tests, which never touch a real file.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from mcp_server.infrastructure.wiki_page_fs import build_wiki_page_port


def test_is_recently_modified_true_for_a_fresh_file(tmp_path: Path) -> None:
    (tmp_path / "reference" / "cortex").mkdir(parents=True)
    page = tmp_path / "reference" / "cortex" / "x.md"
    page.write_text("body")

    port = build_wiki_page_port(str(tmp_path))
    assert port.is_recently_modified("reference/cortex/x.md", within_days=30) is True


def test_is_recently_modified_false_for_a_stale_file(tmp_path: Path) -> None:
    (tmp_path / "reference" / "cortex").mkdir(parents=True)
    page = tmp_path / "reference" / "cortex" / "x.md"
    page.write_text("body")
    old = time.time() - (31 * 86400)
    os.utime(page, (old, old))

    port = build_wiki_page_port(str(tmp_path))
    assert port.is_recently_modified("reference/cortex/x.md", within_days=30) is False


def test_is_recently_modified_false_for_a_missing_file(tmp_path: Path) -> None:
    port = build_wiki_page_port(str(tmp_path))
    result = port.is_recently_modified("reference/cortex/absent.md", within_days=30)
    assert result is False


def test_is_recently_modified_boundary_is_strictly_less_than(
    tmp_path: Path, monkeypatch
) -> None:
    """Mutation-driven (§12): an mtime EXACTLY ``within_days * 86400``
    seconds old must read as stale (``<``, not ``<=``) — pins the
    threshold arithmetic itself, not just the multiplier's sign, since a
    wrong multiplier (``86401`` or ``/`` instead of ``*``) also flips
    this exact boundary. ``time.time()`` is monkeypatched to a fixed
    value so the boundary lands exactly — measuring wall-clock elapsed
    time between ``os.utime`` and the assertion is inherently racy
    (a few microseconds pushes ``age_seconds`` just past the boundary,
    making ``<`` and ``<=`` agree and the mutant invisible)."""
    (tmp_path / "reference" / "cortex").mkdir(parents=True)
    page = tmp_path / "reference" / "cortex" / "x.md"
    page.write_text("body")
    fixed_mtime = 1_700_000_000.0
    os.utime(page, (fixed_mtime, fixed_mtime))
    monkeypatch.setattr(
        "mcp_server.infrastructure.wiki_page_fs.time.time",
        lambda: fixed_mtime + 86400,  # exactly the within_days=1 threshold
    )

    port = build_wiki_page_port(str(tmp_path))
    assert port.is_recently_modified("reference/cortex/x.md", within_days=1) is False


def test_is_recently_modified_scales_with_days_not_a_fixed_constant(
    tmp_path: Path,
) -> None:
    """A file aged 20 seconds is fresh under ``within_days=1`` (threshold
    86400s) but would read as stale under a mutant that divides instead
    of multiplies (``1 / 86400`` ≈ 0.0000116s threshold)."""
    (tmp_path / "reference" / "cortex").mkdir(parents=True)
    page = tmp_path / "reference" / "cortex" / "x.md"
    page.write_text("body")
    twenty_seconds_old = time.time() - 20
    os.utime(page, (twenty_seconds_old, twenty_seconds_old))

    port = build_wiki_page_port(str(tmp_path))
    assert port.is_recently_modified("reference/cortex/x.md", within_days=1) is True


def test_read_text_returns_file_content(tmp_path: Path) -> None:
    (tmp_path / "reference" / "cortex").mkdir(parents=True)
    (tmp_path / "reference" / "cortex" / "a.md").write_text("# A\n\nbody")

    port = build_wiki_page_port(str(tmp_path))
    assert port.read_text("reference/cortex/a.md") == "# A\n\nbody"


def test_read_text_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    port = build_wiki_page_port(str(tmp_path))
    assert port.read_text("reference/cortex/absent.md") is None


def test_read_text_ignores_undecodable_bytes(tmp_path: Path) -> None:
    """Mutation-driven (§12): pins ``errors="ignore"`` — an invalid or
    misspelled error-handler name (e.g. ``"IGNORE"``, unregistered — codec
    error-handler names are case-sensitive, unlike encoding names) raises
    ``LookupError``/``UnicodeDecodeError`` on this invalid byte instead of
    silently dropping it, and neither is caught by ``except OSError``."""
    (tmp_path / "reference" / "cortex").mkdir(parents=True)
    page = tmp_path / "reference" / "cortex" / "bad.md"
    page.write_bytes(b"ok \xffend")

    port = build_wiki_page_port(str(tmp_path))
    assert port.read_text("reference/cortex/bad.md") == "ok end"
