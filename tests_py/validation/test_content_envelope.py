"""E3 — content envelope: maxLength tightened to 10_000 (ADR-0045 R2/R5).

The ``remember`` tool previously accepted content up to 50_000 chars. Taleb
audit surfaced two fragilities at that envelope:

  1. Entity-extraction fallback regex is O(n) in content length; a 50_000-
     char blob ran ~100K regex match attempts per call.
  2. The knowledge-graph insert path materialised substrings for each
     entity mention — OOM-prone on large inputs.

v3.13.0 Phase 1 E3 tightens the bound to 10_000. Inputs larger than 10 K
are rejected at the validation layer with a clear ``ValidationError`` —
the caller must split upstream; the ``remember`` handler does not attempt
implicit splitting (see the handler's docstring and its lack of any
chunk/split code path).

Source: docs/adr/ADR-0045-scalability-governance-rules.md §R2, §R5;
v3.13.0 Phase 1 Fragility Sweep E3.
"""

from __future__ import annotations

import pytest

from mcp_server.errors import ValidationError
from mcp_server.validation.schemas import validate_tool_args


class TestContentEnvelopeRemember:
    # (a) valid content below the envelope passes

    def test_short_content_passes(self):
        result = validate_tool_args("remember", {"content": "hello"})
        assert result["content"] == "hello"

    def test_one_thousand_chars_passes(self):
        text = "x" * 1000
        result = validate_tool_args("remember", {"content": text})
        assert result["content"] == text

    # (b) exact envelope boundary — 10 000 chars passes

    def test_exactly_10000_chars_passes(self):
        text = "x" * 10_000
        result = validate_tool_args("remember", {"content": text})
        assert len(result["content"]) == 10_000

    # (c) one char over — 10 001 chars rejected

    def test_10001_chars_rejected(self):
        text = "x" * 10_001
        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", {"content": text})
        # Error message must cite the field and the length violation.
        assert "content" in str(exc_info.value)
        assert "maximum length" in str(exc_info.value)

    # Extra: former 50 000 envelope must now reject

    def test_50000_chars_rejected(self):
        """The previous envelope (50 K) must now fail — prevents regression."""
        text = "x" * 50_000
        with pytest.raises(ValidationError):
            validate_tool_args("remember", {"content": text})

    # Extra: the ValidationError details include the bound value.

    def test_error_details_cite_max_length(self):
        text = "x" * 20_000
        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", {"content": text})
        # Caller needs to know the envelope to split upstream. The bound
        # surfaces through ``ValidationError.details["maxLength"]``.
        assert exc_info.value.details is not None
        assert exc_info.value.details.get("maxLength") == 10_000
        assert exc_info.value.details.get("field") == "content"
