"""Tests for the low-signal filter on the recall path.

Spike 2026-05-13 found that recall results for design-decision queries
were dominated by ``# Tool: Edit`` auto-captures from unrelated repos.
The filter drops memories carrying a capture marker a Cortex writer emits
(``auto-captured`` / ``tool:edit`` / ``_backfill`` etc.) unless the caller
opts in. Words a user may choose (``audit``, ``wip``, ``stage-N``) never hide
a memory (issue #706, ADR-1123).
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.recall_helpers import (
    LOW_SIGNAL_TAGS,
    filter_low_signal,
    parse_tags,
)


def _mem(content: str, *tags: str) -> dict:
    """Build a minimal result dict that matches recall's output shape."""
    return {
        "memory_id": id(content),
        "content": content,
        "score": 0.9,
        "tags": list(tags),
    }


# ── Filter behaviour ──────────────────────────────────────────────────


def test_tool_edit_capture_is_dropped() -> None:
    results = [_mem("# Tool: Edit\nfile.py changed", "auto-captured", "tool:edit")]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


def test_backfill_import_is_dropped() -> None:
    results = [_mem("Some bulk-imported note", "imported", "_backfill")]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


# Tags no Cortex writer emits: before #706 each one hid the memory.
USER_VOCABULARY_TAGS = (
    "audit",
    "automated",
    "wip",
    "progress",
    "code-review",
    "stage-1",
    "stage-3",
    "stage-11",
)


@pytest.mark.parametrize("tag", USER_VOCABULARY_TAGS)
def test_user_vocabulary_tag_does_not_hide_memory(tag: str) -> None:
    """Issue #706: a user's own memory tagged with an ordinary word is kept."""
    results = [_mem(f"my note tagged {tag}", tag, "research")]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


def test_user_vocabulary_tag_beside_capture_marker_still_dropped() -> None:
    """The capture marker, not the user word, decides."""
    results = [_mem("# Tool: Bash\nls", "auto-captured", "tool:bash", "audit")]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


def test_curated_lesson_is_kept() -> None:
    """A lesson memory tagged with knowledge-shaped tags must survive."""
    results = [_mem("The bug was X; the fix was Y.", "lesson", "bug-fix")]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


def test_decision_record_is_kept() -> None:
    results = [_mem("Decision: adopt pgvector for ANN.", "decision", "architecture")]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


def test_convention_memory_is_kept() -> None:
    results = [_mem("Always use slugify before .md append.", "convention", "rule")]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


# ── Mixed-batch realism: spike scenario ───────────────────────────────


def test_filter_clears_tool_noise_so_lesson_floats_up() -> None:
    """Models the exact spike result: 4 tool-output captures + 1 lesson.
    Filtering must surface the lesson as the only kept hit."""
    results = [
        _mem("# Tool: Edit\nfile1.py changed", "auto-captured", "tool:edit"),
        _mem("# Tool: Edit\nfile2.py changed", "auto-captured", "tool:edit"),
        _mem("# Tool: Bash\ngit status", "auto-captured", "tool:bash"),
        _mem(
            "Decision: 001-zero-dependencies — use Node built-ins only.",
            "decision",
            "adr",
        ),
        _mem("# Tool: Read\nopened file", "auto-captured", "tool:read"),
    ]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 4
    assert "Decision: 001-zero-dependencies" in kept[0]["content"]


# ── String-encoded tags (PG returns tags as JSON-encoded string) ──────


def test_tags_as_json_string_still_filtered() -> None:
    """PG store can serialize tags as a JSON string; the filter must
    parse and apply correctly either way."""
    results = [
        {
            "memory_id": 1,
            "content": "tool capture",
            "tags": '["auto-captured", "tool:edit"]',
        }
    ]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


def test_empty_tags_kept() -> None:
    """A memory with no tags at all is not low-signal."""
    results = [{"memory_id": 1, "content": "untagged memory", "tags": []}]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


def test_missing_tags_key_kept() -> None:
    """Defensive: a result dict that's missing the ``tags`` key is kept."""
    results = [{"memory_id": 1, "content": "untagged memory"}]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1


# ── Set membership invariants ─────────────────────────────────────────


def test_low_signal_tags_are_exactly_the_capture_markers() -> None:
    """Pin the canonical set so a refactor can neither shrink it nor add
    a word a user may choose (ADR-1123)."""
    assert LOW_SIGNAL_TAGS == frozenset(
        {
            "auto-captured",
            "_backfill",
            "imported",
            "session-summary",
            "tool-output",
            "tool:edit",
            "tool:bash",
            "tool:read",
            "tool:write",
            "tool:grep",
            "tool:glob",
            "tool:search",
            "tool:webfetch",
            "tool:websearch",
            "tool:notebookedit",
        }
    )


def test_low_signal_tags_exclude_user_vocabulary() -> None:
    assert not (set(USER_VOCABULARY_TAGS) & LOW_SIGNAL_TAGS)


def test_low_signal_tags_does_not_include_knowledge_signals() -> None:
    """Pin the negative: knowledge-shaped tags must NOT be in the filter."""
    must_exclude = {
        "decision",
        "adr",
        "lesson",
        "convention",
        "architecture",
        "design",
        "rule",
        "standard",
    }
    assert not (must_exclude & LOW_SIGNAL_TAGS)


# ── parse_tags: every input shape the filter receives ─────────────────


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
