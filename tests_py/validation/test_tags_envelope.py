"""E4 — tags envelope: maxItems=20, each tag ≤ 80 chars (ADR-0045 R2).

The ``remember`` schema previously accepted an unbounded ``tags`` array.
Every tag becomes a tsvector lexeme, an FTS-dictionary entry, and a row
in ``memory_entities`` — so a caller submitting 10_000 tags to a single
memory blows up indexing cost without bounded benefit. v3.13.0 Phase 1
E4 adds a bounded envelope:

  - ``maxItems = 20`` tags per memory.
  - Each tag is a string with ``maxLength = 80``.

Rejections happen at the validation layer with a ``ValidationError``
whose ``details`` carries the offending bound (and, for item failures,
the index).

Source: docs/adr/ADR-0045-scalability-governance-rules.md §R2;
v3.13.0 Phase 1 Fragility Sweep E4.
"""

from __future__ import annotations

import pytest

from mcp_server.errors import ValidationError
from mcp_server.validation.schemas import validate_tool_args


def _args_with_tags(tags: list[str]) -> dict:
    """Minimal valid remember args carrying the given tags list."""
    return {"content": "stub content", "tags": tags}


class TestTagsArrayEnvelope:
    # Absence and empty list remain valid.

    def test_tags_absent_is_ok(self):
        result = validate_tool_args("remember", {"content": "stub"})
        # `tags` has no default, so it is simply absent from the result.
        assert "tags" not in result or result["tags"] == []

    def test_empty_tags_passes(self):
        result = validate_tool_args("remember", _args_with_tags([]))
        assert result["tags"] == []

    # maxItems = 20

    def test_20_tags_passes(self):
        tags = [f"tag{i}" for i in range(20)]
        result = validate_tool_args("remember", _args_with_tags(tags))
        assert result["tags"] == tags

    def test_21_tags_rejected(self):
        tags = [f"tag{i}" for i in range(21)]
        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", _args_with_tags(tags))
        assert "maxItems" in str(exc_info.value) or "tags" in str(exc_info.value)
        assert exc_info.value.details is not None
        assert exc_info.value.details.get("maxItems") == 20
        assert exc_info.value.details.get("field") == "tags"

    def test_many_tags_rejected(self):
        """A pathological 10 000-element tag list must be rejected, not
        silently truncated."""
        tags = ["t"] * 10_000
        with pytest.raises(ValidationError):
            validate_tool_args("remember", _args_with_tags(tags))

    # Per-tag maxLength = 80

    def test_80_char_tag_passes(self):
        tag = "a" * 80
        result = validate_tool_args("remember", _args_with_tags([tag]))
        assert result["tags"] == [tag]

    def test_81_char_tag_rejected(self):
        tag = "a" * 81
        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", _args_with_tags([tag]))
        assert exc_info.value.details is not None
        assert exc_info.value.details.get("maxLength") == 80
        assert exc_info.value.details.get("field") == "tags"
        assert exc_info.value.details.get("index") == 0

    def test_offending_tag_index_reported(self):
        """Item index must surface so callers can pinpoint the bad tag."""
        tags = ["ok", "also-ok", "x" * 200, "never-reached"]
        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", _args_with_tags(tags))
        assert exc_info.value.details.get("index") == 2

    # Per-item type enforcement — an int tag must be rejected.

    def test_non_string_tag_rejected(self):
        tags = ["ok", 42]  # int where str expected
        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", _args_with_tags(tags))
        assert exc_info.value.details.get("index") == 1
        assert exc_info.value.details.get("got") == "int"


class TestTagsArrayEnvelopeDoesNotAffectOtherTools:
    """The new items/maxItems logic must not change behaviour of tools
    that use plain untyped ``array`` specs (e.g., record_session_end)."""

    def test_record_session_end_tools_used_unbounded(self):
        result = validate_tool_args(
            "record_session_end",
            {
                "session_id": "abc",
                "tools_used": [f"tool-{i}" for i in range(50)],
            },
        )
        assert len(result["tools_used"]) == 50

    def test_record_session_end_tools_used_accepts_mixed(self):
        result = validate_tool_args(
            "record_session_end",
            {
                "session_id": "abc",
                "tools_used": ["Read", "Write", 123],  # no items spec → no type check
            },
        )
        assert result["tools_used"] == ["Read", "Write", 123]
