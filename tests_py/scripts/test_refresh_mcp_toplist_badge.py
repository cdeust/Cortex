"""Tests for scripts/refresh_mcp_toplist_badge.py — badge refresh gate.

Written unittest-style to match the sibling script gates; Cortex's pytest
collects unittest classes natively.

The property under test throughout is FAIL CLOSED: a figure that cannot be
validated must never reach the badge. A stale badge is a known cost of the
static-asset choice; a confidently wrong one would be a false public claim,
so every failure path below asserts the badge is left untouched.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from xml.etree import ElementTree

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.refresh_mcp_toplist_badge.*") — a bare module name makes every
# mutant look unreached to a scoped mutation run (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.refresh_mcp_toplist_badge",
    Path(__file__).resolve().parents[2] / "scripts" / "refresh_mcp_toplist_badge.py",
)
badge = importlib.util.module_from_spec(_spec)
# Register before exec: @dataclass resolves its owning module through
# sys.modules, which a spec-loaded module is otherwise absent from.
sys.modules[_spec.name] = badge
_spec.loader.exec_module(badge)

# The observed live figure, 2026-07-28.
LIVE_RANK, LIVE_TOTAL = 964, 81_919
LIVE_PAGE = (
    '<p class="x">Cortex is a Model Context Protocol (MCP) server published by '
    "cdeust. It ranks #964 of 81,919 servers tracked on MCP Toplist, and its "
    "repository has 68 GitHub stars.</p>"
)


class TestValidate(unittest.TestCase):
    def test_accepts_a_well_formed_figure(self):
        r = badge.validate(964, 81919, "t")
        self.assertEqual((r.rank, r.total, r.source), (964, 81919, "t"))

    def test_strips_thousands_separators_from_scraped_text(self):
        self.assertEqual(badge.validate("964", "81,919", "t").total, 81919)

    def test_strips_thousands_separators_from_the_rank_too(self):
        # test_strips_thousands_separators_from_scraped_text only exercises
        # a comma on the TOTAL side; a mutant that disables comma-stripping
        # on the RANK side alone (mutmut_8/_9: wrong target string, or the
        # separator inserted instead of removed) is invisible to it.
        self.assertEqual(badge.validate("1,234", 2000, "t").rank, 1234)

    def test_rejects_non_numeric(self):
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.validate("nine", "81,919", "t")
        self.assertIn("non-numeric rank/total: 'nine'/'81,919'", str(ctx.exception))

    def test_rejects_none(self):
        with self.assertRaises(badge.UpstreamError):
            badge.validate(None, 81919, "t")

    def test_rejects_zero_rank(self):
        # Rank is a 1-based position; 0 signals a parser that matched noise.
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.validate(0, 81919, "t")
        self.assertIn("rank 0 is not a positive position", str(ctx.exception))

    def test_rejects_negative_rank(self):
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.validate(-1, 81919, "t")
        self.assertIn("rank -1 is not a positive position", str(ctx.exception))

    def test_rejects_zero_total_before_it_divides(self):
        # Guards Ranking.percentile against ZeroDivisionError.
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.validate(1, 0, "t")
        self.assertIn("total 0 is not a positive field size", str(ctx.exception))

    def test_total_of_exactly_one_is_the_boundary_not_the_cutoff(self):
        # The real guard is total_i < 1; a mutant tightening it to <= 1 or
        # < 2 would wrongly reject a legitimate single-server field.
        r = badge.validate(1, 1, "t")
        self.assertEqual((r.rank, r.total), (1, 1))

    def test_rejects_rank_beyond_the_field(self):
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.validate(81920, 81919, "t")
        self.assertIn("rank 81920 exceeds field size 81919", str(ctx.exception))

    def test_accepts_rank_equal_to_field_size(self):
        self.assertEqual(badge.validate(5, 5, "t").rank, 5)


class TestPercentileAndTier(unittest.TestCase):
    def test_live_figure_rounds_to_one_decimal(self):
        r = badge.validate(LIVE_RANK, LIVE_TOTAL, "t")
        self.assertAlmostEqual(badge.ranking_percentile(r), 1.2)
        self.assertEqual(badge.ranking_tier_text(r), "Top 1.2%")

    def test_very_high_rank_reports_a_bound_not_zero(self):
        # 1/81919 = 0.0012% would render "Top 0.0%", which reads as a bug.
        r = badge.validate(1, LIVE_TOTAL, "t")
        self.assertEqual(badge.ranking_tier_text(r), "Top <0.1%")

    def test_boundary_just_above_the_bound_uses_the_number(self):
        r = badge.validate(1, 1000, "t")
        self.assertEqual(badge.ranking_tier_text(r), "Top 0.1%")

    def test_last_place_is_one_hundred_percent(self):
        r = badge.validate(50, 50, "t")
        self.assertEqual(badge.ranking_tier_text(r), "Top 100.0%")


class TestParseLeaderboard(unittest.TestCase):
    # NOTE on the "utf-8" -> "UTF-8" case mutant (mutmut on
    # `payload.decode("utf-8")`): provably equivalent, not merely assumed.
    # Verified empirically: `codecs.lookup("utf-8") is codecs.lookup("UTF-8")`
    # is True (Python's codec registry normalizes encoding-name case before
    # lookup), so `b"...".decode("utf-8") == b"...".decode("UTF-8")` for
    # every input, valid or invalid. No test can observe a difference
    # because there isn't one. Same equivalence class as
    # scripts/generate_repo_badges.py's argparse-default/maxsplit rationale
    # (PR #283) and TestResolveRanking's identical decode-charset mutant
    # below.
    def _payload(self, doc) -> bytes:
        return json.dumps(doc).encode()

    def test_dict_with_servers_and_explicit_total(self):
        doc = {
            "total": LIVE_TOTAL,
            "servers": [{"id": badge.SERVER_ID, "rank": LIVE_RANK}],
        }
        r = badge.parse_leaderboard(self._payload(doc))
        self.assertEqual((r.rank, r.total), (LIVE_RANK, LIVE_TOTAL))

    def test_bare_list_falls_back_to_list_length_for_total(self):
        doc = [{"id": "other", "rank": 1}, {"id": badge.SERVER_ID, "rank": 2}]
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).total, 2)

    def test_alternate_identity_and_rank_keys(self):
        doc = {"servers": [{"slug": badge.SERVER_ID, "position": 3}, {}, {}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 3)

    def test_absent_server_raises(self):
        doc = {"servers": [{"id": "someone/else", "rank": 1}]}
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.parse_leaderboard(self._payload(doc))
        self.assertIn(f"{badge.SERVER_ID} not present in 1 entries", str(ctx.exception))

    def test_entry_without_a_rank_raises_rather_than_defaulting(self):
        doc = {"servers": [{"id": badge.SERVER_ID, "stars": 68}]}
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.parse_leaderboard(self._payload(doc))
        self.assertIn(
            f"entry for {badge.SERVER_ID} carries no rank", str(ctx.exception)
        )

    def test_invalid_json_raises(self):
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.parse_leaderboard(b"<html>503</html>")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_empty_list_raises(self):
        # An empty list IS an isinstance(list) with `not entries` true; a
        # mutant swapping the guard's `or` for `and` (mutmut_11) still
        # raises here (falls through to the later "not present" error
        # instead), so the message content — not just "raises" — is what
        # distinguishes the two code paths. This message is a plain literal
        # (no f-string placeholder breaking it up), so an exact match is
        # required: a substring check of the same text stays a contiguous
        # substring even inside a whole-string "XX...XX" mutation wrap.
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.parse_leaderboard(b"[]")
        self.assertEqual(
            str(ctx.exception), "leaderboard.json: no server list in document"
        )

    def test_unrecognised_shape_is_refused_not_guessed(self):
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(self._payload({"data": {"rank": 964}}))

    def test_non_dict_entries_are_skipped_not_crashed_on(self):
        doc = {"servers": ["junk", None, {"id": badge.SERVER_ID, "rank": 3}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 3)

    def test_identity_key_absent_is_skipped_not_crashed(self):
        # The identity lookup is `next(generator, None)`; a mutant that
        # drops the `None` default (mutmut_34) raises StopIteration
        # instead of skipping an entry with none of the identity keys.
        doc = {
            "total": 10,
            "servers": [{"stars": 68}, {"id": badge.SERVER_ID, "rank": 6}],
        }
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 6)

    def test_identity_via_name_key(self):
        doc = {"total": 10, "servers": [{"name": badge.SERVER_ID, "rank": 4}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 4)

    def test_identity_via_server_id_key(self):
        doc = {"total": 10, "servers": [{"serverId": badge.SERVER_ID, "rank": 5}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 5)

    def test_rank_via_place_key(self):
        doc = {"total": 10, "servers": [{"id": badge.SERVER_ID, "place": 8}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 8)

    def test_total_from_total_servers_key(self):
        # No "total" key present, so the loop must fall through to the
        # exact "totalServers" key (case-sensitive).
        doc = {"totalServers": 500, "servers": [{"id": badge.SERVER_ID, "rank": 7}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).total, 500)

    def test_total_from_count_key(self):
        # Neither "total" nor "totalServers" present; falls through to
        # the exact "count" key (case-sensitive).
        doc = {"count": 250, "servers": [{"id": badge.SERVER_ID, "rank": 3}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).total, 250)

    def test_rank_beyond_field_is_rejected_by_the_shared_validator(self):
        doc = {"total": 2, "servers": [{"id": badge.SERVER_ID, "rank": 99}]}
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(self._payload(doc))


class TestParseServerPage(unittest.TestCase):
    def test_extracts_both_numbers_from_the_live_sentence(self):
        r = badge.parse_server_page(LIVE_PAGE)
        self.assertEqual((r.rank, r.total), (LIVE_RANK, LIVE_TOTAL))

    def test_reworded_page_raises_rather_than_matching_loosely(self):
        # The failure mode this guards: a page that still says "#964"
        # somewhere but no longer pairs it with the field size.
        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.parse_server_page("<title>Cortex - MCP Server #964</title>")
        self.assertEqual(
            str(ctx.exception),
            "server page: the 'ranks #N of M servers tracked' sentence is absent "
            "— the page was reworded and this parser needs updating",
        )

    def test_empty_document_raises(self):
        with self.assertRaises(badge.UpstreamError):
            badge.parse_server_page("")

    def test_match_is_case_insensitive_and_whitespace_tolerant(self):
        r = badge.parse_server_page("It  Ranks  # 12  of  100  Servers  Tracked here")
        self.assertEqual((r.rank, r.total), (12, 100))


class TestProvenanceComment(unittest.TestCase):
    # Each returned list ITEM is a plain literal (or, for the pct line, an
    # f-string whose literal chunk is broken up by the interpolated value
    # — see the module-level note in TestParseLeaderboard on why that
    # distinction matters). Checking exact LIST-ITEM membership rather
    # than substring-in-joined-text is required throughout this class: a
    # mutant that wraps a whole line in mutmut's "XX...XX" string-content
    # marker still contains the original text as a contiguous substring
    # once joined, so only exact-item equality — not `assertIn` on the
    # joined blob — distinguishes it.
    def _lines(self):
        r = badge.validate(LIVE_RANK, LIVE_TOTAL, "server page")
        return badge._provenance_comment(r, date(2026, 7, 28))

    def test_percentage_arithmetic_is_pinned(self):
        # 964 / 81919 * 100 = 1.1767..., .2f -> "1.18" — deliberately not
        # the rounded "1.2" ranking_tier_text uses, so this pins the
        # arithmetic operator (mutmut_2/_3/_4: /, *, and the *101 typo)
        # independently of the tier-text rounding.
        self.assertTrue(any("1.18%" in line for line in self._lines()))

    def test_fixed_wording_is_pinned(self):
        lines = self._lines()
        self.assertIn(
            "  <!-- GENERATED by scripts/refresh_mcp_toplist_badge.py"
            " — do not hand-edit.",
            lines,
        )
        self.assertIn(
            "       Upstream's score is a popularity and activity signal,"
            " not a quality",
            lines,
        )
        self.assertIn(
            "       assessment, and ~25% of its weighting is undisclosed"
            " — so this badge",
            lines,
        )
        # "says Cortex is RANKED..." and " it IS. -->" are adjacent string
        # literals in the source (implicit concatenation, no operator) —
        # ONE list item, not two — confirmed by printing the real return
        # value rather than assumed from reading the source layout.
        self.assertIn(
            "       says Cortex is RANKED in this tier by MCP Toplist,"
            " never that it IS. -->",
            lines,
        )


class TestRenderBadge(unittest.TestCase):
    def _svg(self, rank=LIVE_RANK, total=LIVE_TOTAL, day=date(2026, 7, 28)) -> str:
        return badge.render_badge(badge.validate(rank, total, "server page"), day)

    def test_output_is_well_formed_xml(self):
        ElementTree.fromstring(self._svg())

    def test_carries_the_tier_and_a_locale_independent_date(self):
        svg = self._svg()
        self.assertIn("Top 1.2% · Jul 2026", svg)

    def test_month_name_does_not_depend_on_runner_locale(self):
        self.assertIn("Mar 2027", self._svg(day=date(2027, 3, 1)))

    def test_records_its_own_provenance_for_the_next_maintainer(self):
        svg = self._svg()
        self.assertIn("964", svg)
        self.assertIn("81,919", svg)
        self.assertIn(badge.SERVER_PAGE_URL, svg)

    def test_claim_is_attributive_never_a_quality_assertion(self):
        # Upstream states its score is "not a quality assessment"; the badge
        # must not outrun that.
        svg = self._svg()
        self.assertIn("RANKED", svg)
        self.assertNotIn("best", svg.lower())

    def test_omits_constructs_githubs_svg_sanitizer_strips(self):
        svg = self._svg()
        self.assertNotIn("<style", svg)
        self.assertNotIn("@import", svg)
        self.assertNotIn("<script", svg)

    def test_references_no_remote_resource(self):
        # A remote reference would reintroduce the third-party beacon the
        # committed asset exists to avoid. The xmlns URI does not count: it
        # is an identifier, never dereferenced by a renderer.
        svg = self._svg()
        for construct in ("<image", "xlink:href", "href=", "url(http", "@import"):
            self.assertNotIn(construct, svg)
        self.assertEqual(
            svg.count("http"),
            svg.count('xmlns="http://www.w3.org/2000/svg"')
            + svg.count(badge.SERVER_PAGE_URL),
        )

    def test_every_text_run_is_pinned_with_textlength(self):
        # textLength is what makes an inaccurate width estimate cost
        # letter-spacing instead of overflow past the panel edge.
        svg = self._svg()
        self.assertEqual(svg.count("<text"), svg.count("textLength="))

    def test_panel_widths_sum_to_the_declared_canvas(self):
        svg = self._svg()
        root = ElementTree.fromstring(svg)
        total_w = float(root.get("width"))
        rects = [r for r in root.iter("{http://www.w3.org/2000/svg}rect")]
        panels = [
            r
            for r in rects
            if r.get("height") == "20" and r.get("fill") in ("#3b3129", "#a53e00")
        ]
        self.assertEqual(sum(float(r.get("width")) for r in panels), total_w)

    def test_wider_message_widens_the_canvas(self):
        narrow = ElementTree.fromstring(self._svg(rank=1, total=LIVE_TOTAL)).get(
            "width"
        )
        wide = ElementTree.fromstring(self._svg(rank=50, total=50)).get("width")
        self.assertGreater(float(wide), float(narrow))

    def test_reproduces_the_measured_reference_geometry(self):
        # The hand-built badge this generator replaced was 216x20 with a
        # 110px message run; the width model must not silently drift off it.
        root = ElementTree.fromstring(self._svg())
        self.assertEqual(root.get("width"), "216")

    def test_label_panel_text_geometry_and_colors_are_pinned(self):
        # Each of these is an explicit (not derived) Panel field per
        # badge_render.Panel's own docstring; nothing here re-derives them,
        # so only an exact-value assertion pins a wrong constant. Parsed
        # via ElementTree (not a raw substring search): the clipPath
        # background rect ALSO carries a literal fill="#fff" for an
        # unrelated reason, so a naive `assertIn('fill="#fff"', svg)`
        # would pass even with message_text_fill mutated to None — the
        # message <text> element's OWN fill attribute is what must be
        # checked, not "does this string appear anywhere".
        root = ElementTree.fromstring(self._svg())
        ns = "{http://www.w3.org/2000/svg}"
        texts = list(root.iter(f"{ns}text"))
        # render() emits [label-shadow, label-face, message-shadow,
        # message-face] in that order.
        label_face, message_face = texts[1], texts[3]
        self.assertEqual(label_face.text, "MCP Toplist")
        self.assertEqual(label_face.get("fill"), "#f8f7f2")
        self.assertEqual(label_face.get("textLength"), "64")
        self.assertEqual(label_face.get("x"), "54")
        self.assertEqual(message_face.get("fill"), "#fff")

    def test_icon_fragments_are_pinned(self):
        # The icon tuple's lines are spliced into the SVG verbatim (no
        # f-string template around them, unlike label/message text), so a
        # mutant that wraps a whole line in mutmut's "XX...XX" string-
        # content marker still contains the ORIGINAL text as a substring
        # (e.g. 'XX  <g fill="#f1eee7">XX' still contains '<g fill=...>').
        # Exact-line membership (not substring search) is what actually
        # distinguishes the mutated line from the real one.
        lines = self._svg().splitlines()
        self.assertIn('  <g fill="#f1eee7">', lines)
        self.assertIn('    <rect x="7" y="10" width="2.6" height="5" rx="0.6"/>', lines)
        self.assertIn(
            '    <rect x="11.2" y="6.5" width="2.6" height="8.5" rx="0.6"/>', lines
        )
        self.assertIn(
            '    <rect x="15.4" y="8.4" width="2.6" height="6.6" rx="0.6"/>', lines
        )
        # Three "  </g>" lines exist when the icon renders (clip-path
        # group, icon group, font group); a mutant that drops or mangles
        # the icon's own closing line collapses this exact-line count.
        self.assertEqual(lines.count("  </g>"), 3)


class TestFetch(unittest.TestCase):
    def test_http_error_becomes_an_upstream_error_naming_the_code(self):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 503, "Service Unavailable", {}, None
            )

        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.fetch("https://example.test/x", opener=opener)
        self.assertIn("503", str(ctx.exception))

    def test_unreachable_host_becomes_an_upstream_error(self):
        def opener(request, timeout=None):
            raise urllib.error.URLError("no route to host")

        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.fetch("https://example.test/x", opener=opener)
        self.assertIn("unreachable", str(ctx.exception))

    def test_timeout_becomes_an_upstream_error(self):
        def opener(request, timeout=None):
            raise TimeoutError("timed out")

        with self.assertRaises(badge.UpstreamError):
            badge.fetch("https://example.test/x", opener=opener)

    def test_sends_the_expected_headers_and_timeout(self):
        # NOTE on header-key CASE mutants NOT covered here: urllib.request.
        # Request.add_header() normalizes every header key via .capitalize()
        # regardless of the source dict's key casing — verified empirically:
        # "User-Agent".capitalize() == "user-agent".capitalize() ==
        # "USER-AGENT".capitalize() == "User-agent", and likewise "Accept"/
        # "accept"/"ACCEPT" all capitalize() to "Accept". A mutant that only
        # changes the case of these two header-key literals is therefore
        # provably equivalent (identical wire behavior); mutmut's own "XX...
        # XX" marker mutations of the same keys ARE real (they change the
        # actual normalized key) and are what this test's exact-value
        # assertions below catch.
        captured = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                return b"ok"

        def opener(request, timeout=None):
            captured["headers"] = dict(request.headers)
            captured["timeout"] = timeout
            return _Response()

        result = badge.fetch("https://example.test/x", opener=opener)
        self.assertEqual(result, b"ok")
        self.assertEqual(
            captured["headers"].get("User-agent"),
            "cortex-badge-refresh (+https://github.com/cdeust/Cortex)",
        )
        self.assertEqual(
            captured["headers"].get("Accept"), "application/json, text/html;q=0.9"
        )
        self.assertEqual(captured["timeout"], badge.TIMEOUT_S)


class TestResolveRanking(unittest.TestCase):
    def test_prefers_the_structured_export_when_it_works(self):
        doc = json.dumps(
            {"total": 10, "servers": [{"id": badge.SERVER_ID, "rank": 2}]}
        ).encode()
        ranking, notices = badge.resolve_ranking(lambda url: doc)
        self.assertEqual(ranking.source, "leaderboard.json")
        self.assertEqual(notices, [])

    def test_falls_back_to_the_page_and_reports_why(self):
        # The live condition as of 2026-07-28: leaderboard.json 503s.
        def fetch_fn(url):
            if url == badge.LEADERBOARD_URL:
                raise badge.UpstreamError("leaderboard.json: HTTP 503")
            return LIVE_PAGE.encode()

        ranking, notices = badge.resolve_ranking(fetch_fn)
        self.assertEqual(ranking.source, "server page")
        self.assertEqual(ranking.rank, LIVE_RANK)
        # The fallback must be announced, never silent.
        self.assertEqual(len(notices), 1)
        self.assertIn("503", notices[0])

    def test_both_paths_failing_raises_and_names_both(self):
        def fetch_fn(url):
            raise badge.UpstreamError(f"{url}: unreachable")

        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.resolve_ranking(fetch_fn)
        message = str(ctx.exception)
        self.assertIn(badge.LEADERBOARD_URL, message)
        self.assertIn(badge.SERVER_PAGE_URL, message)
        # Exact reconstruction pins the prefix wording AND the "\n  - "
        # separator joining each notice — a looser substring check would
        # miss a mutant that mangles either.
        self.assertEqual(
            message,
            "no trusted figure from any source; badge left untouched:\n  - "
            + f"{badge.LEADERBOARD_URL}: unreachable"
            + "\n  - "
            + f"{badge.SERVER_PAGE_URL}: unreachable",
        )

    def test_a_served_but_unparseable_export_still_falls_through(self):
        def fetch_fn(url):
            return (
                b"<html>maintenance</html>"
                if url == badge.LEADERBOARD_URL
                else LIVE_PAGE.encode()
            )

        ranking, notices = badge.resolve_ranking(fetch_fn)
        self.assertEqual(ranking.source, "server page")
        self.assertTrue(notices)

    def test_tolerates_invalid_utf8_bytes_on_the_server_page_path(self):
        # The server-page decode uses errors="replace" specifically so a
        # stray non-UTF-8 byte elsewhere on the page (ads, analytics
        # snippets, etc.) cannot take down parsing of the one sentence we
        # need. Proven empirically: with an ACTUAL invalid byte present,
        # "replace" substitutes U+FFFD and succeeds, "strict" (the
        # implicit default when the errors arg is dropped) raises
        # UnicodeDecodeError, and an unregistered handler name (mutmut's
        # "XXreplaceXX" / "REPLACE" mutants) raises LookupError — but ONLY
        # when a real decode error occurs; on all-valid-UTF-8 input (every
        # other test in this file) the errors handler is never invoked at
        # all, so this is the only test that can distinguish them.
        garbled = (
            "<!-- ".encode() + b"\xff" + " garbled -->".encode() + LIVE_PAGE.encode()
        )

        def fetch_fn(url):
            if url == badge.LEADERBOARD_URL:
                raise badge.UpstreamError("leaderboard.json: HTTP 503")
            return garbled

        ranking, _ = badge.resolve_ranking(fetch_fn)
        self.assertEqual((ranking.rank, ranking.total), (LIVE_RANK, LIVE_TOTAL))

    # NOTE on the "utf-8" -> "UTF-8" case mutant on this same decode call
    # (`raw.decode("utf-8", "replace")` in resolve_ranking's server-page
    # lambda): provably equivalent, same reasoning and same verification
    # as TestParseLeaderboard's identical charset-name mutant above —
    # `codecs.lookup` normalizes encoding-name case before comparing, so
    # the codec selected is byte-for-byte identical regardless of the
    # literal's case, independent of which `errors` handler is paired
    # with it. Not re-verified a second time; the codecs.lookup identity
    # check already covers every call site that names "utf-8"/"UTF-8".


class TestToday(unittest.TestCase):
    def test_uses_utc_not_the_runner_local_clock(self):
        # datetime.now(None) returns naive LOCAL time, which would silently
        # shift the badge's stamped date by the CI runner's timezone offset
        # around midnight. There is no return-value assertion that can
        # observe "which timezone was used" without depending on the actual
        # system clock at test time, so this pins the call contract instead
        # (a legitimate stub-verification test for a one-line datetime
        # wrapper, not a mock of the logic under test).
        with mock.patch.object(badge, "datetime") as mock_datetime:
            mock_datetime.now.return_value.date.return_value = date(2026, 1, 1)
            result = badge._today()
        mock_datetime.now.assert_called_once_with(badge.timezone.utc)
        self.assertEqual(result, date(2026, 1, 1))


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.badge_path = Path(self._tmp.name) / "badge.svg"
        self.addCleanup(self._tmp.cleanup)

    def _patch_upstream(self, ranking=None, error=None, notices=None):
        def fake_resolve(*_args, **_kwargs):
            if error is not None:
                raise error
            return ranking, notices if notices is not None else []

        return mock.patch.object(badge, "resolve_ranking", fake_resolve)

    def _live_ranking(self):
        return badge.validate(LIVE_RANK, LIVE_TOTAL, "server page")

    def test_writes_the_badge_when_absent(self):
        stdout = io.StringIO()
        with (
            self._patch_upstream(self._live_ranking()),
            contextlib.redirect_stdout(stdout),
        ):
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 0)
        self.assertIn("Top 1.2%", self.badge_path.read_text())
        self.assertIn(
            "updated: Top 1.2% (#964 of 81,919, via server page)", stdout.getvalue()
        )

    def test_is_idempotent_when_already_current(self):
        with self._patch_upstream(self._live_ranking()):
            badge.main(["--badge", str(self.badge_path)])
            first = self.badge_path.read_text()
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 0)
        self.assertEqual(self.badge_path.read_text(), first)

    def test_current_status_message_is_printed(self):
        stdout = io.StringIO()
        with self._patch_upstream(self._live_ranking()):
            badge.main(["--badge", str(self.badge_path)])
            with contextlib.redirect_stdout(stdout):
                code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 0)
        self.assertIn(
            "current: Top 1.2% (#964 of 81,919, via server page)", stdout.getvalue()
        )

    def test_check_mode_passes_on_a_current_badge(self):
        with self._patch_upstream(self._live_ranking()):
            badge.main(["--badge", str(self.badge_path)])
            code = badge.main(["--check", "--badge", str(self.badge_path)])
        self.assertEqual(code, 0)

    def test_check_mode_fails_on_a_stale_badge_without_writing(self):
        self.badge_path.write_text("<svg>stale</svg>")
        stderr = io.StringIO()
        with (
            self._patch_upstream(self._live_ranking()),
            contextlib.redirect_stderr(stderr),
        ):
            code = badge.main(["--check", "--badge", str(self.badge_path)])
        self.assertEqual(code, 1)
        self.assertEqual(self.badge_path.read_text(), "<svg>stale</svg>")
        self.assertIn(
            "STALE: badge does not match upstream (Top 1.2%, #964 of 81,919)",
            stderr.getvalue(),
        )

    def test_upstream_failure_exits_nonzero_and_leaves_the_badge_untouched(self):
        # The central fail-closed guarantee: a broken upstream must never be
        # able to blank or corrupt a published claim.
        self.badge_path.write_text("<svg>previous</svg>")
        stderr = io.StringIO()
        with (
            self._patch_upstream(error=badge.UpstreamError("all sources down")),
            contextlib.redirect_stderr(stderr),
        ):
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 1)
        self.assertEqual(self.badge_path.read_text(), "<svg>previous</svg>")
        self.assertIn("FAIL: all sources down", stderr.getvalue())

    def test_upstream_failure_does_not_create_a_badge_from_nothing(self):
        with self._patch_upstream(error=badge.UpstreamError("all sources down")):
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 1)
        self.assertFalse(self.badge_path.exists())

    def test_fallback_notices_are_reported_on_stderr(self):
        stderr = io.StringIO()
        with (
            self._patch_upstream(
                self._live_ranking(), notices=["leaderboard.json: HTTP 503"]
            ),
            contextlib.redirect_stderr(stderr),
        ):
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 0)
        self.assertIn(
            "notice: fell back after: leaderboard.json: HTTP 503", stderr.getvalue()
        )

    def test_help_text_pins_the_description_and_check_flag_help(self):
        # argparse's --help exits (SystemExit) from inside parse_args()
        # itself, before main() ever reaches resolve_ranking() — so under
        # the real code, patching resolve_ranking here changes nothing
        # observable. But a mutant that deletes the `parser.parse_args()`
        # call entirely (never raising SystemExit at all) falls through
        # into resolve_ranking() for real, which — unpatched — is a live
        # network call whose outcome (and therefore this test's pass/fail)
        # depends on the sandbox's network reachability at run time.
        # Patching it removes that nondeterminism regardless of which
        # mutant is under test (reproduced: mutmut flagged this exact
        # mutant "suspicious" — an inconsistent verdict across its own
        # dual-run check — before this fix).
        stdout = io.StringIO()
        with (
            self._patch_upstream(self._live_ranking()),
            mock.patch.dict(os.environ, {"COLUMNS": "80"}),
            contextlib.redirect_stdout(stdout),
            self.assertRaises(SystemExit) as ctx,
        ):
            badge.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        help_lines = stdout.getvalue().splitlines()
        self.assertIn(badge.__doc__.splitlines()[0], help_lines)
        # Exact-line membership, not substring-in-blob: this help string is
        # a plain literal with no f-string placeholder to break up a
        # whole-string "XX...XX" mutation wrap, so only exact equality (of
        # the whole rendered line) catches it.
        self.assertIn(
            "  --check        exit 1 if the badge is out of date; never write",
            help_lines,
        )

    def test_default_badge_path_is_the_committed_asset_constant(self):
        # --badge is optional; when omitted, main() must target BADGE_PATH
        # exactly (not None / not a bare argparse default). Patching the
        # module constant rather than passing --badge is what actually
        # exercises the default= wiring instead of bypassing it.
        with (
            mock.patch.object(badge, "BADGE_PATH", self.badge_path),
            self._patch_upstream(self._live_ranking()),
        ):
            code = badge.main([])
        self.assertEqual(code, 0)
        self.assertTrue(self.badge_path.exists())


if __name__ == "__main__":
    unittest.main()
