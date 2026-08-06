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


# ── Gist composition invariants (mutation-surfaced, issue #366) ───────────
#
# Scoping the §12 mutation run to this file surfaced three surviving mutants in
# extract_gist/_fill_tail — pre-existing gaps, each a behaviour a reader of a
# gist would notice:
#   - _elision(used, len(output)) -> _elision(used, None): the marker reports
#     "of None chars", losing how much was dropped
#   - the tail loop's step -1 -> +1: the range becomes EMPTY, so the tail
#     silently disappears from every gist
#   - the tail loop's `continue` -> `break` on an already-taken index: the tail
#     stops early whenever a signal line sits inside the tail window
# The gist is the only thing a reader sees for an oversized capture, so each of
# these is a silent information loss. Lines below are 9 chars so the budget
# arithmetic is exact and the boundaries land where the comments say.


def _nine(tag: str) -> str:
    """A 9-char line tagged for identification, free of HIGH_VALUE_PATTERNS."""
    return f"{tag}aaaaaa"[:9].ljust(9, "a")


class TestGistCompositionInvariants:
    def test_elision_marker_reports_the_true_total_length(self):
        """The marker is the reader's only record of how much was dropped."""
        from mcp_server.core.gist_extraction import GIST_BUDGET, extract_gist

        output = "\n".join(f"line {i} " + "z" * 40 for i in range(300))
        assert len(output) > GIST_BUDGET, "precondition: must exceed the budget"

        gist = extract_gist(output)

        assert f"of {len(output)} chars" in gist, (
            "elision marker must state the true total char count; got: "
            + next((ln for ln in gist.splitlines() if "gist:" in ln), "<no marker>")
        )

    def test_the_tail_of_the_output_survives_into_the_gist(self):
        """A tail loop that collects nothing would drop the end of every dump."""
        from mcp_server.core.gist_extraction import GIST_BUDGET, extract_gist

        body = "\n".join(f"middle {i} " + "m" * 40 for i in range(300))
        output = f"FIRSTLINEMARKER\n{body}\nLASTLINEMARKER"
        assert len(output) > GIST_BUDGET, "precondition: must exceed the budget"

        gist = extract_gist(output)

        assert "LASTLINEMARKER" in gist, (
            "the final line must reach the gist — an empty tail fill drops the "
            "end of the output silently"
        )

    def test_a_taken_line_inside_the_tail_window_is_skipped_not_terminal(self):
        """An already-taken signal line must not stop the tail fill.

        Layout (9-char lines, budget 70 so the boundaries are exact):
          idx 0-1  taken by the head fill   (limit 0.4*70 = 28 -> 2 lines, used 20)
          idx 6    taken by the signal fill (limit 0.6*70 = 42 -> used 30)
          idx 8,7  taken by the tail fill   (used 50)
          idx 6    ALREADY TAKEN -> must `continue`, not `break`
          idx 5,4  taken by the tail fill   (used 70, exactly at budget)
        With `break`, PL5 and PL4 never appear.
        """
        from mcp_server.core.gist_extraction import extract_gist

        lines = [
            _nine("HD0"),
            _nine("HD1"),
            _nine("PL2"),
            _nine("PL3"),
            _nine("PL4"),
            _nine("PL5"),
            "err6error",  # the only signal line — 9 chars, contains "error"
            _nine("PL7"),
            _nine("PL8"),
        ]
        output = "\n".join(lines)
        budget = 70
        assert len(output) > budget, "precondition: must exceed the budget"

        gist = extract_gist(output, budget=budget)

        assert "err6error" in gist, "precondition: the signal line must be taken"
        assert _nine("PL8") in gist and _nine("PL7") in gist, (
            "precondition: the tail fill must reach the lines after the signal line"
        )
        assert _nine("PL5") in gist, (
            "the tail fill must SKIP the already-taken signal line and keep "
            "walking backwards; breaking there truncates the tail"
        )
        assert _nine("PL4") in gist, (
            "the tail fill must continue past the taken line to the budget"
        )

    def test_signal_fill_budget_accounting_bounds_the_gist(self):
        """The signal pass must charge each line against the budget correctly.

        Two mutation-surfaced gaps live here: an inverted budget check (which
        stops tripping, so the signal pass takes every remaining line) and an
        off-by-two char charge (which under-counts, so the pass takes more lines
        than the budget allows and the tail then over-fills too). Both inflate
        the gist past its stated bound, which is the whole point of the budget:
        an oversized capture must stop outranking curated memories.

        # source: measured on this input 2026-08-06 — correct behaviour yields
        # 3056 chars for a 3599-char all-signal input at GIST_BUDGET=3000
        # (budget + one elision marker). The bound below allows 150 chars of
        # headroom over the budget; broken accounting exceeds it by 250+.
        """
        from mcp_server.core.gist_extraction import GIST_BUDGET, extract_gist

        # Every line is a signal line, so the signal pass does the real work.
        output = "\n".join(["error"] * 600)
        assert len(output) > GIST_BUDGET, "precondition: must exceed the budget"

        gist = extract_gist(output)

        assert len(gist) <= GIST_BUDGET + 150, (
            f"gist is {len(gist)} chars for a {GIST_BUDGET}-char budget — the "
            "signal pass is not charging lines against the budget correctly"
        )

    def test_elision_marker_kept_count_matches_the_budget_actually_used(self):
        """`kept` is the reader's record of how much was retained.

        Under-counting in the fill passes makes this number disagree with the
        content the gist actually carries.
        """
        from mcp_server.core.gist_extraction import GIST_BUDGET, extract_gist

        output = "\n".join(["error"] * 600)
        gist = extract_gist(output)

        marker = next(ln for ln in gist.splitlines() if "gist:" in ln)
        kept = int(marker.split("gist:")[1].split("of")[0].strip())
        assert kept <= GIST_BUDGET, f"kept={kept} exceeds the budget"
        assert kept >= GIST_BUDGET - 60, (
            f"kept={kept} is far below the budget — the fill passes are "
            "under-charging, so more content was taken than reported"
        )
