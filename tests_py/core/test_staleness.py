"""Tests for staleness file-reference extraction, incl. Windows paths.

source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.6
"""

from __future__ import annotations

from mcp_server.core.staleness import extract_file_references


def test_extracts_unix_relative_path():
    refs = extract_file_references("see src/core/staleness.py for details")
    assert "src/core/staleness.py" in refs


def test_extracts_windows_relative_backslash_path():
    refs = extract_file_references("see src\\core\\staleness.py for details")
    # Normalized to forward slashes regardless of separator used.
    assert "src/core/staleness.py" in refs


def test_extracts_windows_drive_absolute_path():
    refs = extract_file_references(
        "memory references C:\\Users\\me\\proj\\app.py which is gone"
    )
    assert "C:/Users/me/proj/app.py" in refs


def test_backslash_and_forward_slash_dedupe_to_one_ref():
    content = "src/a.py and src\\a.py are the same file"
    refs = extract_file_references(content)
    assert refs.count("src/a.py") == 1
    assert "src\\a.py" not in refs


def test_excludes_urls():
    # A URL must yield no filesystem references at all (stronger than checking
    # for a single host substring, which CodeQL flags as incomplete URL
    # sanitization — py/incomplete-url-substring-sanitization).
    refs = extract_file_references("docs at https://example.com/page.html")
    assert refs == []
