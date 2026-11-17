"""``WriteResult.text`` is the page a write left on disk, as ``read_page`` returns it.

``wiki_write`` records the ``wiki.pages`` row, its body hash included, from
this text rather than from a re-read that another writer may already have
replaced (issue #715, Codex review of PR #1092). Each test pins the text to
the file this write produced: the whole page for ``append`` and
``append_section``, the normalized and redacted page for ``create`` and
``replace``, with ``read_page``'s universal newlines.

source: issue #715 (acceptance criterion 3); Codex P2 on PR #1092
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.infrastructure.wiki_pages_listing import append_section
from mcp_server.infrastructure.wiki_store import (
    WriteResult,
    read_page,
    text_as_read,
    write_page,
)

# source: the AWS access-key shape the redaction rules recognise
# (mcp_server/shared/redaction_gate.py), so the write is redacted
_SECRET = "AKIA" + "ABCDEFGHIJKLMNOP"


def test_create_reports_the_page_it_wrote(tmp_path: Path) -> None:
    result = write_page(tmp_path, "notes/a.md", "# A\n")
    assert result == WriteResult("notes/a.md", "create", True, 4, "# A\n")
    assert result.text == read_page(tmp_path, "notes/a.md")


def test_replace_reports_the_normalized_page(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/a.md", "first\n")
    result = write_page(
        tmp_path, "notes/a.md", "---\ntitle: A\n---\nbody\n", mode="replace"
    )
    assert result.text == read_page(tmp_path, "notes/a.md")
    assert "body" in result.text and "first" not in result.text


def test_append_reports_the_whole_page_not_the_fragment(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/a.md", "first")
    result = write_page(tmp_path, "notes/a.md", "second", mode="append")
    assert result.text == "first\n\nsecond\n" == read_page(tmp_path, "notes/a.md")


def test_the_reported_page_is_the_redacted_one(tmp_path: Path) -> None:
    result = write_page(tmp_path, "notes/a.md", f"key {_SECRET}\n")
    assert _SECRET not in result.text
    assert result.text == read_page(tmp_path, "notes/a.md")


def test_bytes_written_counts_the_encoded_page(tmp_path: Path) -> None:
    result = write_page(tmp_path, "notes/a.md", "é\n")
    assert result.bytes_written == len("é\n".encode()) == 3


def test_text_as_read_applies_read_pages_newlines() -> None:
    assert text_as_read("a\r\nb\rc\n".encode()) == "a\nb\nc\n"
    assert text_as_read("é".encode()) == "é"
    assert text_as_read(b"\r\r\n") == "\n\n"


def test_append_section_reports_the_whole_page(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/s.md", "# S")
    result = append_section(tmp_path, "notes/s.md", "Extras", "more")
    assert (
        result.text == "# S\n\n## Extras\n\nmore\n" == read_page(tmp_path, "notes/s.md")
    )
    assert (result.path, result.mode, result.created) == (
        "notes/s.md",
        "append-section",
        False,
    )
    assert result.bytes_written == len(result.text.encode())
