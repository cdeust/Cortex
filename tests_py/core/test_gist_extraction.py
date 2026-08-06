"""Tests for deterministic gist extraction (core, pure logic)."""

from __future__ import annotations

from mcp_server.core.gist_extraction import (
    GIST_BUDGET,
    extract_gist,
    needs_gist,
)

# Two elision markers' worth of fixed overhead is the documented allowance.
_OVERHEAD = 200


def test_needs_gist_threshold():
    assert needs_gist("x" * (GIST_BUDGET + 1)) is True
    assert needs_gist("x" * GIST_BUDGET) is False
    assert needs_gist("") is False


def test_small_output_passthrough():
    small = "line one\nline two\nline three"
    assert extract_gist(small) == small


def test_gist_respects_budget():
    big = "\n".join(f"filler line number {i} padding padding" for i in range(2000))
    gist = extract_gist(big)
    assert len(gist) <= GIST_BUDGET + _OVERHEAD


def test_signal_line_beyond_head_window_survives():
    # Bury a unique error line deep in the dump, far past the head window.
    filler = "\n".join(f"ordinary filler line {i}" for i in range(2000))
    marker = "FATAL: traceback exception occurred in payment handler"
    big = filler[:GIST_BUDGET] + "\n" + marker + "\n" + filler
    gist = extract_gist(big)
    assert marker in gist


def test_elision_marker_present():
    big = "\n".join(f"line {i} content here" for i in range(2000))
    gist = extract_gist(big)
    assert "[gist:" in gist and "full output in artifact" in gist


def test_deterministic():
    big = "\n".join(f"line {i} with some error text" for i in range(2000))
    assert extract_gist(big) == extract_gist(big)


def test_never_exceeds_budget_overhead_no_newlines():
    # A single huge line with no newlines: head/tail fill is line-granular,
    # so the gist must still stay bounded and never raise.
    big = "x" * (GIST_BUDGET * 4)
    gist = extract_gist(big)
    assert len(gist) <= GIST_BUDGET + _OVERHEAD


def test_custom_budget():
    big = "\n".join(f"line {i}" for i in range(500))
    gist = extract_gist(big, budget=300)
    assert len(gist) <= 300 + _OVERHEAD


# ── Artifact pointer round-trip (issue #366) ──────────────────────────────
#
# The pointer is the only link from a memory body to its raw content on disk,
# and `forget` deletes that artifact by parsing it back out. Format and parse
# are therefore one contract: anything format_artifact_pointer emits must be
# recoverable by parse_artifact_pointer, or forget silently leaves content
# behind. These pin the round-trip, including the paths that break naive
# regexes.


class TestArtifactPointerRoundTrip:
    def test_round_trip_recovers_the_path(self):
        from mcp_server.core.gist_extraction import (
            format_artifact_pointer,
            parse_artifact_pointer,
        )

        path = "/home/u/.claude/methodology/artifacts/2026-08/deadbeefcafe0001.md"
        line = format_artifact_pointer(path, 61234)
        assert parse_artifact_pointer(line) == path

    def test_round_trip_inside_a_full_memory_body(self):
        """Production shape: gist text, blank line, then the pointer."""
        from mcp_server.core.gist_extraction import (
            format_artifact_pointer,
            parse_artifact_pointer,
        )

        path = "/tmp/artifacts/2026-08/abc123.md"
        body = "some gist text\n… [gist: 10 of 99 chars] …\n\n" + (
            format_artifact_pointer(path, 99)
        )
        assert parse_artifact_pointer(body) == path

    def test_path_containing_spaces_survives(self):
        """A macOS home or temp dir can contain spaces; the path must not clip."""
        from mcp_server.core.gist_extraction import (
            format_artifact_pointer,
            parse_artifact_pointer,
        )

        path = "/Users/some user/Library/Application Support/artifacts/2026-08/a1.md"
        assert parse_artifact_pointer(format_artifact_pointer(path, 5)) == path

    def test_char_count_suffix_is_not_absorbed_into_the_path(self):
        from mcp_server.core.gist_extraction import (
            format_artifact_pointer,
            parse_artifact_pointer,
        )

        path = "/a/b/c.md"
        line = format_artifact_pointer(path, 4242)
        assert "4242 chars" in line, "precondition: the suffix must be present"
        assert parse_artifact_pointer(line) == path

    def test_absent_pointer_returns_none(self):
        from mcp_server.core.gist_extraction import parse_artifact_pointer

        assert parse_artifact_pointer("a plain memory with no artifact") is None

    def test_empty_content_returns_none(self):
        from mcp_server.core.gist_extraction import parse_artifact_pointer

        assert parse_artifact_pointer("") is None

    def test_malformed_pointer_returns_none_rather_than_a_bad_path(self):
        """Unparseable must mean "nothing safe to delete", never a guess."""
        from mcp_server.core.gist_extraction import parse_artifact_pointer

        assert parse_artifact_pointer("**Artifact:** no backticks here") is None
        assert parse_artifact_pointer("**Artifact:** ``") is None
        assert parse_artifact_pointer("**Artifact:** `   `") is None

    def test_first_pointer_wins_when_a_body_carries_two(self):
        from mcp_server.core.gist_extraction import (
            format_artifact_pointer,
            parse_artifact_pointer,
        )

        first = format_artifact_pointer("/first.md", 1)
        second = format_artifact_pointer("/second.md", 2)
        assert parse_artifact_pointer(f"{first}\n{second}") == "/first.md"
