"""Tests for the low-signal filter on the recall path.

Spike 2026-05-13 found that recall results for design-decision queries
were dominated by ``# Tool: Edit`` auto-captures from unrelated repos.
The filter drops memories a Cortex capture writer recorded by itself,
read from the ``source`` field that writer set, unless the caller opts in.
Tags never decide: a tag is a word a user may choose, so a user's memory
tagged ``audit``, ``imported`` or ``auto-captured`` is kept (issue #706,
ADR-1123, ADR-1140).
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.recall_helpers import filter_low_signal, parse_tags
from mcp_server.shared.capture_source import (
    CAPTURE_SOURCE_PREFIXES,
    CAPTURE_SOURCES,
    is_capture_source,
)


def _mem(content: str, source: str = "user", *tags: str) -> dict:
    """Build a minimal result dict that matches recall's output shape."""
    return {
        "memory_id": id(content),
        "content": content,
        "score": 0.9,
        "source": source,
        "tags": list(tags),
    }


# One source per Cortex capture writer (capture_source.py docstring).
CAPTURE_WRITER_SOURCES = (
    "post_tool_capture",
    "backfill:cortex",
    "import",
    "seed:mcp_server/server.py",
    "session",
)


# ── Filter behaviour ──────────────────────────────────────────────────


@pytest.mark.parametrize("source", CAPTURE_WRITER_SOURCES)
def test_capture_writer_memory_is_dropped(source: str) -> None:
    kept, dropped = filter_low_signal([_mem("captured", source)])
    assert kept == []
    assert dropped == 1


# Before #706 each of these tags hid the memory; the last five were the
# capture tags of ADR-1123, a user may still type them on their own memory.
USER_CHOSEN_TAGS = (
    "audit",
    "automated",
    "wip",
    "stage-3",
    "auto-captured",
    "tool:bash",
    "_backfill",
    "imported",
    "session-summary",
)


@pytest.mark.parametrize("tag", USER_CHOSEN_TAGS)
def test_user_memory_with_any_tag_is_kept(tag: str) -> None:
    """Issue #706: user tags are never used to hide a user's own memories."""
    kept, dropped = filter_low_signal([_mem(f"my note tagged {tag}", "user", tag)])
    assert len(kept) == 1
    assert dropped == 0


def test_capture_source_decides_without_any_tag() -> None:
    """The writer's source, not a tag, hides a capture."""
    kept, dropped = filter_low_signal([_mem("# Tool: Bash\nls", "post_tool_capture")])
    assert kept == []
    assert dropped == 1


def test_missing_or_empty_source_is_kept() -> None:
    """A memory with no writer source is not a capture."""
    results = [
        {"memory_id": 1, "content": "no source key"},
        {"memory_id": 2, "content": "empty source", "source": ""},
        {"memory_id": 3, "content": "null source", "source": None},
    ]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 3
    assert dropped == 0


def test_filter_clears_tool_noise_so_lesson_floats_up() -> None:
    """Models the spike result: 4 tool-output captures + 1 lesson."""
    results = [
        _mem("# Tool: Edit\nfile1.py changed", "post_tool_capture"),
        _mem("# Tool: Edit\nfile2.py changed", "post_tool_capture"),
        _mem("# Tool: Bash\ngit status", "post_tool_capture"),
        _mem("Decision: 001-zero-dependencies — use Node built-ins only.", "user"),
        _mem("# Tool: Read\nopened file", "post_tool_capture"),
    ]
    kept, dropped = filter_low_signal(results)
    assert dropped == 4
    assert [r["content"][:9] for r in kept] == ["Decision:"]


# ── The source set ────────────────────────────────────────────────────


def test_capture_sources_are_exactly_the_capture_writers() -> None:
    """Pin the set so a refactor can neither shrink it nor add a source a
    user-facing writer sets (ADR-1140)."""
    assert CAPTURE_SOURCES == frozenset({"post_tool_capture", "import", "session"})
    assert CAPTURE_SOURCE_PREFIXES == ("backfill:", "seed:")


@pytest.mark.parametrize(
    "source",
    ["user", "", "consolidation", "ingest_codebase", "wiki://adr/x.md", "sessions"],
)
def test_other_sources_are_not_capture_sources(source: str) -> None:
    assert not is_capture_source(source)


@pytest.mark.parametrize("value", [None, 7, ["post_tool_capture"]])
def test_non_string_source_is_not_a_capture_source(value) -> None:
    assert not is_capture_source(value)


# ── parse_tags: every input shape the recall path receives ────────────


def test_parse_tags_decodes_a_json_string() -> None:
    assert parse_tags('["auto-captured", "tool:edit"]') == [
        "auto-captured",
        "tool:edit",
    ]


def test_parse_tags_returns_empty_for_an_undecodable_string() -> None:
    assert parse_tags("not json") == []


def test_parse_tags_returns_a_list_unchanged() -> None:
    tags = ["wip", "audit"]
    assert parse_tags(tags) is tags


@pytest.mark.parametrize("empty", [None, [], ""])
def test_parse_tags_returns_an_empty_list_for_empty_input(empty) -> None:
    assert parse_tags(empty) == []
